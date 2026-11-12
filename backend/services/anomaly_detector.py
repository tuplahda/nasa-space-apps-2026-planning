"""
Context-Aware Microgravity Edge Anomaly Detector (Layer 2).

Evaluates incoming 1Hz astronaut telemetry ticks against NASA-STD-3001
physiological & environmental baselines (`data/nasa_baselines_and_thresholds.json`),
accounting for activity state (SLEEP, REST, EXERCISE, EVA), Flight Day adaptation
("Space Fever"), and 3-tick SEU persistence debouncing via `ring_buffer.py`.

Adheres strictly to JPL Power-of-Ten rules (no recursion, static loop bounds,
functions < 60 lines).
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.models.telemetry import (
    AnomalyAssessment,
    BreachedParameter,
    TelemetryPacket,
)
from backend.services.ring_buffer import (
    AstronautRingBufferManager,
    ChannelTelemetryStats,
)


# Hard upper bounds for loops per JPL Power-of-Ten Rule 2
MAX_VITALS_PARAMS: int = 12
MAX_ASTRONAUT_BUFFERS: int = 16
MAX_OFFICIAL_FILES: int = 10

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DEFAULT_BASELINES_PATH: Path = REPO_ROOT / "data" / "nasa_baselines_and_thresholds.json"
OFFICIAL_DATASET_DIR: Path = REPO_ROOT / "data" / "nasa_official_dataset"

ACTIVITY_STATE_MAP: Dict[str, str] = {
    "SLEEP": "SLEEP",
    "SLEEPING": "SLEEP",
    "REST": "IVA_REST",
    "RESTING": "IVA_REST",
    "IVA_REST": "IVA_REST",
    "NOMINAL": "IVA_REST",
    "GLOVEBOX": "IVA_REST",
    "EXERCISE": "ARED_EXERCISE",
    "ARED": "ARED_EXERCISE",
    "ARED_EXERCISE": "ARED_EXERCISE",
    "EVA": "EVA_SPACEWALK",
    "SPACEWALK": "EVA_SPACEWALK",
    "EVA_SPACEWALK": "EVA_SPACEWALK",
}

PARAM_DISPLAY_NAMES: Dict[str, Tuple[str, str]] = {
    "hr_bpm": ("Heart Rate", "NASA-STD-3001 [V1 3003a]"),
    "sbp_mmHg": ("Systolic BP", "NASA-STD-3001 [V1 3003a]"),
    "dbp_mmHg": ("Diastolic BP", "NASA-STD-3001 [V1 3003a]"),
    "spo2_pct": ("SpO2", "NASA-STD-3001 [V2 6003]"),
    "hrv_rmssd_ms": ("HRV (RMSSD)", "NASA-STD-3001 [V1 3003a]"),
    "cbt_C": ("Core Body Temp", "NASA-STD-3001 [V2 6012]"),
    "rr_bpm": ("Respiration Rate", "NASA-STD-3001 [V1 3003a]"),
    "cabin_ppCO2_mmHg": ("Cabin CO2", "NASA-STD-3001 [V2 6004]"),
    "ambient_radiation_msv_h": ("Ambient Radiation", "NASA-STD-3001 [V1 4030]"),
}


def _threshold_value(description: str) -> Optional[float]:
    """Expose the numeric cutoff in Contract B when the rule has one."""
    match = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)", description)
    return float(match.group(0)) if match else None


def normalize_activity_state(raw_state: str) -> str:
    """Normalize activity state strings across Dheer, Tivesh, and NASA schemas."""
    if not raw_state:
        return "IVA_REST"
    cleaned = raw_state.strip().upper().replace(" ", "_").replace("-", "_")
    return ACTIVITY_STATE_MAP.get(cleaned, "IVA_REST")


class EdgeAnomalyDetector:
    """
    Stateful Layer 2 Edge Anomaly Engine integrating NASA-STD-3001 baselines
    and per-astronaut 60-second ring buffers.
    """

    def __init__(self, baselines_path: Optional[Path] = None) -> None:
        self.baselines_path: Path = baselines_path or DEFAULT_BASELINES_PATH
        self.baselines_data: Dict[str, Any] = self._load_baselines()
        self.ring_managers: Dict[str, AstronautRingBufferManager] = {}

    def _load_baselines(self) -> Dict[str, Any]:
        """Load baseline thresholds with Priority #1 check for `data/nasa_official_dataset/`."""
        data: Dict[str, Any] = {}
        if self.baselines_path.exists():
            with open(self.baselines_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        # Priority #1 Hybrid Strategy: merge any JSON override in data/nasa_official_dataset/
        if OFFICIAL_DATASET_DIR.exists() and OFFICIAL_DATASET_DIR.is_dir():
            files = sorted(OFFICIAL_DATASET_DIR.glob("*.json"))
            for idx in range(MAX_OFFICIAL_FILES):
                if idx >= len(files):
                    break
                try:
                    with open(files[idx], "r", encoding="utf-8") as of:
                        override = json.load(of)
                    if isinstance(override, dict) and "physiological_baselines" in override:
                        data.update(override)
                except (OSError, ValueError):
                    continue
        return data

    def get_or_create_buffer(self, astronaut_id: str) -> AstronautRingBufferManager:
        """Retrieve pre-allocated ring buffer for `astronaut_id` with bounded roster size."""
        if astronaut_id not in self.ring_managers:
            if len(self.ring_managers) >= MAX_ASTRONAUT_BUFFERS:
                first_key = next(iter(self.ring_managers))
                return self.ring_managers[first_key]
            self.ring_managers[astronaut_id] = AstronautRingBufferManager(astronaut_id)
        return self.ring_managers[astronaut_id]

    def evaluate_packet(self, packet: TelemetryPacket) -> AnomalyAssessment:
        """Evaluate a telemetry packet against activity-adapted microgravity thresholds."""
        activity = normalize_activity_state(packet.activity_state)
        channel_vals = self._extract_channel_values(packet)
        raw_evals = self._evaluate_all_thresholds(channel_vals, activity, packet.mission_day)

        raw_breach_flags = {k: (v[0] != "NOMINAL") for k, v in raw_evals.items()}
        ring_mgr = self.get_or_create_buffer(packet.astronaut_id)

        if packet.stateless_evaluation:
            ring_mgr.reset()
            stats_map = ring_mgr.preload_persistent_state(channel_vals, raw_breach_flags)
        else:
            stats_map = ring_mgr.ingest_tick(channel_vals, raw_breach_flags)

        breached_list, seu_filtered = self._build_breached_list(
            raw_evals, stats_map, packet.stateless_evaluation
        )
        self._append_specialized_breaches(packet, breached_list)

        domain_scores, total_risk = self._compute_composite_risk(
            channel_vals, activity, breached_list, packet
        )
        alert_lvl, priority_cls = self._classify_overall_alert(breached_list, total_risk)
        organ_hud = self._compute_organ_hud_pins(breached_list, packet)
        trigger_summary = self._format_triggering_vitals(breached_list, packet)

        should_consult_rag = (
            alert_lvl in ("WARNING_YELLOW", "CRITICAL_RED")
            or len(breached_list) > 0
            or packet.force_mode_b
            or bool(packet.active_scenario_id and packet.active_scenario_id.lower() != "nominal")
        )

        return AnomalyAssessment(
            astronaut_id=packet.astronaut_id,
            normalized_activity_state=activity,
            mission_day=packet.mission_day,
            alert_level=alert_lvl,
            nasa_priority_class=priority_cls,
            risk_score_0_100=total_risk,
            readiness_score_0_100=max(0, 100 - total_risk),
            domain_scores=domain_scores,
            context_evaluated=f"{activity} (Adapted Microgravity Baseline, FD {packet.mission_day})",
            space_fever_adapted=(packet.mission_day >= 75),
            seu_candidates_filtered=seu_filtered,
            breached_parameters=breached_list,
            triggering_vitals_summary=trigger_summary,
            organ_hud_status=organ_hud,
            trigger_rag_consultation=should_consult_rag,
        )

    def _extract_channel_values(self, packet: TelemetryPacket) -> Dict[str, float]:
        """Map TelemetryPacket fields into canonical channel keys."""
        v = packet.vitals
        e = packet.environment
        return {
            "hr_bpm": float(v.heart_rate),
            "sbp_mmHg": float(v.blood_pressure_sys),
            "dbp_mmHg": float(v.blood_pressure_dia),
            "spo2_pct": float(v.spo2),
            "hrv_rmssd_ms": float(v.hrv_ms),
            "cbt_C": float(v.core_temp_c),
            "rr_bpm": float(v.respiration_rate),
            "cabin_ppCO2_mmHg": float(e.cabin_co2_mmhg),
            "cabin_ppO2_mmHg": float(e.cabin_ppo2_mmhg),
            "ambient_radiation_msv_h": float(e.ambient_radiation_msv_h),
            "suit_pressure_psi": float(e.suit_pressure_psi),
        }

    def _evaluate_all_thresholds(
        self, vals: Dict[str, float], activity: str, mission_day: int
    ) -> Dict[str, Tuple[str, str, str, str]]:
        """
        Return `{param: (severity, expected_range_str, threshold_desc, unit)}`
        for all physiological and environmental channels.
        """
        phys = self.baselines_data.get("physiological_baselines", {})
        results: Dict[str, Tuple[str, str, str, str]] = {}

        phys_keys = ["hr_bpm", "sbp_mmHg", "dbp_mmHg", "spo2_pct", "hrv_rmssd_ms", "cbt_C", "rr_bpm"]
        for i in range(MAX_VITALS_PARAMS):
            if i >= len(phys_keys):
                break
            key = phys_keys[i]
            spec = phys.get(key, {})
            results[key] = self._eval_single_vital(
                key, vals.get(key, 0.0), activity, mission_day, spec
            )

        # Evaluate Cabin/Suit CO2 (`NASA-STD-3001 [V2 6004]`)
        co2 = vals.get("cabin_ppCO2_mmHg", 2.0)
        if activity == "EVA_SPACEWALK" and co2 >= 12.5:
            results["cabin_ppCO2_mmHg"] = ("CRITICAL_RED", "< 2.0 mmHg", "> 12.5 mmHg (Suit Limit)", "mmHg")
        elif co2 > 4.5:
            results["cabin_ppCO2_mmHg"] = ("CRITICAL_RED", "< 2.5 mmHg", "> 4.5 mmHg (Acute Limit)", "mmHg")
        elif co2 >= 2.8:
            results["cabin_ppCO2_mmHg"] = ("WARNING_YELLOW", "< 2.5 mmHg", ">= 2.8 mmHg (V2 6004)", "mmHg")
        else:
            results["cabin_ppCO2_mmHg"] = ("NOMINAL", "< 2.5 mmHg", "Nominal", "mmHg")

        # Evaluate Ambient Radiation (`NASA-STD-3001 [V1 4030]`)
        rad = vals.get("ambient_radiation_msv_h", 0.054)
        if rad >= 2.0:
            results["ambient_radiation_msv_h"] = ("CRITICAL_RED", "< 0.06 mSv/h", ">= 2.0 mSv/h (SPE Crisis)", "mSv/h")
        elif rad >= 0.25:
            results["ambient_radiation_msv_h"] = ("WARNING_YELLOW", "< 0.06 mSv/h", ">= 0.25 mSv/h (SPE Watch)", "mSv/h")
        else:
            results["ambient_radiation_msv_h"] = ("NOMINAL", "< 0.06 mSv/h", "Nominal", "mSv/h")

        return results

    def _eval_single_vital(
        self,
        key: str,
        val: float,
        activity: str,
        mission_day: int,
        spec: Dict[str, Any],
    ) -> Tuple[str, str, str, str]:
        """Evaluate one physiological parameter against activity-specific thresholds."""
        unit = str(spec.get("unit", ""))
        mods = spec.get("activity_modifiers_ug", {})
        exp_pair = mods.get(activity) or spec.get("adapted_ug_iva_rest", [0, 100])
        exp_str = f"{exp_pair[0]}-{exp_pair[1]} {unit}".strip()

        # Special microgravity "Space Fever" rule: resting CBT 37.4-38.0°C is nominal post-FD75
        if key == "cbt_C" and activity == "IVA_REST" and mission_day >= 75:
            if 37.0 <= val <= 38.05:
                return ("NOMINAL", "37.4-38.0 °C", "Nominal (Space Fever Adapted)", unit)

        # If reading is inside the explicit activity_modifiers_ug range for this activity, it is nominal
        if activity in mods and len(exp_pair) == 2:
            if float(exp_pair[0]) <= val <= float(exp_pair[1]):
                return ("NOMINAL", exp_str, "Nominal", unit)

        crit_map = spec.get("critical_red", {})
        warn_map = spec.get("warning_yellow", {})
        crit_bounds = crit_map.get(activity) or crit_map.get("DEFAULT") or crit_map.get("IVA_REST", {})
        warn_bounds = warn_map.get(activity) or warn_map.get("DEFAULT") or warn_map.get("IVA_REST", {})

        c_min, c_max = crit_bounds.get("min"), crit_bounds.get("max")
        if c_min is not None and val < float(c_min):
            return ("CRITICAL_RED", exp_str, f"< {c_min} {unit} (Critical Min)", unit)
        if c_max is not None and val > float(c_max):
            return ("CRITICAL_RED", exp_str, f"> {c_max} {unit} (Critical Max)", unit)

        w_min, w_max = warn_bounds.get("min"), warn_bounds.get("max")
        if w_min is not None and val < float(w_min):
            return ("WARNING_YELLOW", exp_str, f"< {w_min} {unit} (Warning Min)", unit)
        if w_max is not None and val > float(w_max):
            return ("WARNING_YELLOW", exp_str, f"> {w_max} {unit} (Warning Max)", unit)

        # Catch subtle drift outside expected microgravity range (e.g. HR=84 in IVA_REST or HR=65 in SLEEP)
        if len(exp_pair) == 2 and key in ("hr_bpm", "rr_bpm", "cbt_C"):
            low, high = float(exp_pair[0]), float(exp_pair[1])
            margin = 5.0 if key == "hr_bpm" else (2.0 if key == "rr_bpm" else 0.35)
            if val > high + margin:
                return ("WARNING_YELLOW", exp_str, f"> {high} {unit} (μg Activity Drift)", unit)
            if val < low - margin:
                return ("WARNING_YELLOW", exp_str, f"< {low} {unit} (μg Activity Drift)", unit)

        return ("NOMINAL", exp_str, "Nominal", unit)

    def _build_breached_list(
        self,
        raw_evals: Dict[str, Tuple[str, str, str, str]],
        stats_map: Dict[str, ChannelTelemetryStats],
        stateless: bool,
    ) -> Tuple[List[BreachedParameter], List[str]]:
        """Filter raw threshold breaches through the 3-tick SEU ring buffer debounce."""
        breached: List[BreachedParameter] = []
        seu_filtered: List[str] = []
        keys = list(raw_evals.keys())

        for i in range(MAX_VITALS_PARAMS):
            if i >= len(keys):
                break
            k = keys[i]
            sev, exp_str, thresh_desc, unit = raw_evals[k]
            st = stats_map.get(k)
            if st is None:
                continue

            if st.integrity_flag in ("SEU_CANDIDATE", "SENSOR_FAULT"):
                seu_filtered.append(f"{k}: raw={st.raw_value} ({st.integrity_flag})")
                continue

            if sev != "NOMINAL":
                is_debounced = True if stateless else st.debounced_anomaly_active
                if is_debounced:
                    disp_name, std_ref = PARAM_DISPLAY_NAMES.get(k, (k, "NASA-STD-3001"))
                    breached.append(
                        BreachedParameter(
                            parameter=k,
                            display_name=disp_name,
                            value=st.validated_value,
                            threshold=_threshold_value(thresh_desc),
                            unit=unit,
                            expected_ug_range=exp_str,
                            threshold_breached=thresh_desc,
                            severity=sev,
                            standard_ref=std_ref,
                            rolling_avg_10s=st.rolling_avg_10s,
                            slew_rate_per_sec=st.slew_rate_per_sec,
                            debounced=is_debounced,
                        )
                    )
                else:
                    seu_filtered.append(
                        f"{k}: transient spike ({st.consecutive_abnormal_ticks}/3 ticks)"
                    )
        return breached, seu_filtered

    def _append_specialized_breaches(
        self, packet: TelemetryPacket, breached: List[BreachedParameter]
    ) -> None:
        """Add breaches from point-of-care diagnostics (OCT, C2M2 ALC, Ultrasound, Bladder)."""
        diag = packet.specialized_diagnostics
        if diag is None:
            return
        if diag.oct_rnfl_um is not None and diag.oct_rnfl_um > 105.0:
            sev = "CRITICAL_RED" if diag.oct_rnfl_um > 115.0 else "WARNING_YELLOW"
            breached.append(
                BreachedParameter(
                    parameter="oct_rnfl_um",
                    display_name="OCT Retinal Nerve Fiber Layer",
                    value=diag.oct_rnfl_um,
                    threshold=105.0,
                    unit="μm",
                    expected_ug_range="90-102 μm",
                    threshold_breached="> 105 μm (SANS Optic Disc Edema)",
                    severity=sev,
                    standard_ref="NASA SANS CPG / JSC-48522",
                    rolling_avg_10s=diag.oct_rnfl_um,
                    slew_rate_per_sec=0.0,
                    debounced=True,
                )
            )
        if diag.alc_cells_uL is not None and diag.alc_cells_uL < 1500.0:
            breached.append(
                BreachedParameter(
                    parameter="alc_cells_uL",
                    display_name="Absolute Lymphocyte Count (C2M2)",
                    value=diag.alc_cells_uL,
                    threshold=1500.0,
                    unit="cells/μL",
                    expected_ug_range="1500-4000 cells/μL",
                    threshold_breached="< 1500 cells/μL (Andrews Radiation Depletion)",
                    severity="CRITICAL_RED",
                    standard_ref="NASA-STD-3001 [V1 4030]",
                    rolling_avg_10s=diag.alc_cells_uL,
                    slew_rate_per_sec=0.0,
                    debounced=True,
                )
            )
        if diag.ultrasound_ijv_thrombus is True:
            breached.append(
                BreachedParameter(
                    parameter="ultrasound_ijv_thrombus",
                    display_name="IJV Ultrasound Venous Scan",
                    value=1.0,
                    threshold=1.0,
                    unit="boolean",
                    expected_ug_range="Compressible / Patent",
                    threshold_breached="Echogenic Thrombus Detected",
                    severity="CRITICAL_RED",
                    standard_ref="ISS Vascular Contingency Protocol",
                    rolling_avg_10s=1.0,
                    slew_rate_per_sec=0.0,
                    debounced=True,
                )
            )
        if diag.bladder_volume_mL is not None and diag.bladder_volume_mL > 500.0:
            breached.append(
                BreachedParameter(
                    parameter="bladder_volume_mL",
                    display_name="Bladder Ultrasound Volume",
                    value=diag.bladder_volume_mL,
                    threshold=500.0,
                    unit="mL",
                    expected_ug_range="< 400 mL",
                    threshold_breached="> 500 mL (Acute Urinary Retention)",
                    severity="CRITICAL_RED",
                    standard_ref="ISS Medical Checklist JSC-48522",
                    rolling_avg_10s=diag.bladder_volume_mL,
                    slew_rate_per_sec=0.0,
                    debounced=True,
                )
            )

    def _compute_composite_risk(
        self,
        vals: Dict[str, float],
        activity: str,
        breached: List[BreachedParameter],
        packet: TelemetryPacket,
    ) -> Tuple[Dict[str, int], int]:
        """
        Calculate continuous Risk Score (0-100) across the 4 weighted NASA domains:
        Hemodynamic (30%), Respiratory/Thermal (25%), Autonomic/Neuro (20%), Env/Radiation (25%).
        """
        hemo, resp, auto, env_score = 8, 6, 6, 4
        for i in range(MAX_VITALS_PARAMS):
            if i >= len(breached):
                break
            b = breached[i]
            pts = 75 if b.severity == "CRITICAL_RED" else 42
            if b.parameter in ("hr_bpm", "sbp_mmHg", "dbp_mmHg", "ultrasound_ijv_thrombus"):
                hemo = min(100, hemo + pts)
            elif b.parameter in ("spo2_pct", "rr_bpm", "cbt_C"):
                resp = min(100, resp + pts)
            elif b.parameter in ("hrv_rmssd_ms", "oct_rnfl_um", "bladder_volume_mL"):
                auto = min(100, auto + pts)
            elif b.parameter in ("cabin_ppCO2_mmHg", "ambient_radiation_msv_h", "alc_cells_uL"):
                env_score = min(100, env_score + pts)

        if packet.environment.donki_spe_active:
            env_score = max(env_score, 85)

        weighted = int(round(0.30 * hemo + 0.25 * resp + 0.20 * auto + 0.25 * env_score))
        if any(b.severity == "CRITICAL_RED" for b in breached):
            weighted = max(weighted, 78)
        elif len(breached) > 0:
            weighted = max(weighted, 45)
        total = max(0, min(100, weighted))

        return (
            {
                "hemodynamic_30pct": hemo,
                "respiratory_thermal_25pct": resp,
                "autonomic_neuro_ocular_20pct": auto,
                "environmental_radiation_25pct": env_score,
            },
            total,
        )

    def _classify_overall_alert(
        self, breached: List[BreachedParameter], risk_score: int
    ) -> Tuple[str, str]:
        """Map breached parameters to NASA-STD-3001 Alarm Priority Hierarchy."""
        if any(b.severity == "CRITICAL_RED" for b in breached) or risk_score >= 75:
            return ("CRITICAL_RED", "CLASS_1_EMERGENCY")
        if len(breached) > 0 or risk_score >= 40:
            return ("WARNING_YELLOW", "CLASS_2_WARNING")
        if risk_score >= 20:
            return ("CAUTION_YELLOW", "CLASS_3_CAUTION")
        return ("NOMINAL", "NOMINAL")

    def _compute_organ_hud_pins(
        self, breached: List[BreachedParameter], packet: TelemetryPacket
    ) -> Dict[str, str]:
        """Compute color states (CYAN, AMBER, RED) for Tivesh's 3D Holographic Body HUD."""
        pins = {
            "SANS-01": "CYAN",  # Head / Neuro-Ocular
            "CV-02": "CYAN",    # Heart / Cardiovascular
            "ECLSS-03": "CYAN", # Lungs / Respiratory & CO2
            "RAD-04": "CYAN",   # Core / Radiation & Thermal
        }
        for i in range(MAX_VITALS_PARAMS):
            if i >= len(breached):
                break
            b = breached[i]
            color = "RED" if b.severity == "CRITICAL_RED" else "AMBER"
            if b.parameter in ("oct_rnfl_um", "hrv_rmssd_ms", "cabin_ppCO2_mmHg"):
                if pins["SANS-01"] != "RED":
                    pins["SANS-01"] = color
            if b.parameter in ("hr_bpm", "sbp_mmHg", "dbp_mmHg", "ultrasound_ijv_thrombus"):
                if pins["CV-02"] != "RED":
                    pins["CV-02"] = color
            if b.parameter in ("spo2_pct", "rr_bpm", "cabin_ppCO2_mmHg"):
                if pins["ECLSS-03"] != "RED":
                    pins["ECLSS-03"] = color
            if b.parameter in ("cbt_C", "ambient_radiation_msv_h", "alc_cells_uL", "bladder_volume_mL"):
                if pins["RAD-04"] != "RED":
                    pins["RAD-04"] = color
        return pins

    def _format_triggering_vitals(
        self, breached: List[BreachedParameter], packet: TelemetryPacket
    ) -> List[str]:
        """Format human-readable vital breach strings for Roy's Medical Panel."""
        summary: List[str] = []
        for i in range(MAX_VITALS_PARAMS):
            if i >= len(breached):
                break
            b = breached[i]
            summary.append(
                f"{b.display_name}: {b.value} {b.unit} (Expected μg: {b.expected_ug_range} | {b.threshold_breached})"
            )
        if not summary:
            v = packet.vitals
            summary.append(
                f"HR: {v.heart_rate} bpm | BP: {v.blood_pressure_sys}/{v.blood_pressure_dia} mmHg | SpO2: {v.spo2}%"
            )
        return summary
