"""Decision logic for balancing charge between the primary battery and the Zendure batteries.

Pure functions only (no Home Assistant imports): fill levels, who charges or discharges first,
a hold time against flapping, the weekly full charge of the primary battery, the solar forecast
stage and the house load history.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .const import SmartMode


class Priority(StrEnum):
    """Which battery system goes first."""

    PRIMARY = "primary"
    ZENDURE = "zendure"


@dataclass(frozen=True)
class Pack:
    """One online Zendure device. `charge_power` is its maximum charge power in W (positive)."""

    soc: float
    min_soc: float
    max_soc: float
    kwh: float
    charge_power: float


def fill_level(soc: float | None, min_soc: float, max_soc: float) -> float | None:
    """Usable fill level in % between the minimum and maximum SoC, or None if unknown."""
    if soc is None or max_soc <= min_soc:
        return None
    return min(100.0, max(0.0, (soc - min_soc) / (max_soc - min_soc) * 100))


def zendure_fill(packs: list[Pack]) -> float | None:
    """Usable fill level of all Zendure devices in %, weighted by energy. None if no device counts."""
    usable = [pack for pack in packs if pack.kwh > 0 and pack.max_soc > pack.min_soc]
    total = sum(pack.kwh * (pack.max_soc - pack.min_soc) for pack in usable)
    if total <= 0:
        return None
    filled = sum(pack.kwh * min(max(pack.soc - pack.min_soc, 0), pack.max_soc - pack.min_soc) for pack in usable)
    return filled / total * 100


def charge_choice(fill_s: float, fill_z: float, lead: float, current: Priority) -> Priority:
    """Who charges first. The primary battery keeps the solar power until it leads by `lead` points."""
    if fill_s >= fill_z + lead:
        return Priority.ZENDURE
    if fill_s <= fill_z + lead - SmartMode.BALANCE_HYSTERESIS:
        return Priority.PRIMARY
    return current


def discharge_choice(fill_s: float, fill_z: float, current: Priority) -> Priority:
    """Who covers the load first: the fuller battery system."""
    if fill_z >= fill_s + SmartMode.BALANCE_HYSTERESIS:
        return Priority.ZENDURE
    if fill_s >= fill_z + SmartMode.BALANCE_HYSTERESIS:
        return Priority.PRIMARY
    return current


class PriorityHold:
    """Holds a priority for a minimum time so it does not flap between two systems."""

    def __init__(self, default: Priority, hold: timedelta) -> None:
        """Start on `default`; the first switch is allowed immediately."""
        self.default = default
        self.hold = hold
        self.value = default
        self._switched: datetime | None = None

    def update(self, desired: Priority | None, time: datetime) -> Priority:
        """Apply `desired` once `hold` has passed since the last switch. None falls back to `default` at once."""
        if desired is None:
            desired = self.default
        elif self._switched is not None and time - self._switched < self.hold:
            return self.value
        if desired != self.value:
            self.value = desired
            self._switched = time
        return self.value


def full_charge_due(last_full: datetime | None, now: datetime) -> bool:
    """True if the weekly full charge is open: `last_full` is before the last Saturday 0:00 (local time of `now`)."""
    days_back = (now.weekday() - SmartMode.PRIMARY_FULL_CHARGE_WEEKDAY) % 7
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return last_full is None or last_full < week_start


class Stage(StrEnum):
    """What the solar forecast means for the rest of today."""

    CLOUDY = "cloudy"  # The primary battery alone can take the forecast surplus
    MIXED = "mixed"  # Needs both battery systems, but not at the same time
    SUNNY = "sunny"  # More than one system can take, both have to charge together
    NONE = "none"  # No usable forecast


FORECAST_SLOT = timedelta(minutes=15)


def forecast_slots(watts: Any, now: datetime) -> list[float] | None:
    """Positive forecast values (W) of the rest of today, or None if there is no forecast for today.

    `watts` is the `watts` attribute of the forecast sensor: ISO time (UTC if it carries no time zone) to W,
    the key is the start of a 15 minute slot. Today is the date of `now` in its own time zone (`now` must be
    timezone-aware). Slots that are already over and entries that cannot be read are left out. An empty
    list means the forecast is there but the sun is down.
    """
    if not isinstance(watts, dict):
        return None
    today = now.date()
    found = False
    rest: list[tuple[datetime, float]] = []
    for key, value in watts.items():
        try:
            start = datetime.fromisoformat(key)
            power = float(value)
        except (TypeError, ValueError):
            continue
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start
        if start.astimezone(now.tzinfo).date() != today:
            continue
        found = True
        if power > 0 and start + FORECAST_SLOT > now:
            rest.append((start, power))
    if not found:
        return None
    return [power for _, power in sorted(rest)]


def classify(
    slots: list[float],
    expected_load: float,
    base_load: float,
    free_primary: float,
    free_zendure: float,
    primary_power: float,
    zendure_power: float,
) -> tuple[Stage, float, float]:
    """Classify the rest of today as `(stage, r_kwh, p_w)`.

    `r_kwh` is the forecast energy above the expected house load, `p_w` the peak above the base load.
    `free_*` are the energy (kWh) the primary battery and the Zendure devices can still take,
    `primary_power` and `zendure_power` the power (W) they can take at most.
    """
    r_kwh = round(sum(max(0.0, w - expected_load) for w in slots) * 0.25 / 1000, 3)
    p_w = max(0.0, max(slots, default=0) - base_load)
    if r_kwh <= free_primary and p_w <= primary_power:
        return Stage.CLOUDY, r_kwh, p_w
    if p_w > zendure_power or r_kwh >= free_primary + free_zendure:
        return Stage.SUNNY, r_kwh, p_w
    return Stage.MIXED, r_kwh, p_w


class StageFilter:
    """Damps the stage: a new one counts once it came up twice in a row."""

    def __init__(self) -> None:
        """Start without a stage."""
        self.value = Stage.NONE
        self._pending: Stage | None = None

    def update(self, stage: Stage) -> Stage:
        """Take over `stage` at once if there was none or none is the new one, otherwise on the second equal result."""
        if stage == Stage.NONE or self.value == Stage.NONE or stage == self._pending:
            self.value = stage
            self._pending = None
        elif stage == self.value:
            self._pending = None
        else:
            self._pending = stage
        return self.value


def lead_for(stage: Stage, full_charge_due: bool, primary_lead: float) -> float:
    """Fill level lead (points) the primary battery gets before the Zendure devices charge too."""
    if full_charge_due or stage == Stage.CLOUDY:
        return 100
    if stage == Stage.SUNNY:
        return 0
    return primary_lead


class LoadTracker:
    """House load readings (W) of the last `window`."""

    def __init__(self, window: timedelta) -> None:
        """Keep readings for `window`."""
        self.window = window
        self._values: deque[tuple[datetime, float]] = deque()

    def add(self, time: datetime, watts: float) -> None:
        """Add a reading and drop those older than `window`."""
        self._values.append((time, watts))
        while self._values[0][0] < time - self.window:
            self._values.popleft()

    def mean(self) -> float | None:
        """Mean load, or None without readings."""
        if not self._values:
            return None
        return sum(watts for _, watts in self._values) / len(self._values)

    def base(self) -> float | None:
        """Base load: the reading at the `LOAD_BASE_QUANTILE` position of the sorted values, None without readings."""
        if not self._values:
            return None
        ordered = sorted(watts for _, watts in self._values)
        return ordered[int(SmartMode.LOAD_BASE_QUANTILE * (len(ordered) - 1))]
