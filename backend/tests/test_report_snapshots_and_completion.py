"""Report delivery and simulator completion; no clinical classification changes."""
from collections import OrderedDict
from copy import deepcopy
from io import BytesIO
import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from backend import main as server
from backend.services import report_store
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine
from backend.services.rag_engine import LocalMedicalRAGEngine
from backend.services.report_pdf import _pdf_safe_text

@pytest.fixture
def simulation(monkeypatch):
    engine = AstronautSimulationEngine()
    monkeypatch.setattr(server, 'astronaut_sim', engine)
    monkeypatch.setattr(server, 'anomaly_detector', EdgeAnomalyDetector())
    monkeypatch.setattr(server, 'rag_engine', LocalMedicalRAGEngine())
    monkeypatch.setattr(server, 'latest_telemetry', None)
    monkeypatch.setattr(server, 'latest_earth_report', None)
    monkeypatch.setattr(report_store, '_reports', OrderedDict())
    monkeypatch.setattr(server.donki_service, 'get_space_weather', server.donki_service._get_cache_fallback)
    return engine

def assess(seed):
    ack = server.simulate_crisis_action({'streaming': True, 'seed': seed})
    for _ in range(20):
        frame = server.advance_telemetry()
        if frame['blind_incident']['phase'] == 'awaiting_doctor':
            break
    assert 'rag_diagnosis' not in frame
    assert server.request_blind_assessment({'incident_id': ack['incident_id']})['status'] == 'ok'
    frame = server.advance_telemetry()
    assert frame['blind_incident']['phase'] == 'assessed'
    return frame

@pytest.mark.parametrize('seed,mode,kind',[(2,'MODE_A_KNOWN_CONDITION','modeled_countermeasure'),(0,'MODE_B_NOVEL_ANOMALY','simulation_only')])
def test_checklist_then_action_recovers_in_ten_backend_ticks(simulation, seed, mode, kind):
    frame = assess(seed)
    decision = frame['rag_diagnosis']
    assert decision['mode'] == mode
    action = frame['blind_incident']['actions'][0]
    assert action['kind'] == kind
    assert action['physical_effect_modeled'] == (kind == 'modeled_countermeasure')
    original_confidence = decision['confidence']
    steps = decision['action_checklist']
    required = [step for step in steps if step.get('critical')] or steps
    request = {'incident_id': frame['simulation_incident'], 'action_id': action['id'], 'acknowledged_steps': []}
    assert server.apply_blind_action(request)['status'] == 'error'
    assert not simulation.is_recovering
    request['acknowledged_steps'] = [step['step'] for step in required]
    assert server.apply_blind_action(request)['status'] == 'ok'
    assert server.apply_blind_action(request)['status'] == 'error'
    frames = [server.advance_telemetry() for _ in range(10)]
    assert any(p['blind_incident']['phase'] == 'recovering' for p in frames)
    assert frames[-1]['blind_incident']['phase'] == 'complete'
    assert frames[-1]['anomaly_assessment']['alert_level'] == 'NOMINAL'
    assert frames[-1]['recovery_status'] == 'COMPLETE'
    assert frames[-1]['rag_diagnosis']['confidence'] == original_confidence
    assert simulation.active_scenario == 'nominal'

@pytest.mark.parametrize('seed',[0,2])
def test_pdf_is_genuine_and_bound_to_original_assessment(simulation, monkeypatch, seed):
    frame = assess(seed)
    report = deepcopy(frame['rag_diagnosis']['earth_report'])
    reference = report['report_ref']
    assert report['assessment_confidence_raw'] == frame['rag_diagnosis']['confidence']
    assert report['assessment_id'] == frame['rag_diagnosis']['diagnosis_id']
    # A newer/changed report must not silently replace the selected one.
    server.latest_earth_report = {'report_id': 'OTHER', 'report_text': 'WRONG REPORT'}
    monkeypatch.setattr(server, 'execute_diagnosis_pipeline', Mock(side_effect=AssertionError('Download reran diagnosis')))
    client = TestClient(server.app)
    response = client.post('/api/reports/download?format=pdf', json={'report_ref': reference}, headers={'Origin': 'http://localhost:5500'})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['x-ares-report-ref'] == reference
    assert reference[:12] in response.headers['content-disposition']
    assert 'X-ARES-Report-Ref' in response.headers['access-control-expose-headers']
    assert response.content.startswith(b'%PDF-')
    reader = PdfReader(BytesIO(response.content))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert report['report_id'] in text
    assert re.sub(r'\s+', ' ', _pdf_safe_text(report['diagnosis'])) in re.sub(r'\s+', ' ', text)
    assert 'WRONG REPORT' not in text
    expired = client.post('/api/reports/download?format=pdf', json={'report_ref': '0' * 64})
    assert expired.status_code == 410

def test_report_store_is_immutable_and_bounded(monkeypatch):
    monkeypatch.setattr(report_store, '_reports', OrderedDict())
    source = {'report_id': 'ONE', 'report_text': 'Original', 'nested': {'value': 1}}
    saved = report_store.capture_report(source, confidence=.74999, assessment_id='DIAG-1')
    source['nested']['value'] = 2
    result = report_store.retrieve_report(saved['report_ref'])
    assert result['nested']['value'] == 1
    result['nested']['value'] = 3
    assert report_store.retrieve_report(saved['report_ref'])['nested']['value'] == 1
    for i in range(report_store.MAX_REPORTS):
        report_store.capture_report({'report_id': str(i), 'report_text': str(i)})
    assert len(report_store._reports) == report_store.MAX_REPORTS
    with pytest.raises(report_store.ReportNotFound):
        report_store.retrieve_report(saved['report_ref'])
