"""Tests for the pure decision functions of the battery balance (fill levels, priority, full charge)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.zendure_ha.balance import (
    LoadTracker,
    Pack,
    Priority,
    PriorityHold,
    Stage,
    StageFilter,
    charge_choice,
    classify,
    discharge_choice,
    fill_level,
    forecast_slots,
    full_charge_due,
    lead_for,
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


NOW = datetime(2026, 11, 15, 12, 10, tzinfo=BER)  # 11:10 UTC


def test_forecast_slots_keep_the_rest_of_today() -> None:
    watts = {
        "2026-11-15T10:45:00+00:00": 900,  # 11:45-12:00 local, over
        "2026-11-15T11:00:00+00:00": 1000,  # current slot
        "2026-11-15T11:15:00+00:00": 1200,
        "2026-11-15T15:30:00+00:00": 0,
        "2026-11-15T23:15:00+00:00": 500,  # 00:15 local on the 16th
    }
    assert forecast_slots(watts, NOW) == [1000, 1200]


def test_forecast_slots_after_sunset_are_empty_not_missing() -> None:
    assert forecast_slots({"2026-11-15T15:30:00+00:00": 0}, NOW) == []


def test_forecast_slots_missing_or_broken() -> None:
    assert forecast_slots(None, NOW) is None
    assert forecast_slots("unavailable", NOW) is None
    assert forecast_slots({}, NOW) is None
    assert forecast_slots({"bad": 5, "2026-11-15T11:00:00+00:00": "abc"}, NOW) is None
    assert forecast_slots({"2026-11-14T11:00:00+00:00": 800}, NOW) is None  # yesterday only


def _classify(slots: list[float]) -> tuple[Stage, float, float]:
    return classify(slots, expected_load=500, base_load=300, free_primary=4.48, free_zendure=6.0, primary_power=2750, zendure_power=4800)


def test_classify_cloudy() -> None:
    assert _classify([800] * 16) == (Stage.CLOUDY, 1.2, 500)


def test_classify_sunny_by_peak() -> None:
    assert _classify([6000] * 8) == (Stage.SUNNY, 11.0, 5700)


def test_classify_sunny_by_energy() -> None:
    assert _classify([3000] * 40) == (Stage.SUNNY, 25.0, 2700)


def test_classify_mixed() -> None:
    assert _classify([3500] * 8) == (Stage.MIXED, 6.0, 3200)


def test_classify_without_slots() -> None:
    assert _classify([]) == (Stage.CLOUDY, 0, 0)


def test_stage_needs_two_equal_results() -> None:
    f = StageFilter()
    assert f.update(Stage.SUNNY) == Stage.SUNNY
    assert f.update(Stage.CLOUDY) == Stage.SUNNY
    assert f.update(Stage.CLOUDY) == Stage.CLOUDY
    assert f.update(Stage.MIXED) == Stage.CLOUDY
    assert f.update(Stage.SUNNY) == Stage.CLOUDY
    assert f.update(Stage.NONE) == Stage.NONE


def test_lead() -> None:
    assert lead_for(Stage.SUNNY, True, 15) == 100
    assert lead_for(Stage.CLOUDY, False, 15) == 100
    assert lead_for(Stage.SUNNY, False, 15) == 0
    assert lead_for(Stage.MIXED, False, 15) == 15
    assert lead_for(Stage.NONE, False, 20) == 20


def test_load_tracker() -> None:
    tracker = LoadTracker(timedelta(hours=24))
    assert tracker.mean() is None and tracker.base() is None
    for i, w in enumerate(range(100, 1001, 100)):
        tracker.add(NOW + timedelta(minutes=i), w)
    assert tracker.mean() == 550
    assert tracker.base() == 200


def test_load_tracker_drops_old_values() -> None:
    tracker = LoadTracker(timedelta(hours=24))
    tracker.add(NOW, 5000)
    tracker.add(NOW + timedelta(hours=25), 100)
    assert tracker.mean() == 100
