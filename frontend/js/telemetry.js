export const regions = {
  'SANS-01': { pin: 'pin-brain', meshes: ['BRAIN'], label: 'Neuro-ocular', fields: ['specialized_diagnostics.oct_rnfl_um', 'specialized_diagnostics.refraction_shift_D'] },
  'CV-02': { pin: 'pin-heart', meshes: ['HEART'], label: 'Cardiovascular', fields: ['vitals.heart_rate', 'vitals.blood_pressure_sys', 'vitals.blood_pressure_dia', 'vitals.hrv_ms'] },
  'ECLSS-03': { pin: 'pin-lungs', meshes: ['LUNG_LEFT', 'LUNG_RIGHT'], label: 'Respiratory', fields: ['vitals.spo2', 'vitals.respiration_rate', 'environment.cabin_co2_mmhg'] },
  'RAD-04': { pin: 'pin-core', meshes: ['BODY_SURFACE'], label: 'Radiation / thermal', fields: ['environment.ambient_radiation_msv_h', 'vitals.core_temp_c'] }
};
export const get = (o, path) => path.split('.').reduce((v, k) => v?.[k], o);
export const finite = v => typeof v === 'number' && Number.isFinite(v);
export const fmt = (v, digits = 0) => finite(v) ? v.toFixed(digits) : '—';
export const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
export function validatePacket(p) {
  if (!p || typeof p !== 'object' || !p.vitals || typeof p.vitals !== 'object' || Array.isArray(p.vitals)) return null;
  if (typeof p.timestamp !== 'string' || !Number.isFinite(Date.parse(p.timestamp))) return null;
  const q = structuredClone(p);
  for(const key of ['name','astronaut_id','activity_state','symptom_log','met','active_scenario_id']) if(q[key]!==undefined && typeof q[key]!=='string') delete q[key];
  q.environment = q.environment && typeof q.environment === 'object' && !Array.isArray(q.environment) ? q.environment : {};
  const bad = new Set([...(Array.isArray(q.missing_vitals)?q.missing_vitals:[]), ...(Array.isArray(q.unreliable_channels)?q.unreliable_channels:[])]);
  const aliases = { heart_rate: 'hr_bpm', blood_pressure_sys: 'sbp_mmHg', blood_pressure_dia: 'dbp_mmHg', spo2: 'spo2_pct', hrv_ms: 'hrv_rmssd_ms', core_temp_c: 'cbt_C', respiration_rate: 'rr_bpm' };
  for (const group of ['vitals', 'environment']) for (const [key, value] of Object.entries(q[group])) {
    if (typeof value !== 'boolean' && (!finite(value) || bad.has(key) || bad.has(aliases[key]) || /FAULT|MISSING|SEU/.test(q.quality_flags?.[key] || q.quality_flags?.[aliases[key]] || ''))) q[group][key] = null;
  }
  return Object.values(q.vitals).some(finite) ? q : null;
}
export function diagnosisPayload(p) {
  // Telemetry broadcasts include dashboard-only fields rejected by extra='forbid'.
  const keys = ['timestamp','met','elapsed_s','mission_day','astronaut_id','name','activity_state','comms_status','vitals','environment','specialized_diagnostics','symptom_log','quality_flags','source_manifest_id','model_version','missing_vitals','unreliable_channels'];
  const result = Object.fromEntries(keys.filter(k => p[k] !== undefined).map(k => [k, p[k]]));
  // Scenario names must never be diagnostic evidence; preserve the observed packet.
  result.stateless_evaluation = true;
  return result;
}
export function classify(p, data) {
  const statuses = Object.fromEntries(Object.keys(regions).map(k => [k, 'unknown']));
  const channels = {};
  const mappings = { heart_rate:['hr_bpm','CV-02'],blood_pressure_sys:['sbp_mmHg','CV-02'],blood_pressure_dia:['dbp_mmHg','CV-02'],hrv_ms:['hrv_rmssd_ms','CV-02'],spo2:['spo2_pct','ECLSS-03'],respiration_rate:['rr_bpm','ECLSS-03'],core_temp_c:['cbt_C','RAD-04'] };
  const activity = ({ RESTING:'IVA_REST',REST:'IVA_REST',EXERCISE:'ARED_EXERCISE',EVA:'EVA_SPACEWALK' })[p.activity_state] || p.activity_state;
  const weight = { unknown:-1, cyan:0, amber:1, red:2 };
  const merge = (r,s) => { if (weight[s] > weight[statuses[r]]) statuses[r]=s; };
  for (const [field,[key,region]] of Object.entries(mappings)) {
    const value=p.vitals[field], spec=data?.physiological_baselines?.[key];
    let status='unknown';
    if (finite(value) && spec) {
      const expected=spec.activity_modifiers_ug?.[activity];
      status='cyan';
      if (!(expected && value>=expected[0] && value<=expected[1])) for (const [band,color] of [['warning_yellow','amber'],['critical_red','red']]) {
        const b=spec[band]?.[activity] || spec[band]?.DEFAULT || spec[band]?.IVA_REST;
        if (b && ((finite(b.min) && value<b.min) || (finite(b.max) && value>b.max))) status=color;
      }
    }
    channels[field]=status; merge(region,status);
  }
  const co2=p.environment.cabin_co2_mmhg, limits=data?.environmental_and_radiation_limits?.cabin_ppCO2_mmHg;
  if (finite(co2) && limits) {
    channels.cabin_co2_mmhg=co2>limits.critical_excursion?'red':co2>=limits.warning_1hr_24hr_max?'amber':'cyan';
    merge('ECLSS-03',channels.cabin_co2_mmhg);
  }
  // No rate threshold is inferred from cumulative radiation limits. Backend edge
  // assessment is authoritative for radiation and SANS when available.
  const authoritative=p.anomaly_assessment?.organ_hud_status;
  for (const [region,color] of Object.entries(authoritative || {})) if (region in statuses) statuses[region]=normalizeStatus(color);
  for (const [region,def] of Object.entries(regions)) if (!authoritative?.[region] && !def.fields.some(path=>finite(get(p,path)))) statuses[region]='unknown';
  const edge=p.anomaly_assessment;
  if(edge && Array.isArray(edge.breached_parameters)) {
    const canonical={heart_rate:'hr_bpm',blood_pressure_sys:'sbp_mmHg',blood_pressure_dia:'dbp_mmHg',hrv_ms:'hrv_rmssd_ms',spo2:'spo2_pct',respiration_rate:'rr_bpm',core_temp_c:'cbt_C',cabin_co2_mmhg:'cabin_ppCO2_mmHg'};
    for(const [field,key] of Object.entries(canonical)) if(channels[field] && channels[field]!=='unknown') {
      const breach=edge.breached_parameters.find(b=>b.parameter===key);
      channels[field]=breach?normalizeStatus(breach.severity):'cyan';
      if(edge.seu_candidates_filtered?.some(value=>String(value).startsWith(key+':'))) channels[field]='unknown';
    }
  }
  return {statuses,channels};
}
export const normalizeStatus = c => ({CYAN:'cyan',NORMAL:'cyan',NOMINAL:'cyan',AMBER:'amber',YELLOW:'amber',WARNING:'amber',WARNING_YELLOW:'amber',RED:'red',CRITICAL:'red',CRITICAL_RED:'red'})[String(c).toUpperCase()] || 'unknown';
export class TelemetryView {
  history=[];
  constructor(data) { this.baselines=data; }
  reset() { this.history=[]; }
  update(p, source) {
    this.packet=p;
    const v=p.vitals,e=p.environment;
    const ids={ 'hr-val':[v.heart_rate,0], 'spo2-val':[v.spo2,1], 'rr-val':[v.respiration_rate,0], 'hrv-val':[v.hrv_ms,1], 'temp-val':[v.core_temp_c,1], 'co2-val':[e.cabin_co2_mmhg,1], 'rad-val':[e.ambient_radiation_msv_h,3], 'suit-pressure-val':[e.suit_pressure_psi,1] };
    for (const [id,[value,digits]] of Object.entries(ids)) setText(id,fmt(value,digits));
    setText('bp-val',`${fmt(v.blood_pressure_sys)}/${fmt(v.blood_pressure_dia)}`);
    setText('met-timer',typeof p.met==='string'?p.met:'—'); setText('mission-day',finite(p.mission_day)?String(p.mission_day).padStart(3,'0'):'—');
    setText('astronaut-name',p.name || 'Unknown crew'); setText('astronaut-id',p.astronaut_id || 'Identity unavailable');
    document.querySelector('.crew-avatar').textContent=(p.name || '—').replace(/^Cmdr\.\s*/,'').split(' ').map(s=>s[0]).slice(0,2).join('');
    setText('activity-badge',(p.activity_state || 'UNKNOWN').replaceAll('_',' '));
    setText('symptom-feed',p.symptom_log || 'No symptom report supplied.'); document.getElementById('symptom-feed').title=p.symptom_log || '';
    setText('head-organ-value',finite(p.specialized_diagnostics?.oct_rnfl_um)?`OCT ${fmt(p.specialized_diagnostics.oct_rnfl_um)} µm`:'No ocular measurement');
    setText('heart-organ-value',`HR ${fmt(v.heart_rate)} bpm`);
    setText('lungs-organ-value',`SpO₂ ${fmt(v.spo2,1)}% · RR ${fmt(v.respiration_rate)}/min`);
    setText('core-organ-value',`CBT ${fmt(v.core_temp_c,1)}°C · RAD ${fmt(e.ambient_radiation_msv_h,3)}`);
    document.getElementById('spo2-meter').style.width=finite(v.spo2)?`${Math.max(0,Math.min(100,v.spo2))}%`:'0%';
    const c=p.comms_status;
    setText('comms-detail',c?`Earth uplink · ${fmt(c.one_way_delay_sec ?? c.one_way_delay_s ?? c.one_way_latency_s)}s one-way · ${c.solar_conjunction_blackout ? 'BLACKOUT' : c.link_status || c.status || c.mode || 'status unavailable'}`:'Earth uplink · delay/status unavailable');
    this.history.push({ timestamp:p.timestamp, hr:v.heart_rate, bp:v.blood_pressure_sys, spo2:v.spo2, co2:e.cabin_co2_mmhg, radiation:e.ambient_radiation_msv_h });
    if (this.history.length>60) this.history.shift();
    const valid=this.history.filter(x=>finite(x.hr));
    const path=document.querySelector('.heart-trace path');
    if(valid.length>1) {
      const lo=Math.min(...valid.map(x=>x.hr))-2, hi=Math.max(...valid.map(x=>x.hr))+2;
      path.setAttribute('d',this.history.map((x,i)=>`${finite(x.hr)?(i&&finite(this.history[i-1].hr)?'L':'M'):'M'}${i/Math.max(1,this.history.length-1)*160} ${finite(x.hr)?22-(x.hr-lo)/(hi-lo)*20:22}`).join(' '));
    } else path.setAttribute('d','');
    path.style.animation='none'; path.style.strokeDasharray='none';
    document.querySelector('.heart-trace').setAttribute('aria-label','Last 60 heart rate samples');
    const result=classify(p,this.baselines);
    const fields={'hr-val':'heart_rate','spo2-val':'spo2','rr-val':'respiration_rate','hrv-val':'hrv_ms','temp-val':'core_temp_c','co2-val':'cabin_co2_mmhg'};
    for (const [id,key] of Object.entries(fields)) document.getElementById(id).dataset.status=result.channels[key];
    return result.statuses;
  }
}
