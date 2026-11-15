"""Decision logic for balancing charge between the primary battery and the Zendure batteries.

Pure functions only (no Home Assistant imports): fill levels, who charges or discharges first,
a hold time against flapping, and the weekly full charge of the primary battery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

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
