// Run with a recent Node.js; no packages or npm required. Runtime remains browser-only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
registerHooks({resolve(specifier,context,next){return next(specifier==='three'?new URL('../vendor/three/three.module.js',import.meta.url).href:specifier.startsWith('three/addons/')?new URL('../vendor/three/addons/'+specifier.slice(13),import.meta.url).href:specifier,context);}});
const {validatePacket,diagnosisPayload,classify}=await import('../js/telemetry.js');
const {MockAdapter}=await import('../js/mock_data.js');
const {Backend}=await import('../js/scenarios.js');
const {TelemetryConnection}=await import('../js/websocket.js');
const {MedicalPanel}=await import('../js/medical_panel.js');
const data=JSON.parse(await readFile(new URL('../data/demo_cases.json',import.meta.url)));
const baselines=JSON.parse(await readFile(new URL('../data/baselines.json',import.meta.url)));
const sample=()=>structuredClone(data.cases.nominal.packet);
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.style={};this.events={};this.attributes={};this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent || '').join('');}
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=nodes;}
  addEventListener(name,cb){this.events[name]=cb;}
  setAttribute(k,v){this.attributes[k]=v;}
  removeAttribute(k){delete this.attributes[k];}
  closest(){return this;}
}
const nodes=new Map();
globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(tag){return new Element(tag);}};

test('packet validation rejects malformed data and invalid timestamps',()=>{
  assert.equal(validatePacket(null),null);assert.equal(validatePacket({type:'ERROR'}),null);
  assert.equal(validatePacket({...sample(),timestamp:'bad'}),null);
  assert.equal(validatePacket({...sample(),vitals:{heart_rate:'62'}}),null);
});
test('missing, nonfinite and flagged channels stay unavailable',()=>{
  const p=sample();delete p.vitals.hrv_ms;p.vitals.heart_rate=Infinity;p.unreliable_channels=['spo2_pct'];
  const q=validatePacket(p);assert.equal(q.vitals.heart_rate,null);assert.equal(q.vitals.spo2,null);assert.equal(q.vitals.hrv_ms,undefined);
});
test('strict diagnosis payload strips dashboard fields and scenario labels',()=>{
  const p={...sample(),active_scenario_id:'zero_day',anomaly_assessment:{},rag_diagnosis:{},routine_schedule:[],mission_readiness_pct:94};
  const q=diagnosisPayload(p);assert.equal(q.active_scenario_id,undefined);assert.equal(q.rag_diagnosis,undefined);assert.equal(q.anomaly_assessment,undefined);assert.equal(q.stateless_evaluation,true);assert.deepEqual(q.vitals,p.vitals);
});
test('activity-specific thresholds prevent an exercise HR false alert',()=>{
  const p=sample();p.vitals.heart_rate=150;p.activity_state='ARED_EXERCISE';
  assert.equal(classify(p,baselines).channels.heart_rate,'cyan');p.activity_state='IVA_REST';assert.equal(classify(p,baselines).channels.heart_rate,'red');
});
test('backend edge status takes precedence; missing ocular readings are not invented',()=>{
  const p=sample();p.anomaly_assessment={organ_hud_status:{'SANS-01':'RED','RAD-04':'AMBER'},breached_parameters:[]};
  assert.equal(classify(p,baselines).statuses['SANS-01'],'red');assert.equal(classify(p,baselines).statuses['RAD-04'],'amber');
  delete p.anomaly_assessment;assert.equal(classify(p,baselines).statuses['SANS-01'],'unknown');
});
test('all offline scenarios validate and assessment fixtures are explicitly demonstration data',()=>{
  const m=new MockAdapter(data);
  for(const key of ['nominal','hypercapnia','solar','zero-day']){m.select(key);assert.ok(validatePacket(m.packet()));assert.equal(m.assessment().demo,true);assert.deepEqual(m.assessment().nasa_citation,{});}
  m.select('nominal');assert.equal(m.assessment().mode,'NOMINAL_TELEMETRY');m.select('zero-day');assert.equal(m.assessment().mode,'MODE_B_NOVEL_ANOMALY');
  m.recover();m.recovery=Date.now()-13000;assert.equal(m.packet().active_scenario_id,'nominal');
});
test('scenario aliases and simulator recovery use actual backend contracts',async()=>{
  const original=globalThis.fetch,calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url:String(url),body:JSON.parse(options.body)});return {ok:true,json:async()=>({status:'ok'})};};
  try {const api=new Backend('http://localhost:8000');await api.trigger('solar');await api.trigger('zero-day');await api.recover('hypercapnia');assert.equal(calls[0].body.scenario,'solar_flare');assert.equal(calls[1].body.scenario,'zero_day');assert.equal(calls[2].body.treatment,'li_oh_swap_and_o2');}finally{globalThis.fetch=original;}
});
test('HTTP errors are surfaced, not converted into successful mock assessments',async()=>{
  const original=globalThis.fetch;globalThis.fetch=async()=>({ok:false,status:422,json:async()=>({detail:'invalid packet'})});
  try {await assert.rejects(new Backend('http://localhost:8000').diagnose(sample()),/invalid packet/);}finally{globalThis.fetch=original;}
});
test('blind launch opts into streaming and keeps replay seed optional', async () => {
  const calls = [];
  const api = new Backend('http://localhost:8000');
  api.request = async (path, body) => { calls.push([path, body]); };
  await api.startBlindCrisis();
  await api.startBlindCrisis(0);
  await api.applyBlindAction(4, 'restore_airflow');
  assert.deepEqual(calls, [
    ['/api/scenarios/simulate-crisis', {streaming: true}],
    ['/api/scenarios/simulate-crisis', {streaming: true, seed: 0}],
    ['/api/treatments/apply', {incident_id: 4, action_id: 'restore_airflow'}],
  ]);
});
test('blind acknowledgement enables only a currently available simulated action', async () => {
  let submitted = 0;
  const panel = new MedicalPanel(async () => { submitted++; });
  const assessment = {...data.cases.hypercapnia.assessment, blindIncident: {
    id: 4, actions: [{id: 'restore_airflow', label: 'Restore airflow'}],
  }};
  panel.reset();
  panel.render(assessment);
  for (const entry of panel.checks) {
    entry.input.checked = true;
    entry.input.events.change();
  }
  assert.equal(submitted, 0);
  assert.equal(panel.submit.textContent, 'Restore airflow');
  assert.equal(panel.submit.disabled, false);
  panel.render({...assessment, blindIncident: {id: 4, actions: []}});
  await panel.recover();
  assert.equal(panel.submit.hidden, true);
  assert.equal(submitted, 0);
});
test('checklist acknowledgements survive stream refresh and recovery submits once',async()=>{
  let submitted=0;const p=new MedicalPanel(async()=>{submitted++;});p.reset();const a={...data.cases.hypercapnia.assessment,demo:true};p.render(a);
  for(const c of p.checks){c.input.checked=true;c.input.events.change();}
  assert.ok(p.ready);assert.equal(submitted,0);assert.ok(p.checks[0].at);
  p.render({...a,execution_time_ms:4});assert.ok(p.checks.every(c=>c.input.checked));
  await Promise.all([p.recover(),p.recover()]);await p.recover();assert.equal(submitted,1);assert.ok(p.submitted);assert.match(nodes.get('checklist-status').textContent,/do not record treatment/);
});
test('Mode B abstains and an unverified citation remains unavailable',()=>{
  const p=new MedicalPanel(async()=>{});p.render({...data.cases['zero-day'].assessment,demo:true});
  assert.equal(nodes.get('diagnosis-title').textContent,'Unclassified novel anomaly');assert.match(nodes.get('citation-text').textContent,/unavailable/);assert.match(nodes.get('assessment-details').textContent,/LOCKOUT/);
});
test('stale recovery response cannot overwrite a new assessment',async()=>{
  let resolve;const p=new MedicalPanel(()=>new Promise(r=>{resolve=r;}));p.render({...data.cases.hypercapnia.assessment,demo:true});
  for(const c of p.checks)c.input.checked=true;p.progress();const pending=p.recover();p.reset('New scenario');resolve({});await pending;assert.equal(p.submitted,false);assert.equal(p.assessment,null);
});
test('WebSocket validation, stale detection, HTTP fallback and bounded reconnect',async()=>{
  const originals={WebSocket:globalThis.WebSocket,fetch:globalThis.fetch,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
  const timers=new Map(),intervals=new Map();let id=0,received=0;const states=[];
  class Socket {static OPEN=1;static CONNECTING=0;constructor(){this.readyState=0;Socket.last=this;}close(){this.readyState=3;this.onclose?.();}}
  globalThis.WebSocket=Socket;globalThis.setTimeout=(cb,ms)=>{timers.set(++id,{cb,ms});return id;};globalThis.clearTimeout=i=>timers.delete(i);globalThis.setInterval=cb=>{intervals.set(++id,cb);return id;};globalThis.clearInterval=i=>intervals.delete(i);
  globalThis.fetch=async()=>({ok:true,json:async()=>sample()});
  let c;
  try {
    c=new TelemetryConnection('http://localhost:8000',()=>received++,s=>states.push(s));c.start();const socket=Socket.last;socket.readyState=1;socket.onopen();
    socket.onmessage({data:JSON.stringify(sample())});socket.onmessage({data:JSON.stringify(sample())});socket.onmessage({data:'invalid JSON'});assert.equal(received,1);assert.ok(states.includes('invalid'));
    c.lastAt=Date.now()-6000;for(const cb of intervals.values())cb();assert.ok(states.includes('stale'));
    c.attempt=10;socket.close();await Promise.resolve();await Promise.resolve();
    assert.ok([...timers.values()].some(t=>t.ms>=30000 && t.ms<=30250));assert.ok(states.includes('disconnected'));
    c.stop();assert.equal(timers.size,0);assert.equal(intervals.size,0);
  } finally {c?.stop();Object.assign(globalThis,originals);}
});
test('actual GLB is upright, skeleton-free and pickable through translucent skin',async()=>{
  const THREE=await import('three');const {AresBodyHUD}=await import('../js/body_hud.js');
  globalThis.ProgressEvent=class {constructor(type,init){Object.assign(this,{type,...init});}};
  // Use real loader / geometry / raycaster with no WebGL rendering or visual-test claim.
  const {GLTFLoader}=await import('../vendor/three/addons/loaders/GLTFLoader.js');
  const bytes=await readFile(new URL('../assets/models/ares_upper_body_hologram.glb',import.meta.url));
  const gltf=await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'');
  const meshes={};gltf.scene.traverse(o=>{if(o.isMesh)meshes[o.name]=o;});
  assert.deepEqual(Object.keys(meshes).sort(),['BODY_SURFACE','BRAIN','HEART','LUNG_LEFT','LUNG_RIGHT','EYE_LEFT','EYE_RIGHT','OPTIC_NERVE_LEFT','OPTIC_NERVE_RIGHT'].sort());
  const bounds=new THREE.Box3().setFromObject(gltf.scene).getSize(new THREE.Vector3());assert.ok(bounds.y>bounds.x && bounds.y>bounds.z);
  const camera=new THREE.PerspectiveCamera(36,1,.01,30);camera.position.set(0,0,1.5);camera.lookAt(0,0,0);camera.updateMatrixWorld();gltf.scene.updateMatrixWorld(true);
  let selected;const hud={camera,meshes,raycaster:new THREE.Raycaster(),renderer:{domElement:{getBoundingClientRect:()=>({left:0,top:0,width:500,height:500})}},select:(region,name)=>{selected=name;}};
  for(const name of ['BRAIN','HEART','LUNG_LEFT','LUNG_RIGHT','EYE_LEFT','EYE_RIGHT']){
    const center=new THREE.Box3().setFromObject(meshes[name]).getCenter(new THREE.Vector3()).project(camera);
    AresBodyHUD.prototype.pick.call(hud,(center.x+1)*250,(-center.y+1)*250);assert.ok(selected && selected!=='BODY_SURFACE',`${name} should select an internal organ through skin`);
  }
  // Exercise the production load path with real GLTFLoader and Three materials;
  // a renderer is unnecessary for geometry, fitting and material assertions.
  const savedFetch=globalThis.fetch;
  globalThis.fetch=async()=>new Response(bytes,{headers:{'Content-Type':'model/gltf-binary'}});
  const loaded=Object.create(AresBodyHUD.prototype);
  Object.assign(loaded,{scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(36,1,.01,30),controls:{target:new THREE.Vector3(),update(){}},container:new Element(),meshes:{},statuses:{}});
  try {
    await loaded.load();assert.equal(loaded.container.dataset.loaded,'true',nodes.get('model-status').textContent);
    assert.ok(loaded.meshes.BODY_SURFACE.material.transparent);assert.ok(loaded.meshes.BODY_SURFACE.material.opacity<.25);assert.equal(loaded.meshes.BODY_SURFACE.material.depthWrite,false);
    assert.equal(loaded.meshes.LUNG_LEFT.material.depthWrite,false);
    for(const name of ['EYE_LEFT','EYE_RIGHT']) {assert.ok(loaded.meshes[name].material.vertexColors);assert.ok(loaded.meshes[name].geometry.getAttribute('color'));assert.equal(loaded.meshes[name].userData.region,'SANS-01');}
    for(const name of ['OPTIC_NERVE_LEFT','OPTIC_NERVE_RIGHT']) assert.equal(loaded.meshes[name].userData.region,'SANS-01');
    const wide=loaded.distance;loaded.camera.aspect=.5;loaded.reset();assert.ok(loaded.distance>=wide);
  } finally {globalThis.fetch=savedFetch;loaded.scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});}
  gltf.scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});
});

test('real HTML preserves unique IDs and all static module DOM references',async()=>{
  const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
  const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
  for(const name of ['app','body_hud','telemetry','medical_panel','scenarios','websocket','mock_data']) {
    const js=await readFile(new URL(`../js/${name}.js`,import.meta.url),'utf8');
    for(const match of js.matchAll(/(?:getElementById|setText)\('([^']+)'/g)) assert.ok(ids.includes(match[1]),`Missing DOM ID: ${match[1]}`);
  }
  assert.ok(html.includes('href="style.css"'));assert.ok(!html.includes('https://fonts.googleapis.com'));
  const {fmt}=await import('../js/telemetry.js');assert.equal(fmt(null),'\u2014');
});

test('dashboard waits for current incident frames and keeps named cases in rehearsal', async () => {
  const originals = {fetch: globalThis.fetch, WebSocket: globalThis.WebSocket,
    location: globalThis.location, window: globalThis.window, querySelector: document.querySelector};
  const events = {};
  const calls = [];
  class Socket {
    static OPEN = 1;
    static CONNECTING = 0;
    readyState = 1;
    constructor() { Socket.current = this; }
    close() { this.readyState = 3; }
  }
  globalThis.location = {search: '', protocol: 'http:'};
  globalThis.window = {addEventListener: (name, callback) => { events[name] = callback; }};
  globalThis.WebSocket = Socket;
  document.querySelector = document.getElementById;
  const button = document.getElementById('run-assessment');
  button.classList = {add() {}, remove() {}};
  document.getElementById('case-select').value = 'nominal';
  globalThis.fetch = async (url, options) => {
    if (url === 'data/baselines.json') return {ok: true, json: async () => baselines};
    if (url === 'data/demo_cases.json') return {ok: true, json: async () => data};
    calls.push([url.pathname, JSON.parse(options.body)]);
    return {ok: true, json: async () => ({status: 'ok', incident_id: 3})};
  };
  function send(incident, tick, phase, diagnosis) {
    const p = {...sample(), simulation_incident: incident,
      timestamp: new Date(Date.UTC(2026, 10, 14, 12, 0, tick)).toISOString()};
    if (phase) {
      delete p.active_scenario_id;
      p.blind_incident = {id: incident, phase, actions: []};
    }
    if (diagnosis) p.rag_diagnosis = diagnosis;
    Socket.current.onmessage({data: JSON.stringify(p)});
  }
  try {
    await import('../js/app.js');
    for (let i = 0; i < 30 && !Socket.current; i++) {
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    assert.ok(Socket.current);
    Socket.current.onopen();
    send(2, 0);
    assert.equal(document.getElementById('rehearsal-cases').hidden, true);
    document.getElementById('rehearsal-toggle').events.click();
    assert.equal(document.getElementById('rehearsal-cases').hidden, false);
    document.getElementById('rehearsal-toggle').events.click();
    await button.events.click();
    assert.deepEqual(calls, [['/api/scenarios/simulate-crisis', {streaming: true}]]);
    const diagnosis = data.cases.hypercapnia.assessment;
    send(2, 1, null, diagnosis);
    assert.equal(document.getElementById('result-mode').textContent, 'AWAITING ASSESSMENT');
    send(3, 2, 'observing');
    assert.equal(document.getElementById('blind-status').textContent, 'Collecting streamed telemetry.');
    send(3, 3, 'assessed', diagnosis);
    assert.match(document.getElementById('result-mode').textContent, /MODE A/);
    send(2, 4, null, data.cases['zero-day'].assessment);
    assert.match(document.getElementById('result-mode').textContent, /MODE A/);
  } finally {
    events.pagehide?.();
    document.querySelector = originals.querySelector;
    delete originals.querySelector;
    Object.assign(globalThis, originals);
  }
});
