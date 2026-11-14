import {test} from 'node:test';
import assert from 'node:assert/strict';
import {advancePhase,TAU,heartbeatScale,inspiration,focusTargets,targetForMesh,fitDistance,visualStyle,smoothStep} from '../js/body_dynamics.js';
test('heartbeat and respiration complete one cycle at their respective observed rates',()=> {
  let heart=0,breath=0;
  for(let tick=0;tick<400;tick++){heart=advancePhase(heart,75,.002);breath=advancePhase(breath,15,.01);}
  assert.ok(heart<1e-10 || Math.abs(TAU-heart)<1e-10);assert.ok(breath<1e-10 || Math.abs(TAU-breath)<1e-10);
  assert.equal(heartbeatScale(0),1);assert.ok(heartbeatScale(Math.PI/2)>1);assert.equal(heartbeatScale(Math.PI*1.5),1);
  assert.equal(inspiration(0),0);assert.equal(inspiration(Math.PI),1);
});
test('rate changes preserve phase; missing, stale or reduced-motion inputs do not advance it',()=> {
  const phase=1.3;assert.ok(Math.abs(advancePhase(phase,120,.1)-(phase+.4*Math.PI))<1e-12);
  for(const rate of [undefined,null,NaN,0,-1])assert.equal(advancePhase(phase,rate,.1),phase);
  assert.equal(advancePhase(phase,75,.1,false),phase);
});
test('brain and eyes are separate targets while paired lungs and eyes share a focus frame',()=> {
  assert.equal(targetForMesh('BRAIN'),'brain');assert.equal(targetForMesh('EYE_LEFT'),'eyes');assert.equal(targetForMesh('OPTIC_NERVE_RIGHT'),'eyes');
  assert.equal(focusTargets.brain.region,focusTargets.eyes.region);assert.ok(!focusTargets.brain.meshes.includes('EYE_LEFT'));
  assert.deepEqual(focusTargets.lungs.meshes,['LUNG_LEFT','LUNG_RIGHT']);
});
test('holographic eyes are subdued, focus dims other organs, and alerts keep their colors',()=> {
  assert.ok(visualStyle('EYE_LEFT','cyan',false,false).opacity<.2);
  assert.equal(visualStyle('EYE_LEFT','cyan',false,false).color,visualStyle('EYE_RIGHT','cyan',false,false).color);
  assert.ok(visualStyle('BRAIN','cyan',false,true).opacity<visualStyle('BRAIN','cyan',false,false).opacity);
  assert.ok(visualStyle('HEART','cyan',true,true).opacity>visualStyle('BRAIN','cyan',false,true).opacity);
  assert.equal(visualStyle('HEART','red',true,true).color,0xff657a);assert.equal(visualStyle('BRAIN','amber',true,true).color,0xffbf69);
});
test('narrow viewports fit the complete bounds and organ zoom requires less distance than overview',()=> {
  const body={x:.514,y:.689,z:.268},heart={x:.119,y:.121,z:.113};
  assert.ok(fitDistance(body,.4,34)>fitDistance(body,1,34));assert.ok(fitDistance(heart,1,34)<fitDistance(body,1,34));
  assert.equal(smoothStep(0),0);assert.equal(smoothStep(1),1);assert.ok(smoothStep(.5)>.5);
});
