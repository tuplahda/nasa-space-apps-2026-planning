// Requires the existing backend on :8000 and frontend HTTP server on :5500.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Backend} from '../js/scenarios.js';
import {TelemetryConnection} from '../js/websocket.js';
import {validatePacket,diagnosisPayload} from '../js/telemetry.js';
const api=new Backend('http://localhost:8000');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const originalState=await api.request('/api/simulation/state');
const fixture=JSON.parse(await readFile(new URL('../data/demo_cases.json',import.meta.url)));
const health=await api.request('/health');assert.equal(health.status,'NOMINAL');
let connection;
try {
  for(const path of ['/','/style.css','/js/app.js','/js/body_hud.js','/js/websocket.js','/js/telemetry.js','/js/scenarios.js','/js/mock_data.js','/js/medical_panel.js','/vendor/three/three.module.js','/vendor/three/addons/loaders/GLTFLoader.js','/vendor/three/addons/controls/OrbitControls.js','/vendor/three/addons/utils/BufferGeometryUtils.js','/assets/models/ares_upper_body_hologram.glb','/data/baselines.json','/data/demo_cases.json']) {
    const response=await fetch('http://localhost:5500'+path);assert.equal(response.status,200,path);await response.arrayBuffer();
  }
  console.log('PASS: all HTML, CSS, modules, GLB and local dependencies served via HTTP');
  const cors=await fetch('http://localhost:8000/api/diagnose',{method:'OPTIONS',headers:{Origin:'http://localhost:5500','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}});
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
  console.log('ALL INTEGRATION CHECKS PASSED');
} finally {
  connection?.stop();
  await api.request('/api/scenarios/trigger',{scenario:originalState.active_scenario || 'nominal'});
}
