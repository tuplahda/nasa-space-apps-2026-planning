"""
Fixed-Size Sliding Ring Buffer & Single Event Upset (SEU) Debounce Filter.

Adheres strictly to NASA JPL Power-of-Ten Safety-Critical Coding Rules:
1. No direct or indirect recursion.
2. All loops have hard, statically verifiable upper bounds (MAX_BUFFER_SIZE = 60).
3. Fixed-size pre-allocated arrays (no unbounded dynamic growth at runtime).
4. Functions kept concise (< 60 lines) with single responsibility.
5. Explicit telemetry integrity checks: plausibility bounds, slew-rate limits,
   3-tick persistence debounce for cosmic-ray bit-flips (SEU_CANDIDATE),
   and Dead-Man Switch staleness detection (TELEMETRY_STALE > 2000ms).
"""

from dataclasses import dataclass
import math
import time
from typing import Dict, List, Optional, Tuple


# Hard static constants per JPL Power-of-Ten Rule 2 & 3
MAX_BUFFER_SIZE: int = 60
ROLLING_WINDOW_SEC: int = 10
DEBOUNCE_PERSISTENCE_TICKS: int = 3
DEBOUNCE_WINDOW_TICKS: int = 5
STALE_THRESHOLD_MS: float = 2000.0
MAX_CHANNELS: int = 16


@dataclass(frozen=True)
class ChannelSpec:
    """Static physiological plausibility and slew-rate bounds for a sensor channel."""

    name: str
    plausible_min: float
    plausible_max: float
    max_slew_per_sec: float
    unit: str


# Pre-defined sensor channel specifications (physiological + habitat sensors)
CHANNEL_SPECS: Dict[str, ChannelSpec] = {
    "hr_bpm": ChannelSpec("hr_bpm", 20.0, 240.0, 35.0, "bpm"),
    "sbp_mmHg": ChannelSpec("sbp_mmHg", 40.0, 260.0, 40.0, "mmHg"),
    "dbp_mmHg": ChannelSpec("dbp_mmHg", 25.0, 160.0, 30.0, "mmHg"),
    "spo2_pct": ChannelSpec("spo2_pct", 50.0, 100.0, 8.0, "%"),
    "hrv_rmssd_ms": ChannelSpec("hrv_rmssd_ms", 1.0, 200.0, 45.0, "ms"),
    "cbt_C": ChannelSpec("cbt_C", 32.0, 43.0, 0.8, "°C"),
    "rr_bpm": ChannelSpec("rr_bpm", 4.0, 60.0, 12.0, "breaths/min"),
    "cabin_ppCO2_mmHg": ChannelSpec("cabin_ppCO2_mmHg", 0.0, 50.0, 5.0, "mmHg"),
    "cabin_ppO2_mmHg": ChannelSpec("cabin_ppO2_mmHg", 50.0, 250.0, 15.0, "mmHg"),
    "ambient_radiation_msv_h": ChannelSpec("ambient_radiation_msv_h", 0.0, 500.0, 100.0, "mSv/h"),
    "suit_pressure_psi": ChannelSpec("suit_pressure_psi", 2.0, 16.0, 2.5, "psi"),
}


@dataclass
class ChannelTelemetryStats:
    """Computed rolling metrics and integrity flags for a single channel tick."""

    channel: str
    raw_value: float
    validated_value: float
    rolling_avg_10s: float
    rolling_avg_60s: float
    slew_rate_per_sec: float
    sample_count: int
    integrity_flag: str  # NOMINAL, SEU_CANDIDATE, SENSOR_FAULT, TELEMETRY_STALE
    consecutive_abnormal_ticks: int
    debounced_anomaly_active: bool


class FixedChannelRingBuffer:
    """
    Pre-allocated 60-slot circular buffer for a single biotelemetry channel.
    Zero dynamic array resizing during operation.
    """

    def __init__(self, spec: ChannelSpec) -> None:
        self.spec: ChannelSpec = spec
        self._values: List[float] = [0.0] * MAX_BUFFER_SIZE
        self._timestamps_ms: List[float] = [0.0] * MAX_BUFFER_SIZE
        self._abnormal_flags: List[int] = [0] * MAX_BUFFER_SIZE
        self._head: int = 0
        self._count: int = 0
        self._monotonic_seq: int = 0
        self._last_updated_ms: float = 0.0
        self._last_valid_value: Optional[float] = None
        self._consecutive_abnormal: int = 0
        self._seu_fault_count: int = 0
        # Tracks a large jump that may be a genuine step change (not a single-tick SEU)
        self._pending_jump_value: Optional[float] = None
        self._pending_jump_count: int = 0

    def reset(self) -> None:
        """Clear state in-place without reallocating the pre-allocated arrays."""
        for i in range(MAX_BUFFER_SIZE):
            self._values[i] = 0.0
            self._timestamps_ms[i] = 0.0
            self._abnormal_flags[i] = 0
        self._head = 0
        self._count = 0
        self._monotonic_seq = 0
        self._last_updated_ms = 0.0
        self._last_valid_value = None
        self._consecutive_abnormal = 0
        self._seu_fault_count = 0
        self._pending_jump_value = None
        self._pending_jump_count = 0

    def push_sample(
        self,
        value: float,
        is_threshold_breached: bool,
        timestamp_ms: Optional[float] = None,
    ) -> ChannelTelemetryStats:
        """Insert a single sample into the fixed ring buffer and compute statistics."""
        now_ms = timestamp_ms if timestamp_ms is not None else (time.monotonic() * 1000.0)
        integrity_flag, clean_val, slew = self._validate_sample(value, now_ms)

        # Write into pre-allocated slot at _head
        self._values[self._head] = clean_val
        self._timestamps_ms[self._head] = now_ms
        # Only count as a physiological breach if sensor reading itself is not a hardware fault
        sample_valid = integrity_flag in ("NOMINAL", "STEP_CONFIRMED")
        breach_bit = 1 if (is_threshold_breached and sample_valid) else 0
        self._abnormal_flags[self._head] = breach_bit

        self._head = (self._head + 1) % MAX_BUFFER_SIZE
        if self._count < MAX_BUFFER_SIZE:
            self._count += 1
        self._monotonic_seq += 1
        self._last_updated_ms = now_ms
        self._last_valid_value = clean_val

        if breach_bit == 1:
            if integrity_flag == "STEP_CONFIRMED":
                # The jump already persisted for 3 ticks while held as SEU_CANDIDATE
                self._consecutive_abnormal = max(
                    self._consecutive_abnormal, DEBOUNCE_PERSISTENCE_TICKS - 1
                )
            self._consecutive_abnormal = min(MAX_BUFFER_SIZE, self._consecutive_abnormal + 1)
        elif integrity_flag == "SEU_CANDIDATE":
            # Single-tick SEU spike does not increment confirmed clinical breach counter
            pass
        else:
            self._consecutive_abnormal = 0

        avg_10s = self.compute_rolling_average(ROLLING_WINDOW_SEC)
        avg_60s = self.compute_rolling_average(MAX_BUFFER_SIZE)
        debounced = self._is_debounced_anomaly(is_threshold_breached, integrity_flag)

        return ChannelTelemetryStats(
            channel=self.spec.name,
            raw_value=value,
            validated_value=round(clean_val, 3),
            rolling_avg_10s=round(avg_10s, 3),
            rolling_avg_60s=round(avg_60s, 3),
            slew_rate_per_sec=round(slew, 3),
            sample_count=self._count,
            integrity_flag=integrity_flag,
            consecutive_abnormal_ticks=self._consecutive_abnormal,
            debounced_anomaly_active=debounced,
        )

    def _validate_sample(
        self, value: float, now_ms: float
    ) -> Tuple[str, float, float]:
        """Check plausibility bounds and rate-of-change (slew rate) for SEU bit-flips."""
        if not math.isfinite(value):
            self._seu_fault_count += 1
            fallback = self._last_valid_value if self._last_valid_value is not None else self.spec.plausible_min
            return ("SENSOR_FAULT", fallback, 0.0)

        if value < self.spec.plausible_min or value > self.spec.plausible_max:
            self._seu_fault_count += 1
            clamped = max(self.spec.plausible_min, min(self.spec.plausible_max, value))
            fallback = self._last_valid_value if self._last_valid_value is not None else clamped
            return ("SENSOR_FAULT", fallback, 0.0)

        if self._last_valid_value is None or self._count == 0:
            return ("NOMINAL", value, 0.0)

        dt_sec = max(0.1, (now_ms - self._last_updated_ms) / 1000.0)
        # Normal 1Hz tick rate: compute per-tick delta and per-second slew rate
        delta = value - self._last_valid_value
        slew_per_sec = delta / min(dt_sec, 1.0)

        if abs(delta) > self.spec.max_slew_per_sec:
            # Large jump: hold as SEU_CANDIDATE unless it persists at the new level for 3 ticks
            if (
                self._pending_jump_value is not None
                and abs(value - self._pending_jump_value) <= self.spec.max_slew_per_sec
            ):
                self._pending_jump_count += 1
            else:
                self._pending_jump_value = value
                self._pending_jump_count = 1
            if self._pending_jump_count >= DEBOUNCE_PERSISTENCE_TICKS:
                # Genuine sustained step change (e.g. depressurization, arrhythmia onset)
                self._pending_jump_value = None
                self._pending_jump_count = 0
                return ("STEP_CONFIRMED", value, slew_per_sec)
            self._seu_fault_count += 1
            return ("SEU_CANDIDATE", self._last_valid_value, slew_per_sec)

        self._pending_jump_value = None
        self._pending_jump_count = 0
        return ("NOMINAL", value, slew_per_sec)

    def compute_rolling_average(self, window_slots: int) -> float:
        """Compute bounded rolling mean over the last `window_slots` samples (no recursion)."""
        if self._count == 0:
            return 0.0
        n = min(self._count, max(1, min(window_slots, MAX_BUFFER_SIZE)))
        total = 0.0
        # Hard static loop bound: at most MAX_BUFFER_SIZE (60) iterations
        for i in range(MAX_BUFFER_SIZE):
            if i >= n:
                break
            idx = (self._head - 1 - i) % MAX_BUFFER_SIZE
            total += self._values[idx]
        return total / float(n)

    def _is_debounced_anomaly(
        self, current_breach: bool, integrity_flag: str
    ) -> bool:
        """
        Enforce 3-tick persistence debounce (or 3-of-5 window) per NASA-STD-3001
        to suppress single-tick transient noise and cosmic-ray bit-flips.
        """
        if integrity_flag in ("SEU_CANDIDATE", "SENSOR_FAULT"):
            return False
        if self._consecutive_abnormal >= DEBOUNCE_PERSISTENCE_TICKS:
            return True
        if self._count < DEBOUNCE_PERSISTENCE_TICKS:
            return False

        # Also check N-of-M (3 of last 5 ticks) hysteresis window
        window = min(self._count, DEBOUNCE_WINDOW_TICKS)
        abnormal_sum = 0
        for i in range(DEBOUNCE_WINDOW_TICKS):
            if i >= window:
                break
            idx = (self._head - 1 - i) % MAX_BUFFER_SIZE
            abnormal_sum += self._abnormal_flags[idx]
        return current_breach and (abnormal_sum >= DEBOUNCE_PERSISTENCE_TICKS)

    def is_stale(self, now_ms: Optional[float] = None) -> bool:
        """Dead-man switch: returns True if telemetry heartbeat exceeds 2000ms."""
        if self._count == 0:
            return True
        current_ms = now_ms if now_ms is not None else (time.monotonic() * 1000.0)
        return (current_ms - self._last_updated_ms) > STALE_THRESHOLD_MS


class AstronautRingBufferManager:
    """
    Manages the fixed 60-second ring buffers across all monitored channels for an astronaut.
    """

    def __init__(self, astronaut_id: str = "ASTRO-01") -> None:
        self.astronaut_id: str = astronaut_id
        self.buffers: Dict[str, FixedChannelRingBuffer] = {}
        self.tick_counter: int = 0
        self.last_packet_ms: float = 0.0

        # Pre-allocate all standard telemetry channels at startup
        channel_keys = list(CHANNEL_SPECS.keys())
        for i in range(MAX_CHANNELS):
            if i >= len(channel_keys):
                break
            key = channel_keys[i]
            self.buffers[key] = FixedChannelRingBuffer(CHANNEL_SPECS[key])

    def reset(self) -> None:
        """Reset all channel buffers in-place (used for isolated stateless snapshots)."""
        self.tick_counter = 0
        self.last_packet_ms = 0.0
        keys = list(self.buffers.keys())
        for i in range(MAX_CHANNELS):
            if i >= len(keys):
                break
            self.buffers[keys[i]].reset()

    def ingest_tick(
        self,
        channel_values: Dict[str, float],
        breached_channels: Dict[str, bool],
        timestamp_ms: Optional[float] = None,
    ) -> Dict[str, ChannelTelemetryStats]:
        """Update all channel ring buffers for a single telemetry tick."""
        now_ms = timestamp_ms if timestamp_ms is not None else (time.monotonic() * 1000.0)
        self.tick_counter += 1
        self.last_packet_ms = now_ms

        results: Dict[str, ChannelTelemetryStats] = {}
        keys = list(CHANNEL_SPECS.keys())
        for i in range(MAX_CHANNELS):
            if i >= len(keys):
                break
            ch = keys[i]
            if ch in channel_values:
                val = float(channel_values[ch])
                breached = bool(breached_channels.get(ch, False))
                results[ch] = self.buffers[ch].push_sample(val, breached, now_ms)
        return results

    def preload_persistent_state(
        self,
        channel_values: Dict[str, float],
        breached_channels: Dict[str, bool],
        ticks: int = DEBOUNCE_PERSISTENCE_TICKS,
    ) -> Dict[str, ChannelTelemetryStats]:
        """
        Seed `ticks` consecutive samples (bounded <= 5) for stateless REST `/api/diagnose`
        calls where a full crisis snapshot is submitted directly for triage.
        """
        bounded_ticks = max(1, min(ticks, DEBOUNCE_WINDOW_TICKS))
        base_ms = time.monotonic() * 1000.0
        latest_stats: Dict[str, ChannelTelemetryStats] = {}
        for step in range(DEBOUNCE_WINDOW_TICKS):
            if step >= bounded_ticks:
                break
            sample_ms = base_ms + float(step * 1000)
            latest_stats = self.ingest_tick(channel_values, breached_channels, sample_ms)
        return latest_stats

    def get_snapshot_summary(self) -> Dict[str, object]:
        """Return diagnostic health of the ring buffer manager and SEU counters."""
        now_ms = time.monotonic() * 1000.0
        stale = (
            True
            if self.tick_counter == 0
            else (now_ms - self.last_packet_ms) > STALE_THRESHOLD_MS
        )
        channels_summary: Dict[str, object] = {}
        keys = list(self.buffers.keys())
        for i in range(MAX_CHANNELS):
            if i >= len(keys):
                break
            k = keys[i]
            buf = self.buffers[k]
            channels_summary[k] = {
                "samples_buffered": buf._count,
                "max_capacity": MAX_BUFFER_SIZE,
                "rolling_avg_10s": round(buf.compute_rolling_average(ROLLING_WINDOW_SEC), 3),
                "rolling_avg_60s": round(buf.compute_rolling_average(MAX_BUFFER_SIZE), 3),
                "consecutive_abnormal_ticks": buf._consecutive_abnormal,
                "seu_fault_count": buf._seu_fault_count,
            }
        return {
            "astronaut_id": self.astronaut_id,
            "monotonic_tick_counter": self.tick_counter,
            "telemetry_stale": stale,
            "max_buffer_size_seconds": MAX_BUFFER_SIZE,
            "debounce_persistence_ticks": DEBOUNCE_PERSISTENCE_TICKS,
            "channels": channels_summary,
        }
