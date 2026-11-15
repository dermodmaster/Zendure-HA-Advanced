# Akku-Ausgleich Sungrow und Zendure – Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Manager entscheidet nach Füllstand und Prognose-Stufe, ob beim Laden der Sungrow oder die Zendures zuerst laden und wer nachts die Last deckt.

**Architecture:** Die Entscheidungslogik kommt als reine Funktionen in ein neues Modul `balance.py`. Der Manager ruft einmal pro Minute `update_balance()` auf. Dort berechnet er Füllstände, die Prognose-Stufe (alle 15 Minuten), den Vorsprung V und die beiden Zuständigkeiten, jeweils mit Haltezeit. `power_surplus` und der Modus `smart_discharging` lesen nur noch die Zuständigkeit. Die Primär-Ladegrenze aus beta6 und `surplus_start_soc` fallen weg.

**Tech Stack:** Python 3.14, Home Assistant Custom Integration, pytest mit `pytest_homeassistant_custom_component` (asyncio_mode auto).

**Spec:** `docs/superpowers/specs/2026-11-14-akku-ausgleich-design.md`

## Global Constraints

- Arbeitsverzeichnis: `zendure-src` (Fork `dermodmaster/Zendure-HA-Advanced`), Branch `battery-balance`.
- Tests: `../venv314/bin/python -m pytest -q` aus `zendure-src`.
- Commits: `git -c user.name="Levent Koch" -c user.email="l.koch@mittwald.de" commit ...`, englische Commit-Messages im Stil der bestehenden („Solar surplus: …“), **kein** `Co-Authored-By`-Trailer (CLAUDE.md des Forks).
- Code-Kommentare englisch wie im bestehenden Code.
- Sungrow-Vorgaben: Kapazität 6,4 kWh, Lade-/Entladeleistung 2750 W, Min-SoC 5 %.
- Vorsprung V: trüb 100, sonnig 0, gemischt oder keine Prognose = `number.zendure_manager_primary_lead` (Vorgabe 15), Vollladung fällig 100 (auch an sonnigen Tagen).
- Hysterese 5 Punkte Füllstand, Haltezeit 15 Minuten, Prognose-Stufe alle 15 Minuten, Wechsel der Stufe erst nach zwei gleichen Ergebnissen.
- Prognose ohne Aufschlag (kein Faktor auf die Prognose-Leistung).
- In jedem Zweifelsfall (Wert fehlt) gilt das heutige Verhalten: Laden Sungrow zuerst, Entladen Zendure deckt die Last.
- Vollladung: fällig ab Samstag 0:00 Ortszeit, erledigt sobald der Sungrow einmal ≥ 99 % erreicht, bleibt sonst fällig bis dahin; Merker überlebt Neustart.

## Review Focus

1. **Neustart mitten am Tag:** Lastverlauf leer, Zeitpunkt der letzten Vollladung erst nach dem Wiederherstellen der Entität bekannt. Erwartet: keine Ausnahme, Stufe aus aktuellem Verbrauch, eine fällige Vollladung geht nicht verloren. Tests in Task 5.
2. **Prognose-Entität fehlt, ist `unavailable` oder das Attribut `watts` ist kaputt:** Erwartet: Stufe „keine“, V = `primary_lead`, keine Ausnahme. Tests in Task 4 und Task 5.
3. **Alle Zendures offline oder ohne Kapazität (`kWh` = 0):** Erwartet: Zendure-Füllstand unbekannt, heutiges Verhalten. Tests in Task 3 und Task 5.
4. **Fehlkonfiguration Sungrow-Max ≤ Min-SoC oder SoC unbekannt:** Erwartet: Sungrow-Füllstand unbekannt, heutiges Verhalten. Tests in Task 3 und Task 5.
5. **Tagesgrenze und Zeitzone:** Prognose-Schlüssel sind UTC, „heute“ ist Ortszeit. Ein Wert um 23:15 UTC gehört zum nächsten Tag. Test in Task 4.

## Dateien

- Create `custom_components/zendure_ha/balance.py` – reine Entscheidungslogik, keine HA-Abhängigkeit außer `datetime`.
- Create `tests/test_balance.py` – Unit-Tests für `balance.py`.
- Create `tests/test_manager_balance.py` – `ZendureManager.update_balance` mit Test-Harness.
- Modify `custom_components/zendure_ha/const.py` – neue CONF-Schlüssel und Konstanten, alte Primär-Grenze-Konstanten weg.
- Modify `custom_components/zendure_ha/manager.py` – Rückbau beta6, `update_balance`, Verdrahtung in `power_surplus` und `MATCHING_DISCHARGE`, Back-off-Fix.
- Modify `custom_components/zendure_ha/config_flow.py` – vier neue Optionen.
- Modify `custom_components/zendure_ha/translations/en.json`, `de.json` – neue Felder und Entitäten, alte Entitäten weg (fr/nl/pl fallen auf Englisch zurück).
- Delete `tests/test_primary_limit.py`.
- Modify `tests/test_surplus.py`, `tests/test_discharge_primary.py`.

---

### Task 1: Back-off nach verspäteter Gerätemeldung (verlorene beta7)

**Files:**
- Modify: `custom_components/zendure_ha/manager.py:929-933` (Zweig `if overshoot > 0` in `power_surplus`)
- Test: `tests/test_surplus.py`

**Interfaces:**
- Consumes: `ZendureManager.devices_input() -> int` (besteht)
- Produces: nichts Neues

- [ ] **Step 1: Testumgebung anlegen**

Run: `cd zendure-src && uv venv --python 3.14 ../venv314 && uv pip install --python ../venv314/bin/python -r requirements.txt -r requirements_test.txt && ../venv314/bin/python -m pytest -q`
Expected: alle bestehenden Tests PASS.

- [ ] **Step 2: Failing test schreiben und bestehenden Test anpassen**

Neu in `tests/test_surplus.py`:

```python
async def test_back_off_uses_the_device_input_now_when_the_report_lagged() -> None:
    # 2026-11-13 13:40:06: Keller still reported 53 W when the import of ~700 W was measured, but already
    # took 1411 W; cutting from 53 W set the target to 0
    manager = _harness(charge=1411, dcpower=1175, load=2600, battery=0, soc=100, meter=700, actual=1411)
    manager.surplus_seen_input = 53
    await _run(manager, p1=700)
    assert manager.surplus_charge == 1411 - 700
```

In `test_observed_back_off_sequence_does_not_wind_down_to_zero` die Schleife ersetzen, Assertion bleibt `4464 - 2156`:

```python
    # (primary battery discharge, device input when it was measured, device input now)
    for i, (battery, seen, now_input) in enumerate([(1143, 4763, 4763), (2156, 4464, 4464), (1533, 4464, 1899)]):
        manager.pv_battery = battery
        manager.surplus_seen_input = seen
        manager.devices[0].homeInput.asInt = now_input // 2
        manager.devices[1].homeInput.asInt = now_input - now_input // 2
```

- [ ] **Step 3: Test laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_surplus.py -q`
Expected: FAIL in `test_back_off_uses_the_device_input_now_when_the_report_lagged` (Ziel 0 statt 711).

- [ ] **Step 4: Implementieren**

Im Zweig `if overshoot > 0:` die Basis auf `max(self.surplus_seen_input, self.devices_input())` setzen, dann `step = min(0, base - overshoot - self.surplus_charge)`. Kommentar: Gerätemeldungen können hinter dem tatsächlichen Bezug zurückliegen.

- [ ] **Step 5: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/zendure_ha/manager.py tests/test_surplus.py
git commit -m "Solar surplus: back off from the device input now when its report lagged"
```

---

### Task 2: Primär-Ladegrenze und Start-SoC entfernen

**Files:**
- Modify: `custom_components/zendure_ha/manager.py` (Init-Attribute `primary_limit_lifted`, `primary_full_charge_due`, `primary_limit_next`, `surplus_released`, `surplus_saturated_since`, `pv_max_soc_entity`; Entitäten `primary_limit`, `surplus_start_soc` in `loadDevices`; Methode `update_primary_limit` und ihr Aufruf in `_run_distribution`; Sättigungsblock und Start-SoC-Block in `power_surplus`; Reset in `update_operation`; Schreibbarkeits-Logik in `update_pv_sensors`)
- Modify: `custom_components/zendure_ha/const.py` (`PRIMARY_SATURATED_FEEDIN`, `PRIMARY_SATURATED_TIME`, `PRIMARY_NIGHT_PV`, `PRIMARY_WRITE_INTERVAL`, `SURPLUS_START_HYSTERESIS` löschen; `PRIMARY_FULL_CHARGE_WEEKDAY` und `PRIMARY_FULL_SOC` bleiben)
- Modify: `translations/en.json`, `translations/de.json` (Einträge `entity.number.primary_limit`, `entity.number.surplus_start_soc` löschen)
- Delete: `tests/test_primary_limit.py`
- Modify: `tests/test_surplus.py` (Tests zu Start-SoC und Sättigung löschen, Harness bereinigen)

**Interfaces:**
- Consumes: –
- Produces: `power_surplus` lädt den Zendure ohne Start-Schwelle; `pv_max_soc` bleibt reiner Lesewert.

- [ ] **Step 1: Tests entfernen**

`tests/test_primary_limit.py` löschen. In `tests/test_surplus.py` löschen: `test_no_charging_below_the_start_soc`, `test_charging_starts_at_the_start_soc`, `test_start_soc_has_a_hysteresis`, `test_start_soc_above_max_soc_still_starts_when_full`, `test_limit_is_lifted_when_the_zendure_cannot_take_all_surplus`, `test_short_saturation_does_not_lift_the_limit`. Im Harness Parameter `start_soc` und die Attribute `surplus_start_soc`, `surplus_released`, `surplus_saturated_since`, `primary_limit_lifted` entfernen.

- [ ] **Step 2: Code entfernen**

Alles unter „Files“ Genannte löschen. `pv_max_soc` wird in `update_pv_sensors` weiter gespiegelt und gelesen.

- [ ] **Step 3: Tests und Restverweise prüfen**

Run: `../venv314/bin/python -m pytest -q && grep -rn "primary_limit\|start_soc\|saturat\|PRIMARY_WRITE\|PRIMARY_NIGHT" custom_components tests`
Expected: Tests PASS, `grep` findet nichts.

- [ ] **Step 4: Commit**

```bash
git add -A custom_components tests
git commit -m "Solar surplus: remove the primary charge limit and the start SoC"
```

---

### Task 3: Füllstände, Zuständigkeit, Haltezeit, Vollladung

**Files:**
- Create: `custom_components/zendure_ha/balance.py`
- Modify: `custom_components/zendure_ha/const.py` (`SmartMode.BALANCE_HYSTERESIS = 5`, `SmartMode.BALANCE_HOLD = timedelta(minutes=15)`)
- Test: `tests/test_balance.py`

**Interfaces:**
- Produces (alle in `balance.py`):
  - `class Priority(StrEnum)`: `PRIMARY = "primary"`, `ZENDURE = "zendure"`
  - `@dataclass(frozen=True) class Pack`: `soc: float`, `min_soc: float`, `max_soc: float`, `kwh: float`, `charge_power: float` (ein Zendure, der online ist; `charge_power` positiv in W)
  - `fill_level(soc: float | None, min_soc: float, max_soc: float) -> float | None` – (soc−min)/(max−min)·100, auf 0–100 begrenzt; `None` bei `soc is None` oder `max_soc <= min_soc`
  - `zendure_fill(packs: list[Pack]) -> float | None` – energiegewichtet: Σ kwh·clamp(soc−min, 0, max−min) / Σ kwh·(max−min) · 100; Packs mit `kwh <= 0` oder `max_soc <= min_soc` zählen nicht; `None`, wenn keiner übrig bleibt
  - `charge_choice(fill_s: float, fill_z: float, lead: float, current: Priority) -> Priority` – `fill_s >= fill_z + lead` → ZENDURE; `fill_s <= fill_z + lead - BALANCE_HYSTERESIS` → PRIMARY; sonst `current`
  - `discharge_choice(fill_s: float, fill_z: float, current: Priority) -> Priority` – `fill_z >= fill_s + 5` → ZENDURE; `fill_s >= fill_z + 5` → PRIMARY; sonst `current`
  - `class PriorityHold`: `__init__(self, default: Priority, hold: timedelta)`, Attribut `value: Priority`, `update(self, desired: Priority | None, time: datetime) -> Priority` – `None` setzt sofort `default`; ein Wechsel erst, wenn seit dem letzten Wechsel `hold` vergangen ist; der erste Wechsel nach dem Start ist sofort erlaubt
  - `full_charge_due(last_full: datetime | None, now: datetime) -> bool` – letzter Samstag 0:00 (Ortszeit von `now`, `weekday() == SmartMode.PRIMARY_FULL_CHARGE_WEEKDAY`) bis `now`; fällig, wenn `last_full is None` oder `last_full` davor liegt

- [ ] **Step 1: Failing tests schreiben**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.zendure_ha.balance import (
    Pack, Priority, PriorityHold, charge_choice, discharge_choice, fill_level, full_charge_due, zendure_fill,
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
```

- [ ] **Step 2: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_balance.py -q`
Expected: FAIL mit `ModuleNotFoundError: custom_components.zendure_ha.balance`.

- [ ] **Step 3: Implementieren**

Signaturen wie unter „Interfaces“. Konstanten aus `SmartMode` importieren.

- [ ] **Step 4: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/zendure_ha/balance.py custom_components/zendure_ha/const.py tests/test_balance.py
git commit -m "Battery balance: fill levels, priority choice with hold, weekly full charge"
```

---

### Task 4: Prognose-Stufe, Vorsprung, Lastverlauf

**Files:**
- Modify: `custom_components/zendure_ha/balance.py`
- Modify: `custom_components/zendure_ha/const.py` (`SmartMode.FORECAST_INTERVAL = timedelta(minutes=15)`, `SmartMode.LOAD_WINDOW = timedelta(hours=24)`, `SmartMode.LOAD_BASE_QUANTILE = 0.2`)
- Test: `tests/test_balance.py`

**Interfaces:**
- Produces (in `balance.py`):
  - `class Stage(StrEnum)`: `CLOUDY = "cloudy"`, `MIXED = "mixed"`, `SUNNY = "sunny"`, `NONE = "none"`
  - `forecast_slots(watts: Any, now: datetime) -> list[float] | None` – `watts` ist das Attribut `watts` (Dict ISO-Zeit → W, Schlüssel = Beginn des 15-Minuten-Abschnitts, UTC; ohne Zeitzone als UTC lesen). `None`, wenn `watts` kein Dict ist oder kein lesbarer Eintrag auf das heutige Datum in Ortszeit von `now` fällt. Sonst die Werte > 0 der heutigen Abschnitte, die noch nicht vorbei sind (Beginn + 15 min > `now`), zeitlich sortiert; nicht lesbare Einträge überspringen.
  - `classify(slots: list[float], expected_load: float, base_load: float, free_primary: float, free_zendure: float, primary_power: float, zendure_power: float) -> tuple[Stage, float, float]` – liefert `(stage, r_kwh, p_w)`:
    - `r_kwh = Σ max(0, w − expected_load) · 0.25 / 1000`
    - `p_w = max(0, max(slots, default=0) − base_load)`
    - CLOUDY, wenn `r_kwh <= free_primary` und `p_w <= primary_power`; sonst SUNNY, wenn `p_w > zendure_power` oder `r_kwh >= free_primary + free_zendure`; sonst MIXED
  - `class StageFilter`: Attribut `value: Stage` (Start `NONE`), `update(self, stage: Stage) -> Stage` – `NONE` gilt sofort; aus `NONE` heraus gilt jede Stufe sofort; sonst gilt eine neue Stufe erst beim zweiten gleichen Ergebnis in Folge
  - `lead_for(stage: Stage, full_charge_due: bool, primary_lead: float) -> float` – fällig → 100; CLOUDY → 100; SUNNY → 0; MIXED, NONE → `primary_lead`
  - `class LoadTracker`: `__init__(self, window: timedelta)`, `add(self, time: datetime, watts: float) -> None` (verwirft Werte älter als `window`), `mean(self) -> float | None`, `base(self) -> float | None` (Wert an Position `int(LOAD_BASE_QUANTILE · (n − 1))` der sortierten Werte); beide `None` ohne Werte

- [ ] **Step 1: Failing tests schreiben**

```python
from custom_components.zendure_ha.balance import LoadTracker, Stage, StageFilter, classify, forecast_slots, lead_for

NOW = datetime(2026, 11, 15, 12, 10, tzinfo=BER)  # 11:10 UTC


def test_forecast_slots_keep_the_rest_of_today() -> None:
    watts = {
        "2026-11-15T10:45:00+00:00": 900,   # 11:45-12:00 local, over
        "2026-11-15T11:00:00+00:00": 1000,  # current slot
        "2026-11-15T11:15:00+00:00": 1200,
        "2026-11-15T15:30:00+00:00": 0,
        "2026-11-15T23:15:00+00:00": 500,   # 00:15 local on the 16th
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
```

Hinweis zu den Zahlen: R in `classify` auf drei Nachkommastellen runden (`round(r_kwh, 3)`), damit die Tupel-Vergleiche exakt sind.

- [ ] **Step 2: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_balance.py -q`
Expected: FAIL mit `ImportError` für `Stage`.

- [ ] **Step 3: Implementieren**

Signaturen wie unter „Interfaces“. Datum mit `dt_util`-freier Logik: `datetime.fromisoformat`, fehlende Zeitzone als `UTC`, Vergleich nach `astimezone(now.tzinfo)`.

- [ ] **Step 4: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/zendure_ha/balance.py custom_components/zendure_ha/const.py tests/test_balance.py
git commit -m "Battery balance: forecast stage, lead and house load window"
```

---

### Task 5: Manager berechnet Zuständigkeit (Optionen, Entitäten, `update_balance`)

**Files:**
- Modify: `custom_components/zendure_ha/const.py` (`CONF_PV_FORECAST = "pv_forecast"`, `CONF_PV_CAPACITY = "pv_capacity"`, `CONF_PV_POWER = "pv_power"`, `CONF_PV_MIN_SOC = "pv_min_soc"`; `SmartMode.PRIMARY_CAPACITY = 6.4`, `SmartMode.PRIMARY_POWER = 2750`, `SmartMode.PRIMARY_MIN_SOC = 5`, `SmartMode.PRIMARY_LEAD = 15`)
- Modify: `custom_components/zendure_ha/manager.py` (`__init__`, `loadDevices`, `update_pv_sensors`, `_async_update_data`, neue Methode `update_balance`)
- Modify: `custom_components/zendure_ha/config_flow.py` (`data_schema` und Options-Schema)
- Modify: `translations/en.json`, `translations/de.json`
- Test: `tests/test_manager_balance.py`

**Interfaces:**
- Consumes: alles aus Task 3 und 4.
- Produces (auf `ZendureManager`):
  - Attribute: `pv_forecast_entity: str | None`, `primary_capacity: float`, `primary_power: float`, `primary_min_soc: float` (gesetzt in `update_pv_sensors(data)`; leere oder ungültige Werte → Vorgaben aus `SmartMode`), `charge_hold: PriorityHold` (Vorgabe PRIMARY), `discharge_hold: PriorityHold` (Vorgabe ZENDURE), `stage_filter: StageFilter`, `load_tracker: LoadTracker`, `forecast_next: datetime | None`
  - Entitäten in `loadDevices`: Zahl `primary_lead` (`ZendureRestoreNumber`, %, 0–100, Vorgabe 15 wie bei `surplus_offset` gesetzt); Sensoren `forecast_stage`, `forecast_surplus` (kWh), `forecast_peak` (W, power), `primary_lead_active` (%), `primary_fill` (%), `zendure_fill` (%), `charge_priority`, `discharge_priority`; `primary_last_full_charge` als `ZendureRestoreSensor` mit Geräteklasse `timestamp`. Attributnamen: `self.primaryLead`, `self.forecastStage`, `self.forecastSurplus`, `self.forecastPeak`, `self.primaryLeadActive`, `self.primaryFill`, `self.zendureFill`, `self.chargePriority`, `self.dischargePriority`, `self.lastFullCharge`.
  - `update_balance(self, now: datetime) -> None` (`now` mit Zeitzone, aus `dt_util.now()`), Ablauf:
    1. Hauslast ohne Zendure = `pv_load − Σ homeInput + Σ homeOutput` über alle Geräte in `load_tracker` eintragen, wenn `pv_load` bekannt.
    2. Vollladung: `last = self.lastFullCharge.native_value`. Ist `last` `None` und die Entität schon in HA (`self.lastFullCharge.hass is not None`), `now` eintragen (erster Start gilt als erledigt). Ist die Entität noch nicht in HA: nicht fällig. Sonst `due = full_charge_due(last, now)`; bei `due` und `pv_soc >= SmartMode.PRIMARY_FULL_SOC` `now` eintragen, `due = False`.
    3. Füllstände: `fill_s = fill_level(pv_soc, primary_min_soc, pv_max_soc or 100)`, `fill_z = zendure_fill(packs)` aus den Geräten mit `online`: `Pack(electricLevel.asNumber, minSoc.asNumber, socSet.asNumber, kWh, -charge_limit)`.
    4. Wenn `forecast_next is None or now >= forecast_next`: `forecast_next = now + FORECAST_INTERVAL`; Stufe berechnen und `stage_filter.update(...)`. Stufe NONE, wenn Prognose-Entität nicht gesetzt oder ohne Zustand, `forecast_slots(...)` `None` liefert oder `pv_soc` unbekannt. Last: `load_tracker.mean()`/`.base()`, ohne Werte die aktuelle Hauslast für beides, ohne die Stufe NONE. `free_primary = max(0, max_s − pv_soc)/100 · primary_capacity`, `free_zendure = Σ max(0, max_soc − soc)/100 · kwh`, `zendure_power = Σ charge_power`.
    5. `lead = lead_for(stage_filter.value, due, primaryLead.asNumber)`
    6. `charge_hold.update(charge_choice(...) if beide Füllstände bekannt else None, now)`, ebenso `discharge_hold` mit `discharge_choice`.
    7. Alle Diagnose-Sensoren setzen (Füllstände gerundet auf ganze %, unbekannt → `None`).
  - Aufruf in `_async_update_data` nach der Geräteschleife: `self.update_balance(dt_util.now())` in `try/except Exception` mit `_LOGGER.error` und Traceback.
- Config-Flow: `data_schema` ergänzt um `vol.Optional(CONF_PV_FORECAST): selector.EntitySelector()`, `vol.Optional(CONF_PV_CAPACITY, default=6.4): vol.Coerce(float)`, `vol.Optional(CONF_PV_POWER, default=2750): vol.Coerce(int)`, `vol.Optional(CONF_PV_MIN_SOC, default=5): vol.Coerce(int)`; Options-Schema analog mit `default=data.get(...)`, Prognose als `str` wie die übrigen Entitäten dort.
- Übersetzungen (en / de), jeweils in `config.step.user.data`, `config.step.reconfigure.data` falls vorhanden, `options.step.init.data`:
  - `pv_forecast`: „Primary PV: Solar forecast sensor with attribute watts (optional)“ / „Primär-PV: Prognose-Sensor mit Attribut watts (optional)“
  - `pv_capacity`: „Primary PV: Battery capacity (kWh)“ / „Primär-PV: Akkukapazität (kWh)“
  - `pv_power`: „Primary PV: Battery charge/discharge power (W)“ / „Primär-PV: Lade-/Entladeleistung des Akkus (W)“
  - `pv_min_soc`: „Primary PV: Battery minimum SoC (%)“ / „Primär-PV: Minimaler Ladestand (%)“
  - `entity.number.primary_lead`: „Primary Battery Lead“ / „Vorsprung Primärakku“
  - `entity.sensor.forecast_stage` mit `state` cloudy/mixed/sunny/none: „Forecast Stage“ (Cloudy, Mixed, Sunny, None) / „Prognose-Stufe“ (Trüb, Gemischt, Sonnig, Keine)
  - `forecast_surplus`: „Forecast Surplus“ / „Prognose Überschuss“; `forecast_peak`: „Forecast Peak“ / „Prognose Spitze“; `primary_lead_active`: „Primary Battery Lead Active“ / „Vorsprung Primärakku aktiv“; `primary_fill`: „Primary Battery Fill“ / „Füllstand Primärakku“; `zendure_fill`: „Zendure Fill“ / „Füllstand Zendure“
  - `charge_priority`, `discharge_priority` mit `state` primary/zendure: „Charge Priority“ / „Laden zuerst“, „Discharge Priority“ / „Entladen zuerst“ (Primary / Zendure, Primärakku / Zendure)
  - `primary_last_full_charge`: „Primary Battery Last Full Charge“ / „Letzte Vollladung Primärakku“

- [ ] **Step 1: Failing tests schreiben**

Harness in `tests/test_manager_balance.py`: `manager = object.__new__(ZendureManager)`; Attribute aus „Produces“ setzen (`primary_capacity=6.4`, `primary_power=2750`, `primary_min_soc=5`, `pv_max_soc=None`, `pv_forecast_entity="sensor.pv_dach_energy_production_today"`, frische `PriorityHold`/`StageFilter`/`LoadTracker`, `forecast_next=None`); `watts` wird in `manager.forecast_watts` abgelegt, `manager.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _e: SimpleNamespace(attributes={"watts": manager.forecast_watts})))` liest es bei jedem Aufruf neu; Sensoren als Recorder mit `.last`; `primaryLead = SimpleNamespace(asNumber=15)`; `lastFullCharge` als Objekt mit `native_value`, `hass` (nicht `None`) und `update_value()`, das `native_value` setzt; Geräte als `SimpleNamespace(online=True, electricLevel=_v(soc), minSoc=_v(10), socSet=_v(90), kWh=8.16, charge_limit=-2400, homeInput=_v(0), homeOutput=_v(0))`. Hilfsfunktion `_watts(power, count)` erzeugt `count` Abschnitte ab `NOW` (Sonntag 2026-11-15 12:10 Berlin), `last_full` Vorgabe Samstag 2026-11-14 13:00.

```python
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


def test_house_load_excludes_the_zendure() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(800, 16), pv_load=2000)
    m.devices[0].homeInput = _v(1500)
    ZendureManager.update_balance(m, NOW)
    assert m.load_tracker.mean() == 500


def test_stage_is_recomputed_only_every_15_minutes() -> None:
    m = _harness(pv_soc=50, zendure_soc=40, watts=_watts(6000, 8), pv_load=500)
    ZendureManager.update_balance(m, NOW)
    m.forecast_watts = _watts(800, 16)  # harness reads this on states.get
    ZendureManager.update_balance(m, NOW + timedelta(minutes=5))
    assert m.forecastStage.last == "sunny"
```

Hinweis: In den Harness-Werten gilt `zendure_soc` für ein Gerät (Keller, min 10, max 90, 2400 W, also `zendure_power` 2400). Eine Last-Probe von 500 W ergibt Mittelwert und Grundlast 500. Der Sungrow-Füllstand bei `pv_soc=50` ist 47,4, der Zendure-Füllstand bei 40 ist 37,5. Bei V = 0 heißt das „Zendure zuerst“, bei V = 15 „Sungrow zuerst“.

- [ ] **Step 2: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_manager_balance.py -q`
Expected: FAIL mit `AttributeError: ... update_balance`.

- [ ] **Step 3: Implementieren**

Konstanten, Optionen, Entitäten, `update_balance` und Aufruf wie unter „Interfaces“. Die neuen Init-Attribute in `__init__` setzen.

- [ ] **Step 4: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q && python3 -c "import json; [json.load(open(f'custom_components/zendure_ha/translations/{l}.json')) for l in ('en','de')]"`
Expected: PASS, JSON lesbar.

- [ ] **Step 5: Commit**

```bash
git add -A custom_components tests
git commit -m "Battery balance: manager decides charge and discharge priority"
```

---

### Task 6: Laden – Zendure zuerst

**Files:**
- Modify: `custom_components/zendure_ha/manager.py` (`power_surplus`, Berechnung der Schrittweite)
- Test: `tests/test_surplus.py`

**Interfaces:**
- Consumes: `self.charge_hold.value: Priority` (Task 5)
- Produces: –

- [ ] **Step 1: Failing tests schreiben**

Import `from custom_components.zendure_ha.balance import Priority`. Harness in `tests/test_surplus.py` um Parameter `priority: Priority = Priority.PRIMARY` erweitern: `manager.charge_hold = SimpleNamespace(value=priority)`.

```python
async def test_zendure_first_takes_the_primary_charge_power() -> None:
    manager = _harness(charge=1000, dcpower=5000, load=1000, battery=-2000, soc=60, priority=Priority.ZENDURE)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 1000 + 2000 - 50


async def test_primary_first_ignores_the_primary_charge_power() -> None:
    manager = _harness(charge=1000, dcpower=5000, load=1000, battery=-2000, soc=60, priority=Priority.PRIMARY)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 1000 - 50 - 100


async def test_zendure_first_holds_inside_the_reserve() -> None:
    manager = _harness(charge=1000, dcpower=2000, load=1000, battery=-40, soc=60, priority=Priority.ZENDURE)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 1000


async def test_zendure_first_backs_off_when_the_primary_discharges() -> None:
    manager = _harness(charge=2000, dcpower=2000, load=2300, battery=300, soc=60, priority=Priority.ZENDURE)
    await _run(manager, p1=0)
    assert manager.surplus_charge == 1700
```

- [ ] **Step 2: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_surplus.py -q`
Expected: FAIL in `test_zendure_first_takes_the_primary_charge_power`.

- [ ] **Step 3: Implementieren**

In `power_surplus` nach `feed_in`: `charging = max(0, -int(self.pv_battery or 0)) if self.charge_hold.value == Priority.ZENDURE else 0`, `available = feed_in + charging`. In den drei Zweigen nach `elif primary_full` `available` statt `feed_in` verwenden; `overshoot` und `primary_full` bleiben unverändert.

- [ ] **Step 4: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/zendure_ha/manager.py tests/test_surplus.py
git commit -m "Solar surplus: the Zendure takes the primary charge power when it charges first"
```

---

### Task 7: Entladen – Sungrow deckt die Last

**Files:**
- Modify: `custom_components/zendure_ha/manager.py` (`powerChanged`, Zweig `ManagerMode.MATCHING_DISCHARGE`)
- Modify: `custom_components/zendure_ha/const.py` (`SmartMode.PRIMARY_POWER_MARGIN = 250`)
- Test: `tests/test_discharge_primary.py`

**Interfaces:**
- Consumes: `self.discharge_hold.value: Priority`, `self.primary_power: float` (Task 5)
- Produces: –

- [ ] **Step 1: Failing tests schreiben**

Import `from custom_components.zendure_ha.balance import Priority`. Harness um `priority: Priority = Priority.ZENDURE` erweitern: `manager.discharge_hold = SimpleNamespace(value=priority)`, `manager.primary_power = 2750`.

```python
async def test_primary_covers_a_small_load() -> None:
    manager = _harness(output=300, battery=400, priority=Priority.PRIMARY)
    assert await _run(manager, p1=0) == 0


async def test_zendure_covers_what_exceeds_the_primary_power() -> None:
    load, zendure = 3500, 0
    for _ in range(12):
        battery = min(2750, load - zendure)
        p1 = load - zendure - battery
        manager = _harness(output=zendure, battery=battery, priority=Priority.PRIMARY)
        zendure = await _run(manager, p1=p1)
    assert abs(zendure - (3500 - 2500)) < 20


async def test_primary_priority_without_battery_sensor_matches_the_meter() -> None:
    manager = _harness(output=300, battery=None, priority=Priority.PRIMARY)
    assert await _run(manager, p1=40) == 340
```

- [ ] **Step 2: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest tests/test_discharge_primary.py -q`
Expected: FAIL in `test_primary_covers_a_small_load`.

- [ ] **Step 3: Implementieren**

Im Zweig `MATCHING_DISCHARGE`, wenn `self.pv_battery is not None`: bei `Priority.PRIMARY` `setpoint += int((self.pv_battery - (self.primary_power - SmartMode.PRIMARY_POWER_MARGIN)) / 2)`, sonst wie bisher `setpoint += int(self.pv_battery / 2)`. Danach unverändert `await self.power_discharge(max(self.produced, setpoint))`. Kommentar: der Zendure übernimmt nur, was über die Leistung des Primärakkus hinausgeht. Abweichung von der Spec-Formulierung (Entscheidung im Plan): Statt erst bei Netzbezug an der 2750-W-Grenze einzuspringen, regelt der Zendure stetig auf „Sungrow höchstens 2500 W“. Das vermeidet Hin- und Herschalten an der Grenze.

- [ ] **Step 4: Tests laufen lassen**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/zendure_ha/manager.py custom_components/zendure_ha/const.py tests/test_discharge_primary.py
git commit -m "Smart discharging: the primary battery covers the load when it is fuller"
```

---

### Task 8: Pull Request

- [ ] **Step 1: Gesamte Suite**

Run: `../venv314/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 2: Push und PR**

```bash
git push
gh pr create --base master --head battery-balance --title "Balance charge between primary battery and Zendure" --body-file <(printf '%s\n' "Zendure first or primary first by fill level and forecast stage; primary covers the night load when it is fuller. Removes the primary charge limit (beta6) and the start SoC. Design: docs/superpowers/specs/2026-11-14-akku-ausgleich-design.md")
```

Merge, Release und Ausrollen nur nach ausdrücklicher Freigabe durch den Nutzer.

## Ausrollen (nach Freigabe, nicht Teil der Umsetzung)

1. `gh pr merge --merge`, `gh release create 1.4.4-beta7 --target master --generate-notes`.
2. HACS: `ha_manage_hacs` update_information und download, dann `ha_restart {"confirm": true}`.
3. Optionen der Zendure-Integration setzen: `pv_forecast = sensor.pv_dach_energy_production_today` (Kapazität, Leistung, Min-SoC bleiben bei den Vorgaben). Achtung: Die Optionen enthalten Passwörter, sie dürfen nicht ausgegeben werden.
4. Prüfen: Update-Entität zeigt beta7, `fuse_group = group2400`, `connection = zenSDK`, `surplus_offset = 50`, neue Sensoren liefern Werte, `number.zendure_manager_primary_lead = 15`.
5. Eine Woche beobachten wie in der Spec unter „Prüfung“: Füllstände, Einspeisung in Sonnenfenstern, Prognose gegen Ertrag, Wechsel der Zuständigkeit pro Tag.
6. Verwaiste Entitäten `number.zendure_manager_primary_limit` und `number.zendure_manager_surplus_start_soc` nur nach Rückfrage aus der Registry löschen.
