"""
Autonomous Astronaut Agent (Digital Twin) Simulation Engine.

Simulates the demo astronaut on a continuous 1000ms tick:
- Sinus respiratory arrhythmia (+/- 3 bpm modulated by breathing rate).
- Microgravity baseline adaptations across SLEEP, IVA_REST, ARED_EXERCISE, EVA_SPACEWALK
  aligned with NASA-STD-3001 and ESA Space Fever findings (adapted post-FD75).
- Integrated with data/simulation_scenario_seeds.json:
    * 6 Quantitative Crisis Trajectories (Hypercapnia, ARS, Heat Strain, Orthostatic Intolerance, Hypoxia, SANS).
    * 24 Synthetic Scenario Seeds (Toxicology, Trauma, Infection, Renal, Immune, Environmental).
    * Dynamic multi-tier first-person symptom logs (Mild, Moderate, Critical).
- Daily Routine Prevention Schedule feed for Mission Control HUD.
- Closed-loop exponential washout recovery when countermeasures are administered.
- Seamless hybrid dataset ingestion from data/nasa_official_dataset/ when available.

Complies strictly with JPL Power-of-Ten safety rules and contains zero emojis.
"""

import csv
import json
import math
from pathlib import Path
import random
from copy import copy
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.models.telemetry import (
    CommsStatus,
    DEMO_ASTRONAUT_ID,
    DEMO_ASTRONAUT_NAME,
    Environment,
    SpecializedDiagnostics,
    TelemetryPacket,
    Vitals,
)
from backend.services.donki_service import donki_service

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NASA_DATASET_DIR = DATA_DIR / "nasa_official_dataset"
SEEDS_FILE = DATA_DIR / "simulation_scenario_seeds.json"
NOMINAL_SYMPTOM_LOG = "Nominal resting baseline; no acute somatic complaints reported."
GENERIC_TREATMENTS = {
    "standard protocol",
    "standard countermeasure protocol",
    "standard emergency countermeasure",
}
HYPERCAPNIA_TREATMENTS = {
    "li_oh_swap_and_o2",
    "lioh canister replacement & 100% o2 flush",
    "lioh canister replacement + 100% o2 flush",
}
TRAJECTORY_SCENARIOS = {
    "traj-hypercapnia": "hypercapnia",
    "traj-ars-spe": "solar_flare",
    "traj-eva-heat-strain": "heat_strain",
    "traj-orthostatic-intolerance": "orthostatic_intolerance",
    "traj-hypoxia": "decompression",
    "traj-sans": "sans",
}
SCENARIO_ALIASES = {
    **TRAJECTORY_SCENARIOS,
    "scenario_1_hypercapnia": "hypercapnia",
    "scenario_2_sans": "sans",
    "scenario_3_orthostatic_intolerance": "orthostatic_intolerance",
    "scenario_3_decompression_hypoxia": "decompression",
    "scenario_4_solar_radiation_ars": "solar_flare",
    "scenario_5_eva_thermal_dcs": "heat_strain",
    "hypoxia": "decompression",
    "mode_b": "zero_day",
    "mode_b_zero_day": "zero_day",
}
MODE_A_CRISIS_SCENARIOS: Tuple[str, ...] = (
    "hypercapnia",
    "solar_flare",
    "sans",
    "decompression",
    "heat_strain",
    "orthostatic_intolerance",
)
MODE_B_CRISIS_SCENARIOS: Tuple[str, ...] = (
    "zero_day",
    "novel_bronchospasm",
    "novel_pleuritic_shock",
    "novel_hypothermic_brady",
)


class ActivityBaseline:
    """Baseline physiological values for an activity state in microgravity."""

    def __init__(
        self,
        hr_base: float,
        sbp_base: float,
        dbp_base: float,
        spo2_base: float,
        hrv_base: float,
        temp_base: float,
        rr_base: float,
    ) -> None:
        self.hr_base = hr_base
        self.sbp_base = sbp_base
        self.dbp_base = dbp_base
        self.spo2_base = spo2_base
        self.hrv_base = hrv_base
        self.temp_base = temp_base
        self.rr_base = rr_base


# Microgravity baselines adjusted for Mission Day 84 (post-FD75 adaptation) per NASA-STD-3001 v2.0
ACTIVITY_PROFILES: Dict[str, ActivityBaseline] = {
    "SLEEP": ActivityBaseline(
        hr_base=48.0,
        sbp_base=102.0,
        dbp_base=62.0,
        spo2_base=98.5,
        hrv_base=72.0,
        temp_base=37.1,  # Post-FD75 sleep core temp (36.8-37.3)
        rr_base=12.0,
    ),
    "IVA_REST": ActivityBaseline(
        hr_base=60.0,
        sbp_base=110.0,
        dbp_base=70.0,
        spo2_base=98.0,
        hrv_base=54.0,
        temp_base=37.6,  # Post-FD75 space fever resting baseline (37.4-38.0)
        rr_base=14.0,
    ),
    "ARED_EXERCISE": ActivityBaseline(
        hr_base=150.0,
        sbp_base=165.0,
        dbp_base=78.0,
        spo2_base=96.8,
        hrv_base=20.0,
        temp_base=38.8,  # ARED heavy exercise thermal range (38.2-39.6)
        rr_base=28.0,
    ),
    "EVA_SPACEWALK": ActivityBaseline(
        hr_base=112.0,
        sbp_base=134.0,
        dbp_base=76.0,
        spo2_base=97.5,
        hrv_base=32.0,
        temp_base=38.0,  # EVA operational range (37.6-38.8)
        rr_base=20.0,
    ),
}

# Daily flight operational schedule for the demo astronaut
DAILY_SCHEDULE_TEMPLATE: List[Dict[str, str]] = [
    {"time": "06:00", "activity": "Sleep Phase Termination & Morning Biometrics", "category": "ROUTINE"},
    {"time": "07:00", "activity": "Breakfast & Metabolic Caloric Tracking", "category": "NUTRITION"},
    {"time": "08:00", "activity": "Orthostatic BP & Hydration Status Assessment", "category": "PREVENTION"},
    {"time": "10:00", "activity": "ECLSS Life-Support Inspection & Air Quality Check", "category": "SYSTEMS"},
    {"time": "13:30", "activity": "30-min ARED Resistive Exercise Countermeasure", "category": "COUNTERMEASURE"},
    {"time": "15:00", "activity": "Point-of-Care Ultrasound & Fluid Shift Tracking", "category": "CLINICAL"},
    {"time": "19:00", "activity": "Evening Mission Debrief & Tele-Medical Check-in", "category": "ROUTINE"},
    {"time": "22:00", "activity": "Sleep Phase & Nocturnal Biometrics Monitoring", "category": "SLEEP"},
]


class AstronautSimulationEngine:
    """
    Autonomous Astronaut Digital Twin state machine.
    Ticks every 1000ms, producing validated TelemetryPacket objects.
    """

    def __init__(
        self,
        astronaut_id: str = DEMO_ASTRONAUT_ID,
        name: str = DEMO_ASTRONAUT_NAME,
        mission_day: int = 84,
    ) -> None:
        self.astronaut_id = astronaut_id
        self.name = name
        self.mission_day = mission_day
        self.tick_count: int = 0
        self.activity_state: str = "IVA_REST"
        self.active_scenario: str = "nominal"

        # Scenario progression state (0.0 = nominal, 1.0 = full crisis)
        self.scenario_progression: float = 0.0
        self.target_progression: float = 0.0
        self.progression_rate: float = 0.12  # Reaches full crisis in ~8-10 ticks

        # Recovery state
        self.is_recovering: bool = False
        self.active_treatment: Optional[str] = None
        self.recovery_tick: int = 0
        self.recovery_start: float = 0.0
        self.incident_id: int = 0
        self._treatment_options: set[str] = set()
        self._treatment_policy_key = None
        self._latest_packet: Optional[TelemetryPacket] = None
        self._readiness_score: Optional[int] = None
        self._readiness_tick: int = -1
        self._readiness_detector = None

        # Dynamic demo "Simulate Crisis" state (temporary vitals anomaly + auto-recovery)
        self._crisis_rng = random.Random()
        self.temporary_crisis_ticks_remaining: int = 0
        self.temporary_crisis_auto_recover: bool = False
        self.last_simulated_crisis: Optional[str] = None
        self.dynamic_crisis_label: Optional[str] = None
        self.dynamic_perturbation: Dict[str, float] = {}
        self.dynamic_overrides: Dict[str, float] = {}
        self.dynamic_symptom_log: Optional[str] = None
        self.blind_crisis: Optional[str] = None
        self.blind_assessment_requested: bool = False
        self.blind_onset_ticks = 0
        self.blind_progression_rate = 0.12
        self.blind_noise: Optional[random.Random] = None
        self.blind_recovery_cause: Optional[str] = None
        self.blind_recovery_rate = 0.35
        self.administered_steps: set[str] = set()
        self.treated_regions: set[str] = set()

        # Mission Elapsed Time base (Day 84, 10:15:00)
        self.met_seconds: int = (84 * 86400) + (10 * 3600) + (15 * 60)

        # Loaded scenario seeds and trajectories
        self.seed_library: Dict[str, Any] = {}
        self._load_scenario_seeds()

        # Baseline overrides if external official NASA dataset is discovered
        self.external_dataset_loaded: bool = False
        self.external_rows: List[Dict[str, Any]] = []
        self.external_row_index: int = 0
        self._check_and_load_external_nasa_dataset()

    def _load_scenario_seeds(self) -> None:
        """Load the synthetic scenario seed vectors."""
        if not SEEDS_FILE.exists():
            return
        try:
            with open(SEEDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            seeds = data.get("synthetic_scenario_seeds_24", [])
            for s in seeds:
                sid = s.get("seed_id", "").lower()
                self.seed_library[sid] = s
                name = s.get("name", "").lower()
                if name:
                    self.seed_library[name] = s
        except Exception:
            pass

    def _check_and_load_external_nasa_dataset(self) -> None:
        """
        Universal flexible loader for data/nasa_official_dataset/.
        Supports heterogeneous column names (HR, heart_rate, Pulse, SpO2, etc.).
        """
        if not NASA_DATASET_DIR.exists():
            return

        for path in sorted(NASA_DATASET_DIR.glob("*.csv")) + sorted(NASA_DATASET_DIR.glob("*.json")):
            try:
                with path.open(encoding="utf-8-sig", newline="") as source:
                    rows = list(csv.DictReader(source)) if path.suffix == ".csv" else json.load(source)
                if not isinstance(rows, list):
                    continue
                normalized = [self._normalize_external_row(row) for row in rows if isinstance(row, dict)]
                self.external_rows = [row for row in normalized if row]
                if self.external_rows:
                    self.external_dataset_loaded = True
                    return
            except (OSError, ValueError, csv.Error):
                continue

    def _normalize_external_row(self, row: Dict[str, Any]) -> Dict[str, float]:
        """Map heterogeneous NASA CSV/JSON headers to standard biometric keys."""
        normalized: Dict[str, float] = {}
        cleaned_row = {str(k).strip().lower(): v for k, v in row.items()}
        aliases = {
            "hr": ["hr", "heart_rate", "pulse", "bpm", "heartrate", "hr_bpm"],
            "sbp": ["sbp", "blood_pressure_sys", "sys", "systolic", "sbp_mmhg", "sys_bp"],
            "dbp": ["dbp", "blood_pressure_dia", "dia", "diastolic", "dbp_mmhg", "dia_bp"],
            "spo2": ["spo2", "o2_sat", "oxygen_saturation", "spo2_pct", "pulse_ox"],
            "hrv": ["hrv", "hrv_ms", "rmssd", "hrv_rmssd_ms"],
            "temp": ["temp", "core_temp", "core_temp_c", "cbt", "cbt_c", "temperature", "tcore_c"],
            "rr": ["rr", "respiration_rate", "resp_rate", "rr_bpm", "breathing_rate", "rr_breaths_min"],
            "co2": ["co2", "cabin_co2", "cabin_co2_mmhg", "ppco2", "cabin_ppco2_mmhg", "ppco2_mmhg"],
        }
        for target, keys in aliases.items():
            for k in keys:
                if k in cleaned_row:
                    try:
                        value = float(cleaned_row[k])
                        if math.isfinite(value):
                            normalized[target] = value
                            break
                    except (ValueError, TypeError):
                        pass
        return normalized

    def list_available_scenarios(self) -> List[Dict[str, str]]:
        """Return full catalog of 6 trajectories and 24 seeds for frontend UI selection."""
        catalog: List[Dict[str, str]] = [
            {"id": "nominal", "name": "Nominal Resting Baseline", "category": "Baseline"},
            {"id": "hypercapnia", "name": "Acute & Chronic Hypercapnia (CO2 Intoxication)", "category": "Quantitative Trajectory"},
            {"id": "solar_flare", "name": "Solar Particle Event / Radiation Storm", "category": "Quantitative Trajectory"},
            {"id": "heat_strain", "name": "EVA Heat Strain & Cooling Loop Failure", "category": "Quantitative Trajectory"},
            {"id": "orthostatic_intolerance", "name": "Microgravity Orthostatic Intolerance", "category": "Quantitative Trajectory"},
            {"id": "decompression", "name": "Cabin / Suit Decompression & Acute Hypoxia", "category": "Quantitative Trajectory"},
            {"id": "sans", "name": "Spaceflight-Associated Neuro-Ocular Syndrome", "category": "Quantitative Trajectory"},
            {"id": "zero_day", "name": "Unclassified Multi-System Anomaly", "category": "Simulation Demo"},
            {"id": "dehydration", "name": "Dehydration / Volume Depletion", "category": "Simulation Demo"},
        ]
        # Append 24 seeds
        seen = set()
        for s in self.seed_library.values():
            sid = s.get("seed_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                catalog.append({
                    "id": sid,
                    "name": s.get("name", sid),
                    "category": s.get("category", "Synthetic Seed"),
                })
        return catalog

    def get_routine_schedule(self, readiness_score: Optional[int] = None) -> Dict[str, Any]:
        """Return the schedule with readiness from the current physiological assessment."""
        if readiness_score is not None:
            self._readiness_score = max(0, min(100, int(readiness_score)))
            self._readiness_tick = self.tick_count
        elif self._latest_packet is not None and self._readiness_tick != self.tick_count:
            from backend.services.anomaly_detector import EdgeAnomalyDetector

            if self._readiness_detector is None:
                self._readiness_detector = EdgeAnomalyDetector()
            observation = copy(self._latest_packet)
            observation.active_scenario_id = None
            observation.stateless_evaluation = True
            assessment = self._readiness_detector.evaluate_packet(observation)
            self._readiness_score = assessment.readiness_score_0_100
            self._readiness_tick = self.tick_count
        # Determine time of day from mission elapsed time
        rem = self.met_seconds % 86400
        hour = rem // 3600
        minute = (rem % 3600) // 60
        current_time_str = f"{hour:02d}:{minute:02d}"

        active_item = DAILY_SCHEDULE_TEMPLATE[0]
        schedule_status = []
        for item in DAILY_SCHEDULE_TEMPLATE:
            item_time = item["time"]
            status = "UPCOMING"
            if item_time <= current_time_str:
                status = "COMPLETED"
                active_item = item
            schedule_status.append({
                "time": item_time,
                "activity": item["activity"],
                "category": item["category"],
                "status": "ACTIVE" if item == active_item else status,
            })

        return {
            "mission_day": self.mission_day,
            "met_time": current_time_str,
            "active_block": active_item["activity"],
            "schedule": schedule_status,
            "crew_readiness_score": self._readiness_score,
        }

    def set_activity_state(self, new_state: str) -> Dict[str, Any]:
        """Change the activity if it is one of the simulator's supported states."""
        clean = new_state.upper().strip() if isinstance(new_state, str) else ""
        if clean not in ACTIVITY_PROFILES:
            return {"status": "error", "message": "Unknown simulation activity."}
        self.activity_state = clean
        return {"status": "ok", "activity_state": clean}

    def trigger_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """
        Inject a crisis scenario into the digital twin.
        Supports core trajectories ('hypercapnia', 'solar_flare', 'sans', 'decompression',
        'heat_strain', 'orthostatic_intolerance') as well as 24 seed IDs ('SEED-TOX-01', etc.).
        """
        name = scenario_name.lower().strip() if isinstance(scenario_name, str) else ""
        normalized = name.replace(" ", "_")
        normalized = SCENARIO_ALIASES.get(normalized, normalized)
        if normalized in ("nominal", "normal", "healthy", "baseline"):
            self._clear_dynamic_crisis_state()
            self.blind_crisis = self.blind_noise = self.blind_recovery_cause = None
            self.blind_assessment_requested = False
            self.incident_id += 1
            self._treatment_options.clear()
            self._treatment_policy_key = None
            self.active_scenario = "nominal"
            self.target_progression = 0.0
            self.scenario_progression = 0.0
            self.is_recovering = False
            self.active_treatment = None
            return {
                "status": "ok",
                "scenario": "nominal",
                "message": "Reset to nominal baseline.",
            }

        seed = self.seed_library.get(name)
        if seed:
            normalized = seed["seed_id"].lower()
        elif normalized not in TRAJECTORY_SCENARIOS.values() and normalized not in ("dehydration", "zero_day"):
            return {"status": "error", "message": "Unknown simulation scenario."}
        self._clear_dynamic_crisis_state()
        self.blind_crisis = self.blind_noise = self.blind_recovery_cause = None
        self.blind_assessment_requested = False
        self.incident_id += 1
        self._treatment_options.clear()
        self._treatment_policy_key = None
        if self.active_scenario != normalized:
            self.scenario_progression = 0.0
        self.active_scenario = normalized
        self.target_progression = 1.0
        self.is_recovering = False
        self.active_treatment = None
        return {
            "status": "ok",
            "scenario": normalized,
            "message": f"Injected scenario: {normalized}. Vitals trending into crisis.",
        }

    def _clear_dynamic_crisis_state(self) -> None:
        """Reset temporary demo crisis perturbations and countdown timers."""
        self.temporary_crisis_ticks_remaining = 0
        self.temporary_crisis_auto_recover = False
        self.dynamic_crisis_label = None
        self.dynamic_perturbation.clear()
        self.dynamic_overrides.clear()
        self.dynamic_symptom_log = None
        self.administered_steps.clear()
        self.treated_regions.clear()

    def _start_temporary_crisis_recovery(self) -> None:
        """Automatically start biological recovery washout after a temporary crisis expires."""
        self.is_recovering = True
        self.active_treatment = "Temporary Demo Crisis Timeout (Auto-Recovery)"
        self.recovery_tick = 0
        self.recovery_start = max(0.25, self.scenario_progression)
        if self.blind_crisis:
            self.blind_recovery_cause = "automatic"
            self.temporary_crisis_auto_recover = False
            return
        self.temporary_crisis_ticks_remaining = 0
        self.temporary_crisis_auto_recover = False
        self.dynamic_crisis_label = None
        self.dynamic_perturbation.clear()
        self.dynamic_overrides.clear()
        self.dynamic_symptom_log = None
        self.administered_steps.clear()
        self.treated_regions.clear()

    def simulate_crisis(
        self,
        *,
        only_if_nominal: bool = False,
        mode_preference: Optional[str] = None,
        duration_ticks: int = 15,
        seed: Optional[int] = None,
        streaming: bool = False,
    ) -> Dict[str, Any]:
        """
        Dynamically inject a random, non-hardcoded temporary vital problem for demo
        purposes (especially when astronaut vitals are nominal) with auto-recovery.
        """
        if only_if_nominal and self.active_scenario != "nominal":
            return {
                "status": "skipped",
                "already_in_crisis": True,
                "scenario": self.active_scenario,
                "message": f"Astronaut already experiencing active crisis: {self.active_scenario}.",
            }

        rng = random.Random(seed) if seed is not None else self._crisis_rng
        pref = mode_preference.strip().lower() if isinstance(mode_preference, str) else ""
        if pref in ("mode_a", "known", "high_confidence"):
            candidates = list(MODE_A_CRISIS_SCENARIOS)
        elif pref in ("mode_b", "unknown", "novel", "low_confidence", "zero_day"):
            candidates = list(MODE_B_CRISIS_SCENARIOS)
        else:
            candidates = list(MODE_A_CRISIS_SCENARIOS) + list(MODE_B_CRISIS_SCENARIOS)

        if seed is None and len(candidates) > 1 and self.last_simulated_crisis in candidates:
            candidates = [candidate for candidate in candidates if candidate != self.last_simulated_crisis]

        chosen = rng.choice(candidates)
        is_mode_b_profile = chosen in MODE_B_CRISIS_SCENARIOS
        base_scenario = "zero_day" if is_mode_b_profile else chosen

        result = self.trigger_scenario(base_scenario)
        if result.get("status") == "error":
            return result

        ticks = max(3, min(120, int(duration_ticks)))
        self.scenario_progression = round(rng.uniform(0.84, 1.0), 3)
        self.target_progression = 1.0
        self.temporary_crisis_ticks_remaining = ticks
        self.temporary_crisis_auto_recover = not streaming
        self.last_simulated_crisis = chosen
        self.dynamic_crisis_label = chosen

        if chosen == "novel_bronchospasm":
            self.dynamic_overrides = {
                "heart_rate": round(rng.uniform(116.0, 134.0), 1),
                "blood_pressure_sys": round(rng.uniform(132.0, 146.0), 1),
                "blood_pressure_dia": round(rng.uniform(82.0, 94.0), 1),
                "spo2": round(rng.uniform(88.5, 91.8), 1),
                "hrv_ms": round(rng.uniform(12.0, 21.0), 1),
                "core_temp_c": round(rng.uniform(37.4, 38.2), 2),
                "respiration_rate": round(rng.uniform(24.0, 30.0), 1),
            }
            self.dynamic_symptom_log = rng.choice([
                "Sudden audible expiratory wheezing, prolonged expiration, and acute bronchospasm with air hunger.",
                "Progressive tight chest with diffuse expiratory wheeze and prolonged expiration of unknown origin.",
            ])
        elif chosen == "novel_pleuritic_shock":
            self.dynamic_overrides = {
                "heart_rate": round(rng.uniform(120.0, 138.0), 1),
                "blood_pressure_sys": round(rng.uniform(78.0, 88.0), 1),
                "blood_pressure_dia": round(rng.uniform(48.0, 58.0), 1),
                "spo2": round(rng.uniform(87.0, 90.8), 1),
                "hrv_ms": round(rng.uniform(10.0, 18.0), 1),
                "core_temp_c": round(rng.uniform(36.4, 37.9), 2),
                "respiration_rate": round(rng.uniform(24.0, 31.0), 1),
            }
            self.dynamic_symptom_log = rng.choice([
                "Acute unilateral chest pain, severe dyspnea, rapidly worsening shock and impending collapse.",
                "Sharp pleuritic chest pain on inspiration with progressive dyspnea and hypotensive presyncope.",
            ])
        elif chosen == "novel_hypothermic_brady":
            self.dynamic_overrides = {
                "heart_rate": round(rng.uniform(44.0, 56.0), 1),
                "blood_pressure_sys": round(rng.uniform(88.0, 100.0), 1),
                "blood_pressure_dia": round(rng.uniform(56.0, 66.0), 1),
                "spo2": round(rng.uniform(92.0, 95.2), 1),
                "hrv_ms": round(rng.uniform(20.0, 32.0), 1),
                "core_temp_c": round(rng.uniform(34.6, 35.6), 2),
                "respiration_rate": round(rng.uniform(10.0, 13.0), 1),
            }
            self.dynamic_symptom_log = rng.choice([
                "Uncontrollable shivering after cooling-loop leak; progressive hypothermia and cold exposure.",
                "Severe shivering, numbness, hypothermia from thermal suit loop failure and cold exposure.",
            ])
        elif chosen == "zero_day":
            self.dynamic_perturbation = {
                "heart_rate": round(rng.uniform(5.0, 16.0), 1),
                "blood_pressure_sys": round(rng.uniform(-6.0, 4.0), 1),
                "spo2": round(rng.uniform(-2.0, 0.4), 1),
                "core_temp_c": round(rng.uniform(0.1, 0.7), 2),
                "respiration_rate": round(rng.uniform(2.0, 6.0), 1),
            }
            self.dynamic_symptom_log = rng.choice([
                "Unexplained metallic taste, peripheral tingling, and sudden systemic weakness.",
                "Acute bilateral paresthesia, unexplained malaise, and transient orthostatic dimming.",
            ])
        else:
            self.dynamic_perturbation = {
                "heart_rate": round(rng.uniform(2.0, 7.0), 1),
                "blood_pressure_sys": round(rng.uniform(1.0, 6.0), 1),
                "hrv_ms": round(rng.uniform(-4.0, -0.5), 1),
                "core_temp_c": round(rng.uniform(0.05, 0.25), 2),
                "respiration_rate": round(rng.uniform(0.5, 2.5), 1),
            }
            self.dynamic_symptom_log = None

        if streaming:
            self.blind_crisis = chosen
            self.blind_assessment_requested = False
            self.blind_onset_ticks = 2
            self.blind_progression_rate = rng.uniform(0.08, 0.13)
            self.blind_noise = random.Random(rng.getrandbits(64))
            self.scenario_progression = 0.0
            self.target_progression = rng.uniform(0.87, 1.0)

        return {
            "status": "ok",
            "scenario": chosen,
            "base_scenario": base_scenario,
            "mode_hint": "MODE_B_NOVEL" if is_mode_b_profile else "MODE_A_KNOWN",
            "temporary_crisis": True,
            "auto_recovery_ticks": ticks,
            "dynamic_perturbation": dict(self.dynamic_overrides or self.dynamic_perturbation),
            "message": f"Dynamic temporary crisis '{chosen}' injected for {ticks} ticks.",
        }

    def _apply_dynamic_crisis_modifiers(self, packet: TelemetryPacket, strength: float = 1.0) -> None:
        """Apply active dynamic crisis overrides or jitter while clamping physiological bounds."""
        bounds = {
            "heart_rate": (30.0, 220.0, 1),
            "blood_pressure_sys": (60.0, 220.0, 1),
            "blood_pressure_dia": (35.0, 140.0, 1),
            "spo2": (70.0, 100.0, 1),
            "hrv_ms": (3.0, 160.0, 1),
            "core_temp_c": (33.5, 42.5, 2),
            "respiration_rate": (6.0, 50.0, 1),
        }
        if self.dynamic_overrides:
            for field_name, target_value in self.dynamic_overrides.items():
                if hasattr(packet.vitals, field_name) and field_name in bounds:
                    low, high, digits = bounds[field_name]
                    baseline = float(getattr(packet.vitals, field_name))
                    clamped = max(low, min(high, baseline + strength * (float(target_value) - baseline)))
                    setattr(packet.vitals, field_name, round(clamped, digits))
        if self.dynamic_perturbation:
            for field_name, delta in self.dynamic_perturbation.items():
                if hasattr(packet.vitals, field_name) and field_name in bounds:
                    low, high, digits = bounds[field_name]
                    current = float(getattr(packet.vitals, field_name))
                    clamped = max(low, min(high, current + strength * float(delta)))
                    setattr(packet.vitals, field_name, round(clamped, digits))
        if self.dynamic_symptom_log and strength >= 0.35 and not self.is_recovering:
            packet.symptom_log = self.dynamic_symptom_log

    def set_treatment_options(self, treatments: List[str], policy_key=None) -> None:
        """Register exact countermeasure names from the current filtered RAG decision."""
        self._treatment_options = {" ".join(value.lower().split()) for value in treatments if value.strip()}
        self._treatment_policy_key = policy_key

    def apply_treatment(self, treatment_name: str) -> Dict[str, Any]:
        """
        Administer countermeasure to initiate closed-loop biological recovery.
        Vitals will decay back to baseline over 5-10 seconds.
        """
        treatment_id = " ".join(treatment_name.lower().split()) if isinstance(treatment_name, str) else ""
        if treatment_id not in GENERIC_TREATMENTS | HYPERCAPNIA_TREATMENTS | self._treatment_options:
            return {"status": "error", "message": "Unknown simulation treatment."}
        if treatment_id in HYPERCAPNIA_TREATMENTS and self.active_scenario not in ("nominal", "hypercapnia"):
            return {"status": "error", "message": "This treatment is for the hypercapnia scenario."}
        if self.active_scenario == "nominal" or self.is_recovering:
            return {"status": "ok", "message": "No new recovery was started."}
        self.is_recovering = True
        self.active_treatment = treatment_name
        self.recovery_tick = 0
        self.recovery_start = self.scenario_progression
        self.target_progression = 0.0
        return {
            "status": "ok",
            "action": "TREATMENT_APPLIED",
            "treatment": treatment_name,
            "message": f"Administered {treatment_name}. Commencing smooth biological recovery.",
        }

    def cure_scenario(self) -> Dict[str, Any]:
        """Convenience alias for recovery initiation."""
        return self.apply_treatment("Standard Countermeasure Protocol")

    def _format_met(self) -> str:
        """Format Mission Elapsed Time string: DDD:HH:MM:SS."""
        total = self.met_seconds
        days = total // 86400
        rem = total % 86400
        hours = rem // 3600
        rem = rem % 3600
        minutes = rem // 60
        seconds = rem % 60
        return f"{days:03d}:{hours:02d}:{minutes:02d}:{seconds:02d}"

    def step(self) -> TelemetryPacket:
        """
        Advance simulation by 1000ms and return a validated TelemetryPacket.
        Adheres to JPL Power-of-Ten: bounded mathematical operations, no recursion.
        """
        self.tick_count += 1
        self.met_seconds += 1
        before_onset = bool(self.blind_crisis and self.blind_onset_ticks > 0)
        if before_onset:
            self.blind_onset_ticks -= 1
        progression_rate = self.blind_progression_rate if self.blind_crisis else self.progression_rate

        # Smooth scenario progression towards target
        if self.is_recovering:
            self.recovery_tick += 1
            # Exponential washout biological decay curve: e^(-0.35 * t)
            decay_rate = (self.blind_recovery_rate
                          if self.blind_recovery_cause == "operator" else 0.35)
            decay_factor = math.exp(-decay_rate * self.recovery_tick)
            self.scenario_progression = max(0.0, self.recovery_start * decay_factor)
            if self.recovery_tick >= 10:
                self.scenario_progression = 0.0
                self.is_recovering = False
                self.active_scenario = "nominal"
                self.active_treatment = None
                self._treatment_options.clear()
                self._treatment_policy_key = None
                self._clear_dynamic_crisis_state()
        elif not before_onset:
            if self.scenario_progression < self.target_progression:
                self.scenario_progression = min(
                    self.target_progression,
                    self.scenario_progression + progression_rate,
                )
            elif self.scenario_progression > self.target_progression:
                self.scenario_progression = max(
                    self.target_progression,
                    self.scenario_progression - progression_rate,
                )

        # Baseline resolution
        baseline = ACTIVITY_PROFILES.get(self.activity_state, ACTIVITY_PROFILES["IVA_REST"])
        hr_base = baseline.hr_base
        sbp_base = baseline.sbp_base
        dbp_base = baseline.dbp_base
        spo2_base = baseline.spo2_base
        hrv_base = baseline.hrv_base
        temp_base = baseline.temp_base
        rr_base = baseline.rr_base
        cabin_co2 = 2.4  # nominal mmHg

        # If official external NASA dataset was provided, override baseline values with real rows
        if self.external_dataset_loaded and self.external_rows:
            norm_vals = self.external_rows[self.external_row_index % len(self.external_rows)]
            self.external_row_index += 1
            if "hr" in norm_vals:
                hr_base = norm_vals["hr"]
            if "sbp" in norm_vals:
                sbp_base = norm_vals["sbp"]
            if "dbp" in norm_vals:
                dbp_base = norm_vals["dbp"]
            if "spo2" in norm_vals:
                spo2_base = norm_vals["spo2"]
            if "hrv" in norm_vals:
                hrv_base = norm_vals["hrv"]
            if "temp" in norm_vals:
                temp_base = norm_vals["temp"]
            if "rr" in norm_vals:
                rr_base = norm_vals["rr"]
            if "co2" in norm_vals:
                cabin_co2 = norm_vals["co2"]

        # Sinus respiratory arrhythmia oscillation (+/- 3 bpm modulated by respiration rate)
        resp_freq_hz = rr_base / 60.0
        sinus_arrhythmia = 3.0 * math.sin(2.0 * math.pi * resp_freq_hz * self.tick_count)

        # Subtle organic noise (+/- 0.4 bpm, +/- 0.3 mmHg, +/- 0.02 deg C)
        noise = self.blind_noise or random
        noise_hr = noise.uniform(-0.4, 0.4)
        noise_bp = noise.uniform(-0.3, 0.3)
        noise_temp = noise.uniform(-0.02, 0.02)

        # Environmental defaults
        cabin_ppo2 = 160.0
        suit_pressure = 4.3 if self.activity_state == "EVA_SPACEWALK" else 14.7
        space_weather = donki_service.get_space_weather(
            force_active_flare=(not self.blind_crisis and self.active_scenario in ("solar_flare", "traj-ars-spe"))
        )
        ambient_radiation = space_weather.ambient_radiation_msv_h
        donki_spe_active = space_weather.spe_active

        symptom_log = NOMINAL_SYMPTOM_LOG

        quality_flags = {}
        # Scenario-specific physiological shifts
        p = self.scenario_progression
        scen = "nominal" if before_onset else self.active_scenario
        if self.blind_crisis and self.dynamic_overrides:
            scen = "nominal"  # The sampled profile supplies the vital changes.

        if scen in ("hypercapnia", "traj-hypercapnia", "scenario_1_hypercapnia"):
            cabin_co2 = 2.4 + (10.4 * p)
            delta_co2 = max(0.0, cabin_co2 - (2.4 if self.blind_crisis else 2.0))
            rr_base += 0.45 * delta_co2
            hr_base += 1.8 * delta_co2
            sbp_base += 1.4 * delta_co2
            dbp_base += 0.6 * delta_co2
            hrv_base = max(10.0, hrv_base - (2.2 * delta_co2))
            if p < 0.4:
                symptom_log = (
                    "Woke up with a dull frontal pressure headache and mild facial warmth; sleep felt fragmented."
                )
            elif p < 0.8:
                symptom_log = (
                    "Frontal headache is throbbing now with mild nausea, malaise, and strange tingling along cheek and jaw; breathing feels deeper at rest."
                )
            else:
                symptom_log = (
                    "Severe air hunger and chest heaving, pounding headache, dizzy and losing track of checklist steps."
                )

        elif scen in ("solar_flare", "traj-ars-spe", "scenario_4_solar_radiation_ars"):
            ambient_radiation = 0.065 + (4.785 * p)
            donki_spe_active = not self.blind_crisis or p >= 0.35
            hr_base += 14.0 * p
            rr_base += 4.0 * p
            hrv_base = max(12.0, hrv_base - (15.0 * p))
            symptom_log = (
                "Personal dosimeter warning alarm active; subtle metallic taste on tongue; visual phosphenes."
            )

        elif scen in ("sans", "traj-sans", "scenario_2_sans"):
            sbp_base += 12.0 * p
            dbp_base += 6.0 * p
            hr_base += 4.0 * p
            symptom_log = (
                "Progressive hyperopic blur when reading checklists; globe tightness and mild retrobulbar fullness."
            )

        elif scen in ("decompression", "hypoxia", "traj-hypoxia", "scenario_3_decompression_hypoxia"):
            suit_pressure = (suit_pressure if self.blind_crisis else 4.3) - (1.1 * p)
            spo2_base = max(76.0, spo2_base - (17.5 * p))
            hr_base += 38.0 * p
            rr_base += 14.0 * p
            symptom_log = (
                "Suit pressure drop alert; ear tympanic pain, acute dyspnea, and hypoxic lightheadedness."
            )

        elif scen in ("heat_strain", "traj-eva-heat-strain"):
            temp_base = min(39.2, temp_base + (1.2 * p))
            hr_base += 26.0 * p
            rr_base += 6.0 * p
            hrv_base = max(14.0, hrv_base - (18.0 * p))
            symptom_log = (
                "Spacesuit internal temperature rising rapidly; heavy profuse sweating in LCVG, heart pounding against ribs."
            )

        elif scen in ("orthostatic_intolerance", "traj-orthostatic-intolerance"):
            sbp_base = max(86.0, sbp_base - (24.0 * p))
            dbp_base = max(52.0, dbp_base - (16.0 * p))
            hr_base += 34.0 * p
            hrv_base = max(12.0, hrv_base - (24.0 * p))
            symptom_log = (
                "Profound dizziness and graying vision upon standing; extreme lightheadedness, nausea."
            )

        elif scen == "zero_day":
            sbp_base -= 42.0 * p
            dbp_base -= 20.0 * p
            spo2_base -= 14.0 * p
            hr_base += 40.0 * p
            rr_base += 15.0 * p
            symptom_log = "I feel faint and short of breath. My hands are cold and I am having trouble focusing."

        elif scen in ("dehydration",):
            sbp_base = max(88.0, sbp_base - (20.0 * p))
            hr_base += 28.0 * p
            hrv_base = max(14.0, hrv_base - (22.0 * p))
            symptom_log = (
                "Orthostatic tachycardia on movement; profound dry oral mucosa and general lethargy."
            )

        # Dynamic seed lookup if a specific SEED-* or name was requested
        elif scen in self.seed_library:
            seed_info = self.seed_library[scen]
            vec = seed_info.get("vector", {})
            hr_base += (vec.get("dHR_bpm", 15.0) or 0.0) * p
            sbp_base += (vec.get("dSBP_mmHg", 0.0) or 0.0) * p
            dbp_base += (vec.get("dDBP_mmHg", 0.0) or 0.0) * p
            spo2_base += (vec.get("dSpO2_pct", 0.0) or 0.0) * p
            rr_base += (vec.get("dRR_bpm", 4.0) or 0.0) * p
            temp_base += (vec.get("dTcore_C", 0.0) or 0.0) * p
            hrv_base *= 1.0 + (vec.get("dRMSSD_pct") or 0.0) * p / 100.0
            symptom_log = seed_info.get("symptoms", "Somatic discomfort noted.")
            if vec.get("dRR_bpm") is None:
                quality_flags["respiration_rate"] = "motion_artifact_unreliable"
            if vec.get("dRMSSD_pct") is None:
                quality_flags["hrv_ms"] = "non_autonomic_unreliable"

        # Override symptom log during recovery
        if self.is_recovering:
            treatment_desc = self.active_treatment or "Emergency Countermeasure Protocol"
            symptom_log = (
                f"Treatment active ({treatment_desc}). Vitals stabilizing smoothly back to nominal microgravity baseline."
            )
            if self.blind_crisis:
                symptom_log = "Simulated readings are trending back toward baseline."
        elif self.blind_crisis and p < 0.35:
            symptom_log = NOMINAL_SYMPTOM_LOG

        # Assemble finalized physiological values with noise and bounds
        calc_hr = max(35.0, min(220.0, hr_base + sinus_arrhythmia + noise_hr))
        calc_sbp = max(60.0, min(230.0, sbp_base + noise_bp))
        calc_dbp = max(40.0, min(140.0, dbp_base + (noise_bp * 0.5)))
        calc_spo2 = max(70.0, min(100.0, spo2_base + noise.uniform(-0.1, 0.1)))
        calc_hrv = max(5.0, min(150.0, hrv_base + noise.uniform(-0.8, 0.8)))
        calc_temp = max(34.0, min(42.0, temp_base + noise_temp))
        calc_rr = max(6.0, min(45.0, rr_base + noise.uniform(-0.2, 0.2)))
        calc_ve = max(4.0, min(60.0, (calc_rr * 0.55)))

        vitals = Vitals(
            heart_rate=round(calc_hr, 1),
            blood_pressure_sys=round(calc_sbp, 1),
            blood_pressure_dia=round(calc_dbp, 1),
            spo2=round(calc_spo2, 1),
            hrv_ms=round(calc_hrv, 1),
            core_temp_c=round(calc_temp, 2),
            respiration_rate=round(calc_rr, 1),
            ve_l_min=round(calc_ve, 2),
        )

        environment = Environment(
            cabin_co2_mmhg=round(cabin_co2, 2),
            ambient_radiation_msv_h=round(ambient_radiation, 3),
            suit_pressure_psi=round(suit_pressure, 2),
            cabin_ppo2_mmhg=round(cabin_ppo2, 1),
            suit_pico2_mmhg=round(cabin_co2 * 0.9, 2),
            donki_spe_active=donki_spe_active,
        )

        specialized = None
        if scen in ("sans", "traj-sans", "scenario_2_sans"):
            rnfl = 95.0 + (18.0 * math.log(1.0 + (max(0, self.mission_day - 15) / 30.0)))
            specialized = SpecializedDiagnostics(
                oct_rnfl_um=round(95.0 + (rnfl - 95.0) * p, 1),
                refraction_shift_D=round(0.25 * math.floor(max(0, self.mission_day - 21) / 25.0) * p, 2),
            )

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        packet = TelemetryPacket(
            timestamp=now_iso,
            met=self._format_met(),
            mission_day=self.mission_day,
            astronaut_id=self.astronaut_id,
            name=self.name,
            activity_state=self.activity_state,
            active_scenario_id=self.active_scenario,
            comms_status=CommsStatus(
                one_way_delay_sec=1200,
                mode="DELAYED",
                solar_conjunction_blackout=False,
            ),
            vitals=vitals,
            environment=environment,
            specialized_diagnostics=specialized,
            symptom_log=symptom_log,
            quality_flags=quality_flags or None,
        )
        if not before_onset and self.active_scenario != "nominal":
            if self.blind_crisis:
                self._apply_dynamic_crisis_modifiers(packet, p)
            elif not self.is_recovering:
                self._apply_dynamic_crisis_modifiers(packet)
            if not self.is_recovering and self.temporary_crisis_ticks_remaining > 0:
                self.temporary_crisis_ticks_remaining -= 1
                if self.temporary_crisis_ticks_remaining == 0 and self.temporary_crisis_auto_recover:
                    self._start_temporary_crisis_recovery()

        self._latest_packet = packet
        return packet


# Global singleton instance
astronaut_sim = AstronautSimulationEngine()
