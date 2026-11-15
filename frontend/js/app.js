import { TelemetryView, classify, resolveTreatedRegions, setText } from './telemetry.js';
import { TelemetryConnection } from './websocket.js';
import { Backend } from './scenarios.js';
import { MedicalPanel } from './medical_panel.js';
import { ReportDownloads } from './reports.js';
import { InsightsView } from './assessment_insights.js';

const query=new URLSearchParams(location.search);
const localApiDefault=location.protocol==='http:' && /^(localhost|127\.0\.0\.1)$/i.test(location.hostname)
  ? 'http://localhost:8000'
  : location.origin;
// A same-origin Render deployment serves the dashboard and API together. A
// separate frontend host can still override this explicitly with ?api=...
// (or window.ARES_API_BASE before this module loads).
const api=new Backend(query.get('api') || window.ARES_API_BASE || localApiDefault);
let view,body,connection,packet,mode='waiting',transport='',generation=0;
let starting=false,expectedIncident=null,lastIncident=null,consultation=null,revealedIncident=null,activeTreatedRegions=[];
const simulateButton=document.getElementById('run-assessment');
const consultButton=document.getElementById('analyze-crisis');
const revealButton=document.getElementById('reveal-incident');
const resetSimulation=document.getElementById('reset-simulation');
const reports=new ReportDownloads(api);
const insights=new InsightsView();
const formatTime=timestamp=>new Date(timestamp).toLocaleTimeString('en-GB',{timeZone:'Indian/Mauritius'});
const fresh=()=>mode==='backend' && packet && connection?.lastAt && Date.now()-connection.lastAt<=5000;
const panel=new MedicalPanel(async(info={})=> {
  if(!fresh())throw new Error('Fresh backend telemetry is required.');
  const actionPacket=packet;
  const incident=packet.blind_incident;
  const acknowledged=info.acknowledgedSteps || panel.checks.filter(step=>step.input.checked).map(step=>step.step);
  const baseStatuses=view?classify({...actionPacket,treated_regions:[],blind_incident:incident?{...incident,treated_regions:[]}:undefined},view.baselines).statuses:(actionPacket.anomaly_assessment?.organ_hud_status||{});
  const treatedRegions=info.partial?resolveTreatedRegions(info.steps||[],acknowledged,baseStatuses):[];
  const details={...info,acknowledgedSteps:acknowledged,treatedRegions};
  const applyPartialVisuals=result=>{
    if(info.partial) {
      activeTreatedRegions=Array.isArray(result?.treated_regions)&&result.treated_regions.length?result.treated_regions:treatedRegions;
      actionPacket.treated_regions=activeTreatedRegions;
      const states=view.update(actionPacket,transport);body?.update(actionPacket,states);updateAlerts(states);
    } else activeTreatedRegions=[];
    return result;
  };
  if(incident) {
    if(incident.phase!=='assessed' || incident.id!==consultation?.incidentId)throw new Error('There is no matching current consultation action.');
    const action=incident.actions?.[0];if(!action)throw new Error('No modeled recovery action was returned.');
    insights.requestAction(actionPacket,info.administeredAt,details);
    try { return applyPartialVisuals(await api.applyBlindAction(incident.id,action.id,acknowledged,info.partial)); }
    catch(error) { insights.failure('Simulated action failed',actionPacket,info.administeredAt);throw error; }
  }
  insights.requestAction(actionPacket,info.administeredAt,details);
  try { return applyPartialVisuals(await api.recover(packet.active_scenario_id,{acknowledgedSteps:acknowledged,partial:info.partial})); }
  catch(error) { insights.failure('Simulated action failed',actionPacket,info.administeredAt);throw error; }
});
function controlError(message='') {
  const node=document.getElementById('control-error');node.hidden=!message;node.textContent=message;
}
function updateControls() {
  const incident=packet?.blind_incident,active=incident && (incident.phase!=='complete' || packet?.anomaly_assessment?.alert_level!=='NOMINAL');
  simulateButton.disabled=!fresh() || starting || !!active || expectedIncident!==null
    || (!!packet?.active_scenario_id && packet.active_scenario_id!=='nominal');
  const pending=consultation?.status==='pending';
  resetSimulation.hidden=!incident || incident.phase==='complete';
  resetSimulation.disabled=!fresh() || starting || pending;
  consultButton.disabled=!fresh() || starting || pending || !!incident && incident.phase!=='awaiting_doctor';
  consultButton.textContent=pending?'Consulting…':'Consult Doctor';
  consultButton.setAttribute('aria-busy',String(pending));
  consultButton.title=!fresh()?'Waiting for fresh backend telemetry':incident && incident.phase==='observing'?'The backend requires anomalous telemetry before consultation':incident && incident.phase!=='awaiting_doctor'?'The current incident has already been assessed or is recovering':'Request a doctor assessment of the latest observed telemetry';
}
function showIncident(incident) {
  const node=document.getElementById('blind-status');node.hidden=!incident;
  revealButton.hidden=!incident?.reveal || revealedIncident===incident.id;
  if(!incident)return;
  const recovery=incident.recovery_cause==='operator'?'Requested simulated recovery':'Automatic recovery';
  node.textContent=({observing:'Crisis telemetry is developing. Doctor idle.',awaiting_doctor:'Abnormal telemetry detected. Consult Doctor when ready.',analyzing:'The backend doctor is assessing the current telemetry.',assessed:'Consultation available for this incident.',recovering:`${recovery} in progress.`,complete:packet?.anomaly_assessment?.alert_level==='NOMINAL'?'Backend confirms recovery complete · monitoring is nominal.':'Backend reports recovery completion · waiting for nominal telemetry.'})[incident.phase] || 'Monitoring the current incident.';
  if(incident.phase==='assessed' && !incident.actions?.length)node.textContent+=' No physical recovery action is modeled for this incident; reset the simulation to start another test.';
  if(revealedIncident===incident.id && incident.reveal)node.textContent+=` Simulated incident: ${incident.reveal}.`;
}
function updateProvenance() {
  if(!consultation) {
    setText('assessment-time','No consultation requested');
    setText('assessment-freshness','Live telemetry alerts are monitoring observations, not a diagnosis.');return;
  }
  if(consultation.status==='pending') {
    setText('assessment-time',`Requested ${formatTime(consultation.requestedAt)} MET`);
    setText('assessment-freshness','Awaiting the backend doctor. Live telemetry continues updating.');return;
  }
  if(consultation.status==='failed')return;
  setText('assessment-time',`Received ${formatTime(consultation.receivedAt)} MET · telemetry ${formatTime(consultation.sourceTimestamp)} MET`);
  const newer=Date.parse(packet?.timestamp)>Date.parse(consultation.sourceTimestamp);
  setText('assessment-freshness',!fresh()?'Backend disconnected or stale. This is a retained consultation.':newer?'Last consultation · newer telemetry has arrived; this result is not a new assessment of every tick.':'Last consultation · source telemetry shown above.');
}
function updateAlerts(states) {
  const critical=Object.keys(states).filter(key=>states[key]==='red'),warning=Object.keys(states).filter(key=>states[key]==='amber');
  const level=critical.length?'critical':warning.length?'warning':Object.values(states).every(x=>x==='unknown')?'unknown':'nominal';
  document.querySelector('.dashboard-grid').dataset.alert=level;
  const node=document.getElementById('telemetry-alert');node.dataset.status=level;
  node.textContent=level==='critical'?`Critical telemetry · ${critical.join(', ')}`:level==='warning'?`Telemetry warning · ${warning.join(', ')}`:level==='unknown'?'Telemetry status unavailable':'Telemetry within current monitoring bands';
}
function ingest(p,source) {
  if(starting || (expectedIncident!==null && (!Number.isInteger(p.simulation_incident) || p.simulation_incident<expectedIncident))
    || (lastIncident!==null && Number.isInteger(p.simulation_incident) && p.simulation_incident<lastIncident))return;
  if(expectedIncident!==null && p.simulation_incident>=expectedIncident)expectedIncident=null;
  if(lastIncident!==p.simulation_incident) {
    lastIncident=p.simulation_incident;generation++;consultation=null;activeTreatedRegions=[];reports.reset();
    panel.reset('Telemetry monitoring is active. Press Consult Doctor to request an assessment.');
  }
  if(activeTreatedRegions.length && !Array.isArray(p.treated_regions) && !Array.isArray(p.blind_incident?.treated_regions))p.treated_regions=activeTreatedRegions;
  packet=p;transport=source;mode='backend';
  insights.observe(p);
  const states=view.update(p,source);body?.update(p,states);updateAlerts(states);
  setText('packet-source',`SIMULATED TELEMETRY · ${formatTime(p.timestamp)} MET`);
  setText('data-badge','AGENT · 1 Hz');
  const resolved=p.anomaly_assessment?.alert_level==='NOMINAL'
    && (p.blind_incident?.phase==='complete' || (!p.blind_incident && p.recovery_status==='COMPLETE' && p.active_scenario_id==='nominal'));
  if(resolved && consultation) {
    // A completed treatment response alone is not proof of recovery. Clear the
    // consultation only on the server's completed, nominal telemetry snapshot.
    generation++;consultation=null;activeTreatedRegions=[];reports.reset();
    panel.reset('Recovery complete. Monitoring telemetry; consult the doctor when a new assessment is needed.');
    setText('assessment-latency','ENGINE STANDBY');
  }
  showIncident(resolved?null:p.blind_incident);
  // The blind streaming contract truly gates Layer 3 on the server. Unsolicited
  // diagnoses from legacy/non-blind streams are not displayed as consultations.
  if(!resolved && consultation && consultation.incidentId===p.simulation_incident && p.rag_diagnosis
    && ['assessed','recovering','complete'].includes(p.blind_incident?.phase)) {
    if(consultation.status==='pending' || consultation.status==='failed') {
      consultation.status='complete';consultation.receivedAt=new Date().toISOString();consultation.sourceTimestamp=p.timestamp;
      setText('assessment-latency',`CONSULTATION ${(performance.now()-consultation.start).toFixed(0)} ms`);
    }
    if(consultation.status==='complete') {
      const assessment={...p.rag_diagnosis,blindIncident:p.blind_incident};
      panel.render(assessment);
      insights.receiveAssessment(assessment,p);
      if(!consultation.reportBound){reports.setAssessment(assessment,{incidentId:p.simulation_incident});consultation.reportBound=true;}
    }
  }
  updateProvenance();updateControls();
}
simulateButton.addEventListener('click',async()=> {
  if(simulateButton.disabled || starting)return;
  starting=true;controlError();simulateButton.classList.add('is-loading');simulateButton.setAttribute('aria-busy','true');updateControls();
  const version=generation;
  try {
    const result=await api.startBlindCrisis();
    if(version!==generation)return;
    if(!Number.isInteger(result.incident_id))throw new Error('The backend did not acknowledge a random streaming incident.');
    expectedIncident=result.incident_id;consultation=null;activeTreatedRegions=[];reports.reset();
    panel.reset('Random crisis started. Monitoring changing vitals; doctor remains idle until consultation.');
    showIncident(null);setText('assessment-latency','MONITORING TELEMETRY');updateProvenance();
  } catch(error) {controlError(`${error.message} Random streaming simulation requires the existing simulate-crisis endpoint; no local fallback is used.`);}
  finally {starting=false;simulateButton.classList.remove('is-loading');simulateButton.setAttribute('aria-busy','false');updateControls();}
});
consultButton.addEventListener('click',async()=> {
  if(consultButton.disabled || !fresh())return;
  const observed=structuredClone(packet),incident=observed.blind_incident,version=generation;
  insights.requestConsultation(observed);
  consultation={incidentId:observed.simulation_incident,status:'pending',requestedAt:new Date().toISOString(),sourceTimestamp:observed.timestamp,start:performance.now()};
  panel.error('');controlError();setText('assessment-latency','CONSULTING DOCTOR…');updateProvenance();updateControls();
  try {
    if(incident) {
      // This endpoint evaluates the server's latest live packet for this incident;
      // it accepts the incident ID, not a fabricated frontend assessment payload.
      await api.analyzeBlindCrisis(incident.id);
    } else {
      const result=await api.diagnose(observed);
      if(version!==generation || consultation?.incidentId!==observed.simulation_incident)return;
      panel.render(result);reports.setAssessment(result,{incidentId:observed.simulation_incident});consultation.reportBound=true;consultation.status='complete';consultation.receivedAt=new Date().toISOString();
      insights.receiveAssessment(result,observed);
      setText('assessment-latency',`CONSULTATION ${(performance.now()-consultation.start).toFixed(0)} ms`);
    }
  } catch(error) {
    if(version===generation && consultation) {
      consultation.status='failed';panel.error(error.message);setText('assessment-latency','CONSULTATION FAILED');
      insights.failure('Consultation failed');
      setText('assessment-freshness','Consultation failed. No new assessment is available; retry when permitted by the backend.');
    }
  } finally {updateProvenance();updateControls();}
});
resetSimulation.addEventListener('click',async()=> {
  if(resetSimulation.disabled || !fresh())return;
  starting=true;controlError();updateControls();
  try {
    await api.trigger('nominal');
    const observed=await api.snapshot('nominal');
    starting=false;expectedIncident=null;activeTreatedRegions=[];ingest(observed,transport);
  } catch(error) {controlError(`Simulation reset failed: ${error.message}`);}
  finally {starting=false;updateControls();}
});
revealButton.addEventListener('click',()=> {
  const incident=packet?.blind_incident;if(incident?.phase==='complete'){revealedIncident=incident.id;showIncident(incident);}
});
async function init() {
  panel.reset('Connect the astronaut agent, then simulate a crisis. Consult Doctor requests the clinical assessment separately.');
  updateProvenance();updateControls();
  try {
    const response=await fetch('data/baselines.json');if(!response.ok)throw new Error('Local monitoring baselines failed to load.');
    view=new TelemetryView(await response.json());
    try {
      const explanations=await fetch('data/user_explanations.json');
      if(explanations.ok)insights.catalog=await explanations.json();
    } catch { /* Monitoring stays available; unmatched explanations use the explicit fallback. */ }
    try {const {AresBodyHUD}=await import('./body_hud.js');body=new AresBodyHUD(document.getElementById('body-canvas'));}
    catch(error){setText('model-status',`3D unavailable: ${error.message}`);}
    connection=new TelemetryConnection(api.base,ingest,(state,label)=> {
      const node=document.getElementById('api-state');node.dataset.state=state;
      if(state==='connected') {mode='backend';setText('api-state-label',`API CONNECTED · ${label==='WebSocket'?'WS':'HTTP'}`);}
      else {
        setText('api-state-label',state==='stale'?'STALE TELEMETRY':state==='connecting'?'CONNECTING API':state==='invalid'?'INVALID PACKET':'API DISCONNECTED');
        if(state==='stale' || state==='disconnected') {
          mode='disconnected';body?.markStale();insights.markStale();setText('telemetry-alert','Backend unavailable · readings and organ status are retained, not fresh observations.');document.getElementById('telemetry-alert').dataset.status='unknown';setText('data-badge',state==='stale'?'STALE':'DISCONNECTED');
          setText('packet-source',packet?'BACKEND UNAVAILABLE · retained readings':'NO BACKEND TELEMETRY · reconnecting');
        }
      }
      updateProvenance();updateControls();
    });
    connection.start();
  } catch(error) {setText('api-state-label','FRONTEND ERROR');controlError(`${error.message} Serve the frontend through HTTP.`);}
}
window.addEventListener('pagehide',()=>{connection?.stop();body?.dispose();reports.dispose();});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
init();
