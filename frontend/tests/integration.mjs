// Requires the existing backend on :8000 and frontend HTTP server on :5500.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Backend} from '../js/scenarios.js';
import {TelemetryConnection} from '../js/websocket.js';
import {validatePacket,diagnosisPayload} from '../js/telemetry.js';
const api=new Backend(process.env.ARES_TEST_API || 'http://localhost:8000');
const frontend=process.env.ARES_TEST_FRONTEND || 'http://localhost:5500';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const originalState=await api.request('/api/simulation/state');
const fixture=JSON.parse(await readFile(new URL('../data/demo_cases.json',import.meta.url)));
const health=await api.request('/health');assert.equal(health.status,'NOMINAL');
let connection;
try {
  for(const path of ['/','/style.css','/js/app.js','/js/reports.js','/js/body_dynamics.js','/js/body_hud.js','/js/websocket.js','/js/telemetry.js','/js/scenarios.js','/js/mock_data.js','/js/medical_panel.js','/vendor/three/three.module.js','/vendor/three/addons/loaders/GLTFLoader.js','/vendor/three/addons/controls/OrbitControls.js','/vendor/three/addons/utils/BufferGeometryUtils.js','/assets/models/ares_upper_body_hologram.glb','/data/baselines.json','/data/demo_cases.json']) {
    const response=await fetch(frontend+path);assert.equal(response.status,200,path);await response.arrayBuffer();
  }
  console.log('PASS: all HTML, CSS, modules, GLB and local dependencies served via HTTP');
  const cors=await fetch(api.base+'/api/diagnose',{method:'OPTIONS',headers:{Origin:'http://localhost:5500','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}});
  assert.equal(cors.headers.get('access-control-allow-origin'),'http://localhost:5500');console.log('PASS: backend CORS supports frontend port 5500');
  let count=0;const states=[];
  connection=new TelemetryConnection(api.base,(p)=>{assert.ok(validatePacket(p));count++;},s=>states.push(s));connection.start();
  for(let i=0;i<20 && count<2;i++)await delay(250);assert.ok(count>=2,'1 Hz WebSocket frames');
  const before=count;connection.socket.close();for(let i=0;i<25 && count<=before;i++)await delay(250);assert.ok(count>before,'WebSocket reconnect delivered fresh telemetry');
  connection.stop();console.log('PASS: real WebSocket receives 1 Hz packets and reconnects after closure');
  for(const key of ['hypercapnia','solar','zero-day','nominal']) {
    const triggered=await api.trigger(key);assert.equal(triggered.status,'ok');const packet=await api.snapshot(key);assert.ok(validatePacket(packet));
    const diagnosed=await api.diagnose(packet);assert.ok(typeof diagnosed.mode==='string');assert.ok(diagnosed.confidence>=0 && diagnosed.confidence<=1);
    console.log(`PASS: scenario ${key}, fresh agent snapshot and strict diagnosis request (${diagnosed.mode})`);
    if(key==='hypercapnia') {
      await delay(1200);const later=await api.snapshot(key);assert.notEqual(later.timestamp,packet.timestamp);
      assert.notEqual(later.environment.cabin_co2_mmhg,packet.environment.cabin_co2_mmhg,'Agent changes CO2 dynamically');
      const recovery=await api.recover(key);assert.equal(recovery.status,'ok');console.log('PASS: dynamic astronaut progression and existing simulated treatment endpoint');
    }
  }
  for(const key of ['hypercapnia','solar','zero-day']) {
    const result=await api.diagnose(fixture.cases[key].packet);
    assert.equal(result.mode,key==='zero-day'?'MODE_B_NOVEL_ANOMALY':'MODE_A_KNOWN_CONDITION');console.log(`PASS: backend sample assessment ${key}: ${result.mode}`);
  }
  const real=await api.snapshot();assert.equal(diagnosisPayload(real).routine_schedule,undefined);
  const frames=[];
  connection=new TelemetryConnection(api.base,p=>frames.push(p),()=>{});
  connection.start();
  async function waitForFrame(incidentId, test) {
    for(let i=0;i<60;i++) {
      const frame=frames.find(p=>p.blind_incident?.id===incidentId && test(p));
      if(frame) return frame;
      await delay(250);
    }
    assert.fail('Expected blind incident frame was not streamed');
  }
  const known=await api.startBlindCrisis(2);
  assert.deepEqual(Object.keys(known).sort(),['incident_id','status']);
  const initial=await waitForFrame(known.incident_id,()=>true);
  assert.equal(initial.blind_incident.phase,'observing');
  assert.equal(initial.rag_diagnosis,undefined);
  assert.equal(initial.active_scenario_id,undefined);
  assert.equal(initial.blind_incident.reveal,undefined);
  const waiting=await waitForFrame(known.incident_id,p=>p.blind_incident.phase==='awaiting_doctor');
  assert.equal(waiting.rag_diagnosis,undefined);
  await api.analyzeBlindCrisis(known.incident_id);
  const knownFrame=await waitForFrame(known.incident_id,p=>p.blind_incident.phase==='assessed');
  assert.equal(knownFrame.rag_diagnosis.mode,'MODE_A_KNOWN_CONDITION');
  assert.ok(knownFrame.environment.cabin_co2_mmhg>initial.environment.cabin_co2_mmhg);
  const knownPDF=await api.downloadReport(knownFrame.rag_diagnosis.earth_report.report_ref);assert.ok(knownPDF.blob.size>1000);
  const action=knownFrame.blind_incident.actions[0].id;
  await assert.rejects(api.applyBlindAction(known.incident_id-1,action));
  await api.applyBlindAction(known.incident_id,action,knownFrame.rag_diagnosis.action_checklist.map(step=>step.step));
  await assert.rejects(api.applyBlindAction(known.incident_id,action));
  await waitForFrame(known.incident_id,p=>p.blind_incident.phase==='recovering' && p.blind_incident.recovery_cause==='operator');
  const complete=await waitForFrame(known.incident_id,p=>p.blind_incident.phase==='complete');
  assert.equal(complete.blind_incident.reveal,'hypercapnia');
  const unknown=await api.request('/api/scenarios/simulate-crisis',{streaming:true,seed:0,duration_ticks:10});
  const unknownWaiting=await waitForFrame(unknown.incident_id,p=>p.blind_incident.phase==='awaiting_doctor');
  assert.equal(unknownWaiting.rag_diagnosis,undefined);
  await api.analyzeBlindCrisis(unknown.incident_id);
  const abstained=await waitForFrame(unknown.incident_id,p=>p.blind_incident.phase==='assessed');
  assert.equal(abstained.rag_diagnosis.mode,'MODE_B_NOVEL_ANOMALY');
  const fallback=abstained.blind_incident.actions[0];assert.equal(fallback.kind,'simulation_only');assert.equal(fallback.physical_effect_modeled,false);
  const unknownPDF=await api.downloadReport(abstained.rag_diagnosis.earth_report.report_ref);assert.ok(unknownPDF.blob.size>1000);
  await api.applyBlindAction(unknown.incident_id,fallback.id,abstained.rag_diagnosis.action_checklist.map(step=>step.step));
  const recovered=await waitForFrame(unknown.incident_id,p=>p.blind_incident.phase==='complete');assert.equal(recovered.anomaly_assessment.alert_level,'NOMINAL');
  const originalAgain=await api.downloadReport(knownFrame.rag_diagnosis.earth_report.report_ref);assert.equal(originalAgain.filename,knownPDF.filename);
  console.log('PASS: random streaming onset; no diagnosis before consultation; Mode A and B treatment-to-nominal recovery; matched original PDF downloads; stale/duplicate action rejection');
  console.log('ALL INTEGRATION CHECKS PASSED');
} finally {
  connection?.stop();
  await api.request('/api/scenarios/trigger',{scenario:originalState.active_scenario || 'nominal'});
}
