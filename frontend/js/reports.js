// Download policy uses raw clinical confidence; telemetry updates never request a consultation.
export function reportPolicy(assessment) {
  const c=assessment?.confidence;
  if(typeof c!=='number' || !Number.isFinite(c) || c<0 || c>1)return 'none';
  if(c<.75)return assessment.mode==='NOMINAL_TELEMETRY'?'none':'automatic';
  return 'manual';
}
export class ReportDownloads {
  constructor(api,{download=triggerBrowserDownload,storage}={}) {
    if(storage===undefined){try{storage=globalThis.sessionStorage;}catch{}}
    this.api=api;this.download=download;this.storage=storage;this.version=0;this.attempted=new Set();
    try {this.attempted=new Set(JSON.parse(storage?.getItem('ares-report-auto-v1')||'[]'));}catch{/* Session storage can be unavailable. */}
    this.send=document.getElementById('send-earth');this.retry=document.getElementById('download-report');
    this.send.addEventListener('click',()=>this.request(false));this.retry.addEventListener('click',()=>this.request(false));this.reset();
  }
  message(text,error='') {
    document.getElementById('report-status').textContent=text;
    const node=document.getElementById('report-error');node.textContent=error;node.hidden=!error;
  }
  reset() {
    this.version++;this.abort?.abort();this.current=null;this.busy=false;
    this.send.hidden=true;this.retry.hidden=true;this.send.disabled=false;this.retry.disabled=false;
    this.message('PDF report available after consultation.');
  }
  setAssessment(assessment,{incidentId}={}) {
    const policy=reportPolicy(assessment);if(policy==='none'){this.reset();return;}
    const report=assessment.earth_report;
    if(!report?.report_ref || report.assessment_confidence_raw!==assessment.confidence || report.assessment_id!==assessment.diagnosis_id) {
      this.reset();this.message('PDF unavailable.','The backend did not provide a matching immutable assessment report. Restart the updated backend and request a new consultation.');return;
    }
    const key=JSON.stringify([this.api.base,incidentId??null,assessment.diagnosis_id,report.report_ref]);
    if(this.current?.key===key)return;
    this.reset();this.current={key,policy,reference:report.report_ref};
    this.send.hidden=policy!=='manual';this.retry.hidden=policy!=='automatic';
    if(policy==='manual')this.message('Send to Earth downloads this consultation PDF. A download does not confirm Earth transmission.');
    else if(this.attempted.has(key))this.message('Automatic download was already requested for this assessment. Use Download Report if you need a copy.');
    else {
      this.attempted.add(key);try{this.storage?.setItem('ares-report-auto-v1',JSON.stringify([...this.attempted].slice(-128)));}catch{}
      void this.request(true);
    }
  }
  async request(automatic=false) {
    if(this.busy || !this.current)return;
    const current=this.current,version=this.version;this.busy=true;this.send.disabled=true;this.retry.disabled=true;
    this.abort=new AbortController();this.message('Preparing the selected assessment PDF…');
    try {
      const file=await this.api.downloadReport(current.reference,{signal:this.abort.signal});
      if(version!==this.version || current.key!==this.current?.key)return;
      await this.download(file);
      if(version!==this.version)return;
      this.message(automatic?'Automatic PDF download requested. If your browser did not start it, use Download Report.':'PDF download requested. This does not confirm Earth transmission.');
    } catch(error) {
      if(version!==this.version)return;
      this.retry.hidden=false;
      this.message('No replacement report was downloaded.',`${error.message} If automatic downloads are blocked, use Download Report to retry.`);
    } finally {
      if(version===this.version){this.busy=false;this.send.disabled=false;this.retry.disabled=false;}
    }
  }
  dispose(){this.version++;this.abort?.abort();}
}
export function triggerBrowserDownload({blob,filename}) {
  const url=URL.createObjectURL(blob),anchor=document.createElement('a');
  anchor.href=url;anchor.download=filename;anchor.hidden=true;document.body.append(anchor);
  try {anchor.click();}finally {anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  // Browsers do not expose reliable programmatic proof that a file was saved.
  // The visible retry control stays available without changing security settings.
}
