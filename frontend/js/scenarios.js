import { diagnosisPayload, validatePacket } from './telemetry.js';
export const scenarioNames={ nominal:'nominal',hypercapnia:'hypercapnia',solar:'solar_flare','zero-day':'zero_day' };
export class Backend {
  constructor(base) { this.base=base; }
  async request(path,body) {
    const response=await fetch(new URL(path,this.base),{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(8000),cache:'no-store'});
    let data;
    try { data=await response.json(); } catch { throw new Error(`API returned non-JSON (${response.status})`); }
    if(!response.ok || data?.status==='error') throw new Error(`${path}: ${data.message || JSON.stringify(data.detail || response.status)}`);
    return data;
  }
  async trigger(key) {
    if(!(key in scenarioNames)) throw new Error('Unknown scenario');
    return this.request('/api/scenarios/trigger',{scenario:scenarioNames[key]});
  }
  startBlindCrisis(seed) {
    const payload = {streaming: true};
    if (seed !== undefined) payload.seed = seed;
    return this.request('/api/scenarios/simulate-crisis', payload);
  }
  analyzeBlindCrisis(incidentId) {
    return this.request('/api/scenarios/analyze-crisis', {incident_id: incidentId});
  }
  applyBlindAction(incidentId, actionId, acknowledgedSteps) {
    return this.request('/api/treatments/apply', {incident_id: incidentId, action_id: actionId, ...(acknowledgedSteps ? {acknowledged_steps: acknowledgedSteps} : {})});
  }
  async downloadReport(reference,{signal}={}) {
    const response=await fetch(new URL('/api/reports/download?format=pdf',this.base),{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report_ref:reference}),
      signal:signal?AbortSignal.any([signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000)
    });
    if(!response.ok) {
      let detail;try{const payload=await response.json();detail=payload.detail||payload.message;}catch{}
      throw new Error(typeof detail==='string'?detail:`Report request failed (${response.status}).`);
    }
    if(!response.headers.get('content-type')?.toLowerCase().startsWith('application/pdf'))throw new Error('The server did not return a PDF.');
    if(response.headers.get('x-ares-report-ref')!==reference)throw new Error('The returned report did not match this assessment.');
    const blob=await response.blob(),header=new Uint8Array(await blob.slice(0,5).arrayBuffer());
    if(String.fromCharCode(...header)!=='%PDF-')throw new Error('The report response is not a genuine PDF.');
    const disposition=response.headers.get('content-disposition')||'';
    const supplied=/filename="?([^";]+)"?/i.exec(disposition)?.[1];
    const filename=(supplied||`ares_assessment_${reference.slice(0,16)}.pdf`).replace(/[^a-zA-Z0-9_.-]/g,'_').slice(0,180);
    return {blob,filename:filename.endsWith('.pdf')?filename:filename+'.pdf'};
  }
  async snapshot(key) {
    for(let i=0;i<6;i++) {
      const raw=await this.request('/api/telemetry/current');
      const packet=validatePacket(raw);
      if(packet && (!key || packet.active_scenario_id===scenarioNames[key])) return packet;
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    throw new Error('Astronaut agent has not published the selected scenario yet. Waiting for stream updates.');
  }
  diagnose(packet) { return this.request('/api/diagnose',diagnosisPayload(packet)); }
  recover(key) { return this.request('/api/treatments/apply',{treatment:key==='hypercapnia'?'li_oh_swap_and_o2':'standard countermeasure protocol'}); }
}
