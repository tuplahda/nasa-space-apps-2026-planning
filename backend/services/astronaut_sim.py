"""
Autonomous Astronaut Simulation Service bridge for A.R.E.S. Med backend.
Maintained by Dheer (Autonomous Astronaut Agent Engine).
"""

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import importlib.util

_agent_dir = WORKSPACE_ROOT / "Autonomous agent(dheer)"
_sim_file = _agent_dir / "astronaut_sim.py"

if _sim_file.exists():
    _spec = importlib.util.spec_from_file_location("astronaut_sim_module", _sim_file)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        AstronautSimulationEngine = _mod.AstronautSimulationEngine
        ActivityBaseline = _mod.ActivityBaseline
        ACTIVITY_PROFILES = _mod.ACTIVITY_PROFILES
        TRAJECTORY_SCENARIOS = _mod.TRAJECTORY_SCENARIOS
        NOMINAL_SYMPTOM_LOG = _mod.NOMINAL_SYMPTOM_LOG
        astronaut_sim = _mod.astronaut_sim
    else:
        raise ImportError("Failed to load spec from " + str(_sim_file))
else:
    raise FileNotFoundError("astronaut_sim.py not found in " + str(_agent_dir))

__all__ = [
    "AstronautSimulationEngine",
    "ActivityBaseline",
    "ACTIVITY_PROFILES",
    "TRAJECTORY_SCENARIOS",
    "NOMINAL_SYMPTOM_LOG",
    "astronaut_sim",
]
