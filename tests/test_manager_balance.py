"""Tests for ZendureManager.update_balance: who charges and discharges first, from the live inputs."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.zendure_ha.balance import LoadTracker, Priority, PriorityHold, StageFilter
from custom_components.zendure_ha.const import (
    CONF_PV_CAPACITY,
    CONF_PV_FORECAST,
    CONF_PV_MIN_SOC,
    CONF_PV_POWER,
    SmartMode,
)
from custom_components.zendure_ha.manager import ZendureManager

BER = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 15, 12, 10, tzinfo=BER)  # Sunday
LAST_SATURDAY = datetime(2026, 11, 14, 13, 0, tzinfo=BER)


class _RecordingSensor:
    def __init__(self) -> None:
        self.values: list[Any] = []

    def update_value(self, value: Any) -> None:
        self.values.append(value)

    @property
    def last(self) -> Any:
        return self.values[-1] if self.values else None


class _LastFullCharge:
    """Stands in for the restored timestamp sensor; `hass` is set once the entity is in Home Assistant."""

    def __init__(self, value: datetime | None) -> None:
        self.native_value = value
        self.hass: Any = object()

    def update_value(self, value: datetime) -> None:
        self.native_value = value


def _v(value: float) -> SimpleNamespace:
    return SimpleNamespace(asNumber=value, asInt=int(value), native_value=value)


def _no_value() -> SimpleNamespace:
    """A sensor without a value yet: `asNumber` reads 0 then, `native_value` is None."""
    return SimpleNamespace(asNumber=0, asInt=0, native_value=None)


def _watts(power: int, count: int) -> dict[str, int]:
    """Forecast `watts` attribute: `count` slots of 15 minutes from NOW on."""
    return {(NOW + timedelta(minutes=15 * i)).isoformat(): power for i in range(count)}


def _harness(
    *,
    pv_soc: float | None,
    zendure_soc: float,
    watts: Any,
    pv_load: float | None,
    last_full: datetime | None = LAST_SATURDAY,
) -> ZendureManager:
    manager = object.__new__(ZendureManager)
    manager.primary_capacity = 6.4
    manager.primary_power = 2750
    manager.primary_min_soc = 5
    manager.pv_soc = pv_soc
    manager.pv_max_soc = None
    manager.pv_load = pv_load
    manager.pv_forecast_entity = "sensor.pv_dach_energy_production_today"
    manager.charge_hold = PriorityHold(Priority.PRIMARY, SmartMode.BALANCE_HOLD)
    manager.discharge_hold = PriorityHold(Priority.ZENDURE, SmartMode.BALANCE_HOLD)
    manager.stage_filter = StageFilter()
    manager.load_tracker = LoadTracker(SmartMode.LOAD_WINDOW)
    manager.forecast_next = None
    manager.forecast_watts = watts
    manager.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _e: SimpleNamespace(attributes={"watts": manager.forecast_watts})))
    for name in (
        "forecastStage",
        "forecastSurplus",
        "forecastPeak",
        "primaryLeadActive",
        "primaryFill",
        "zendureFill",
        "chargePriority",
        "dischargePriority",
    ):
        setattr(manager, name, _RecordingSensor())
    manager.primaryLead = SimpleNamespace(asNumber=15)
    manager.lastFullCharge = _LastFullCharge(last_full)
    manager.devices = [
        SimpleNamespace(
            online=True,
            electricLevel=_v(zendure_soc),
            minSoc=_v(10),
            socSet=_v(90),
            kWh=8.16,
            charge_limit=-2400,
            homeInput=_v(0),
            homeOutput=_v(0),
        )
    ]
    return manager


def test_cloudy_forecast_keeps_the_primary_first() -> None:
    m = _harness(pv_soc=60, zendure_soc=30, watts=_watts(800, 16), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    assert m.forecastStage.last == "cloudy"
    assert m.primaryLeadActive.last == 100
    assert m.chargePriority.last == "primary"


def test_sunny_forecast_lets_the_zendure_charge_first() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    assert m.forecastStage.last == "sunny"
    assert m.primaryLeadActive.last == 0
    assert m.chargePriority.last == "zendure"


def test_mixed_forecast_uses_the_configured_lead() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(2500, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    assert m.forecastStage.last == "mixed"
    assert m.primaryLeadActive.last == 15
    assert m.chargePriority.last == "primary"


def test_missing_forecast_uses_the_configured_lead() -> None:
    for watts in (None, "unavailable"):
        m = _harness(pv_soc=50, zendure_soc=40, watts=watts, pv_load=500)
        ZendureManager.update_balance(m, NOW)
        assert m.forecastStage.last == "none"
        assert m.primaryLeadActive.last == 15


def test_forecast_sensor_without_state_or_not_configured_uses_the_configured_lead() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    m.hass.states.get = lambda _e: None
    ZendureManager.update_balance(m, NOW)
    assert m.forecastStage.last == "none"
    assert m.primaryLeadActive.last == 15

    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    m.pv_forecast_entity = None
    ZendureManager.update_balance(m, NOW)
    assert m.forecastStage.last == "none"
    assert m.primaryLeadActive.last == 15


def test_due_full_charge_keeps_the_primary_first_on_a_sunny_day() -> None:
    m = _harness(pv_soc=80, zendure_soc=10, watts=_watts(6000, 8), pv_load=500, last_full=datetime(2026, 11, 13, 15, 0, tzinfo=BER))
    ZendureManager.update_balance(m, NOW)
    assert m.primaryLeadActive.last == 100
    assert m.chargePriority.last == "primary"


def test_full_charge_is_recorded_at_99() -> None:
    m = _harness(pv_soc=99.5, zendure_soc=10, watts=_watts(6000, 8), pv_load=500, last_full=datetime(2026, 11, 13, 15, 0, tzinfo=BER))
    ZendureManager.update_balance(m, NOW)
    assert m.lastFullCharge.native_value == NOW


def test_first_start_counts_as_done() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500, last_full=None)
    ZendureManager.update_balance(m, NOW)
    assert m.lastFullCharge.native_value == NOW
    assert m.primaryLeadActive.last == 0


def test_last_full_charge_not_written_before_restore() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500, last_full=None)
    m.lastFullCharge.hass = None
    ZendureManager.update_balance(m, NOW)
    assert m.lastFullCharge.native_value is None


def test_unknown_primary_soc_falls_back_to_today() -> None:
    m = _harness(pv_soc=None, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    assert m.chargePriority.last == "primary"
    assert m.dischargePriority.last == "zendure"


def test_all_zendures_offline_falls_back_to_today() -> None:
    m = _harness(pv_soc=80, zendure_soc=10, watts=_watts(6000, 8), pv_load=500)
    for d in m.devices:
        d.online = False
    ZendureManager.update_balance(m, NOW)
    assert m.chargePriority.last == "primary"
    assert m.dischargePriority.last == "zendure"


def test_online_zendure_without_soc_falls_back_to_today() -> None:
    m = _harness(pv_soc=80, zendure_soc=10, watts=_watts(6000, 8), pv_load=500)
    m.devices[0].electricLevel = _no_value()
    ZendureManager.update_balance(m, NOW)
    assert m.zendureFill.last is None
    assert m.chargePriority.last == "primary"
    assert m.dischargePriority.last == "zendure"


def test_house_load_excludes_the_zendure() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(800, 16), pv_load=2000)
    m.devices[0].homeInput = _v(1500)
    ZendureManager.update_balance(m, NOW)
    assert m.load_tracker.mean() == 500


def test_house_load_that_is_not_a_number_is_not_tracked() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(800, 16), pv_load=float("nan"))
    ZendureManager.update_balance(m, NOW)
    assert m.load_tracker.mean() is None
    assert m.forecastStage.last == "none"


def test_stage_is_recomputed_only_every_15_minutes() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    m.forecast_watts = _watts(800, 16)  # harness reads this on states.get
    # without the gate the second cloudy result would already switch the stage
    ZendureManager.update_balance(m, NOW + timedelta(minutes=5))
    ZendureManager.update_balance(m, NOW + timedelta(minutes=10))
    assert m.forecastStage.last == "sunny"
    assert m.forecast_next == NOW + SmartMode.FORECAST_INTERVAL


def test_fill_levels_are_published_as_whole_percent() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    assert m.primaryFill.last == 47
    assert m.zendureFill.last == 38


def test_unknown_fill_levels_are_published_as_none() -> None:
    m = _harness(pv_soc=None, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    for d in m.devices:
        d.online = False
    ZendureManager.update_balance(m, NOW)
    assert m.primaryFill.last is None
    assert m.zendureFill.last is None


def test_pv_options_fall_back_to_the_defaults() -> None:
    m = object.__new__(ZendureManager)
    m.pvEvents = []
    m.pv_sensors = {}
    m.update_pv_sensors({CONF_PV_FORECAST: "sensor.forecast", CONF_PV_CAPACITY: "10.5", CONF_PV_POWER: 3000, CONF_PV_MIN_SOC: 10})
    assert (m.pv_forecast_entity, m.primary_capacity, m.primary_power, m.primary_min_soc) == ("sensor.forecast", 10.5, 3000, 10)

    m.update_pv_sensors({CONF_PV_FORECAST: "", CONF_PV_CAPACITY: "", CONF_PV_POWER: "abc", CONF_PV_MIN_SOC: None})
    assert m.pv_forecast_entity is None
    assert (m.primary_capacity, m.primary_power, m.primary_min_soc) == (SmartMode.PRIMARY_CAPACITY, SmartMode.PRIMARY_POWER, SmartMode.PRIMARY_MIN_SOC)

    m.update_pv_sensors({})
    assert (m.primary_capacity, m.primary_power, m.primary_min_soc) == (SmartMode.PRIMARY_CAPACITY, SmartMode.PRIMARY_POWER, SmartMode.PRIMARY_MIN_SOC)
