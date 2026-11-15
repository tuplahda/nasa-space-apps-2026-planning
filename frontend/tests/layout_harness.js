import {Backend} from '../js/scenarios.js';
const api=new Backend(new URLSearchParams(location.search).get('api')||'http://localhost:8001');
const frame=document.getElementById('app'),phase=document.getElementById('phase'),results=document.getElementById('results'),preview=document.getElementById('preview');
let width=1366,height=768,running=false;const errors=[];
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function log(line){results.textContent+=line+'\n';fitPreview();}
function fitPreview(){const scale=Math.min(1,(innerWidth-24)/width,Math.max(280,innerHeight-preview.offsetTop-16)/height);frame.style.width=width+'px';frame.style.height=height+'px';frame.style.transform=`scale(${scale})`;preview.style.width=width*scale+'px';preview.style.height=height*scale+'px';}
async function until(check,message,timeout=20000){const start=performance.now();let lastError='';while(performance.now()-start<timeout){try{const value=await check();if(value)return value;}catch(error){lastError=error.message;}await wait(200);}throw new Error(message+(lastError?' · '+lastError:''));}
async function dimensions(w,h){
  width=w;height=h;fitPreview();await wait(160);
  const doc=frame.contentDocument,win=frame.contentWindow,q=s=>doc.querySelector(s),rect=s=>q(s).getBoundingClientRect();
  const checks={viewport:win.innerWidth===w&&win.innerHeight===h,pageWidth:doc.documentElement.scrollWidth<=w+1,pageHeight:Math.max(doc.documentElement.scrollHeight,doc.body.scrollHeight)<=h+1,
    noFooter:!q('footer'),noRepeatedMotion:!q('#animation-status'),leftFits:q('.telemetry-panel').scrollHeight<=q('.telemetry-panel').clientHeight+1,
    bottomFits:q('.model-bottom-panel').scrollHeight<=q('.model-bottom-panel').clientHeight+1&&rect('.model-bottom-panel').bottom<=h+1,
    canvasAboveBottom:rect('#body-canvas').bottom<=rect('.model-bottom-panel').top+1,modelVisible:rect('#body-canvas').height>150,
    doctorScroll:['auto','scroll'].includes(win.getComputedStyle(q('.clinical-panel')).overflowY),controlsVisible:rect('#run-assessment').right<=w&&rect('#analyze-crisis').right<=w,
    lastVitalVisible:rect('#activity-badge').bottom<=rect('.telemetry-panel').bottom,
    crewVisible:rect('#astronaut-id').bottom<=rect('.telemetry-column').bottom};
  const failed=Object.entries(checks).filter(([,pass])=>!pass).map(([name])=>name);
  log(`${failed.length?'FAIL':'PASS'} ${w}×${h}: ${failed.length?failed.join(', '):'page, left panel, model and bottom panel fit; doctor scrolling only'}`);
  log(`  page=${doc.documentElement.scrollWidth}×${doc.documentElement.scrollHeight}; left=${q('.telemetry-panel').clientHeight}/${q('.telemetry-panel').scrollHeight}; canvas=${Math.round(rect('#body-canvas').height)}px; browserErrors=${errors.length}`);
  phase.textContent=failed.length?'Layout checks failed: '+failed.join(', '):'Layout checks passed at '+w+' × '+h;
  return checks;
}
frame.addEventListener('load',async()=>{
  const win=frame.contentWindow;win.addEventListener('error',e=>errors.push(e.message));win.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
  try{await until(()=>frame.contentDocument.getElementById('body-canvas')?.dataset.loaded==='true','GLB did not load',15000);await dimensions(width,height);}catch(error){phase.textContent='FAIL: '+error.message;}
});
frame.src='../index.html?api='+encodeURIComponent(api.base);fitPreview();
window.addEventListener('resize',fitPreview);
document.getElementById('size-1366').onclick=()=>{if(!running)void dimensions(1366,768);};
document.getElementById('size-1920').onclick=()=>{if(!running)void dimensions(1920,1080);};
document.getElementById('crew-check').onclick=async()=>{
  if(running)return;
  const doc=frame.contentDocument,q=id=>doc.getElementById(id),comparison=q('comparison-card'),timeline=q('timeline-card');
  try {
    if(q('crew-toggle').getAttribute('aria-expanded')!=='true')q('crew-toggle').click();
    comparison.open=true;timeline.open=true;await wait(200);
    const panel=q('crew-panel').getBoundingClientRect(),body=doc.querySelector('.body-panel').getBoundingClientRect();
    if(!q('crew-panel').contains(comparison)||!q('crew-panel').contains(timeline)||doc.querySelector('.clinical-panel').contains(comparison))throw new Error('History is not owned by the crew panel');
    if(panel.right>body.left||panel.bottom>height||doc.documentElement.scrollWidth>width||doc.documentElement.scrollHeight>height)throw new Error('Crew history overlaps or overflows the dashboard');
    if(q('crew-insights').scrollWidth>q('crew-insights').clientWidth)throw new Error('Crew history has horizontal overflow');
    if(/\bMUT\b/.test(doc.body.innerText))throw new Error('A visible MUT label remains');
    log(`PASS ${width}×${height}: existing crew history fits its column; no overlap, page scroll or MUT labels; browserErrors=${errors.length}`);
    phase.textContent='Crew history verified. Close it with Close crew history or Escape.';
  }catch(error){phase.textContent='FAIL: '+error.message;log('FAIL '+error.message);}
};
async function liveCase(seed) {
  if(running)return;running=true;phase.textContent='Resetting isolated simulator…';
  const doc=frame.contentDocument,q=id=>doc.getElementById(id);
  try {
    await api.trigger('nominal');await api.snapshot('nominal');
    const ack=await api.startBlindCrisis(seed);
    await until(async()=>{const p=await api.snapshot();return p.blind_incident?.id===ack.incident_id&&p.blind_incident.phase==='awaiting_doctor'&&p;},'No consultation-ready incident');
    await until(()=>!q('analyze-crisis').disabled,'Consultation control did not enable');q('analyze-crisis').click();
    const assessed=await until(async()=>{const p=await api.snapshot();return p.blind_incident?.id===ack.incident_id&&p.blind_incident.phase==='assessed'&&p;},'Doctor did not return assessment');
    const a=assessed.rag_diagnosis,reference=a.earth_report.report_ref;
    if([...q('assessment-details').querySelectorAll('b')].some(node=>node.textContent==='VERIFICATION'))throw new Error('Verification subtitle is still displayed');
    log(`REAL ASSESSMENT ${a.mode}; raw confidence=${a.confidence}; report=${reference.slice(0,12)}`);
    if(a.confidence>=.75) {
      await until(()=>!q('send-earth').hidden,'Send to Earth was not shown');
      phase.textContent='ACTION: click Send to Earth in the doctor panel to verify the manual browser download.';
      await until(()=>q('report-status').textContent.startsWith('PDF download requested.'),'Manual report download was not requested',120000);
    } else {
      await until(()=>q('report-status').textContent.includes('Automatic PDF download requested')||!q('report-error').hidden,'Automatic PDF request did not finish');
      if(!q('report-error').hidden)throw new Error(q('report-error').textContent);
      log('Automatic PDF initiation confirmed in production UI; inspect Chrome Downloads for the saved file.');
    }
    const inputs=[...doc.querySelectorAll('#treatment-checklist input')];
    for(const input of inputs){input.checked=true;input.dispatchEvent(new frame.contentWindow.Event('change',{bubbles:true}));}
    const before=await api.snapshot();if(before.blind_incident.phase!=='assessed')throw new Error('Acknowledgement unexpectedly started recovery');
    if(q('apply-treatment').disabled)throw new Error('Treatment did not enable after required acknowledgements');
    phase.textContent='Checklist acknowledged; requesting backend treatment and waiting for nominal telemetry…';q('apply-treatment').click();
    await until(async()=>{const p=await api.snapshot();return p.blind_incident?.id===ack.incident_id&&p.blind_incident.phase==='complete'&&p.anomaly_assessment.alert_level==='NOMINAL';},'Recovery did not complete nominally',18000);
    await until(()=>!q('run-assessment').disabled,'Simulate Crisis did not re-enable');
    await until(()=>q('result-mode').textContent==='AWAITING ASSESSMENT','Doctor panel did not reset after nominal recovery');
    if(q('assessment-details').children.length || !q('send-earth').hidden || !q('download-report').hidden || !q('apply-treatment').disabled)throw new Error('Stale clinical content or controls survived recovery');
    if(!q('plain-assessment').hidden || !q('evidence-card').hidden || q('plain-title').textContent || !q('technical-assessment').open)throw new Error('Doctor insights did not clear to their no-crisis state');
    if(q('comparison-card').hidden || q('timeline-card').hidden)throw new Error('Crew incident history was lost on clinical reset');
    if(doc.querySelector('.clinical-panel').scrollTop!==0)throw new Error('Doctor panel did not scroll back to its default view');
    log(`PASS ${a.mode}: acknowledgements alone had no effect; backend recovery completed nominally; next crisis enabled.`);
    phase.textContent='Live recovery/report check passed. Inspect the browser download and PDF contents.';
    await dimensions(width,height);
  }catch(error){phase.textContent='FAIL: '+error.message;log('FAIL '+error.message);}finally{running=false;}
}
document.getElementById('case-a').onclick=()=>liveCase(2);document.getElementById('case-b').onclick=()=>liveCase(0);
