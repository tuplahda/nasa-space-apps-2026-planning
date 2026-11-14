"""
NASA DONKI Space Weather Service bridge for A.R.E.S. Med backend.
Maintained by Dheer (Autonomous Astronaut Agent Engine).
"""

import sys
from pathlib import Path

# Ensure root workspace directory is in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

# Dynamically load from 'Autonomous agent(dheer)' folder to ensure single source of truth
import importlib.util

_agent_dir = WORKSPACE_ROOT / "Autonomous agent(dheer)"
_donki_file = _agent_dir / "donki_service.py"

if _donki_file.exists():
    _spec = importlib.util.spec_from_file_location("donki_service_module", _donki_file)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        DonkiSpaceWeatherService = _mod.DonkiSpaceWeatherService
        SpaceWeatherReport = _mod.SpaceWeatherReport
        donki_service = _mod.donki_service
    else:
        raise ImportError("Failed to load spec from " + str(_donki_file))
else:
    raise FileNotFoundError("donki_service.py not found in " + str(_agent_dir))

__all__ = ["DonkiSpaceWeatherService", "SpaceWeatherReport", "donki_service"]
