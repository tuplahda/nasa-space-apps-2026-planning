"""
NASA DONKI Space Weather Service.

Queries NASA's Space Weather Database Of Notifications, Knowledge, Information
(DONKI) for Solar Energetic Particle (SEP) and Solar Flare events.
Includes offline air-gapped fallback using local JSON cache per JPL Power-of-Ten rules.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger("ares_med.donki")

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "donki_cache.json"
DONKI_API_BASE = "https://api.nasa.gov/DONKI/SEP"
DEFAULT_TIMEOUT_SEC = 1.0
MAX_RETRIES = 1
LIVE_CACHE_TTL_SEC = 300.0  # 5 minutes
FAILURE_COOLDOWN_SEC = 60.0  # If network fails, don't retry for 60 seconds


@dataclass
class SpaceWeatherReport:
    """Standardized Space Weather telemetry packet segment."""
    spe_active: bool
    ambient_radiation_msv_h: float
    proton_flux_pfu: Optional[float]
    flare_class: Optional[str]
    severity: str
    recommended_action: str
    source: str
    timestamp: str
    dose_is_simulated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DonkiSpaceWeatherService:
    """
    Client for NASA DONKI API with automatic air-gap fallback cache.
    Adheres to JPL Power-of-Ten: bounded timeouts, explicit loops, zero recursion.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_path: Optional[Path] = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.api_key = api_key or os.getenv("NASA_API_KEY", "DEMO_KEY")
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self.timeout_sec = timeout_sec
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_live_check: float = 0.0
        self._last_failure_time: float = 0.0
        self._last_report: Optional[SpaceWeatherReport] = None
        self._load_local_cache()

    def _load_local_cache(self) -> None:
        """Load local JSON cache into memory for immediate air-gap access."""
        if not self.cache_path.exists():
            logger.warning("DONKI cache file not found at %s", self.cache_path)
            self._cached_data = None
            return

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self._cached_data = json.load(f)
            logger.info("Loaded offline DONKI cache from %s", self.cache_path)
        except Exception as exc:
            logger.error("Failed to parse DONKI cache file: %s", exc)
            self._cached_data = None

    def _get_cache_fallback(self, force_active_flare: bool = False) -> SpaceWeatherReport:
        """Retrieve fallback report from local cache data."""
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self._cached_data:
            rad = 4.85 if force_active_flare else 0.065
            return SpaceWeatherReport(
                spe_active=force_active_flare,
                ambient_radiation_msv_h=rad,
                proton_flux_pfu=420.5 if force_active_flare else 0.8,
                flare_class="X8.7" if force_active_flare else None,
                severity="WARNING_HIGH_FLUX" if force_active_flare else "NOMINAL_BACKGROUND",
                recommended_action=(
                    "Retreat to radiation storm shelter immediately"
                    if force_active_flare
                    else "Unrestricted operational clearance"
                ),
                source="HARDCODED_OFFLINE_GUARDRAIL",
                timestamp=now_iso,
            )

        if force_active_flare:
            events = self._cached_data.get("cached_events", [])
            if events:
                top_event = events[0]
                flare_cls = None
                linked = top_event.get("linkedEvents", [])
                for item in linked:
                    if "classType" in item:
                        flare_cls = item["classType"]
                        break

                return SpaceWeatherReport(
                    spe_active=True,
                    ambient_radiation_msv_h=float(top_event.get("calculated_radiation_dose_msv_h", 4.85)),
                    proton_flux_pfu=float(top_event.get("proton_flux_gt_10mev_pfu", 420.5)),
                    flare_class=flare_cls or "X8.7",
                    severity=str(top_event.get("severity", "WARNING_HIGH_FLUX")),
                    recommended_action=str(top_event.get("recommended_action", "Retreat to shelter")),
                    source="OFFLINE_AIRGAP_CACHE",
                    timestamp=now_iso,
                )

        nominal = self._cached_data.get("nominal_state", {})
        return SpaceWeatherReport(
            spe_active=bool(nominal.get("spe_active", False)),
            ambient_radiation_msv_h=float(nominal.get("ambient_radiation_msv_h", 0.065)),
            proton_flux_pfu=float(nominal.get("proton_flux_gt_10mev_pfu", 0.8)),
            flare_class=None,
            severity=str(nominal.get("severity", "NOMINAL_BACKGROUND")),
            recommended_action=str(nominal.get("recommended_action", "Unrestricted operational clearance")),
            source="OFFLINE_AIRGAP_CACHE",
            timestamp=now_iso,
        )

    def fetch_live_events(self) -> Optional[List[Dict[str, Any]]]:
        """
        Query NASA DONKI SEP endpoint with bounded retries and timeout.
        Returns None on any network/parsing failure.
        """
        now = datetime.now(timezone.utc)
        start_date = now.strftime("%Y-%m-%d")
        params = {
            "startDate": start_date,
            "api_key": self.api_key,
        }
        url = f"{DONKI_API_BASE}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "ARES-Med-SpaceApps2026/1.0"})

        for _ in range(MAX_RETRIES):
            try:
                with urlopen(req, timeout=self.timeout_sec) as response:
                    if response.status == 200:
                        raw = response.read().decode("utf-8")
                        data = json.loads(raw)
                        if isinstance(data, list):
                            return data
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                logger.debug("DONKI fetch failed: %s", exc)

        return None

    def get_space_weather(self, force_active_flare: bool = False) -> SpaceWeatherReport:
        """
        Get space weather report with non-blocking memory cache and offline fallback.
        """
        if force_active_flare:
            return self._get_cache_fallback(force_active_flare=True)

        now_mono = time.monotonic()
        # Return in-memory cached report if still fresh
        if self._last_report is not None and (now_mono - self._last_live_check) < LIVE_CACHE_TTL_SEC:
            return self._last_report

        # If recently failed (e.g. offline/air-gapped), don't block; return fallback immediately
        if (now_mono - self._last_failure_time) < FAILURE_COOLDOWN_SEC:
            return self._get_cache_fallback(force_active_flare=False)

        # Attempt live fetch
        live_data = self.fetch_live_events()
        if live_data is None:
            self._last_failure_time = now_mono
            rep = self._get_cache_fallback(force_active_flare=False)
            self._last_report = rep
            return rep

        self._last_live_check = now_mono
        now_iso = datetime.now(timezone.utc).isoformat()
        if len(live_data) == 0:
            rep = SpaceWeatherReport(
                spe_active=False,
                ambient_radiation_msv_h=0.065,
                proton_flux_pfu=0.8,
                flare_class=None,
                severity="NOMINAL_BACKGROUND",
                recommended_action="Unrestricted operational clearance",
                source="LIVE_DONKI_API",
                timestamp=now_iso,
            )
            self._last_report = rep
            return rep

        event = max(
            (item for item in live_data if isinstance(item, dict)),
            key=lambda item: str(item.get("eventTime") or ""),
            default={},
        )
        if not event:
            return self._get_cache_fallback()
        flare_cls = None
        for item in event.get("linkedEvents") or []:
            if isinstance(item, dict) and "classType" in item:
                flare_cls = item["classType"]
                break

        # SEP event metadata can be available without flux or an onboard dose measurement.
        def number(*keys: str) -> Optional[float]:
            for key in keys:
                value = event.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                    return float(value)
            return None

        flux = number("proton_flux_gt_10mev_pfu", "proton_flux_pfu")
        simulated_dose = self._get_cache_fallback(force_active_flare=True).ambient_radiation_msv_h
        rep = SpaceWeatherReport(
            spe_active=True,
            ambient_radiation_msv_h=simulated_dose,
            proton_flux_pfu=flux,
            flare_class=flare_cls,
            severity="SEP_EVENT_RECORDED",
            recommended_action="Check onboard dosimetry before evaluating crew exposure.",
            source="LIVE_DONKI_API",
            timestamp=str(event.get("eventTime") or now_iso),
        )
        self._last_report = rep
        return rep


donki_service = DonkiSpaceWeatherService()
