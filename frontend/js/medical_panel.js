import { setText, finite } from './telemetry.js';
const el=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
const display=x=>typeof x==='string'?x:JSON.stringify(x);
export class MedicalPanel {
  constructor(onRecover) {
    this.onRecover=onRecover; this.version=0; this.audit=[];
    this.submit=document.getElementById('apply-treatment');
    this.submit.addEventListener('click',()=>this.recover());
  }
  reset(message='Waiting for the astronaut agent assessment.') {
    this.signature=null; this.assessment=null; this.version++; this.submitted=false; this.pending=false; this.checks=[]; this.ready=false;
    setText('result-mode','AWAITING ASSESSMENT'); setText('result-severity','—'); setText('diagnosis-title','Monitoring telemetry');setText('diagnosis-summary',message);
    setText('confidence-value','—');document.getElementById('confidence-meter').style.width='0%';
    document.getElementById('treatment-checklist').replaceChildren(el('li','No assessment actions available.','empty-action'));
    document.getElementById('assessment-details').replaceChildren();
    setText('action-count','0');setText('citation-text','Verified NASA citation unavailable.');document.getElementById('citation-text').removeAttribute('title');
    document.getElementById('diagnosis-card').className='diagnosis-card';
    this.submit.hidden=false;
    this.submit.textContent='Administer Treatment';
    this.submit.disabled=true; setText('checklist-status','Checklist records operator acknowledgement only.');this.error('');
    const panel=document.querySelector?.('.clinical-panel');if(panel)panel.scrollTop=0;
  }
  error(message) { const node=document.getElementById('clinical-error');node.hidden=!message;node.textContent=message; }
  render(a) {
    if(!a || typeof a!=='object' || typeof a.mode!=='string' || !finite(a.confidence) || a.confidence<0 || a.confidence>1) {this.error('Invalid assessment response; result not displayed.');return;}
    this.assessment=a; this.error('');
    const nominal=a.mode==='NOMINAL_TELEMETRY'; const modeB=!nominal && (a.confidence<.75 || a.mode.includes('MODE_B'));
    setText('result-mode',`${a.demo?'DEMO · ':''}${nominal?'NOMINAL':modeB?'MODE B · ABSTENTION':'MODE A · KNOWN CONDITION'}`);
    setText('result-severity',a.severity || 'UNAVAILABLE');
    setText('diagnosis-title',modeB?'Unclassified novel anomaly':a.condition || a.diagnosis || 'Condition unavailable');
    setText('diagnosis-summary',a.demo?'Offline example assessment · repository sample snapshot; not a live diagnosis or NASA-verified assessment.':a.abstention_reason || a.clinical_reasoning || 'No assessment explanation supplied.');
    setText('confidence-value',`${Math.round(a.confidence*100)}%`); document.getElementById('confidence-meter').style.width=`${a.confidence*100}%`;
    document.getElementById('diagnosis-card').className=`diagnosis-card ${a.severity?.includes('CLASS_1')?'alert':nominal?'':'warning'}`;
    const details=document.getElementById('assessment-details'); details.replaceChildren();
    const add=(label,value)=>{if(value && (!Array.isArray(value)||value.length)){const block=el('div');if(label)block.append(el('b',label));block.append(el('p',Array.isArray(value)?value.map(display).join('\n'):display(value)));details.append(block);}};
    add('SOURCE',a.source_document || 'Unavailable');
    add(null,a.demo?'UNVERIFIED DEMONSTRATION':a.clinical_protocol_verification_status || a.source_verification_status || 'Verification unavailable');
    if(modeB) {
      add('ABSTENTION REASON',a.abstention_reason);
      add('SYMPTOM-BASED STABILIZATION',a.abc_vital_stabilization?.protocol);
      add('POINT-OF-CARE ORDERS',(a.point_of_care_orders || []).map(x=>[x.order,x.hardware].filter(Boolean).join(' · ')));
      add('DRUG SAFETY LOCKOUT',a.drug_lockout_warning || a.safety_warning);
      const u=a.telemetry_uplink;
      add('EARTH UPLINK',u?`${u.store_and_forward_priority || 'Priority unavailable'} · ${u.uplink_target || 'Target unavailable'} ? Queue reported by backend; delivery not confirmed.`:'Uplink unavailable');
    } else add('CHeCS PACK',a.checs_subpack);
    add('CONTRAINDICATIONS',a.contraindications_locked);
    const c=a.nasa_citation; let verified=false;
    if(!a.demo && a.nasa_direct_quote && c?.url) {
      try {const u=new URL(c.url);verified=u.protocol==='https:' && (u.hostname==='nasa.gov'||u.hostname.endsWith('.nasa.gov'));} catch { /* Unusable citation is not a verified link. */ }
    }
    const citation=document.getElementById('citation-text'); citation.replaceChildren();
    if(verified) {
      const link=el('a',[c.document,c.section].filter(Boolean).join(' · ')); link.href=c.url; link.target='_blank';link.rel='noopener noreferrer';
      citation.append(link,el('span',` · ${a.nasa_direct_quote}`));
      citation.title=a.nasa_direct_quote;
    } else {citation.textContent='Verified NASA citation unavailable for this assessment.';citation.removeAttribute('title');}
    const steps=a.action_checklist || a.action_plan || [];
    const signature=JSON.stringify([a.demo,a.mode,a.condition,steps]);
    // Streamed updates refresh values without losing acknowledgement state.
    if(signature!==this.signature) {
      this.signature=signature;this.version++;this.submitted=false;this.pending=false;this.checks=[];
      const list=document.getElementById('treatment-checklist');list.replaceChildren();
      steps.forEach((step,index)=> {
        const row=el('li',undefined,step.critical?'critical':'');const label=el('label');const input=el('input'); input.type='checkbox'; input.dataset.step=String(step.step ?? index+1);
        const copy=el('span',step.action || 'Action unavailable');
        if(step.critical) copy.prepend(el('b','CRITICAL · ','critical-label'));
        const stamp=el('small',''); label.append(input,copy); row.append(label,stamp);list.append(row);
        const record={input,critical:!!step.critical,step:step.step ?? index+1,action:step.action||'',stamp,administered:false,administeredAt:null};this.checks.push(record);
        input.addEventListener('change',()=> {
          if(record.administered){input.checked=true;return;}
          record.at=input.checked?new Date().toISOString():null;
          stamp.textContent=record.at?`Acknowledged ${new Date(record.at).toLocaleTimeString('en-GB',{timeZone:'Indian/Mauritius'})} MET`:'';
          this.audit.push({assessment:a.diagnosis_id,step:record.step,acknowledged:input.checked,timestamp:new Date().toISOString()});
          if(this.audit.length>200) this.audit.shift(); this.progress();
        });
      });
      if(!steps.length) list.append(el('li','No action checklist returned.','empty-action'));
    }
    this.progress();
  }
  progress() {
    const checks=this.checks || [], done=checks.filter(x=>x.input.checked).length;
    const unadministeredChecked=checks.filter(x=>x.input.checked && !x.administered);
    const administeredCount=checks.filter(x=>x.administered).length;
    this.ready=checks.length>0 && unadministeredChecked.length>0;
    setText('action-count',`${done}/${checks.length}`);
    const blind = this.assessment?.blindIncident;
    const action = blind?.actions?.[0];
    const recovering=blind?.phase==='recovering',complete=blind?.phase==='complete';
    this.submit.textContent=recovering?'Recovering…':complete?'Recovery complete':'Administer Treatment';
    this.submit.title=action?.label || 'Request backend simulated recovery';
    this.submit.hidden=false;
    this.submit.disabled=!this.ready || this.pending || this.submitted || (!!blind && (!action || blind.phase!=='assessed'));
    for(const c of checks) c.input.disabled=this.pending || this.submitted || c.administered;
    setText('checklist-status',recovering?'Backend recovery in progress. Waiting for nominal telemetry.':complete?'Backend recovery completed. Acknowledgements are not administration records.':action?.kind==='simulation_only' && !this.pending && !this.submitted && !administeredCount?`${done}/${checks.length} acknowledged · simulation-only completion; no validated physical treatment is implied.`:this.submitted?'Simulated recovery requested. Acknowledgements do not record treatment administration.':administeredCount>0 && !this.pending?`${administeredCount}/${checks.length} administered · check remaining tasks to complete recovery.`:this.pending?'Requesting simulated recovery…':`${this.assessment?.demo?'LOCAL DEMONSTRATION · ':''}${done}/${checks.length} acknowledged · session only; no medical administration recorded.`);
  }
  async recover() {
    if(!this.ready || this.pending || this.submitted || this.submit.disabled) return;
    const version=this.version,administeredAt=new Date().toISOString();
    const newlyChecked=this.checks.filter(x=>x.input.checked && !x.administered);
    const allChecked=this.checks.filter(x=>x.input.checked || x.administered);
    const partial=allChecked.length<this.checks.length;
    this.pending=true;this.progress();this.error('');
    try {
      await this.onRecover({
        newlyChecked:newlyChecked.map(x=>x.step),
        acknowledgedSteps:allChecked.map(x=>x.step),
        totalSteps:this.checks.length,
        partial,
        administeredAt,
        steps:this.checks.map(x=>({step:x.step,action:x.action,critical:x.critical})),
      });
      if(version===this.version) {
        const timeStr=new Date(administeredAt).toLocaleTimeString('en-GB',{timeZone:'Indian/Mauritius'});
        for(const c of newlyChecked) {
          c.administered=true;c.administeredAt=administeredAt;
          c.stamp.textContent=`Administered ${timeStr} MET`;
        }
        this.submitted=!partial;
      }
    }
    catch(e) { if(version===this.version)this.error(`Recovery failed: ${e.message}. You may retry.`); }
    finally {if(version===this.version){this.pending=false;this.progress();}}
  }
}
