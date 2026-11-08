"""Scenario tests for the smart_discharging mode next to a primary PV battery.

The primary hybrid inverter regulates the grid meter to zero with its own battery.
Without knowing that battery's power, the Zendure only sees p1 ~ 0 and keeps its
current output: the split between both batteries drifts, and the Zendure can even
end up charging the primary battery (energy ping-pong through two conversions).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from custom_components.zendure_ha.const import DeviceState, ManagerMode
from custom_components.zendure_ha.manager import ZendureManager


class _RecordingSensor:
    def __init__(self) -> None:
        self.values: list[Any] = []

    def update_value(self, value: Any) -> None:
        self.values.append(value)


def _value(v: int) -> SimpleNamespace:
    return SimpleNamespace(asInt=v, asNumber=float(v))


class _DischargingDevice:
    def __init__(self, output: int) -> None:
        self.batteryOutput = _value(output)
        self.homeOutput = _value(output)
        self.batteryInput = _value(0)
        self.homeInput = _value(0)
        self.solarInput = _value(0)
        self.electricLevel = _value(90)
        self.state = DeviceState.ACTIVE
        self.pwr_offgrid = 0
        self.pwr_produced = 0
        self.pwr_max = 2400
        self.discharge_optimal = 300
        self.exports_bypass = False
        self.actualKwh = 7.0
        self.kWh = 8.16
        self.fuseGrp = SimpleNamespace(discharge_limit=lambda _d: 2400)

    async def power_get(self) -> bool:
        return True


def _harness(*, output: int, battery: float | None) -> ZendureManager:
    manager = object.__new__(ZendureManager)
    manager.operation = ManagerMode.MATCHING_DISCHARGE
    manager.devices = [_DischargingDevice(output)]
    manager.pv_battery = battery
    manager.charge = []
    manager.charge_limit = 0
    manager.charge_optimal = 0
    manager.charge_weight = 0
    manager.discharge = []
    manager.discharge_bypass = 0
    manager.discharge_limit = 0
    manager.discharge_optimal = 0
    manager.discharge_produced = 0
    manager.discharge_weight = 0
    manager.idle = []
    manager.idle_lvlmax = 0
    manager.idle_lvlmin = 100
    manager.produced = 0
    manager.power = _RecordingSensor()
    manager.availableKwh = _RecordingSensor()
    manager.globalSoc = _RecordingSensor()
    manager.discharge_calls = []

    async def power_discharge(setpoint: int) -> None:
        manager.discharge_calls.append(setpoint)

    manager.power_discharge = power_discharge
    return manager


async def _run(manager: ZendureManager, p1: int) -> int:
    await ZendureManager.powerChanged(manager, p1, False, datetime.now())
    return manager.discharge_calls[-1]


async def test_zendure_stops_charging_the_primary_battery() -> None:
    # observed 2026-11-08 16:40: Zendure 1300 W out, primary battery charging 735 W, meter 0
    manager = _harness(output=1300, battery=-735)
    assert await _run(manager, p1=0) < 1300 - 300


async def test_zendure_takes_over_from_discharging_primary_battery() -> None:
    # observed 2026-11-08 17:45: Zendure 317 W, primary battery discharging 373 W, meter 42 W
    manager = _harness(output=317, battery=373)
    assert await _run(manager, p1=42) > 317 + 42 + 150


async def test_converges_to_zendure_covering_the_load() -> None:
    # house load 700 W, primary battery follows the meter immediately (it regulates to zero)
    load, zendure = 700, 300
    for _ in range(12):
        battery = load - zendure
        manager = _harness(output=zendure, battery=battery)
        zendure = await _run(manager, p1=0)
    assert abs(zendure - load) < 10


async def test_idle_primary_battery_keeps_meter_matching() -> None:
    manager = _harness(output=300, battery=0)
    assert await _run(manager, p1=40) == 340


async def test_without_primary_battery_sensor_behaviour_is_unchanged() -> None:
    manager = _harness(output=300, battery=None)
    assert await _run(manager, p1=40) == 340
