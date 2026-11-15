// Run with a recent Node.js; no packages or npm required. Runtime remains browser-only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
registerHooks({resolve(specifier,context,next){return next(specifier==='three'?new URL('../vendor/three/three.module.js',import.meta.url).href:specifier.startsWith('three/addons/')?new URL('../vendor/three/addons/'+specifier.slice(13),import.meta.url).href:specifier,context);}});
const {validatePacket,diagnosisPayload,classify,resolveTreatedRegions}=await import('../js/telemetry.js');
const {MockAdapter}=await import('../js/mock_data.js');
const {Backend}=await import('../js/scenarios.js');
const {TelemetryConnection}=await import('../js/websocket.js');
const {MedicalPanel}=await import('../js/medical_panel.js');
const {InsightsView}=await import('../js/assessment_insights.js');
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
  focus(){document.activeElement=this;}
}
const nodes=new Map();
globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(tag){return new Element(tag);},createElementNS(namespace,tag){return new Element(tag);}};

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
    id: 4, phase: 'assessed', actions: [{id: 'restore_airflow', label: 'Restore airflow'}],
  }};
  panel.reset();
  panel.render(assessment);
  for (const entry of panel.checks) {
    entry.input.checked = true;
    entry.input.events.change();
  }
  assert.equal(submitted, 0);
  assert.equal(panel.submit.textContent, 'Administer Treatment');
  assert.equal(panel.submit.disabled, false);
  panel.render({...assessment, blindIncident: {id: 4, actions: []}});
  await panel.recover();
  assert.equal(panel.submit.hidden, false);
  assert.equal(panel.submit.disabled, true);
  assert.equal(submitted, 0);
});
test('checklist acknowledgements survive stream refresh and recovery submits once',async()=>{
  let submitted=0;const p=new MedicalPanel(async()=>{submitted++;});p.reset();const a={...data.cases.hypercapnia.assessment,demo:true};p.render(a);
  for(const c of p.checks){c.input.checked=true;c.input.events.change();}
  assert.ok(p.ready);assert.equal(submitted,0);assert.ok(p.checks[0].at);
  p.render({...a,execution_time_ms:4});assert.ok(p.checks.every(c=>c.input.checked));
  await Promise.all([p.recover(),p.recover()]);await p.recover();assert.equal(submitted,1);assert.ok(p.submitted);assert.match(nodes.get('checklist-status').textContent,/do not record treatment/);
});
test('partial checklist administration (2 of 4 tasks) heals headache/SANS-01 before lungs/ECLSS-03 and allows remaining tasks',async()=>{
  const calls=[];const p=new MedicalPanel(async info=>{calls.push(info);});p.reset();
  const fourStepAssessment={...structuredClone(data.cases.hypercapnia.assessment),action_checklist:[
    {step:1,action:'Relocate crewmember out of low-ventilation compartment immediately.',critical:true},
    {step:2,action:'Administer Acetaminophen 650 mg PO for frontal headache (avoid opioids).',critical:true},
    {step:3,action:'Deploy portable ventilation fans and run ECLSS diagnostics on CDRA scrubber beds.',critical:true},
    {step:4,action:'Deploy 100% O2 via demand mask (RSP) to restore lung oxygenation.',critical:true},
  ],blindIncident:{id:9,phase:'assessed',actions:[{id:'restore_airflow',label:'Restore airflow'}]}};
  p.render(fourStepAssessment);
  assert.equal(p.submit.disabled,true);
  // Check only 2 of the 4 critical tasks (relocate + headache analgesia).
  p.checks[0].input.checked=true;p.checks[0].input.events.change();
  p.checks[1].input.checked=true;p.checks[1].input.events.change();
  assert.equal(p.ready,true);assert.equal(p.submit.disabled,false);
  await p.recover();
  assert.equal(calls.length,1);assert.equal(calls[0].partial,true);
  assert.deepEqual(calls[0].acknowledgedSteps,[1,2]);assert.equal(calls[0].totalSteps,4);
  assert.ok(p.checks[0].administered && p.checks[1].administered);
  assert.ok(!p.checks[2].administered && !p.checks[3].administered);
  assert.equal(p.checks[0].input.disabled,true);assert.equal(p.checks[2].input.disabled,false);
  assert.equal(p.submitted,false);assert.equal(p.submit.disabled,true);
  assert.match(p.checks[0].stamp.textContent,/^Administered /);
  // 3D model organ statuses: headache (SANS-01) turns cyan while lungs (ECLSS-03) remain red.
  const baseStatuses={'SANS-01':'red','ECLSS-03':'red','CV-02':'cyan','RAD-04':'cyan'};
  const treated=resolveTreatedRegions(fourStepAssessment.action_checklist,calls[0].acknowledgedSteps,baseStatuses);
  assert.deepEqual(treated,['SANS-01']);
  const partialPacket={...structuredClone(data.cases.hypercapnia.packet),anomaly_assessment:{organ_hud_status:{'SANS-01':'RED','ECLSS-03':'RED','CV-02':'CYAN','RAD-04':'CYAN'}},treated_regions:treated};
  const partialClassified=classify(partialPacket,baselines).statuses;
  assert.equal(partialClassified['SANS-01'],'cyan');assert.equal(partialClassified['ECLSS-03'],'red');
  // Now check the remaining 2 tasks and administer full recovery.
  p.checks[2].input.checked=true;p.checks[2].input.events.change();
  p.checks[3].input.checked=true;p.checks[3].input.events.change();
  assert.equal(p.ready,true);assert.equal(p.submit.disabled,false);
  await p.recover();
  assert.equal(calls.length,2);assert.equal(calls[1].partial,false);
  assert.deepEqual(calls[1].acknowledgedSteps,[1,2,3,4]);
  assert.equal(p.submitted,true);assert.ok(p.checks.every(c=>c.administered && c.input.disabled));
  const fullTreated=resolveTreatedRegions(fourStepAssessment.action_checklist,calls[1].acknowledgedSteps,baseStatuses);
  assert.ok(fullTreated.includes('SANS-01') && fullTreated.includes('ECLSS-03'));
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
    for(const name of ['EYE_LEFT','EYE_RIGHT']) {assert.equal(loaded.meshes[name].material.vertexColors,false);assert.ok(loaded.meshes[name].geometry.getAttribute('color'));assert.equal(loaded.meshes[name].userData.region,'SANS-01');}
    for(const name of ['OPTIC_NERVE_LEFT','OPTIC_NERVE_RIGHT']) assert.equal(loaded.meshes[name].userData.region,'SANS-01');
    const wide=loaded.distance;loaded.camera.aspect=.5;loaded.reset(false);assert.ok(loaded.distance>=wide);
    loaded.selectedTarget='heart';loaded.focusOn('heart',false);loaded.model.updateMatrixWorld(true);
    const heartCenter=new THREE.Box3().setFromObject(loaded.meshes.HEART).getCenter(new THREE.Vector3());
    assert.ok(loaded.controls.target.distanceTo(heartCenter)<1e-8);
    loaded.focusOn('lungs',true);const oldGoal=loaded.cameraTransition.target.clone();loaded.focusOn('brain',true);
    assert.ok(loaded.cameraTransition.target.distanceTo(oldGoal)>.01);loaded.stepCamera(performance.now()+1200);assert.equal(loaded.cameraTransition,null);
    loaded.reset(false);assert.equal(loaded.selectedTarget,null);assert.equal(loaded.meshes.EYE_LEFT.visible,true);
    loaded.setLayerVisibility('eyes',false);assert.equal(loaded.meshes.EYE_LEFT.visible,false);assert.equal(loaded.meshes.BRAIN.visible,true);
    loaded.reset(false);loaded.reduced={matches:false};const now=performance.now();loaded.freshAt=now;loaded.heartRate=120;loaded.respirationRate=15;
    const heartPosition=loaded.meshes.HEART.position.clone(),lungPosition=loaded.meshes.LUNG_LEFT.position.clone();
    loaded.stepPhysiology(.125,now);assert.ok(loaded.meshes.HEART.scale.x>1);assert.ok(loaded.meshes.LUNG_LEFT.scale.z>1);
    assert.ok(loaded.meshes.HEART.position.equals(heartPosition));assert.ok(loaded.meshes.LUNG_LEFT.position.equals(lungPosition));
    const phase=loaded.heartPhase;loaded.stepPhysiology(.1,now+6000);assert.equal(loaded.heartPhase,phase);
    assert.equal(loaded.scan.parent,loaded.model);assert.ok(Math.abs(loaded.scan.rotation.x+Math.PI/2)<1e-8);
  } finally {globalThis.fetch=savedFetch;loaded.scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});}
  gltf.scene.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});
});

test('real HTML preserves unique IDs and all static module DOM references',async()=>{
  const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
  const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
  for(const name of ['app','assessment_insights','body_hud','telemetry','medical_panel','reports','scenarios','websocket','mock_data']) {
    const js=await readFile(new URL(`../js/${name}.js`,import.meta.url),'utf8');
    for(const match of js.matchAll(/(?:getElementById|setText)\('([^']+)'/g)) assert.ok(ids.includes(match[1]),`Missing DOM ID: ${match[1]}`);
  }
  assert.ok(html.includes('href="style.css"'));assert.ok(!html.includes('https://fonts.googleapis.com'));
  const crew=html.slice(html.indexOf('id="crew-panel"'),html.indexOf('</aside>'));
  for(const id of ['comparison-card','timeline-card'])assert.ok(crew.includes(`id="${id}"`),`${id} belongs to crew panel`);
  const doctor=html.slice(html.indexOf('<aside class="clinical-column">'));
  assert.ok(!doctor.includes('id="comparison-card"') && !doctor.includes('id="timeline-card"'));
  assert.match(crew,/button id="crew-toggle"[^>]*type="button"[^>]*aria-expanded="false"[^>]*aria-controls="crew-insights"/);
  for(const name of ['app','medical_panel','assessment_insights']) {
    const js=await readFile(new URL(`../js/${name}.js`,import.meta.url),'utf8');
    assert.doesNotMatch(js,/\bMUT\b/);
  }
  const {fmt}=await import('../js/telemetry.js');assert.equal(fmt(null),'\u2014');
});

test('crew history opens and closes accessibly; completed history survives a cleared clinical view',()=>{
  const insights=new InsightsView(),p={...sample(),simulation_incident:9,blind_incident:{id:9,phase:'assessed'}};
  insights.observe(p);insights.receiveAssessment(data.cases.hypercapnia.assessment,p);
  const toggle=nodes.get('crew-toggle');toggle.events.click();
  assert.equal(toggle.attributes['aria-expanded'],'true');
  assert.equal(nodes.get('crew-insights').hidden,false);
  assert.equal(document.activeElement,nodes.get('crew-close'));
  assert.equal(nodes.get('comparison-card').hidden,false);
  assert.equal(nodes.get('timeline-card').hidden,false);
  nodes.get('crew-close').events.click();
  assert.equal(toggle.attributes['aria-expanded'],'false');assert.equal(document.activeElement,toggle);
  toggle.events.click();let prevented=false;
  nodes.get('crew-panel').events.keydown({key:'Escape',preventDefault(){prevented=true;}});
  assert.ok(prevented);assert.equal(nodes.get('crew-insights').hidden,true);
  assert.equal(document.activeElement,toggle);
  assert.match(nodes.get('evidence-context').textContent,/ MET/);
  insights.observe({...p,blind_incident:{id:9,phase:'complete'},anomaly_assessment:{alert_level:'CRITICAL_RED'}});
  assert.equal(nodes.get('plain-assessment').hidden,false);
  insights.observe({...p,timestamp:'2026-11-15T15:00:01Z',blind_incident:{id:9,phase:'complete'},anomaly_assessment:{alert_level:'NOMINAL'}});
  for(const id of ['plain-assessment','evidence-card'])assert.equal(nodes.get(id).hidden,true);
  for(const id of ['plain-title','plain-summary','plain-score','plain-source','insight-state'])assert.equal(nodes.get(id).textContent,'');
  assert.equal(nodes.get('technical-assessment').open,true);
  assert.equal(nodes.get('comparison-card').hidden,false);assert.equal(nodes.get('timeline-card').hidden,false);
  assert.match(nodes.get('incident-events').textContent,/Backend confirms nominal/);
  insights.observe(p);insights.receiveAssessment(data.cases.hypercapnia.assessment,p);
  assert.equal(nodes.get('plain-assessment').hidden,true);
  const medical=new MedicalPanel(async()=>{});medical.render(data.cases.hypercapnia.assessment);
  assert.ok(!nodes.get('assessment-details').children.some(block=>block.children.some(child=>child.tagName==='b' && child.textContent==='VERIFICATION')));
  assert.match(nodes.get('assessment-details').textContent,/UNVERIFIED_SIMULATION_CONTENT/);
});

test('dashboard separates random simulation from explicit consultation and ignores stale incident results', async () => {
  const originals={fetch:globalThis.fetch,WebSocket:globalThis.WebSocket,location:globalThis.location,window:globalThis.window,querySelector:document.querySelector};
  const events={},calls=[];
  class Socket {
    static OPEN=1;static CONNECTING=0;readyState=1;
    constructor(){Socket.current=this;}close(){this.readyState=3;}
  }
  globalThis.location={search:'',protocol:'http:',hostname:'localhost',origin:'http://localhost:5500'};
  globalThis.window={addEventListener:(name,cb)=>{events[name]=cb;}};
  globalThis.WebSocket=Socket;document.querySelector=document.getElementById;
  const button=document.getElementById('run-assessment');button.classList={add(){},remove(){}};
  globalThis.fetch=async(url,options)=> {
    if(url==='data/baselines.json')return {ok:true,json:async()=>baselines};
    if(url==='data/user_explanations.json')return {ok:true,json:async()=>({protocols:{}})};
    calls.push([url.pathname,options?.body?JSON.parse(options.body):null]);
    return {ok:true,json:async()=>({status:'ok',incident_id:3})};
  };
  function send(incident,tick,phase,diagnosis,alert='NOMINAL') {
    const p={...sample(),simulation_incident:incident,timestamp:new Date(Date.UTC(2026,10,15,12,0,tick)).toISOString()};
    if(phase) {delete p.active_scenario_id;p.blind_incident={id:incident,phase,actions:[]};p.anomaly_assessment={alert_level:alert};}
    if(phase==='awaiting_doctor'){p.vitals.spo2=86;p.anomaly_assessment={organ_hud_status:{'ECLSS-03':'RED'}};}
    if(diagnosis)p.rag_diagnosis=diagnosis;
    Socket.current.onmessage({data:JSON.stringify(p)});
  }
  try {
    await import('../js/app.js');
    for(let i=0;i<30&&!Socket.current;i++)await new Promise(r=>setTimeout(r,5));
    assert.ok(Socket.current);Socket.current.onopen();
    send(2,0,null,data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    await button.events.click();
    assert.deepEqual(calls,[['/api/scenarios/simulate-crisis',{streaming:true}]]);
    send(2,1,null,data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    send(3,2,'observing');assert.equal(document.getElementById('analyze-crisis').disabled,true);
    send(3,3,'awaiting_doctor');
    assert.equal(document.getElementById('plain-assessment').hidden,true);
    assert.match(document.getElementById('telemetry-alert').textContent,/Critical telemetry/);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    const consult=document.getElementById('analyze-crisis');assert.equal(consult.disabled,false);
    await consult.events.click();await consult.events.click();
    assert.deepEqual(calls[1],['/api/scenarios/analyze-crisis',{incident_id:3}]);assert.equal(calls.length,2);
    send(3,4,'assessed',data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('plain-assessment').hidden,false);
    assert.equal(document.getElementById('technical-assessment').open,false);
    assert.match(document.getElementById('result-mode').textContent,/MODE A/);
    assert.match(document.getElementById('assessment-latency').textContent,/CONSULTATION \d+ ms/);
    send(3,5,'recovering',data.cases.hypercapnia.assessment);
    assert.match(document.getElementById('assessment-freshness').textContent,/newer telemetry/);
    send(2,6,null,data.cases['zero-day'].assessment);assert.match(document.getElementById('result-mode').textContent,/MODE A/);
    // Completion must also be nominal; the old diagnosis remains until then.
    send(3,7,'complete',data.cases.hypercapnia.assessment,'CRITICAL');
    assert.match(document.getElementById('result-mode').textContent,/MODE A/);
    assert.equal(button.disabled,true);
    send(3,8,'complete',data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('plain-assessment').hidden,true);
    assert.equal(document.getElementById('evidence-card').hidden,true);
    assert.equal(document.getElementById('plain-title').textContent,'');
    assert.equal(document.getElementById('technical-assessment').open,true);
    assert.match(document.getElementById('incident-events').textContent,/Backend confirms nominal/);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    assert.equal(document.getElementById('diagnosis-title').textContent,'Monitoring telemetry');
    assert.equal(document.getElementById('confidence-meter').style.width,'0%');
    assert.equal(document.getElementById('assessment-details').children.length,0);
    assert.equal(document.getElementById('apply-treatment').disabled,true);
    assert.equal(document.getElementById('send-earth').hidden,true);
    assert.equal(document.getElementById('download-report').hidden,true);
    assert.equal(document.getElementById('blind-status').hidden,true);
    assert.equal(button.disabled,false);
    send(3,7,'assessed',data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('plain-assessment').hidden,true);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    send(3,9,'complete',data.cases.hypercapnia.assessment);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    // A subsequent Mode B incident must clear in exactly the same way.
    await button.events.click();send(4,10,'awaiting_doctor');await consult.events.click();
    send(4,11,'assessed',data.cases['zero-day'].assessment);
    assert.match(document.getElementById('result-mode').textContent,/MODE B/);
    send(4,12,'recovering',data.cases['zero-day'].assessment);
    assert.match(document.getElementById('result-mode').textContent,/MODE B/);
    send(4,13,'complete',data.cases['zero-day'].assessment);
    assert.equal(document.getElementById('result-mode').textContent,'AWAITING ASSESSMENT');
    assert.equal(button.disabled,false);
    const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
    assert.ok(!html.includes('id="rehearsal-toggle"'));assert.ok(!html.includes('id="data-mode"'));
    assert.ok(!calls.some(x=>x[0]==='/api/diagnose'));
  } finally {
    events.pagehide?.();document.querySelector=originals.querySelector;delete originals.querySelector;Object.assign(globalThis,originals);
  }
});
