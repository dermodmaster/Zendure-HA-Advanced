"""Scenario tests for the charge limit the manager sets on the primary battery.

The primary battery (DC-coupled) charges up to a limit (e.g. 80 %) and then only buffers
fluctuations, while the Zendure takes the surplus. The limit is lifted when the Zendure is
full, when it cannot take all of the surplus, and once a week for a full charge.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from custom_components.zendure_ha.const import DeviceState, ManagerMode
from custom_components.zendure_ha.manager import ZendureManager

FRIDAY_NOON = datetime(2026, 11, 13, 12, 0)
SATURDAY_NOON = datetime(2026, 11, 14, 12, 0)
SUNDAY_NOON = datetime(2026, 11, 15, 12, 0)
ENTITY = "number.battery_max_soc"


class _Services:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def async_call(self, domain: str, service: str, data: dict[str, Any], **_kwargs: Any) -> None:
        self.calls.append((domain, service, data))


def _harness(
    *,
    limit: float = 80,
    current: float = 100,
    soc: float = 60,
    dcpower: float = 3000,
    full: bool = False,
    entity: str | None = ENTITY,
    operation: ManagerMode = ManagerMode.SOLAR_SURPLUS,
) -> ZendureManager:
    manager = object.__new__(ZendureManager)
    services = _Services()
    state = SimpleNamespace(state=str(current), attributes={"min": 50.0, "max": 100.0})
    manager.hass = SimpleNamespace(services=services, states=SimpleNamespace(get=lambda _e: state))
    manager.services = services
    manager.operation = operation
    manager.pv_max_soc_entity = entity
    manager.pv_max_soc = current
    manager.pv_soc = soc
    manager.pv_dcpower = dcpower
    manager.primary_limit = SimpleNamespace(asNumber=limit)
    manager.primary_limit_lifted = False
    manager.primary_full_charge_due = False
    manager.primary_limit_next = datetime.min
    state_full = DeviceState.SOCFULL if full else DeviceState.ACTIVE
    manager.devices = [SimpleNamespace(online=True, state=state_full), SimpleNamespace(online=True, state=state_full)]
    return manager


def _written(manager: ZendureManager) -> list[float]:
    return [data["value"] for _d, _s, data in manager.services.calls]


async def test_limit_is_written_while_the_zendure_still_charges() -> None:
    manager = _harness()
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert manager.services.calls == [("number", "set_value", {"entity_id": ENTITY, "value": 80})]


async def test_limit_is_lifted_when_the_zendure_is_full() -> None:
    manager = _harness(current=80, full=True)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == [100]


async def test_lifted_limit_stays_lifted_during_the_day() -> None:
    manager = _harness(current=100)
    manager.primary_limit_lifted = True
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == []


async def test_limit_is_rearmed_at_night() -> None:
    manager = _harness(current=100, dcpower=0)
    manager.primary_limit_lifted = True
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON.replace(hour=23))
    assert manager.primary_limit_lifted is False
    assert _written(manager) == [80]


async def test_saturday_charges_the_primary_battery_full() -> None:
    manager = _harness(current=80)
    await ZendureManager.update_primary_limit(manager, SATURDAY_NOON)
    assert _written(manager) == [100]


async def test_full_charge_stays_due_until_the_primary_battery_was_full() -> None:
    manager = _harness(current=100, soc=95)
    manager.primary_full_charge_due = True
    await ZendureManager.update_primary_limit(manager, SUNDAY_NOON)
    assert _written(manager) == []
    manager.pv_soc = 99.5
    await ZendureManager.update_primary_limit(manager, SUNDAY_NOON)
    assert manager.primary_full_charge_due is False
    assert _written(manager) == [80]


async def test_limit_100_switches_the_feature_off() -> None:
    manager = _harness(limit=100, current=80)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == [100]


async def test_limit_below_the_inverter_minimum_is_clamped() -> None:
    manager = _harness(limit=30)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == [50]


async def test_writes_are_throttled() -> None:
    manager = _harness()
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON + timedelta(seconds=10))
    assert _written(manager) == [80]


async def test_nothing_is_written_when_the_manager_is_off() -> None:
    manager = _harness(operation=ManagerMode.OFF)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == []


async def test_nothing_is_written_without_a_writable_entity() -> None:
    manager = _harness(entity=None)
    await ZendureManager.update_primary_limit(manager, FRIDAY_NOON)
    assert _written(manager) == []
