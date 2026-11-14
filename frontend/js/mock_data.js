export class MockAdapter {
  constructor(fixtures) { this.cases=fixtures.cases; this.key='nominal'; this.tick=0; this.recovery=0; }
  select(key) { if(!this.cases[key]) throw new Error('Unknown demo scenario'); this.key=key; this.recovery=0; }
  packet() {
    const p=structuredClone(this.cases[this.key].packet), n=this.cases.nominal.packet;
    const fraction=this.recovery ? Math.min(1,(Date.now()-this.recovery)/12000) : 0;
    if(fraction) for(const group of ['vitals','environment']) for(const k of Object.keys(p[group])) {
      if(typeof p[group][k]==='number') p[group][k]+=(n[group][k]-p[group][k])*fraction;
    }
    if(fraction===1) { this.select('nominal'); return this.packet(); }
    p.vitals.heart_rate+=Math.sin(++this.tick*.45)*1.3;
    p.timestamp=new Date().toISOString(); p.active_scenario_id=this.key;
    const elapsed=42*86400+14*3600+30*60+12+this.tick;
    p.met=[Math.floor(elapsed/86400),Math.floor(elapsed/3600)%24,Math.floor(elapsed/60)%60,elapsed%60].map((x,i)=>String(x).padStart(i?2:3,'0')).join(':');
    p.comms_status={one_way_delay_sec:1214,link_status:'DEMO ? no Earth transmission'};
    // Explicit scenario fixtures, never presented as a new clinical evaluation.
    p.anomaly_assessment={organ_hud_status: fraction ? {} : this.cases[this.key].assessment.organ_hud_status};
    return p;
  }
  assessment() {
    const a=structuredClone(this.cases[this.key].assessment);
    a.demo=true; a.nasa_direct_quote=''; a.nasa_citation={};
    a.source_document='Offline repository example snapshot'; a.source_verification_status='UNVERIFIED_DEMONSTRATION';
    return a;
  }
  start(callback) { this.stop(); this.callback=callback; callback(this.packet()); this.timer=setInterval(()=>callback(this.packet()),1000); }
  stop() { clearInterval(this.timer); }
  recover() { this.recovery=Date.now(); return {status:'ok',message:'Local demonstration recovery started. No medical action recorded.'}; }
}
