"""Constants for Zendure."""

from datetime import timedelta
from enum import Enum

DOMAIN = "zendure_ha"

CONF_APPTOKEN = "token"
CONF_P1METER = "p1meter"
CONF_PV_DCPOWER = "pv_dcpower"  # Total DC Power of the primary PV system
CONF_PV_LOAD = "pv_load"  # Load Power of the primary PV system
CONF_PV_METER = "pv_meter"  # Meter active power (grid) of the primary PV system
CONF_PV_BATTERY = "pv_battery"  # Battery Power of the primary PV system (neg = charging)
CONF_PV_SOC = "pv_soc"  # State of charge of the primary battery
CONF_PV_MAX_SOC = "pv_max_soc"  # Maximum state of charge of the primary battery (e.g. its inverter setting)
CONF_PV_FORECAST = "pv_forecast"  # Solar forecast sensor with the attribute `watts` (optional)
CONF_PV_CAPACITY = "pv_capacity"  # Capacity of the primary battery (kWh)
CONF_PV_POWER = "pv_power"  # Charge/discharge power of the primary battery (W)
CONF_PV_MIN_SOC = "pv_min_soc"  # Minimum state of charge of the primary battery (%)
CONF_PRICE = "price"
CONF_MQTTLOG = "mqttlog"
CONF_MQTTLOCAL = "mqttlocal"
CONF_MQTTSERVER = "mqttserver"
CONF_SIM = "simulation"
CONF_MQTTPORT = "mqttport"
CONF_MQTTUSER = "mqttuser"
CONF_MQTTPSW = "mqttpsw"
CONF_WIFISSID = "wifissid"
CONF_WIFIPSW = "wifipsw"
CONF_AUTO_MQTT_USER = "auto_mqtt_user"

CONF_HAKEY = "C*dafwArEOXK"


class AcMode:
    INPUT = 1
    OUTPUT = 2


class DeviceState(Enum):
    OFFLINE = 0
    SOCEMPTY = 1
    INACTIVE = 2
    SOCFULL = 3
    ACTIVE = 4


class ManagerMode(Enum):
    OFF = 0
    MANUAL = 1
    MATCHING = 2
    MATCHING_DISCHARGE = 3
    MATCHING_CHARGE = 4
    STORE_SOLAR = 5
    SOLAR_SURPLUS = 6


class ManagerState(Enum):
    IDLE = 0
    CHARGE = 1
    DISCHARGE = 2
    OFF = 3


class SmartMode:
    SOCFULL = 1
    SOCEMPTY = 2
    ZENSDK = 2
    CONNECTED = 10

    TIMEFAST = 2.2  # Fast update interval after significant change
    TIMEZERO = 4  # Normal update interval

    # Standard deviation thresholds for detecting significant changes
    P1_STDDEV_FACTOR = 3.5  # Multiplier for P1 meter stddev calculation
    P1_STDDEV_MIN = 15  # Minimum stddev value for P1 changes (watts)
    P1_MIN_UPDATE = timedelta(milliseconds=400)
    SETPOINT_STDDEV_FACTOR = 5.0  # Multiplier for power average stddev calculation
    SETPOINT_STDDEV_MIN = 50  # Minimum stddev value for power average (watts)

    HEMSOFF_TIMEOUT = 60  # Seconds before HEMS state is set to OFF if no updates are received

    POWER_START = 50  # Minimum Power (W) for starting a device
    DISCHARGE_STOP = 0.8  # Stop the lowest of several discharging devices below this share of its optimal power
    POWER_TOLERANCE = 5  # Device-level power tolerance (W) before updating

    # Solar surplus mode (charging without grid feed-in)
    SURPLUS_SETTLE = timedelta(seconds=8)  # Wait after a charge step before probing upwards again
    SURPLUS_SETTLE_DOWN = timedelta(0)  # Back off on every fresh reading: the back-off target is absolute, it cannot wind down
    SURPLUS_DEADBAND = 15  # Minimum surplus margin (W) before adjusting the charge target
    SURPLUS_SOCFULL_MARGIN = 1  # Primary battery counts as full at its maximum SoC minus this margin (%)
    SURPLUS_HOLD = timedelta(minutes=2)  # After charging, stay in charge mode this long before covering grid import

    PRIMARY_FULL_CHARGE_WEEKDAY = 5  # Saturday: charge the primary battery to 100 % (BMS calibration, cell balancing)
    PRIMARY_FULL_SOC = 99  # Primary SoC (%) that counts as the weekly full charge being done

    BALANCE_HYSTERESIS = 5  # Fill level difference (percentage points) needed before the charge/discharge priority flips back
    BALANCE_HOLD = timedelta(minutes=15)  # Minimum time between two priority switches
    FORECAST_INTERVAL = timedelta(minutes=15)  # How often the solar forecast is read and classified
    LOAD_WINDOW = timedelta(hours=24)  # House load history used for the expected and the base load
    LOAD_BASE_QUANTILE = 0.2  # Quantile of the house load history that counts as the base load

    PRIMARY_CAPACITY = 6.4  # Default capacity of the primary battery (kWh)
    PRIMARY_POWER = 2750  # Default charge/discharge power of the primary battery (W)
    PRIMARY_MIN_SOC = 5  # Default minimum SoC of the primary battery (%)
    PRIMARY_LEAD = 15  # Default fill level lead (percentage points) of the primary battery in a mixed or unknown forecast
