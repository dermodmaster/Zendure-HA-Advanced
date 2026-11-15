"""Ranges of the primary battery options in the config flow."""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous as vol

from custom_components.zendure_ha.config_flow import ZendureConfigFlow
from custom_components.zendure_ha.const import CONF_PV_CAPACITY, CONF_PV_MIN_SOC, CONF_PV_POWER, SmartMode

BASE = {"token": "t", "p1meter": "sensor.p1", "mqttlog": False, "mqttlocal": False}


def _validate(**options: Any) -> dict[str, Any]:
    return ZendureConfigFlow.data_schema(BASE | options)


def test_defaults_are_within_the_ranges() -> None:
    data = _validate()
    assert data[CONF_PV_CAPACITY] == SmartMode.PRIMARY_CAPACITY
    assert data[CONF_PV_POWER] == SmartMode.PRIMARY_POWER
    assert data[CONF_PV_MIN_SOC] == SmartMode.PRIMARY_MIN_SOC


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (CONF_PV_CAPACITY, 0),
        (CONF_PV_CAPACITY, 101),
        (CONF_PV_POWER, 200),  # below the discharge margin: the Zendure would charge the primary battery
        (CONF_PV_POWER, 20001),
        (CONF_PV_MIN_SOC, -1),
        (CONF_PV_MIN_SOC, 100),
    ],
)
def test_values_outside_the_ranges_are_rejected(key: str, value: float) -> None:
    with pytest.raises(vol.Invalid):
        _validate(**{key: value})


def test_values_at_the_range_edges_are_accepted() -> None:
    data = _validate(**{CONF_PV_CAPACITY: "0.1", CONF_PV_POWER: "500", CONF_PV_MIN_SOC: 99})
    assert (data[CONF_PV_CAPACITY], data[CONF_PV_POWER], data[CONF_PV_MIN_SOC]) == (0.1, 500, 99)
