"""Scenario tests for ZendureManager.power_surplus (solar surplus mode).

The primary PV system (hybrid inverter with a DC-coupled battery) charges its own
battery before it feeds anything into the grid. The Zendure (AC-coupled, lower
round-trip efficiency) must therefore only take what would otherwise be fed in,
and must give power back as soon as it draws from the primary battery.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from custom_components.zendure_ha.manager import ZendureManager


class _RecordingSensor:
    def __init__(self) -> None:
        self.values: list[Any] = []

    def update_value(self, value: Any) -> None:
        self.values.append(value)

    @property
    def last(self) -> Any:
        return self.values[-1] if self.values else None


def _harness(
    *,
    charge: int,
    dcpower: float,
    load: float,
    battery: float,
    soc: float,
    meter: float = 0,
    reserve: int = 50,
    probe: int = 100,
    last_charge: datetime = datetime.min,
    actual: int | None = None,
    max_soc: float | None = None,
    start_soc: float = 0,
) -> ZendureManager:
    manager = object.__new__(ZendureManager)
    manager.pv_dcpower = dcpower
    manager.pv_load = load
    manager.pv_meter = meter
    manager.pv_battery = battery
    manager.pv_soc = soc
    manager.pv_max_soc = max_soc
    manager.surplus_start_soc = SimpleNamespace(asNumber=start_soc)
    manager.surplus_released = False
    manager.surplus_saturated_since = None
    manager.primary_limit_lifted = False
    manager.surplus_charge = charge
    manager.surplus_dirty = True
    manager.surplus_next = datetime.min
    manager.surplus_next_down = datetime.min
    manager.surplus_last_charge = last_charge
    manager.surplus_offset = SimpleNamespace(asNumber=reserve)
    manager.surplus_probe = SimpleNamespace(asNumber=probe)
    manager.surplusMargin = _RecordingSensor()
    manager.surplusEffOffset = _RecordingSensor()
    manager.surplusPrimaryFull = _RecordingSensor()
    manager.surplusTarget = _RecordingSensor()
    # what the devices really take from the grid (they lag behind the target)
    taken = charge if actual is None else actual
    # device input when the latest primary/grid readings arrived
    manager.surplus_seen_input = taken
    manager.devices = [
        SimpleNamespace(charge_limit=-2400, homeInput=SimpleNamespace(asInt=taken // 2)),
        SimpleNamespace(charge_limit=-2400, homeInput=SimpleNamespace(asInt=taken - taken // 2)),
    ]
    manager.charge_calls = []
    manager.discharge_calls = []

    async def power_charge(setpoint: int, _time: datetime) -> None:
        manager.charge_calls.append(setpoint)

    async def power_discharge(setpoint: int) -> None:
        manager.discharge_calls.append(setpoint)

    manager.power_charge = power_charge
    manager.power_discharge = power_discharge
    return manager


async def _run(manager: ZendureManager, p1: int) -> None:
    await ZendureManager.power_surplus(manager, p1, datetime.now() + timedelta(seconds=30))


async def test_primary_not_full_takes_only_feed_in_above_reserve() -> None:
    # primary battery charges at its limit, 800 W are fed in -> Zendure takes 750 W more
    manager = _harness(charge=1000, dcpower=6000, load=2200, battery=-2700, soc=60)
    await _run(manager, p1=-800)
    assert manager.surplus_charge == 1750
    assert manager.charge_calls == [-1750]
    assert manager.surplusEffOffset.last == 50
    assert manager.surplusPrimaryFull.last == 0


async def test_primary_not_full_without_feed_in_backs_off() -> None:
    # nothing is fed in although the primary battery is not full:
    # the Zendure may be taking from the primary battery -> give power back
    manager = _harness(charge=2000, dcpower=5000, load=3000, battery=-1700, soc=40)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 2000 - 50 - 100
    assert manager.charge_calls == [-1850]


async def test_inverter_losses_do_not_ramp_up_the_zendure() -> None:
    # DC - load leaves ~300 W of inverter losses, but nothing is fed in:
    # the old margin logic ramped the Zendure up here and squeezed the primary battery
    manager = _harness(charge=2000, dcpower=5000, load=2700, battery=-2000, soc=40)
    await _run(manager, p1=0)
    assert manager.surplus_charge < 2000


async def test_feed_in_inside_reserve_band_keeps_target() -> None:
    manager = _harness(charge=1500, dcpower=6000, load=1800, battery=-2700, soc=60)
    await _run(manager, p1=-60)
    assert manager.surplus_charge == 1500


async def test_small_feed_in_below_reserve_backs_off_proportionally() -> None:
    manager = _harness(charge=1500, dcpower=6000, load=1800, battery=-2700, soc=60)
    await _run(manager, p1=-20)
    assert manager.surplus_charge == 1470


async def test_primary_discharging_backs_off_by_overshoot() -> None:
    manager = _harness(charge=2000, dcpower=2000, load=2600, battery=400, soc=40)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 1600


async def test_grid_import_backs_off() -> None:
    manager = _harness(charge=2000, dcpower=2000, load=2300, battery=0, soc=40, meter=300)
    await _run(manager, p1=300)
    assert manager.surplus_charge == 1700


async def test_primary_full_probes_upward_without_reserve() -> None:
    # primary battery full and curtailing: probe upward to harvest the hidden surplus
    manager = _harness(charge=500, dcpower=3000, load=3000, battery=0, soc=100)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 600
    assert manager.surplusEffOffset.last == 0
    assert manager.surplusPrimaryFull.last == 1


async def test_target_is_capped_at_combined_charge_limit() -> None:
    manager = _harness(charge=4500, dcpower=9000, load=1500, battery=-2700, soc=60)
    await _run(manager, p1=-3000)
    assert manager.surplus_charge == 4800


async def test_cloud_dip_keeps_charge_mode_at_zero() -> None:
    # observed 2026-11-13 11:59: PV fell from 8 kW to 2 kW for ~20 s, target dropped to 0 and the
    # devices were switched to discharge mode; the charge restart then waited 60 s while 4.6 kW were fed in
    manager = _harness(charge=2400, dcpower=2100, load=2700, battery=2600, soc=100, last_charge=datetime.now())
    await _run(manager, p1=0)
    assert manager.surplus_charge == 0
    assert manager.charge_calls == [0]
    assert manager.discharge_calls == []


async def test_grid_import_right_after_charging_does_not_discharge() -> None:
    manager = _harness(charge=2400, dcpower=2100, load=3300, battery=2600, soc=100, meter=600, last_charge=datetime.now())
    await _run(manager, p1=600)
    assert manager.discharge_calls == []
    assert manager.charge_calls == [0]


async def test_grid_import_after_hold_time_discharges() -> None:
    manager = _harness(charge=0, dcpower=0, load=300, battery=0, soc=20, meter=300)
    await _run(manager, p1=300)
    assert manager.discharge_calls == [300]


async def test_charging_records_the_last_charge_time() -> None:
    manager = _harness(charge=1000, dcpower=6000, load=2200, battery=-2700, soc=60)
    await _run(manager, p1=-800)
    assert manager.surplus_last_charge > datetime.min


async def test_back_off_starts_from_what_the_devices_take() -> None:
    # target 4800, but the devices only reached 3500: cutting the target by the overshoot
    # would have no effect for several readings and then crash it to 0
    manager = _harness(charge=4800, dcpower=8000, load=8000, battery=1000, soc=100, actual=3500)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 2500


async def test_repeated_readings_of_one_state_do_not_cut_again() -> None:
    manager = _harness(charge=4800, dcpower=8000, load=9200, battery=1143, soc=100, actual=4763)
    now = datetime.now()
    await ZendureManager.power_surplus(manager, 0, now)
    first = manager.surplus_charge
    manager.surplus_dirty = True
    await ZendureManager.power_surplus(manager, 0, now + timedelta(seconds=1))
    assert first == 4763 - 1143
    assert manager.surplus_charge == first


async def test_observed_back_off_sequence_does_not_wind_down_to_zero() -> None:
    # 2026-11-13 12:37:55-12:38:04: (primary battery discharge, device input when it was measured)
    manager = _harness(charge=4800, dcpower=8000, load=9200, battery=0, soc=100)
    now = datetime.now()
    for i, (battery, seen) in enumerate([(1143, 4763), (2156, 4464), (1533, 4464)]):
        manager.pv_battery = battery
        manager.surplus_seen_input = seen
        manager.surplus_dirty = True
        await ZendureManager.power_surplus(manager, 0, now + timedelta(seconds=3 * i))
    assert manager.surplus_charge == 4464 - 2156


async def test_back_off_counts_primary_discharge_and_grid_import() -> None:
    # 2026-11-13 13:03:52: 2.7 kW from the primary battery and 1.8 kW from the grid at the same time
    manager = _harness(charge=4800, dcpower=2800, load=7000, battery=2699, soc=100, meter=1787, actual=4633)
    await _run(manager, p1=1787)
    assert manager.surplus_charge == 4633 - 2699 - 1787


async def test_back_off_right_after_an_upward_step() -> None:
    # 2026-11-13 13:03:45: a +100 W probe step blocked the back-off for 6 s while 2 kW were imported
    manager = _harness(charge=4553, dcpower=8000, load=6500, battery=0, soc=100, actual=4540)
    now = datetime.now()
    await ZendureManager.power_surplus(manager, -500, now)
    assert manager.surplus_charge > 4553
    manager.pv_dcpower = 2800
    manager.surplus_dirty = True
    await ZendureManager.power_surplus(manager, 1976, now + timedelta(seconds=1))
    assert manager.surplus_charge == 4540 - 1976


async def test_primary_counts_as_full_at_its_configured_max_soc() -> None:
    # primary battery limited to 90 % in the inverter: at 90 % it is full -> no reserve, probe upward
    manager = _harness(charge=500, dcpower=3000, load=3000, battery=0, soc=90, max_soc=90)
    await _run(manager, p1=0)
    assert manager.surplusPrimaryFull.last == 1
    assert manager.surplus_charge == 600


async def test_primary_at_90_is_not_full_without_max_soc() -> None:
    manager = _harness(charge=500, dcpower=3000, load=3000, battery=0, soc=90)
    await _run(manager, p1=0)
    assert manager.surplusPrimaryFull.last == 0


async def test_no_charging_below_the_start_soc() -> None:
    # primary battery at 40 % charges at its limit and 800 W are fed in, but the start is set to 50 %
    manager = _harness(charge=0, dcpower=6000, load=2200, battery=-2700, soc=40, start_soc=50)
    await _run(manager, p1=-800)
    assert manager.surplus_charge == 0
    assert manager.charge_calls == [0]


async def test_charging_starts_at_the_start_soc() -> None:
    manager = _harness(charge=0, dcpower=6000, load=2200, battery=-2700, soc=50, start_soc=50)
    await _run(manager, p1=-800)
    assert manager.surplus_charge == 750


async def test_start_soc_has_a_hysteresis() -> None:
    manager = _harness(charge=1000, dcpower=6000, load=2200, battery=-2700, soc=50, start_soc=50)
    await _run(manager, p1=-60)
    assert manager.surplus_charge == 1000
    manager.pv_soc = 48.5
    manager.surplus_dirty = True
    await _run(manager, p1=-60)
    assert manager.surplus_charge == 1000
    manager.pv_soc = 47.9
    manager.surplus_dirty = True
    await _run(manager, p1=-60)
    assert manager.surplus_charge == 0


async def test_start_soc_above_max_soc_still_starts_when_full() -> None:
    manager = _harness(charge=0, dcpower=3000, load=3000, battery=0, soc=89.5, max_soc=90, start_soc=95)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 100


async def test_limit_is_lifted_when_the_zendure_cannot_take_all_surplus() -> None:
    # primary battery at its 80 % limit, Zendure at its 4800 W maximum and still 500 W fed in for 2 minutes
    manager = _harness(charge=4800, dcpower=9000, load=8500, battery=0, soc=80, max_soc=80)
    now = datetime.now()
    await ZendureManager.power_surplus(manager, -500, now)
    assert manager.primary_limit_lifted is False
    manager.surplus_dirty = True
    await ZendureManager.power_surplus(manager, -500, now + timedelta(seconds=130))
    assert manager.primary_limit_lifted is True


async def test_short_saturation_does_not_lift_the_limit() -> None:
    manager = _harness(charge=4800, dcpower=9000, load=8500, battery=0, soc=80, max_soc=80)
    now = datetime.now()
    await ZendureManager.power_surplus(manager, -500, now)
    manager.surplus_dirty = True
    await ZendureManager.power_surplus(manager, 0, now + timedelta(seconds=60))
    manager.surplus_dirty = True
    await ZendureManager.power_surplus(manager, -500, now + timedelta(seconds=130))
    assert manager.primary_limit_lifted is False
