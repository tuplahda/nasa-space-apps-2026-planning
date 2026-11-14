"""Bounded, immutable snapshots of reports already produced by the clinical engine."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock

MAX_REPORTS = 128
_reports = OrderedDict()
_lock = RLock()

class ReportNotFound(ValueError):
    pass

def capture_report(report, *, confidence=None, assessment_id=None, incident_id=None):
    snapshot = deepcopy(report)
    snapshot.pop("report_ref", None)
    if confidence is not None:
        snapshot["assessment_confidence_raw"] = confidence
    if assessment_id is not None:
        snapshot["assessment_id"] = assessment_id
    if incident_id is not None:
        snapshot["simulation_incident"] = incident_id
    reference = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    snapshot["report_ref"] = reference
    with _lock:
        if reference not in _reports:
            _reports[reference] = deepcopy(snapshot)
        while len(_reports) > MAX_REPORTS:
            _reports.popitem(last=False)
    return snapshot

def retrieve_report(reference):
    if not isinstance(reference, str) or len(reference) != 64:
        raise ReportNotFound("The assessment report reference is invalid or unavailable.")
    with _lock:
        if reference not in _reports:
            raise ReportNotFound("This assessment report has expired or the server restarted. Request a new consultation; no newer report was substituted.")
        return deepcopy(_reports[reference])
