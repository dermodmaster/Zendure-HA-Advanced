"""Tests for the pure decision functions of the battery balance (fill levels, priority, full charge)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.zendure_ha.balance import (
    Pack,
    Priority,
    PriorityHold,
    charge_choice,
    discharge_choice,
    fill_level,
    full_charge_due,
    zendure_fill,
)

BER = ZoneInfo("Europe/Berlin")
KELLER = Pack(soc=50, min_soc=10, max_soc=90, kwh=8.16, charge_power=2400)
WOHNZIMMER = Pack(soc=100, min_soc=10, max_soc=100, kwh=5.28, charge_power=2400)


def test_fill_level_scales_between_min_and_max() -> None:
    assert round(fill_level(30, 5, 100), 1) == 26.3
    assert fill_level(3, 5, 100) == 0
    assert fill_level(95, 5, 90) == 100


def test_fill_level_unknown() -> None:
    assert fill_level(None, 5, 100) is None
    assert fill_level(50, 90, 90) is None


def test_zendure_fill_is_energy_weighted() -> None:
    assert round(zendure_fill([KELLER, WOHNZIMMER]), 1) == 71.1


def test_zendure_fill_without_usable_devices() -> None:
    assert zendure_fill([]) is None
    assert zendure_fill([Pack(soc=50, min_soc=10, max_soc=100, kwh=0, charge_power=2400)]) is None


def test_charge_choice_hysteresis() -> None:
    assert charge_choice(60, 45, 15, Priority.PRIMARY) == Priority.ZENDURE
    assert charge_choice(55, 45, 15, Priority.ZENDURE) == Priority.PRIMARY
    assert charge_choice(57, 45, 15, Priority.ZENDURE) == Priority.ZENDURE
    assert charge_choice(57, 45, 15, Priority.PRIMARY) == Priority.PRIMARY


def test_charge_choice_lead_100_keeps_the_primary_first() -> None:
    assert charge_choice(90, 0, 100, Priority.PRIMARY) == Priority.PRIMARY


def test_discharge_choice_hysteresis() -> None:
    assert discharge_choice(50, 55, Priority.PRIMARY) == Priority.ZENDURE
    assert discharge_choice(52, 55, Priority.PRIMARY) == Priority.PRIMARY
    assert discharge_choice(60, 55, Priority.ZENDURE) == Priority.PRIMARY


def test_priority_hold() -> None:
    t0 = datetime(2026, 11, 15, 12, 0, tzinfo=BER)
    hold = PriorityHold(Priority.PRIMARY, timedelta(minutes=15))
    assert hold.update(Priority.ZENDURE, t0) == Priority.ZENDURE
    assert hold.update(Priority.PRIMARY, t0 + timedelta(minutes=10)) == Priority.ZENDURE
    assert hold.update(Priority.PRIMARY, t0 + timedelta(minutes=15)) == Priority.PRIMARY
    assert hold.update(Priority.ZENDURE, t0 + timedelta(minutes=16)) == Priority.PRIMARY
    assert hold.update(None, t0 + timedelta(minutes=17)) == Priority.PRIMARY


def test_unknown_value_falls_back_immediately() -> None:
    t0 = datetime(2026, 11, 15, 12, 0, tzinfo=BER)
    hold = PriorityHold(Priority.ZENDURE, timedelta(minutes=15))
    hold.update(Priority.PRIMARY, t0)
    assert hold.update(None, t0 + timedelta(minutes=1)) == Priority.ZENDURE


def test_full_charge_due_from_saturday_until_done() -> None:
    friday = datetime(2026, 11, 13, 15, 0, tzinfo=BER)
    assert full_charge_due(friday, datetime(2026, 11, 14, 0, 5, tzinfo=BER))
    assert full_charge_due(friday, datetime(2026, 11, 15, 12, 0, tzinfo=BER))
    assert full_charge_due(friday, datetime(2026, 11, 16, 12, 0, tzinfo=BER))
    assert full_charge_due(None, datetime(2026, 11, 16, 12, 0, tzinfo=BER))


def test_full_charge_done_once_per_week() -> None:
    done = datetime(2026, 11, 14, 13, 0, tzinfo=BER)
    assert not full_charge_due(done, datetime(2026, 11, 14, 14, 0, tzinfo=BER))
    assert not full_charge_due(done, datetime(2026, 11, 15, 12, 0, tzinfo=BER))
    assert not full_charge_due(done, datetime(2026, 11, 20, 23, 59, tzinfo=BER))
    assert full_charge_due(done, datetime(2026, 11, 21, 0, 0, tzinfo=BER))
