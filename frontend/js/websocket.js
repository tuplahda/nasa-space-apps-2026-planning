import { validatePacket } from './telemetry.js';
export class TelemetryConnection {
  constructor(base, onPacket, onState) {
    Object.assign(this,{base,onPacket,onState,attempt:0,stopped:true,lastAt:0,lastTimestamp:0,polling:false});
  }
  start() {
    this.stopped=false;
    this.connect();
    this.watch=setInterval(()=> {
      if(this.lastAt && Date.now()-this.lastAt>5000) this.onState('stale','Telemetry stale (>5s)');
      if(this.lastAt && Date.now()-this.lastAt>12000 && this.socket?.readyState===WebSocket.OPEN) this.socket.close();
    },1000);
  }
  accept(raw,transport) {
    const packet=validatePacket(raw);
    if(!packet) return;
    const timestamp=Date.parse(packet.timestamp);
    if(timestamp<=this.lastTimestamp) return; // Reject duplicates and out-of-order snapshots.
    this.lastTimestamp=timestamp; this.lastAt=Date.now(); this.attempt=0;
    this.onState('connected',transport); this.onPacket(packet,transport);
  }
  connect() {
    if(this.stopped) return;
    const url=new URL('/ws/telemetry',this.base); url.protocol=url.protocol==='https:'?'wss:':'ws:';
    this.onState('connecting',`Reconnecting (${this.attempt+1})`);
    const socket=this.socket=new WebSocket(url);
    const timeout=this.openTimeout=setTimeout(()=>{if(socket.readyState===WebSocket.CONNECTING) socket.close();},4500);
    socket.onopen=()=>clearTimeout(timeout);
    socket.onmessage=event=> {
      try { this.accept(JSON.parse(event.data),'WebSocket'); } catch { this.onState('invalid','Invalid telemetry packet ignored'); }
    };
    socket.onerror=()=>{}; // onclose handles retry and HTTP fallback.
    socket.onclose=()=> {
      clearTimeout(timeout);
      if(this.stopped) return;
      this.onState('disconnected','WebSocket unavailable; checking HTTP telemetry');
      this.poll();
      const delay=Math.min(30000,1000*2**Math.min(this.attempt++,5))+Math.random()*250;
      this.retry=setTimeout(()=>this.connect(),delay);
    };
  }
  async poll() {
    if(this.stopped || this.polling) return;
    this.polling=true;
    try {
      const response=await fetch(new URL('/api/telemetry/current',this.base),{signal:AbortSignal.timeout(3000),cache:'no-store'});
      if(response.ok && !this.stopped) this.accept(await response.json(),'HTTP polling');
    } catch { /* Connection state is already visible; continue bounded retries. */ }
    finally {
      this.polling=false;
      if(!this.stopped && this.socket?.readyState!==WebSocket.OPEN) this.pollTimer=setTimeout(()=>this.poll(),1000);
    }
  }
  stop() {
    this.stopped=true;
    clearTimeout(this.retry); clearTimeout(this.pollTimer); clearTimeout(this.openTimeout); clearInterval(this.watch);
    if(this.socket) { this.socket.onclose=null; this.socket.close(); }
  }
}
