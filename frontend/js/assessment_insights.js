// Presentation only: this module never diagnoses, changes treatment, or writes reports.
import { finite } from './telemetry.js';

export const METRICS = [
  {key:'heart_rate', parameter:'hr_bpm', group:'vitals', label:'Heart rate', unit:'bpm', digits:1},
  {key:'blood_pressure_sys', parameter:'sbp_mmHg', group:'vitals', label:'Blood pressure (upper)', unit:'mmHg', digits:1},
  {key:'blood_pressure_dia', parameter:'dbp_mmHg', group:'vitals', label:'Blood pressure (lower)', unit:'mmHg', digits:1},
  {key:'spo2', parameter:'spo2_pct', group:'vitals', label:'Blood oxygen', unit:'%', digits:1},
  {key:'respiration_rate', parameter:'rr_bpm', group:'vitals', label:'Breathing rate', unit:'/min', digits:1},
  {key:'hrv_ms', parameter:'hrv_rmssd_ms', group:'vitals', label:'Heart-rate variability', unit:'ms', digits:1},
  {key:'core_temp_c', parameter:'cbt_C', group:'vitals', label:'Core temperature', unit:'°C', digits:2},
  {key:'cabin_co2_mmhg', parameter:'cabin_ppCO2_mmHg', group:'environment', label:'Cabin carbon dioxide', unit:'mmHg', digits:2},
  {key:'ambient_radiation_msv_h', parameter:'ambient_radiation_msv_h', group:'environment', label:'Radiation rate', unit:'mSv/h', digits:3},
  {key:'suit_pressure_psi', parameter:'suit_pressure_psi', group:'environment', label:'Suit pressure', unit:'psi', digits:2},
];
const byParameter = new Map(METRICS.map(metric=>[metric.parameter,metric]));
const invalidFlag = /fault|missing|seu|unreliable|invalid|artifact/i;
const snapshot = packet => packet ? structuredClone(Object.fromEntries([
  'timestamp','met','mission_day','astronaut_id','simulation_incident','vitals','environment',
  'symptom_log','quality_flags','missing_vitals','unreliable_channels','anomaly_assessment',
].filter(key=>packet[key]!==undefined).map(key=>[key,packet[key]]))) : null;
const scopeOf = packet => JSON.stringify([packet?.astronaut_id??null,packet?.simulation_incident??null]);

export function reading(packet, metric) {
  const absent = [...(packet?.missing_vitals||[]),...(packet?.unreliable_channels||[])];
  const flag = packet?.quality_flags?.[metric.key] || packet?.quality_flags?.[metric.parameter] || '';
  const filtered = packet?.anomaly_assessment?.seu_candidates_filtered || [];
  if(absent.includes(metric.key) || absent.includes(metric.parameter) || invalidFlag.test(String(flag))
    || filtered.some(value=>String(value).startsWith(metric.parameter+':'))) return null;
  const value = packet?.[metric.group]?.[metric.key];
  return finite(value)?value:null;
}

export function explainAssessment(assessment, catalog={}) {
  if(assessment?.mode==='NOMINAL_TELEMETRY') return {
    title:'No monitoring alerts in this assessment',
    summary:'The recorded assessment found no monitoring threshold breaches. Continue observing the readings.',
    source:'Recorded backend assessment',
  };
  if(assessment?.mode?.includes('MODE_B') || assessment?.confidence<.75) return {
    title:'The cause has not been identified',
    summary:'The system did not identify a supported condition with enough confidence. Its checklist focuses on stabilization and further checks.',
    source:'Project Mode B response; no disease explanation inferred',
  };
  const entry=catalog.protocols?.[assessment?.scenario_id];
  return entry ? {title:entry.title,summary:entry.summary,source:`Explanation of project protocol ${assessment.scenario_id}`} : {
    title:'Plain-English explanation unavailable',
    summary:'No stored explanation matches this assessment. Open the technical assessment for the original wording.',
    source:'No matching explanation; no substitute condition selected',
  };
}

export function evidenceFor(assessment, packet) {
  const edge=assessment?.layer2_assessment || packet?.anomaly_assessment;
  const rows=(Array.isArray(edge?.breached_parameters)?edge.breached_parameters:[]).slice(0,16).map(breach=>{
    const metric=byParameter.get(breach.parameter);
    const valid=metric ? reading(packet,metric)!==null : false;
    return {
      label:metric?.label || breach.display_name || breach.parameter || 'Unlabelled observation',
      value:valid && finite(breach.value)?`${breach.value} ${breach.unit||metric.unit}`:'Unavailable / unreliable',
      range:breach.expected_ug_range || 'Reference not supplied',
      flag:valid?(breach.severity==='CRITICAL_RED'?'Critical flag':'Monitoring flag'):'Reading excluded',
      source:breach.standard_ref || 'Backend monitoring assessment',
    };
  });
  return {rows,symptoms:packet?.symptom_log || 'No symptom text supplied.',
    quality:[...(packet?.missing_vitals||[]),...(packet?.unreliable_channels||[])],
    context:edge?.context_evaluated || packet?.activity_state || 'Context not supplied'};
}

export class IncidentInsights {
  constructor() { this.reset(null); }
  reset(scope) {
    this.scope=scope;this.events=[];this.seen=new Set();this.current=null;this.assessment=null;
    this.consultation=null;this.evidence=null;this.before=null;this.after=null;this.lastActionAt=null;
    this.history=[];this.actionRequested=false;this.recoveryStarted=false;this.complete=false;this.stale=false;
  }
  event(key,label,packet=this.current,origin='telemetry',timestamp=packet?.timestamp) {
    if(this.seen.has(key))return;
    this.seen.add(key);
    this.events.push({key,label,timestamp:timestamp||null,met:packet?.met||null,origin});
    if(this.events.length>32)this.events.shift();
  }
  observe(packet) {
    const scope=scopeOf(packet);
    if(scope!==this.scope)this.reset(scope);
    if(this.complete)return;
    this.current=snapshot(packet);this.stale=false;
    const incident=packet.blind_incident;
    if(incident)this.event('incident','Incident first observed');
    if(['WARNING_YELLOW','CRITICAL_RED'].includes(packet.anomaly_assessment?.alert_level))this.event('anomaly','Abnormal readings flagged');
    if(incident?.phase==='recovering' || packet.recovery_status==='ACTIVE') {
      this.recoveryStarted=true;this.event('recovery','Backend recovery started');
    }
    if(this.assessment) {
      this.after=snapshot(packet);
      const last=this.history.at(-1);
      if(!last || last.timestamp!==packet.timestamp) {
        this.history.push({timestamp:packet.timestamp,value:reading(packet,METRICS[0])});
        if(this.history.length>60)this.history.shift();
      }
    }
    const completed=incident?.phase==='complete' || (!incident && packet.recovery_status==='COMPLETE' && packet.active_scenario_id==='nominal');
    if(completed && packet.anomaly_assessment?.alert_level==='NOMINAL') {
      this.event('complete','Backend confirms nominal monitoring');this.complete=true;
    }
  }
  requestConsultation(packet, now=new Date().toISOString()) {
    this.observe(packet);
    this.event(`request-${this.events.length}`,'Consultation requested',packet,'browser request',now);
  }
  receiveAssessment(assessment, packet) {
    if(scopeOf(packet)!==this.scope || !assessment || !finite(assessment.confidence) || assessment.confidence<0 || assessment.confidence>1 || typeof assessment.mode!=='string')return false;
    if(this.assessment)return false;
    this.assessment=structuredClone(assessment);this.consultation=snapshot(packet);
    this.before=snapshot(packet);this.after=snapshot(packet);this.evidence=evidenceFor(assessment,this.consultation);
    this.history=[{timestamp:packet.timestamp,value:reading(packet,METRICS[0])}];
    this.event('assessment','Assessment received',packet,'browser receipt',new Date().toISOString());
    return true;
  }
  requestAction(packet, now=new Date().toISOString(), details=null) {
    if(scopeOf(packet)!==this.scope || !this.assessment || this.complete)return;
    const hadAction=this.actionRequested;
    if(!hadAction){this.before=snapshot(packet);this.history=[];}
    this.actionRequested=true;this.lastActionAt=now;
    const countLabel=details?.acknowledgedSteps && details?.totalSteps?` (${details.acknowledgedSteps.length}/${details.totalSteps} tasks)`:'';
    const label=details?.partial?`Partial treatment administered${countLabel}`:details && hadAction?`Remaining treatment administered${countLabel}`:`Simulated action requested${countLabel}`;
    this.event(`action-${this.events.length}`,label,packet,'browser request',now);
  }
  failure(label, packet=this.current, now=new Date().toISOString()) {
    if(scopeOf(packet)!==this.scope)return;
    this.event(`failure-${this.events.length}`,label,this.current,'browser receipt',now);
    if(label==='Simulated action failed' && !this.recoveryStarted) {
      this.actionRequested=false;this.lastActionAt=null;this.before=snapshot(this.consultation);
    }
  }
  comparison() {
    return METRICS.map(metric=>{
      const before=reading(this.before,metric),after=reading(this.after,metric);
      return {...metric,before,after,delta:before===null || after===null?null:after-before};
    });
  }
}

const element=(tag,text,className)=>{
  const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;
};
const clock=timestamp=>timestamp && Number.isFinite(Date.parse(timestamp))
  ?new Date(timestamp).toLocaleTimeString('en-GB',{timeZone:'Indian/Mauritius'})+' MUT':'Time not supplied';
const valueText=(value,metric)=>value===null?'—':value.toFixed(metric.digits);

export class InsightsView {
  constructor(catalog={}) { this.model=new IncidentInsights();this.catalog=catalog;this.render(); }
  observe(packet) { this.model.observe(packet);this.render(); }
  requestConsultation(packet) { this.model.requestConsultation(packet);this.render(); }
  receiveAssessment(assessment,packet) {
    if(this.model.receiveAssessment(assessment,packet)) {
      document.getElementById('technical-assessment').open=false;
      this.render();
    }
  }
  requestAction(packet,now,details) { this.model.requestAction(packet,now,details);this.render(); }
  failure(label,packet,now) { this.model.failure(label,packet,now);this.render(); }
  markStale() {this.model.stale=true;this.render();}
  render() {
    const m=this.model;
    const renderKey=JSON.stringify([m.scope,m.stale,m.complete,m.actionRequested,m.lastActionAt,m.recoveryStarted,m.events,m.assessment?.diagnosis_id,m.before,m.after]);
    if(renderKey===this.renderKey)return;
    this.renderKey=renderKey;
    const plain=document.getElementById('plain-assessment'),evidence=document.getElementById('evidence-card');
    plain.hidden=!m.assessment;evidence.hidden=!m.assessment;
    document.getElementById('comparison-card').hidden=!m.assessment;
    document.getElementById('timeline-card').hidden=m.events.length===0;
    if(this.renderedScope!==m.scope)document.getElementById('technical-assessment').open=!m.assessment;
    this.renderedScope=m.scope;
    if(m.assessment) {
      const explanation=explainAssessment(m.assessment,this.catalog);
      document.getElementById('plain-title').textContent=explanation.title;
      document.getElementById('plain-summary').textContent=explanation.summary;
      document.getElementById('plain-source').textContent=explanation.source+'. Project explanation; not clinically reviewed.';
      document.getElementById('plain-score').textContent=`Pattern match: ${Math.round(m.assessment.confidence*100)}%. This is an algorithm score, not the probability of a disease.`;
      document.getElementById('insight-state').textContent=m.complete?'Completed incident · recorded assessment':m.stale?'Connection stale · retained assessment':'Recorded consultation';
      const evidenceSignature=JSON.stringify([m.scope,m.consultation.timestamp,m.evidence]);
      if(evidenceSignature!==this.evidenceSignature) {
        this.evidenceSignature=evidenceSignature;
        const list=document.getElementById('evidence-list');list.replaceChildren();
        for(const row of m.evidence.rows) {
          const item=element('li');item.append(element('strong',`${row.label}: ${row.value}`),
            element('span',`${row.flag} · reference ${row.range}`),element('small',row.source));list.append(item);
        }
        if(!m.evidence.rows.length)list.append(element('li','No structured monitoring flags were supplied. No abnormal reading has been inferred.'));
        document.getElementById('evidence-symptoms').textContent=m.evidence.symptoms;
        document.getElementById('evidence-context').textContent=`Context: ${m.evidence.context} · source telemetry ${clock(m.consultation.timestamp)}${m.evidence.quality.length?' · missing/unreliable: '+m.evidence.quality.join(', '):''}`;
      }
      document.getElementById('comparison-state').textContent=m.complete
        ?'Final backend-confirmed nominal snapshot. Normal readings do not establish that the underlying condition is cured.'
        :m.stale?'Connection stale. The last received measurements are retained.'
        :m.recoveryStarted?'Backend recovery is active. The right column shows the latest observed readings.'
        :m.actionRequested?'Action requested; awaiting backend recovery confirmation.'
        :'At consultation versus current readings. Treatment has not been requested.';
      document.getElementById('comparison-before-label').textContent=m.actionRequested?'At action request':'At consultation';
      document.getElementById('comparison-after-label').textContent=m.complete?'Final observed':'Latest observed';
      const rows=m.comparison();
      if(!this.comparisonCells) {
        const tbody=document.getElementById('comparison-rows');tbody.replaceChildren();
        this.comparisonCells=rows.map(row=>{
          const tr=element('tr'),heading=element('th',`${row.label} (${row.unit})`);
          heading.setAttribute('scope','row');
          const cells=[element('td'),element('td'),element('td')];tr.append(heading,...cells);tbody.append(tr);return cells;
        });
      }
      for(const [index,row] of rows.entries()) {
        const values=[valueText(row.before,row),valueText(row.after,row),row.delta===null?'—':`${row.delta>0?'+':''}${row.delta.toFixed(row.digits)}`];
        values.forEach((value,column)=>{const cell=this.comparisonCells[index][column];if(cell.textContent!==value)cell.textContent=value;});
      }
      document.getElementById('comparison-times').textContent=`Before: ${clock(m.lastActionAt || m.before?.timestamp)} · latest: ${clock(m.after?.timestamp)}. Changes are numerical, not a clinical improvement score. Unavailable readings are shown as —.`;
      this.renderTrend();
    }
    const eventSignature=JSON.stringify(m.events);
    if(eventSignature!==this.eventSignature) {
      this.eventSignature=eventSignature;
      const list=document.getElementById('incident-events');list.replaceChildren();
      for(const event of m.events) {
        const item=element('li');item.append(element('strong',event.label),element('small',`${clock(event.timestamp)} · ${event.origin}${event.met?' · '+(event.origin==='telemetry'?'MET ':'last observed MET ')+event.met:''}`));list.append(item);
      }
    }
  }
  renderTrend() {
    const points=this.model.history;
    const values=points.filter(point=>finite(point.value)).map(point=>point.value);
    const node=document.getElementById('comparison-trend');node.replaceChildren();
    if(values.length<2){node.textContent='Heart-rate trend appears after two distinct telemetry samples.';return;}
    const low=Math.min(...values)-2,high=Math.max(...values)+2;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 280 46');svg.setAttribute('role','img');svg.setAttribute('aria-label','Observed heart-rate samples; gaps indicate unavailable readings');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',points.map((point,index)=>finite(point.value)?`${index && finite(points[index-1].value)?'L':'M'}${(index/(points.length-1)*280).toFixed(1)},${(42-(point.value-low)/(high-low)*38).toFixed(1)}`:'').join(' '));
    svg.append(path);node.append(svg,element('small',`Heart rate · last ${points.length} observed samples · ${low.toFixed(0)}–${high.toFixed(0)} bpm display scale`));
  }
}
