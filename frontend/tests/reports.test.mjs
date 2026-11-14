import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ReportDownloads,reportPolicy} from '../js/reports.js';
import {Backend} from '../js/scenarios.js';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
class Element {hidden=false;disabled=false;textContent='';events={};addEventListener(name,cb){this.events[name]=cb;}}
let nodes;
function dom(){nodes=new Map();globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};}
function assessment(confidence=.7,ref='a'.repeat(64)) {
  return {confidence,mode:confidence<.75?'MODE_B_NOVEL_ANOMALY':'MODE_A_KNOWN_CONDITION',diagnosis_id:'DIAG-TEST',earth_report:{report_ref:ref,assessment_confidence_raw:confidence,assessment_id:'DIAG-TEST'}};
}
const file={blob:new Blob(['%PDF-1.4\nTEST FIXTURE']),filename:'assessment.pdf'};
function storage(){const values=new Map();return {getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};}
test('raw confidence boundary: .74999 automatic, exactly .75 and above manual',()=> {
  assert.equal(reportPolicy(assessment(.74999)),'automatic');assert.equal(reportPolicy(assessment(.75)),'manual');assert.equal(reportPolicy(assessment(.75001)),'manual');
  assert.equal(reportPolicy({...assessment(.5),mode:'NOMINAL_TELEMETRY'}),'none');assert.equal(reportPolicy(assessment(NaN)),'none');
});
test('automatic report is initiated once across repeated frames, reconnect copies and session recreation',async()=> {
  dom();let fetches=0,downloads=0;const saved=storage(),api={base:'http://test',downloadReport:async()=>{fetches++;return file;}};
  const first=new ReportDownloads(api,{storage:saved,download:()=>downloads++});
  first.setAssessment(assessment(.74999),{incidentId:1});await tick();first.setAssessment(structuredClone(assessment(.74999)),{incidentId:1});await tick();
  assert.equal(fetches,1);assert.equal(downloads,1);assert.equal(nodes.get('download-report').hidden,false);assert.match(nodes.get('report-status').textContent,/If your browser/);
  first.dispose();const second=new ReportDownloads(api,{storage:saved,download:()=>downloads++});second.setAssessment(assessment(.74999),{incidentId:1});await tick();assert.equal(downloads,1);
  second.setAssessment(assessment(.7,'b'.repeat(64)),{incidentId:2});await tick();assert.equal(downloads,2);second.dispose();
});
test('75 percent exposes Send to Earth without auto-download and prevents concurrent duplicate clicks',async()=> {
  dom();let calls=0,downloads=0;const api={base:'http://test',downloadReport:async()=>{calls++;return file;}};
  const controller=new ReportDownloads(api,{storage:storage(),download:()=>downloads++});controller.setAssessment(assessment(.75),{incidentId:1});await tick();
  assert.equal(calls,0);assert.equal(nodes.get('send-earth').hidden,false);assert.equal(nodes.get('download-report').hidden,true);
  await Promise.all([controller.request(),controller.request()]);assert.equal(calls,1);assert.equal(downloads,1);assert.match(nodes.get('report-status').textContent,/does not confirm Earth transmission/);controller.dispose();
});
test('blocked automatic download keeps a user-initiated retry and never silently repeats',async()=> {
  dom();let blocked=true,downloads=0;const controller=new ReportDownloads({base:'http://test',downloadReport:async()=>file},{storage:storage(),download:()=>{if(blocked)throw new Error('Browser blocked automatic downloading');downloads++;}});
  controller.setAssessment(assessment(),{incidentId:4});await tick();assert.match(nodes.get('report-error').textContent,/blocked/);assert.equal(nodes.get('download-report').hidden,false);
  controller.setAssessment(assessment(),{incidentId:4});await tick();assert.equal(downloads,0);blocked=false;await controller.request();assert.equal(downloads,1);assert.equal(nodes.get('report-error').hidden,true);controller.dispose();
});
test('failed PDF request can retry, and an obsolete pending response cannot download after a new incident',async()=> {
  dom();let fail=true,calls=0;const controller=new ReportDownloads({base:'http://test',downloadReport:async()=>{if(fail)throw new Error('API offline');return file;}},{storage:storage(),download:()=>calls++});
  controller.setAssessment(assessment(.9),{incidentId:1});await controller.request();assert.match(nodes.get('report-error').textContent,/API offline/);fail=false;await controller.request();assert.equal(calls,1);controller.dispose();
  let resolve;const pending=new ReportDownloads({base:'http://test',downloadReport:()=>new Promise(r=>{resolve=r;})},{storage:storage(),download:()=>calls++});
  pending.setAssessment(assessment(),{incidentId:1});pending.setAssessment(assessment(.9,'b'.repeat(64)),{incidentId:2});resolve(file);await tick();assert.equal(calls,1);pending.dispose();
});
test('a report must match the displayed assessment raw confidence and identity',async()=> {
  dom();let calls=0;const controller=new ReportDownloads({base:'http://test',downloadReport:async()=>{calls++;return file;}},{storage:storage()});
  const wrong=assessment();wrong.earth_report.assessment_confidence_raw=.99;controller.setAssessment(wrong,{incidentId:1});await tick();assert.equal(calls,0);assert.match(nodes.get('report-error').textContent,/matching immutable/);controller.dispose();
});
test('PDF transport requires matching reference, PDF content-type, real signature and propagates server errors',async()=> {
  const original=globalThis.fetch;const ref='c'.repeat(64),api=new Backend('http://localhost:8000');let kind='valid';
  globalThis.fetch=async(url,options)=> {
    assert.equal(new URL(url).pathname,'/api/reports/download');assert.equal(new URL(url).searchParams.get('format'),'pdf');assert.deepEqual(JSON.parse(options.body),{report_ref:ref});
    if(kind==='error')return new Response(JSON.stringify({detail:'Report expired'}),{status:410,headers:{'content-type':'application/json'}});
    return new Response(kind==='signature'?'not a PDF':'%PDF-1.7\nTest',{headers:{'content-type':kind==='mime'?'text/html':'application/pdf','x-ares-report-ref':kind==='reference'?'other':ref,'content-disposition':'attachment; filename="source_assessment.pdf"'}});
  };
  try {
    const result=await api.downloadReport(ref);assert.equal(result.filename,'source_assessment.pdf');assert.ok(result.blob.size>5);
    for(const [value,message] of [['mime',/not return a PDF/],['reference',/did not match/],['signature',/not a genuine PDF/],['error',/expired/]]){kind=value;await assert.rejects(api.downloadReport(ref),message);}
  } finally {globalThis.fetch=original;}
});
