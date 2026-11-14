"""
Biotelemetry, Anomaly Assessment, and Clinical Decision Support Data Models.

Bridges both Dheer's Telemetry Schema (`DHEER-GUIDE.md` / `vanilla_frontend_architecture.md`)
and the Master Engineering Plan (`hackathon_master_plan.md` / `clinical_decision_protocol_2_modes.md`).
Validates and sanitizes all inputs at the API boundary per `security_and_safety_guardrails.md`.

Includes automatic pure-Python standard-library fallback if Pydantic is not installed
in an air-gapped environment.
"""

from typing import Any, Dict, List, Optional, Tuple


DEMO_ASTRONAUT_ID = "ASTRO-01"
DEMO_ASTRONAUT_NAME = "Cmdr. Alex Vance"

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


def _reject_unknown_fields(data: Dict[str, Any], allowed: set[str], model_name: str) -> None:
    """Match Pydantic's extra='forbid' behavior in the standard-library fallback."""
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown {model_name} field(s): {', '.join(sorted(unknown))}")


CORE_VITAL_KEYS = (
    "heart_rate",
    "blood_pressure_sys",
    "blood_pressure_dia",
    "spo2",
    "hrv_ms",
    "core_temp_c",
    "respiration_rate",
)

VITAL_ALIAS_MAP = {
    "hr_bpm": "heart_rate",
    "HR_bpm": "heart_rate",
    "sbp_mmHg": "blood_pressure_sys",
    "SBP_mmHg": "blood_pressure_sys",
    "dbp_mmHg": "blood_pressure_dia",
    "DBP_mmHg": "blood_pressure_dia",
    "spo2_pct": "spo2",
    "SpO2_pct": "spo2",
    "hrv_rmssd_ms": "hrv_ms",
    "HRV_RMSSD_ms": "hrv_ms",
    "cbt_C": "core_temp_c",
    "Tcore_C": "core_temp_c",
    "tcore_c": "core_temp_c",
    "rr_bpm": "respiration_rate",
    "RR_breaths_min": "respiration_rate",
    "rr_breaths_min": "respiration_rate",
    "ve_L_min": "ve_l_min",
}

ENV_ALIAS_MAP = {
    "cabin_ppCO2_mmHg": "cabin_co2_mmhg",
    "ppCO2_mmHg": "cabin_co2_mmhg",
    "ppco2_mmhg": "cabin_co2_mmhg",
    "dosimetry_rate_mSv_hr": "ambient_radiation_msv_h",
    "radiation_mSv_h": "ambient_radiation_msv_h",
    "radiation_msv_h": "ambient_radiation_msv_h",
    "cabin_ppO2_mmHg": "cabin_ppo2_mmhg",
    "ppO2_mmHg": "cabin_ppo2_mmhg",
    "suit_PICO2_mmHg": "suit_pico2_mmhg",
}


def _normalize_vitals_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Dheer, NASA, and canonical 1 Hz vital field names."""
    normalized = dict(data)
    for src_key, dst_key in VITAL_ALIAS_MAP.items():
        if src_key in normalized:
            if dst_key not in normalized or normalized[dst_key] is None:
                normalized[dst_key] = normalized[src_key]
            normalized.pop(src_key, None)
    for core_key in CORE_VITAL_KEYS:
        if core_key in normalized and normalized[core_key] is None:
            normalized.pop(core_key, None)
    return normalized


def _normalize_env_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize environment keys and convert canonical `O2_kPa` to `cabin_ppo2_mmhg`."""
    normalized = dict(data)
    for src_key, dst_key in ENV_ALIAS_MAP.items():
        if src_key in normalized:
            if dst_key not in normalized or normalized[dst_key] is None:
                normalized[dst_key] = normalized[src_key]
            normalized.pop(src_key, None)
    for kpa_key in ("O2_kPa", "o2_kpa"):
        if kpa_key in normalized:
            raw_kpa = normalized.pop(kpa_key, None)
            if raw_kpa is not None and normalized.get("cabin_ppo2_mmhg") is None:
                try:
                    normalized["cabin_ppo2_mmhg"] = round(float(raw_kpa) * 7.50062, 2)
                except (TypeError, ValueError):
                    pass
    for req_env_key in (
        "cabin_co2_mmhg",
        "ambient_radiation_msv_h",
        "suit_pressure_psi",
        "cabin_ppo2_mmhg",
        "donki_spe_active",
        "bfo_dose_rate_mGy_hr",
    ):
        if req_env_key in normalized and normalized[req_env_key] is None:
            normalized.pop(req_env_key, None)
    return normalized


def _normalize_comms_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Contract A communications status fields."""
    return dict(data)


def _format_elapsed_met(elapsed_s: Any) -> str:
    """Convert elapsed seconds into MET `DDD:HH:MM:SS` format."""
    try:
        total = max(0, int(float(elapsed_s)))
    except (TypeError, ValueError):
        return "000:00:00:00"
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{days:03d}:{hours:02d}:{minutes:02d}:{seconds:02d}"


def _normalize_quality_flags(raw_flags: Any) -> Tuple[Optional[Dict[str, str]], List[str]]:
    """Normalize `quality_flags` (dict or list) and identify unreliable channels."""
    if raw_flags is None:
        return None, []
    bad_markers = ("UNRELIABLE", "MISSING", "DROPOUT", "INVALID", "FAULT", "CORRUPT", "BAD", "SUSPECT")
    normalized: Dict[str, str] = {}
    unreliable: List[str] = []

    def _canon_channel(name: str) -> str:
        if name in ("O2_kPa", "o2_kpa"):
            return "cabin_ppo2_mmhg"
        return VITAL_ALIAS_MAP.get(name, ENV_ALIAS_MAP.get(name, name))

    if isinstance(raw_flags, dict):
        for k, v in raw_flags.items():
            key_s = str(k)
            val_s = str(v)
            normalized[key_s] = val_s
            upper_v = val_s.upper()
            if any(m in upper_v for m in bad_markers):
                unreliable.append(_canon_channel(key_s))
    elif isinstance(raw_flags, list):
        for entry in raw_flags:
            key_s = str(entry)
            normalized[key_s] = "UNRELIABLE"
            unreliable.append(_canon_channel(key_s))
    return normalized, sorted(set(unreliable))


def _detect_missing_vitals(raw_vitals: Any) -> List[str]:
    """Return canonical vital names omitted or set to None in the input payload."""
    if raw_vitals is None:
        return list(CORE_VITAL_KEYS)
    if isinstance(raw_vitals, dict):
        present: set[str] = set()
        for k, val in raw_vitals.items():
            if val is None:
                continue
            canon = VITAL_ALIAS_MAP.get(k, k)
            if canon in CORE_VITAL_KEYS:
                try:
                    float(val)
                    present.add(canon)
                except (TypeError, ValueError):
                    pass
        return [key for key in CORE_VITAL_KEYS if key not in present]
    present = set()
    for core_key in CORE_VITAL_KEYS:
        if getattr(raw_vitals, core_key, None) is not None:
            present.add(core_key)
    return [key for key in CORE_VITAL_KEYS if key not in present]


def _unpack_packet_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Support Dheer's schema, Contract A nested `astronaut` schema, canonical 1 Hz keys, and flat dicts."""
    payload = dict(data)
    if "timestamp_utc" in payload:
        ts_val = payload.pop("timestamp_utc")
        if ts_val is not None and "timestamp" not in payload:
            payload["timestamp"] = ts_val
    if "elapsed_s" in payload and payload["elapsed_s"] is not None and "met" not in payload:
        payload["met"] = _format_elapsed_met(payload["elapsed_s"])
    if "crew_state_id" in payload:
        cs_val = payload.pop("crew_state_id")
        if cs_val is not None and "activity_state" not in payload:
            payload["activity_state"] = cs_val
    if "scenario_id" in payload:
        sc_val = payload.pop("scenario_id")
        if sc_val is not None and not payload.get("active_scenario_id"):
            payload["active_scenario_id"] = sc_val

    if "astronaut" in payload and isinstance(payload["astronaut"], dict):
        astro = payload["astronaut"]
        _reject_unknown_fields(
            astro,
            {"id", "name", "activity_state", "active_scenario_id", "vitals", "specialized_diagnostics", "symptom_log"},
            "astronaut",
        )
        payload.setdefault("astronaut_id", astro.get("id", DEMO_ASTRONAUT_ID))
        payload.setdefault("name", astro.get("name", DEMO_ASTRONAUT_NAME))
        payload.setdefault("activity_state", astro.get("activity_state", "IVA_REST"))
        payload.setdefault("active_scenario_id", astro.get("active_scenario_id"))
        payload.setdefault("vitals", astro.get("vitals", {}))
        payload.setdefault("specialized_diagnostics", astro.get("specialized_diagnostics"))
        payload.setdefault("symptom_log", astro.get("symptom_log", ""))
        payload.pop("astronaut", None)

    vital_keys = set(VITAL_ALIAS_MAP.keys()) | set(CORE_VITAL_KEYS) | {"ve_l_min"}
    if "vitals" not in payload:
        extracted_vitals = {k: payload[k] for k in vital_keys if k in payload}
        if extracted_vitals:
            payload["vitals"] = extracted_vitals
            for key in extracted_vitals:
                payload.pop(key, None)

    env_keys = set(ENV_ALIAS_MAP.keys()) | {
        "cabin_co2_mmhg", "ambient_radiation_msv_h", "suit_pressure_psi",
        "cabin_ppo2_mmhg", "suit_pico2_mmhg", "donki_spe_active",
        "cabin_pressure_kPa", "cabin_temp_C", "O2_kPa", "o2_kpa",
        "bfo_dose_rate_mGy_hr",
    }
    if "environment" not in payload:
        extracted_env = {k: payload[k] for k in env_keys if k in payload}
        if extracted_env:
            payload["environment"] = extracted_env
            for key in extracted_env:
                payload.pop(key, None)

    if "scenario" in payload:
        if not payload.get("active_scenario_id"):
            payload["active_scenario_id"] = payload["scenario"]
        payload.pop("scenario", None)

    if "vitals" in payload:
        payload.setdefault("missing_vitals", _detect_missing_vitals(payload["vitals"]))
    elif not payload.get("force_mode_b", False):
        payload.setdefault("missing_vitals", list(CORE_VITAL_KEYS))
    else:
        payload.setdefault("missing_vitals", [])

    q_flags, unreliable = _normalize_quality_flags(payload.get("quality_flags"))
    if q_flags is not None:
        payload["quality_flags"] = q_flags
    payload.setdefault("unreliable_channels", unreliable)

    return payload


if PYDANTIC_AVAILABLE:

    class CommsStatus(BaseModel):
        """Communications and autonomy state from Contract A."""

        model_config = ConfigDict(extra="forbid")

        one_way_delay_sec: int = Field(default=0, ge=0, le=86400)
        mode: str = Field(default="AUTONOMOUS_LEVEL_V", min_length=1, max_length=64)
        solar_conjunction_blackout: bool = False

        @model_validator(mode="before")
        @classmethod
        def normalize_comms(cls, data: Any) -> Any:
            if isinstance(data, dict):
                return _normalize_comms_dict(data)
            return data

    class Vitals(BaseModel):
        """Astronaut physiological vital signs supporting both naming conventions."""

        model_config = ConfigDict(extra="forbid", populate_by_name=True)

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

        model_config = ConfigDict(extra="forbid", populate_by_name=True)

        cabin_co2_mmhg: float = Field(default=2.2, ge=0.0, le=50.0)
        ambient_radiation_msv_h: float = Field(default=0.054, ge=0.0, le=500.0)
        bfo_dose_rate_mGy_hr: Optional[float] = Field(default=None, ge=0.0, le=500.0)
        suit_pressure_psi: float = Field(default=4.3, ge=2.0, le=16.0)
        cabin_ppo2_mmhg: float = Field(default=148.0, ge=50.0, le=250.0)
        suit_pico2_mmhg: Optional[float] = Field(default=None, ge=0.0, le=50.0)
        donki_spe_active: bool = Field(default=False)
        cabin_pressure_kPa: Optional[float] = Field(default=None, ge=0.0, le=200.0)
        cabin_temp_C: Optional[float] = Field(default=None, ge=-100.0, le=100.0)

        @model_validator(mode="before")
        @classmethod
        def normalize_env_aliases(cls, data: Any) -> Any:
            if isinstance(data, dict):
                return _normalize_env_dict(data)
            return data

    class SpecializedDiagnostics(BaseModel):
        """Optional point-of-care medical diagnostic inputs (OCT, C2M2 CBC, Ultrasound)."""

        model_config = ConfigDict(extra="forbid")

        oct_rnfl_um: Optional[float] = None
        refraction_shift_D: Optional[float] = None
        alc_cells_uL: Optional[float] = None
        ultrasound_ijv_thrombus: Optional[bool] = None
        bladder_volume_mL: Optional[float] = None

    class TelemetryPacket(BaseModel):
        """Unified 1Hz Astronaut Telemetry Packet & `/api/diagnose` Request Payload."""

        model_config = ConfigDict(extra="forbid", populate_by_name=True)

        timestamp: str = Field(default="2026-11-14T10:15:30Z")
        met: str = Field(default="042:14:30:12")
        elapsed_s: Optional[float] = Field(default=None, ge=0.0)
        mission_day: int = Field(default=84, ge=1, le=1200)
        astronaut_id: str = Field(default=DEMO_ASTRONAUT_ID)
        name: str = Field(default=DEMO_ASTRONAUT_NAME)
        activity_state: str = Field(default="IVA_REST")
        active_scenario_id: Optional[str] = Field(default=None)
        comms_status: Optional[CommsStatus] = Field(default=None)
        vitals: Vitals = Field(default_factory=Vitals)
        environment: Environment = Field(default_factory=Environment)
        specialized_diagnostics: Optional[SpecializedDiagnostics] = Field(default=None)
        symptom_log: str = Field(default="Nominal resting state; no acute complaints.")
        force_mode_b: bool = Field(default=False)
        stateless_evaluation: bool = Field(default=True)
        quality_flags: Optional[Dict[str, str]] = Field(default=None)
        source_manifest_id: Optional[str] = Field(default=None)
        model_version: Optional[str] = Field(default=None)
        missing_vitals: List[str] = Field(default_factory=list)
        unreliable_channels: List[str] = Field(default_factory=list)

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
        threshold: Optional[float] = None
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
    class CommsStatus:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            _reject_unknown_fields(
                kwargs,
                {"one_way_delay_sec", "mode", "solar_conjunction_blackout"},
                "comms_status",
            )
            normalized = _normalize_comms_dict(kwargs)
            self.one_way_delay_sec = int(normalized.get("one_way_delay_sec", 0))
            self.mode = str(normalized.get("mode", "AUTONOMOUS_LEVEL_V"))
            self.solar_conjunction_blackout = bool(normalized.get("solar_conjunction_blackout", False))
            if not 0 <= self.one_way_delay_sec <= 86400 or not self.mode:
                raise ValueError("Invalid comms_status values")

        def model_dump(self) -> Dict[str, Any]:
            return dict(self.__dict__)

    class Vitals:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            _reject_unknown_fields(
                kwargs,
                set(VITAL_ALIAS_MAP.keys()) | set(CORE_VITAL_KEYS) | {"ve_l_min"},
                "vitals",
            )
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
            _reject_unknown_fields(
                kwargs,
                set(ENV_ALIAS_MAP.keys()) | {
                    "cabin_co2_mmhg", "ambient_radiation_msv_h", "suit_pressure_psi",
                    "cabin_ppo2_mmhg", "suit_pico2_mmhg", "donki_spe_active",
                    "cabin_pressure_kPa", "cabin_temp_C", "O2_kPa", "o2_kpa",
                    "bfo_dose_rate_mGy_hr",
                },
                "environment",
            )
            norm = _normalize_env_dict(kwargs)
            self.cabin_co2_mmhg = _clamp_float(norm.get("cabin_co2_mmhg", 2.2), 2.2, 0.0, 50.0)
            self.ambient_radiation_msv_h = _clamp_float(norm.get("ambient_radiation_msv_h", 0.054), 0.054, 0.0, 500.0)
            self.bfo_dose_rate_mGy_hr = (
                _clamp_float(norm["bfo_dose_rate_mGy_hr"], 0.0, 0.0, 500.0)
                if norm.get("bfo_dose_rate_mGy_hr") is not None else None
            )
            self.suit_pressure_psi = _clamp_float(norm.get("suit_pressure_psi", 4.3), 4.3, 2.0, 16.0)
            self.cabin_ppo2_mmhg = _clamp_float(norm.get("cabin_ppo2_mmhg", 148.0), 148.0, 50.0, 250.0)
            self.suit_pico2_mmhg = norm.get("suit_pico2_mmhg")
            self.donki_spe_active = bool(norm.get("donki_spe_active", False))
            self.cabin_pressure_kPa = (
                _clamp_float(norm["cabin_pressure_kPa"], 101.3, 0.0, 200.0)
                if norm.get("cabin_pressure_kPa") is not None else None
            )
            self.cabin_temp_C = (
                _clamp_float(norm["cabin_temp_C"], 22.0, -100.0, 100.0)
                if norm.get("cabin_temp_C") is not None else None
            )

    class SpecializedDiagnostics:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            _reject_unknown_fields(
                kwargs,
                {"oct_rnfl_um", "refraction_shift_D", "alc_cells_uL", "ultrasound_ijv_thrombus", "bladder_volume_mL"},
                "specialized_diagnostics",
            )
            self.oct_rnfl_um = kwargs.get("oct_rnfl_um")
            self.refraction_shift_D = kwargs.get("refraction_shift_D")
            self.alc_cells_uL = kwargs.get("alc_cells_uL")
            self.ultrasound_ijv_thrombus = kwargs.get("ultrasound_ijv_thrombus")
            self.bladder_volume_mL = kwargs.get("bladder_volume_mL")

    class TelemetryPacket:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            unpacked = _unpack_packet_dict(kwargs)
            root_fields = (
                {
                    "timestamp", "met", "elapsed_s", "mission_day", "astronaut_id", "name", "activity_state",
                    "active_scenario_id", "comms_status", "vitals", "environment",
                    "specialized_diagnostics", "symptom_log", "force_mode_b", "stateless_evaluation",
                    "quality_flags", "source_manifest_id", "model_version",
                    "missing_vitals", "unreliable_channels", "astronaut", "scenario",
                    "cabin_co2_mmhg", "ambient_radiation_msv_h", "bfo_dose_rate_mGy_hr", "suit_pressure_psi",
                    "cabin_ppo2_mmhg", "suit_pico2_mmhg", "donki_spe_active",
                    "cabin_pressure_kPa", "cabin_temp_C", "O2_kPa", "o2_kpa", "ve_l_min",
                }
                | set(VITAL_ALIAS_MAP.keys())
                | set(CORE_VITAL_KEYS)
                | set(ENV_ALIAS_MAP.keys())
            )
            _reject_unknown_fields(unpacked, root_fields, "telemetry")
            self.timestamp = str(unpacked.get("timestamp", "2026-11-14T10:15:30Z"))
            self.met = str(unpacked.get("met", "042:14:30:12"))
            self.elapsed_s = unpacked.get("elapsed_s")
            self.mission_day = int(unpacked.get("mission_day", 84))
            self.astronaut_id = str(unpacked.get("astronaut_id", DEMO_ASTRONAUT_ID))
            self.name = str(unpacked.get("name", DEMO_ASTRONAUT_NAME))
            self.activity_state = str(unpacked.get("activity_state", "IVA_REST"))
            self.active_scenario_id = unpacked.get("active_scenario_id")
            comms = unpacked.get("comms_status")
            self.comms_status = (
                comms if isinstance(comms, CommsStatus) or comms is None else CommsStatus(**comms)
            )
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
            self.quality_flags = unpacked.get("quality_flags")
            self.source_manifest_id = unpacked.get("source_manifest_id")
            self.model_version = unpacked.get("model_version")
            self.missing_vitals = list(unpacked.get("missing_vitals", []))
            self.unreliable_channels = list(unpacked.get("unreliable_channels", []))

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
            self.threshold = kwargs.get("threshold")
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
