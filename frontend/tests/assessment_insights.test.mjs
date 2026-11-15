import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {IncidentInsights, METRICS, evidenceFor, explainAssessment, reading} from '../js/assessment_insights.js';

const catalog=JSON.parse(await readFile(new URL('../data/user_explanations.json',import.meta.url),'utf8'));
const protocols=JSON.parse(await readFile(new URL('../../data/rag_protocols_expanded.json',import.meta.url),'utf8'));
const fixtures=JSON.parse(await readFile(new URL('../data/demo_cases.json',import.meta.url),'utf8'));
const assessment=()=>structuredClone(fixtures.cases.hypercapnia.assessment);
const packet=(second=0,overrides={})=>({
  ...structuredClone(fixtures.cases.hypercapnia.packet),
  timestamp:`2026-11-15T06:00:${String(second).padStart(2,'0')}Z`,met:`084:10:00:${String(second).padStart(2,'0')}`,
  astronaut_id:'ASTRO-01',simulation_incident:7,
  anomaly_assessment:structuredClone(fixtures.cases.hypercapnia.assessment.layer2_assessment),
  blind_incident:{id:7,phase:'awaiting_doctor'},...overrides,
});

test('all forty stored explanations point to matching original project records',()=>{
  assert.equal(catalog.review_status,'project_authored_not_clinically_reviewed');
  assert.equal(Object.keys(catalog.protocols).length,40);
  for(const [id,entry] of Object.entries(catalog.protocols)) {
    const [,collection,index]=entry.source_pointer.split('/');
    const record=protocols[collection][Number(index)];
    assert.equal(record.protocol_id||record.scenario_id,id);
    assert.equal(entry.technical_title,record.title);
    for(const field of entry.source_fields)assert.ok(field in record);
    assert.ok(entry.title && entry.summary);
    assert.doesNotMatch(entry.summary,/\b\d+\b/,'explanations must not invent clinical numbers or doses');
  }
});

test('explanations use the recorded decision only and never infer a cause for Mode B or unknown IDs',()=>{
  assert.equal(explainAssessment(assessment(),catalog).title,'Excess carbon dioxide exposure');
  assert.match(explainAssessment({...assessment(),mode:'MODE_B_NOVEL_ANOMALY'},catalog).title,/not been identified/);
  assert.match(explainAssessment({...assessment(),scenario_id:'NEW-UNREVIEWED'},catalog).title,/unavailable/);
  assert.match(explainAssessment({...assessment(),confidence:.74},catalog).title,/not been identified/);
});

test('before consultation, unsolicited diagnoses and hidden simulator labels produce no explanation or comparison',()=>{
  const m=new IncidentInsights();
  m.observe(packet(0,{active_scenario_id:'hypercapnia',rag_diagnosis:assessment()}));
  assert.equal(m.assessment,null);assert.equal(m.before,null);assert.equal(m.after,null);
  assert.ok(!m.events.some(event=>event.key==='assessment'));
});

test('evidence preserves backend ranges, reported symptoms, and consultation snapshots',()=>{
  const m=new IncidentInsights(),p=packet(),a=assessment();
  const original=JSON.stringify(a);
  m.requestConsultation(p,'2026-11-15T06:00:01Z');
  assert.equal(m.receiveAssessment(a,p),true);
  const row=m.evidence.rows.find(row=>row.label==='Cabin carbon dioxide');
  assert.match(row.value,/12\.8/);assert.equal(row.range,'< 2.0 mmHg');
  p.symptom_log='Later symptom report';a.clinical_reasoning='Later edit';
  assert.notEqual(m.evidence.symptoms,p.symptom_log);
  assert.equal(m.assessment.clinical_reasoning,JSON.parse(original).clinical_reasoning);
  assert.equal(m.events.find(e=>e.key.startsWith('request-')).origin,'browser request');
  assert.equal(m.events.find(e=>e.key==='assessment').origin,'browser receipt');
});

test('failed or repeated assessment frames cannot overwrite the original explanation and evidence',()=>{
  const m=new IncidentInsights(),p=packet();m.observe(p);
  assert.equal(m.receiveAssessment({...assessment(),confidence:2},p),false);
  assert.equal(m.receiveAssessment(assessment(),p),true);
  assert.equal(m.receiveAssessment({...assessment(),scenario_id:'CPG-32'},packet(1)),false);
  assert.equal(m.assessment.scenario_id,'SCENARIO_1_HYPERCAPNIA');
});

test('action request freezes its actual before snapshot; completion requires nominal backend telemetry',()=>{
  const m=new IncidentInsights(),p=packet();m.observe(p);m.receiveAssessment(assessment(),p);
  const before=packet(2);before.vitals.heart_rate=120;
  m.requestAction(before,'2026-11-15T06:00:03Z');
  before.vitals.heart_rate=999;
  const recovering=packet(4,{blind_incident:{id:7,phase:'recovering'}});recovering.vitals.heart_rate=90;
  m.observe(recovering);
  const heart=m.comparison().find(row=>row.key==='heart_rate');
  assert.equal(heart.before,120);assert.equal(heart.after,90);assert.equal(heart.delta,-30);
  assert.ok(m.recoveryStarted);assert.equal(m.complete,false);
  m.observe(packet(5,{blind_incident:{id:7,phase:'complete'},anomaly_assessment:{alert_level:'CRITICAL_RED'}}));
  assert.equal(m.complete,false);
  const done=packet(6,{blind_incident:{id:7,phase:'complete'},anomaly_assessment:{alert_level:'NOMINAL'}});
  m.observe(done);assert.equal(m.complete,true);
  m.observe(packet(7));assert.equal(m.after.timestamp,done.timestamp);
  assert.equal(m.events.filter(event=>event.key==='complete').length,1);
});

test('missing, unreliable and SEU-filtered channels never generate invented values or deltas; zero is valid',()=>{
  const oxygen=METRICS.find(row=>row.key==='spo2'),radiation=METRICS.find(row=>row.key==='ambient_radiation_msv_h');
  const p=packet();p.unreliable_channels=['spo2_pct'];p.environment.ambient_radiation_msv_h=0;
  assert.equal(reading(p,oxygen),null);assert.equal(reading(p,radiation),0);
  const a=assessment();a.layer2_assessment.breached_parameters.push({parameter:'spo2_pct',value:88,unit:'%',expected_ug_range:'backend reference'});
  assert.equal(evidenceFor(a,p).rows.at(-1).value,'Unavailable / unreliable');
  const m=new IncidentInsights();m.observe(p);m.receiveAssessment(a,p);
  assert.equal(m.comparison().find(row=>row.key==='spo2').delta,null);
  p.unreliable_channels=[];p.quality_flags={spo2:'motion_artifact_unreliable'};assert.equal(reading(p,oxygen),null);
  p.quality_flags={};p.anomaly_assessment.seu_candidates_filtered=['spo2_pct: rejected jump'];assert.equal(reading(p,oxygen),null);
});

test('new incidents and crew changes clear prior observations; late failed actions cannot contaminate them',()=>{
  const m=new IncidentInsights(),old=packet();m.observe(old);m.receiveAssessment(assessment(),old);
  m.observe(packet(1,{simulation_incident:8,blind_incident:{id:8,phase:'observing'}}));
  m.failure('Simulated action failed',old);
  assert.equal(m.assessment,null);assert.equal(m.history.length,0);assert.equal(m.events.some(e=>e.label==='Simulated action failed'),false);
  assert.equal(m.receiveAssessment(assessment(),old),false);
  m.receiveAssessment(assessment(),packet(2,{simulation_incident:8}));
  m.observe(packet(3,{astronaut_id:'OTHER-CREW',simulation_incident:8}));assert.equal(m.assessment,null);
});

test('request failures are recorded without claiming treatment or recovery; sample history stays bounded',()=>{
  const m=new IncidentInsights(),p=packet();m.observe(p);m.receiveAssessment(assessment(),p);
  m.requestAction(packet(1));m.failure('Simulated action failed');
  assert.equal(m.actionRequested,false);assert.equal(m.recoveryStarted,false);
  for(let i=0;i<120;i++)m.observe({...packet(),timestamp:new Date(Date.parse(p.timestamp)+i*1000).toISOString()});
  assert.equal(m.history.length,60);
  assert.equal(m.events.filter(event=>event.key==='anomaly').length,1);
  assert.equal(m.events.some(event=>event.key==='recovery'),false);
});
