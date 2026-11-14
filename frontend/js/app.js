import { TelemetryView, normalizeStatus, setText, finite } from './telemetry.js';
import { TelemetryConnection } from './websocket.js';
import { Backend } from './scenarios.js';
import { MedicalPanel } from './medical_panel.js';
import { MockAdapter } from './mock_data.js';

const query=new URLSearchParams(location.search);
const api=new Backend(query.get('api') || `${location.protocol==='https:'?'https:':'http:'}//localhost:8000`);
let view,body,mock,connection,packet,mode='waiting',transport='',activeKey='nominal',busy=false,generation=0,lastScenario;
const button=document.getElementById('run-assessment'), modeButton=document.getElementById('data-mode');
const panel=new MedicalPanel(async()=> {
  if(mode==='demo') return mock.recover();
  if(mode!=='backend' || !connection?.lastAt || Date.now()-connection.lastAt>5000) throw new Error('Fresh backend telemetry is required.');
  return api.recover(activeKey);
});
function status(state,label) {
  const node=document.getElementById('api-state');node.dataset.state=state;
  setText('api-state-label',label);
}
function sourceLabel() {
  const demo=mode==='demo';
  setText('packet-source',demo?'SIMULATED TELEMETRY · LOCAL DEMO':mode==='backend'?`SIMULATED TELEMETRY · ASTRONAUT AGENT · ${transport}`:'NO TELEMETRY');
  setText('data-badge',demo?'SIMULATED · DEMO':mode==='backend'?'SIMULATED · AGENT':'WAITING');
}
function ingest(p,source) {
  if(mode==='demo' && source!=='demo') return;
  packet=p;transport=source;const scenario=p.active_scenario_id;
  if(mode==='backend') {
    activeKey=({nominal:'nominal',hypercapnia:'hypercapnia',solar_flare:'solar','zero_day':'zero-day'})[scenario] || scenario;
    if(lastScenario!==undefined && scenario!==lastScenario) panel.reset('Scenario changed. Waiting for the astronaut agent clinical result.');
    lastScenario=scenario;
  }
  const states=view.update(p,source);body?.update(p,states);sourceLabel();
  if(mode==='backend' && p.rag_diagnosis && !busy) panel.render(p.rag_diagnosis);
  // Remove obsolete emergency instructions once the edge reports recovery.
  if(mode==='backend' && !p.rag_diagnosis && p.anomaly_assessment?.alert_level==='NOMINAL' && panel.assessment && panel.assessment.mode!=='NOMINAL_TELEMETRY') panel.reset('Latest edge assessment is nominal. Monitoring for a new clinical result.');
  if(mode==='demo' && mock.key!==activeKey) {activeKey=mock.key;panel.render(mock.assessment());}
}
function demo(automatic=false) {
  generation++; busy=false;button.disabled=false;button.classList.remove('is-loading');button.setAttribute('aria-busy','false');
  mode='demo';view.reset();packet=null;lastScenario=undefined;activeKey=document.getElementById('case-select').value;
  if(!automatic) connection?.stop();
  mock.select(activeKey);panel.reset();mock.start(p=>ingest(p,'demo'));panel.render(mock.assessment());
  status('simulated','SIMULATED · LOCAL DEMO');modeButton.textContent='Connect to backend';sourceLabel();
}
function followBackend() {
  generation++;mode='waiting';packet=null;lastScenario=undefined;mock.stop();connection?.stop();view.reset();panel.reset();status('connecting','CONNECTING API');sourceLabel();
  modeButton.textContent='Use local demo';
  connection=new TelemetryConnection(api.base,(p,t)=> {
    if(mode!=='backend') {generation++;mode='backend';mock.stop();view.reset();panel.reset();modeButton.textContent='Use local demo';status('connected',`API CONNECTED · ${t==='WebSocket'?'WS':'HTTP'}`);}
    ingest(p,t);
  },(state,label)=> {
    if(mode==='demo') return;
    if(state==='connected') status('connected',`API CONNECTED · ${label==='WebSocket'?'WS':'HTTP'}`);
    else {status(state,state==='stale'?'STALE TELEMETRY':state==='invalid'?'INVALID PACKET':state==='connecting'?'RECONNECTING API':'API DISCONNECTED');if(state==='stale') {setText('packet-source','STALE TELEMETRY · values retained');body?.update(packet,Object.fromEntries(['SANS-01','CV-02','ECLSS-03','RAD-04'].map(k=>[k,'unknown'])));}}
  });
  connection.start();
  const expected=generation;clearTimeout(window.aresFallback);
  window.aresFallback=setTimeout(()=>{if(mode==='waiting' && expected===generation)demo(true);},5500);
}
button.addEventListener('click',async()=> {
  if(busy || !mock) return;
  const key=document.getElementById('case-select').value;busy=true;button.disabled=true;button.classList.add('is-loading');button.setAttribute('aria-busy','true');setText('assessment-latency','SIMULATING…');panel.error('');
  const started=performance.now(),version=generation;
  try {
    if(mode==='demo') {mock.select(key);activeKey=key;panel.reset();ingest(mock.packet(),'demo');panel.render(mock.assessment());}
    else {
      if(mode!=='backend') throw new Error('API unavailable. Select local demo or wait for connection.');
      await api.trigger(key);if(version!==generation)return;
      panel.reset('Scenario injected. The astronaut agent changes vitals dynamically; assessments follow observed telemetry.');
      const current=await api.snapshot(key);if(version!==generation)return;
      ingest(current,transport);const result=await api.diagnose(current);if(version!==generation)return;
      panel.render(result);
      if(result.organ_hud_status) body?.update(current,Object.fromEntries(Object.entries(result.organ_hud_status).map(([id,s])=>[id,normalizeStatus(s)])));
    }
    setText('assessment-latency',`${mode==='demo'?'DEMO RENDER':'ASSESSMENT'} ${(performance.now()-started).toFixed(0)} ms`);
  } catch(e) {if(version===generation){panel.error(e.message);setText('assessment-latency','ASSESSMENT FAILED');}}
  finally {if(version===generation){busy=false;button.disabled=false;button.classList.remove('is-loading');button.setAttribute('aria-busy','false');}}
});
modeButton.addEventListener('click',()=>{if(mode==='demo') followBackend();else demo();});
async function init() {
  panel.reset();
  try {
    const [baselineResponse,demoResponse]=await Promise.all([fetch('data/baselines.json'),fetch('data/demo_cases.json')]);
    if(!baselineResponse.ok || !demoResponse.ok) throw new Error('Local telemetry reference files could not load.');
    view=new TelemetryView(await baselineResponse.json());mock=new MockAdapter(await demoResponse.json());
    // A WebGL problem must not stop the telemetry and clinical console.
    try {const {AresBodyHUD}=await import('./body_hud.js');body=new AresBodyHUD(document.getElementById('body-canvas'));}
    catch(e) {setText('model-status',`3D unavailable: ${e.message}`);}
    if(query.get('mode')==='demo')demo();else followBackend();
  } catch(e) {status('disconnected','FRONTEND ERROR');panel.error(`${e.message} Serve frontend through HTTP, not file://.`);button.disabled=true;}
}
window.addEventListener('pagehide',()=>{connection?.stop();mock?.stop();body?.dispose();clearTimeout(window.aresFallback);});
window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
init();
