const API_BASE = `http://${location.hostname === 'localhost' ? 'localhost' : '127.0.0.1'}:8000`;
const cases = {
  nominal: {
    name: 'Nominal rest',
    payload: {
      timestamp: '2026-11-14T10:15:30Z',
      met: '042:14:30:12',
      mission_day: 84,
      astronaut_id: 'ASTRO-01',
      name: 'Cmdr. Maya Lin',
      activity_state: 'IVA_REST',
      vitals: {
        heart_rate: 62,
        blood_pressure_sys: 112,
        blood_pressure_dia: 70,
        spo2: 98,
        hrv_ms: 42,
        core_temp_c: 37.6,
        respiration_rate: 13,
      },
      environment: {
        cabin_co2_mmhg: 2.2,
        ambient_radiation_msv_h: 0.054,
        suit_pressure_psi: 4.3,
      },
      symptom_log: 'Nominal resting state; no acute complaints.',
    },
  },
  hypercapnia: {
    name: 'EVA / elevated CO₂',
    payload: {
      timestamp: '2026-11-14T10:15:30Z',
      met: '042:14:30:12',
      mission_day: 84,
      astronaut_id: 'ASTRO-01',
      name: 'Cmdr. Maya Lin',
      activity_state: 'EVA_SPACEWALK',
      vitals: {
        heart_rate: 118,
        blood_pressure_sys: 142,
        blood_pressure_dia: 92,
        spo2: 95.8,
        hrv_ms: 22.4,
        core_temp_c: 37.6,
        respiration_rate: 20,
      },
      environment: {
        cabin_co2_mmhg: 12.8,
        ambient_radiation_msv_h: 0.054,
        suit_pressure_psi: 4.3,
      },
      symptom_log: 'Throbbing frontal headache, facial flushing, air feels sluggish and short of breath.',
    },
  },
  solar: {
    name: 'Solar event',
    payload: {
      timestamp: '2026-11-14T11:00:00Z',
      met: '042:15:15:00',
      mission_day: 84,
      astronaut_id: 'ASTRO-01',
      name: 'Cmdr. Maya Lin',
      activity_state: 'EVA_SPACEWALK',
      vitals: {
        heart_rate: 98,
        blood_pressure_sys: 96,
        blood_pressure_dia: 64,
        spo2: 97,
        hrv_ms: 19,
        core_temp_c: 38.4,
        respiration_rate: 18,
      },
      environment: {
        cabin_co2_mmhg: 2.1,
        ambient_radiation_msv_h: 4.2,
        suit_pressure_psi: 4.3,
        donki_spe_active: true,
      },
      symptom_log: 'Sudden anorexia, severe nausea, repeated vomiting, acute fatigue.',
    },
  },
  'zero-day': {
    name: 'Unclassified anomaly',
    payload: {
      timestamp: '2026-11-14T14:20:00Z',
      met: '042:18:35:00',
      mission_day: 84,
      astronaut_id: 'ASTRO-01',
      name: 'Cmdr. Maya Lin',
      activity_state: 'IVA_REST',
      vitals: {
        heart_rate: 114,
        blood_pressure_sys: 84,
        blood_pressure_dia: 52,
        spo2: 89.2,
        hrv_ms: 14,
        core_temp_c: 38.9,
        respiration_rate: 24,
      },
      environment: {
        cabin_co2_mmhg: 2,
        ambient_radiation_msv_h: 0.054,
      },
      symptom_log: 'Unexplained metallic taste, peripheral tingling, sudden weakness.',
    },
  },
};

const ui = {
  apiState: document.getElementById('api-state'),
  apiStateLabel: document.getElementById('api-state-label'),
  caseSelect: document.getElementById('case-select'),
  runButton: document.getElementById('run-assessment'),
  hr: document.getElementById('hr-val'),
  bp: document.getElementById('bp-val'),
  spo2: document.getElementById('spo2-val'),
  spo2Meter: document.getElementById('spo2-meter'),
  respiration: document.getElementById('rr-val'),
  hrv: document.getElementById('hrv-val'),
  temperature: document.getElementById('temp-val'),
  co2: document.getElementById('co2-val'),
  radiation: document.getElementById('rad-val'),
  suitPressure: document.getElementById('suit-pressure-val'),
  activity: document.getElementById('activity-badge'),
  astronautName: document.getElementById('astronaut-name'),
  astronautId: document.getElementById('astronaut-id'),
  missionDay: document.getElementById('mission-day'),
  symptom: document.getElementById('symptom-feed'),
  source: document.getElementById('packet-source'),
  latency: document.getElementById('assessment-latency'),
  diagnosisCard: document.getElementById('diagnosis-card'),
  resultMode: document.getElementById('result-mode'),
  severity: document.getElementById('result-severity'),
  diagnosis: document.getElementById('diagnosis-title'),
  summary: document.getElementById('diagnosis-summary'),
  confidence: document.getElementById('confidence-value'),
  confidenceMeter: document.getElementById('confidence-meter'),
  actionCount: document.getElementById('action-count'),
  actions: document.getElementById('treatment-checklist'),
  citation: document.getElementById('citation-text'),
  pins: {
    sans: document.getElementById('pin-brain'),
    cv: document.getElementById('pin-heart'),
    eclss: document.getElementById('pin-lungs'),
    rad: document.getElementById('pin-core'),
  },
  pinValues: {
    head: document.getElementById('head-organ-value'),
    heart: document.getElementById('heart-organ-value'),
    lungs: document.getElementById('lungs-organ-value'),
    core: document.getElementById('core-organ-value'),
  },
  bodyModel: document.getElementById('body-avatar-svg'),
};

const numberText = (value, digits = 1) => {
  if (value === undefined || value === null || value === '') return '—';
  return Number.isInteger(Number(value)) ? String(value) : Number(value).toFixed(digits);
};

function renderTelemetry(payload) {
  const vitals = payload.vitals;
  const environment = payload.environment;
  ui.hr.textContent = numberText(vitals.heart_rate);
  ui.bp.textContent = `${numberText(vitals.blood_pressure_sys)}/${numberText(vitals.blood_pressure_dia)}`;
  ui.spo2.textContent = numberText(vitals.spo2);
  ui.spo2Meter.style.width = `${Math.max(0, Math.min(100, Number(vitals.spo2) || 0))}%`;
  ui.respiration.textContent = numberText(vitals.respiration_rate);
  ui.hrv.textContent = numberText(vitals.hrv_ms);
  ui.temperature.textContent = numberText(vitals.core_temp_c);
  ui.co2.textContent = numberText(environment.cabin_co2_mmhg, 1);
  ui.radiation.textContent = numberText(environment.ambient_radiation_msv_h, 3);
  ui.suitPressure.textContent = numberText(environment.suit_pressure_psi, 1);
  ui.pinValues.head.textContent = `HRV ${numberText(vitals.hrv_ms)} ms`;
  ui.pinValues.heart.textContent = `HR ${numberText(vitals.heart_rate)} bpm`;
  ui.pinValues.lungs.textContent = `SpO₂ ${numberText(vitals.spo2)}% · RR ${numberText(vitals.respiration_rate)}/min`;
  ui.pinValues.core.textContent = `CBT ${numberText(vitals.core_temp_c)}°C · RAD ${numberText(environment.ambient_radiation_msv_h, 3)}`;
  ui.activity.textContent = String(payload.activity_state || 'UNKNOWN').replaceAll('_', ' ');
  ui.astronautName.textContent = payload.name || 'Crew member';
  ui.astronautId.textContent = `${payload.astronaut_id || 'UNKNOWN'} · MISSION DAY ${String(payload.mission_day || '—').padStart(3, '0')}`;
  ui.missionDay.textContent = String(payload.mission_day || 0).padStart(3, '0');
  ui.symptom.textContent = payload.symptom_log || 'No crew report provided.';
  ui.source.textContent = 'SAMPLE CASE · NOT LIVE TELEMETRY';
  ui.latency.textContent = 'ASSESSMENT REQUIRED';
}

function setAwaitingAssessment() {
  ui.diagnosisCard.classList.remove('alert', 'warning');
  ui.resultMode.textContent = 'AWAITING ASSESSMENT';
  ui.severity.textContent = '—';
  ui.diagnosis.textContent = 'Telemetry ready';
  ui.summary.textContent = 'Choose a case and run an assessment to see the onboard clinical engine result.';
  ui.confidence.textContent = '—';
  ui.confidenceMeter.style.width = '0%';
  ui.actionCount.textContent = '0';
  ui.actions.replaceChildren();
  const empty = document.createElement('li');
  empty.className = 'empty-action';
  empty.textContent = 'Actions from the assessment will appear here.';
  ui.actions.append(empty);
  ui.citation.textContent = 'NASA-STD-3001 references are returned by the backend assessment.';
  Object.values(ui.pins).forEach((pin) => {
    pin.className = 'organ-pin unknown';
  });
  ui.bodyModel.classList.remove(
    'status-red-head', 'status-amber-head',
    'status-red-heart', 'status-amber-heart',
    'status-red-lungs', 'status-amber-lungs',
    'status-red-core', 'status-amber-core',
  );
}

function updatePinStates(result) {
  const statuses = result.organ_hud_status
    || result.layer2_assessment?.organ_hud_status
    || result.assessment?.organ_hud_status
    || {};
  const statusToClass = { CYAN: 'cyan', AMBER: 'amber', RED: 'red' };
  const statusByPin = {
    sans: statuses['SANS-01'],
    cv: statuses['CV-02'],
    eclss: statuses['ECLSS-03'],
    rad: statuses['RAD-04'],
  };
  const modelClassByPin = {
    sans: 'head',
    cv: 'heart',
    eclss: 'lungs',
    rad: 'core',
  };
  ui.bodyModel.classList.remove(
    'status-red-head', 'status-amber-head',
    'status-red-heart', 'status-amber-heart',
    'status-red-lungs', 'status-amber-lungs',
    'status-red-core', 'status-amber-core',
  );
  Object.entries(statusByPin).forEach(([key, status]) => {
    ui.pins[key].className = `organ-pin ${statusToClass[status] || 'unknown'}`;
    if (statusToClass[status] && statusToClass[status] !== 'cyan') {
      ui.bodyModel.classList.add(`status-${statusToClass[status]}-${modelClassByPin[key]}`);
    }
  });
}

function renderActions(actions) {
  ui.actions.replaceChildren();
  if (!Array.isArray(actions) || actions.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'empty-action';
    empty.textContent = 'No additional actions returned.';
    ui.actions.append(empty);
    ui.actionCount.textContent = '0';
    return;
  }

  actions.forEach((item) => {
    const row = document.createElement('li');
    if (item && typeof item === 'object') {
      row.textContent = item.action || item.title || JSON.stringify(item);
      if (item.critical) row.classList.add('critical');
    } else {
      row.textContent = String(item);
    }
    ui.actions.append(row);
  });
  ui.actionCount.textContent = String(actions.length).padStart(2, '0');
}

function renderAssessment(result, elapsedMs) {
  const confidence = Math.max(0, Math.min(1, Number(result.confidence) || 0));
  const mode = String(result.mode || 'ASSESSMENT').replaceAll('_', ' ');
  const severity = String(result.severity || 'UNSPECIFIED').replaceAll('_', ' ');
  const isEmergency = severity.includes('EMERGENCY') || severity.includes('CRITICAL');
  const isWarning = !isEmergency && (severity.includes('WARNING') || result.mode === 'MODE_A_KNOWN_CONDITION');
  ui.diagnosisCard.classList.toggle('alert', isEmergency);
  ui.diagnosisCard.classList.toggle('warning', isWarning);
  ui.resultMode.textContent = mode;
  ui.severity.textContent = severity;
  ui.diagnosis.textContent = result.diagnosis || result.condition || 'Assessment completed';
  const triggerSummary = Array.isArray(result.triggering_vitals)
    ? result.triggering_vitals.slice(0, 2).join(' · ')
    : '';
  ui.summary.textContent = result.abstention_reason
    || triggerSummary
    || result.clinical_reasoning
    || 'Assessment completed by the local clinical engine.';
  ui.confidence.textContent = `${Math.round(confidence * 100)}%`;
  ui.confidenceMeter.style.width = `${confidence * 100}%`;
  renderActions(result.action_checklist || result.action_plan || []);

  const citation = result.nasa_citation;
  const citationParts = citation
    ? [citation.document, citation.section].filter(Boolean)
    : [result.source_document, ...(Array.isArray(result.nasa_citations) ? result.nasa_citations : [])].filter(Boolean);
  ui.citation.textContent = citationParts.join(' · ') || 'No citation returned by the backend.';
  updatePinStates(result);
  ui.source.textContent = 'BACKEND ASSESSMENT · SAMPLE INPUT';
  ui.latency.textContent = `ROUND TRIP ${elapsedMs} ms`;
}

async function checkApi() {
  try {
    const response = await fetch(`${API_BASE}/health`, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Health endpoint returned HTTP ${response.status}`);
    const health = await response.json();
    ui.apiState.className = 'api-state online';
    ui.apiStateLabel.textContent = health.status === 'NOMINAL' ? 'API ONLINE' : 'API READY';
    ui.apiState.title = `${health.system || 'A.R.E.S. backend'} · ${health.operation_mode || 'ready'}`;
  } catch (error) {
    ui.apiState.className = 'api-state offline';
    ui.apiStateLabel.textContent = 'API OFFLINE';
    ui.apiState.title = `Cannot reach ${API_BASE}/health: ${error.message}`;
  }
}

async function runAssessment() {
  const selectedCase = cases[ui.caseSelect.value];
  if (!selectedCase) return;

  ui.runButton.disabled = true;
  ui.runButton.classList.add('is-loading');
  ui.runButton.setAttribute('aria-busy', 'true');
  ui.runButton.querySelector('.run-icon').textContent = '⟳';
  ui.resultMode.textContent = 'RUNNING ASSESSMENT';
  ui.diagnosis.textContent = 'Evaluating telemetry';
  ui.summary.textContent = 'Sending the selected case to the local clinical engine.';
  ui.latency.textContent = 'REQUEST IN PROGRESS';
  const started = performance.now();

  try {
    const response = await fetch(`${API_BASE}/api/diagnose`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(selectedCase.payload),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail || result;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    renderAssessment(result, Math.round(performance.now() - started));
    ui.apiState.className = 'api-state online';
    ui.apiStateLabel.textContent = 'API ONLINE';
  } catch (error) {
    ui.diagnosisCard.classList.add('alert');
    ui.resultMode.textContent = 'ASSESSMENT FAILED';
    ui.severity.textContent = 'API ERROR';
    ui.diagnosis.textContent = 'Clinical engine unavailable';
    ui.summary.textContent = error.message;
    ui.confidence.textContent = '—';
    ui.confidenceMeter.style.width = '0%';
    ui.actionCount.textContent = '0';
    ui.actions.replaceChildren();
    ui.citation.textContent = `Check that the A.R.E.S. backend is running at ${API_BASE}.`;
    ui.latency.textContent = 'REQUEST FAILED';
    ui.apiState.className = 'api-state offline';
    ui.apiStateLabel.textContent = 'API ERROR';
    ui.apiState.title = error.message;
  } finally {
    ui.runButton.disabled = false;
    ui.runButton.classList.remove('is-loading');
    ui.runButton.removeAttribute('aria-busy');
    ui.runButton.querySelector('.run-icon').textContent = '↗';
  }
}

function startMissionClock() {
  let elapsedSeconds = (42 * 24 * 60 * 60) + (14 * 60 * 60) + (30 * 60) + 12;
  const timer = document.getElementById('met-timer');
  const render = () => {
    const days = Math.floor(elapsedSeconds / 86400);
    const hours = Math.floor((elapsedSeconds % 86400) / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    timer.textContent = [days, hours, minutes, seconds].map((value, index) => String(value).padStart(index === 0 ? 3 : 2, '0')).join(':');
    elapsedSeconds += 1;
  };
  render();
  window.setInterval(render, 1000);
}

ui.caseSelect.addEventListener('change', () => {
  const selectedCase = cases[ui.caseSelect.value];
  if (!selectedCase) return;
  renderTelemetry(selectedCase.payload);
  setAwaitingAssessment();
});
ui.runButton.addEventListener('click', runAssessment);

renderTelemetry(cases[ui.caseSelect.value].payload);
setAwaitingAssessment();
startMissionClock();
checkApi();
