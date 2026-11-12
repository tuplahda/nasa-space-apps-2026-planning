"""
Biotelemetry, Anomaly Assessment, and Clinical Decision Support Data Models.

Bridges both Dheer's Telemetry Schema (`DHEER-GUIDE.md` / `vanilla_frontend_architecture.md`)
and the Master Engineering Plan (`hackathon_master_plan.md` / `clinical_decision_protocol_2_modes.md`).
Validates and sanitizes all inputs at the API boundary per `security_and_safety_guardrails.md`.

Includes automatic pure-Python standard-library fallback if Pydantic is not installed
in an air-gapped environment.
"""

from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field, model_validator

    PYDANTIC_AVAILABLE = True
except ImportError:  # pragma: no cover - Air-gapped stdlib fallback
    PYDANTIC_AVAILABLE = False
    BaseModel = object  # type: ignore


def _clamp_float(val: Any, default: float, low: float, high: float) -> float:
    """Safely parse and clamp a float within physiological plausibility bounds."""
    try:
        num = float(val)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, num))


def _normalize_vitals_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize both Dheer (`heart_rate`) and NASA (`hr_bpm`) vital field names."""
    normalized = dict(data)
    alias_map = {
        "hr_bpm": "heart_rate",
        "sbp_mmHg": "blood_pressure_sys",
        "dbp_mmHg": "blood_pressure_dia",
        "spo2_pct": "spo2",
        "hrv_rmssd_ms": "hrv_ms",
        "cbt_C": "core_temp_c",
        "rr_bpm": "respiration_rate",
        "ve_L_min": "ve_l_min",
    }
    for src_key, dst_key in alias_map.items():
        if src_key in normalized and dst_key not in normalized:
            normalized[dst_key] = normalized[src_key]
    return normalized


def _normalize_env_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize both `cabin_co2_mmhg` and `cabin_ppCO2_mmHg` environment keys."""
    normalized = dict(data)
    alias_map = {
        "cabin_ppCO2_mmHg": "cabin_co2_mmhg",
        "dosimetry_rate_mSv_hr": "ambient_radiation_msv_h",
        "bfo_dose_rate_mGy_hr": "ambient_radiation_msv_h",
        "cabin_ppO2_mmHg": "cabin_ppo2_mmhg",
        "suit_PICO2_mmHg": "suit_pico2_mmhg",
    }
    for src_key, dst_key in alias_map.items():
        if src_key in normalized and dst_key not in normalized:
            normalized[dst_key] = normalized[src_key]
    return normalized


def _unpack_packet_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Support Dheer's schema, Contract A nested `astronaut` schema, and flat dicts."""
    payload = dict(data)
    if "astronaut" in payload and isinstance(payload["astronaut"], dict):
        astro = payload["astronaut"]
        payload.setdefault("astronaut_id", astro.get("id", "ASTRO-01"))
        payload.setdefault("name", astro.get("name", "Cmdr. Maya Lin"))
        payload.setdefault("activity_state", astro.get("activity_state", "IVA_REST"))
        payload.setdefault("active_scenario_id", astro.get("active_scenario_id"))
        payload.setdefault("vitals", astro.get("vitals", {}))
        payload.setdefault("specialized_diagnostics", astro.get("specialized_diagnostics"))
        payload.setdefault("symptom_log", astro.get("symptom_log", ""))

    vital_keys = {
        "heart_rate", "hr_bpm", "blood_pressure_sys", "sbp_mmHg",
        "blood_pressure_dia", "dbp_mmHg", "spo2", "spo2_pct",
        "hrv_ms", "hrv_rmssd_ms", "core_temp_c", "cbt_C",
        "respiration_rate", "rr_bpm",
    }
    if "vitals" not in payload:
        extracted_vitals = {k: payload[k] for k in vital_keys if k in payload}
        if extracted_vitals:
            payload["vitals"] = extracted_vitals

    env_keys = {
        "cabin_co2_mmhg", "cabin_ppCO2_mmHg", "ambient_radiation_msv_h",
        "dosimetry_rate_mSv_hr", "suit_pressure_psi", "cabin_ppO2_mmHg",
        "suit_PICO2_mmHg", "donki_spe_active",
    }
    if "environment" not in payload:
        extracted_env = {k: payload[k] for k in env_keys if k in payload}
        if extracted_env:
            payload["environment"] = extracted_env

    if "scenario" in payload and not payload.get("active_scenario_id"):
        payload["active_scenario_id"] = payload["scenario"]

    return payload


if PYDANTIC_AVAILABLE:

    class Vitals(BaseModel):
        """Astronaut physiological vital signs supporting both naming conventions."""

        model_config = ConfigDict(extra="ignore", populate_by_name=True)

        heart_rate: float = Field(default=62.0, ge=20.0, le=240.0, alias="hr_bpm")
        blood_pressure_sys: float = Field(default=112.0, ge=40.0, le=260.0, alias="sbp_mmHg")
        blood_pressure_dia: float = Field(default=70.0, ge=25.0, le=160.0, alias="dbp_mmHg")
        spo2: float = Field(default=98.0, ge=50.0, le=100.0, alias="spo2_pct")
        hrv_ms: float = Field(default=42.0, ge=1.0, le=200.0, alias="hrv_rmssd_ms")
        core_temp_c: float = Field(default=37.6, ge=32.0, le=43.0, alias="cbt_C")
        respiration_rate: float = Field(default=13.0, ge=4.0, le=60.0, alias="rr_bpm")
        ve_l_min: Optional[float] = Field(default=None, alias="ve_L_min")

        @model_validator(mode="before")
        @classmethod
        def normalize_vital_aliases(cls, data: Any) -> Any:
            if isinstance(data, dict):
                return _normalize_vitals_dict(data)
            return data

    class Environment(BaseModel):
        """Spacecraft habitat ECLSS and space radiation environment."""

        model_config = ConfigDict(extra="ignore", populate_by_name=True)

        cabin_co2_mmhg: float = Field(default=2.2, ge=0.0, le=50.0)
        ambient_radiation_msv_h: float = Field(default=0.054, ge=0.0, le=500.0)
        suit_pressure_psi: float = Field(default=4.3, ge=2.0, le=16.0)
        cabin_ppo2_mmhg: float = Field(default=148.0, ge=50.0, le=250.0)
        suit_pico2_mmhg: Optional[float] = Field(default=None, ge=0.0, le=50.0)
        donki_spe_active: bool = Field(default=False)

        @model_validator(mode="before")
        @classmethod
        def normalize_env_aliases(cls, data: Any) -> Any:
            if isinstance(data, dict):
                return _normalize_env_dict(data)
            return data

    class SpecializedDiagnostics(BaseModel):
        """Optional point-of-care medical diagnostic inputs (OCT, C2M2 CBC, Ultrasound)."""

        model_config = ConfigDict(extra="ignore")

        oct_rnfl_um: Optional[float] = None
        refraction_shift_D: Optional[float] = None
        alc_cells_uL: Optional[float] = None
        ultrasound_ijv_thrombus: Optional[bool] = None
        bladder_volume_mL: Optional[float] = None

    class TelemetryPacket(BaseModel):
        """Unified 1Hz Astronaut Telemetry Packet & `/api/diagnose` Request Payload."""

        model_config = ConfigDict(extra="ignore", populate_by_name=True)

        timestamp: str = Field(default="2026-11-14T10:15:30Z")
        met: str = Field(default="042:14:30:12")
        mission_day: int = Field(default=84, ge=1, le=1200)
        astronaut_id: str = Field(default="ASTRO-01")
        name: str = Field(default="Cmdr. Maya Lin")
        activity_state: str = Field(default="IVA_REST")
        active_scenario_id: Optional[str] = Field(default=None)
        vitals: Vitals = Field(default_factory=Vitals)
        environment: Environment = Field(default_factory=Environment)
        specialized_diagnostics: Optional[SpecializedDiagnostics] = Field(default=None)
        symptom_log: str = Field(default="Nominal resting state; no acute complaints.")
        force_mode_b: bool = Field(default=False)
        stateless_evaluation: bool = Field(default=True)

        @model_validator(mode="before")
        @classmethod
        def unpack_nested_astronaut_or_flat_vitals(cls, data: Any) -> Any:
            if isinstance(data, dict):
                return _unpack_packet_dict(data)
            return data

    class BreachedParameter(BaseModel):
        """Details of a single physiological or environmental threshold breach."""

        parameter: str
        display_name: str
        value: float
        unit: str
        expected_ug_range: str
        threshold_breached: str
        severity: str
        standard_ref: str
        rolling_avg_10s: float
        slew_rate_per_sec: float
        debounced: bool

    class AnomalyAssessment(BaseModel):
        """Layer 2 Edge Anomaly Detector Output (Contract B)."""

        astronaut_id: str
        normalized_activity_state: str
        mission_day: int
        alert_level: str
        nasa_priority_class: str
        risk_score_0_100: int
        readiness_score_0_100: int
        domain_scores: Dict[str, int]
        context_evaluated: str
        space_fever_adapted: bool
        seu_candidates_filtered: List[str]
        breached_parameters: List[BreachedParameter]
        triggering_vitals_summary: List[str]
        organ_hud_status: Dict[str, str]
        trigger_rag_consultation: bool

else:
    # Pure standard-library fallback classes with identical interface
    class Vitals:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            norm = _normalize_vitals_dict(kwargs)
            self.heart_rate = _clamp_float(norm.get("heart_rate", 62.0), 62.0, 20.0, 240.0)
            self.blood_pressure_sys = _clamp_float(norm.get("blood_pressure_sys", 112.0), 112.0, 40.0, 260.0)
            self.blood_pressure_dia = _clamp_float(norm.get("blood_pressure_dia", 70.0), 70.0, 25.0, 160.0)
            self.spo2 = _clamp_float(norm.get("spo2", 98.0), 98.0, 50.0, 100.0)
            self.hrv_ms = _clamp_float(norm.get("hrv_ms", 42.0), 42.0, 1.0, 200.0)
            self.core_temp_c = _clamp_float(norm.get("core_temp_c", 37.6), 37.6, 32.0, 43.0)
            self.respiration_rate = _clamp_float(norm.get("respiration_rate", 13.0), 13.0, 4.0, 60.0)
            self.ve_l_min = norm.get("ve_l_min")

    class Environment:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            norm = _normalize_env_dict(kwargs)
            self.cabin_co2_mmhg = _clamp_float(norm.get("cabin_co2_mmhg", 2.2), 2.2, 0.0, 50.0)
            self.ambient_radiation_msv_h = _clamp_float(norm.get("ambient_radiation_msv_h", 0.054), 0.054, 0.0, 500.0)
            self.suit_pressure_psi = _clamp_float(norm.get("suit_pressure_psi", 4.3), 4.3, 2.0, 16.0)
            self.cabin_ppo2_mmhg = _clamp_float(norm.get("cabin_ppo2_mmhg", 148.0), 148.0, 50.0, 250.0)
            self.suit_pico2_mmhg = norm.get("suit_pico2_mmhg")
            self.donki_spe_active = bool(norm.get("donki_spe_active", False))

    class SpecializedDiagnostics:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.oct_rnfl_um = kwargs.get("oct_rnfl_um")
            self.refraction_shift_D = kwargs.get("refraction_shift_D")
            self.alc_cells_uL = kwargs.get("alc_cells_uL")
            self.ultrasound_ijv_thrombus = kwargs.get("ultrasound_ijv_thrombus")
            self.bladder_volume_mL = kwargs.get("bladder_volume_mL")

    class TelemetryPacket:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            unpacked = _unpack_packet_dict(kwargs)
            self.timestamp = str(unpacked.get("timestamp", "2026-11-14T10:15:30Z"))
            self.met = str(unpacked.get("met", "042:14:30:12"))
            self.mission_day = int(unpacked.get("mission_day", 84))
            self.astronaut_id = str(unpacked.get("astronaut_id", "ASTRO-01"))
            self.name = str(unpacked.get("name", "Cmdr. Maya Lin"))
            self.activity_state = str(unpacked.get("activity_state", "IVA_REST"))
            self.active_scenario_id = unpacked.get("active_scenario_id")
            v_raw = unpacked.get("vitals", {})
            self.vitals = v_raw if isinstance(v_raw, Vitals) else Vitals(**(v_raw or {}))
            e_raw = unpacked.get("environment", {})
            self.environment = e_raw if isinstance(e_raw, Environment) else Environment(**(e_raw or {}))
            d_raw = unpacked.get("specialized_diagnostics")
            self.specialized_diagnostics = (
                d_raw if isinstance(d_raw, SpecializedDiagnostics) or d_raw is None else SpecializedDiagnostics(**d_raw)
            )
            self.symptom_log = str(unpacked.get("symptom_log", "Nominal resting state; no acute complaints."))
            self.force_mode_b = bool(unpacked.get("force_mode_b", False))
            self.stateless_evaluation = bool(unpacked.get("stateless_evaluation", True))

        @classmethod
        def model_validate(cls, data: Any) -> "TelemetryPacket":
            if isinstance(data, cls):
                return data
            return cls(**(data if isinstance(data, dict) else {}))

    class BreachedParameter:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.parameter = kwargs["parameter"]
            self.display_name = kwargs["display_name"]
            self.value = kwargs["value"]
            self.unit = kwargs["unit"]
            self.expected_ug_range = kwargs["expected_ug_range"]
            self.threshold_breached = kwargs["threshold_breached"]
            self.severity = kwargs["severity"]
            self.standard_ref = kwargs["standard_ref"]
            self.rolling_avg_10s = kwargs["rolling_avg_10s"]
            self.slew_rate_per_sec = kwargs["slew_rate_per_sec"]
            self.debounced = kwargs["debounced"]

        def model_dump(self) -> Dict[str, Any]:
            return dict(self.__dict__)

    class AnomalyAssessment:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.astronaut_id = kwargs["astronaut_id"]
            self.normalized_activity_state = kwargs["normalized_activity_state"]
            self.mission_day = kwargs["mission_day"]
            self.alert_level = kwargs["alert_level"]
            self.nasa_priority_class = kwargs["nasa_priority_class"]
            self.risk_score_0_100 = kwargs["risk_score_0_100"]
            self.readiness_score_0_100 = kwargs["readiness_score_0_100"]
            self.domain_scores = kwargs["domain_scores"]
            self.context_evaluated = kwargs["context_evaluated"]
            self.space_fever_adapted = kwargs["space_fever_adapted"]
            self.seu_candidates_filtered = kwargs["seu_candidates_filtered"]
            self.breached_parameters = kwargs["breached_parameters"]
            self.triggering_vitals_summary = kwargs["triggering_vitals_summary"]
            self.organ_hud_status = kwargs["organ_hud_status"]
            self.trigger_rag_consultation = kwargs["trigger_rag_consultation"]

        def model_dump(self) -> Dict[str, Any]:
            out = dict(self.__dict__)
            out["breached_parameters"] = [
                b.model_dump() if hasattr(b, "model_dump") else dict(b.__dict__)
                for b in self.breached_parameters
            ]
            return out
