# Akku-Ausgleich Sungrow und Zendure (Winterbetrieb)

Stand: 2026-11-15, zur Freigabe. Betrifft `custom_components/zendure_ha/manager.py` (Modi `solar_surplus` und `smart_discharging`).

## Ziel und Warum

Im Winter kommt die Sonne oft nur für ein paar Stunden. Ein solches Sonnenfenster bringt bis etwa 7 kW Überschuss. Damit er ganz in die Akkus geht, müssen alle drei Akkus zu dem Zeitpunkt Platz haben: Sungrow etwa 2,75 kW, Keller 2,4 kW, Wohnzimmer etwa 2,1 kW.

Der Sungrow-Akku ist DC-gekoppelt und verliert am wenigsten. Bei schwacher Sonne soll er deshalb bevorzugt laden. Er soll aber nicht allein volllaufen, während die Zendures leer sind, sonst fehlen bei einem späteren Sonnenfenster 2,75 kW Ladeleistung.

Beim Entladen liefert der vollste Akku. Bei kleiner Last soll möglichst nur ein Gerät laufen. Die Ladestände sollen sich so angleichen, dass alle abends etwa gleich voll sind.

Abwägung (Annahme, nicht gemessen): Der Umweg über einen Zendure kostet etwa 6–10 % mehr Verlust, also 2–3 ct pro kWh. Eine kWh, die mangels Platz eingespeist wird, kostet etwa 20 ct (30 ct Bezug, 8 ct Vergütung). Pro kWh ist fehlender Platz also teurer. Trübe Tage sind im Winter aber häufiger, und gerade an ihnen setzt die Prognose zu viel Sonne an (siehe Güte der Prognose). Deshalb bekommt die Prognose keinen Aufschlag (Nutzer, 2026-11-15).

## Nicht-Ziele

- Sommerbetrieb, also die Einspeisegrenze von 60 % nutzen, um mittags Spitzen in die Akkus zu laden. Das kommt später.
- Schreiben in den Sungrow. Der Wechselrichter übernimmt den Max-SoC aus Register 13057 nicht. Die Ursache ist offen und wird hier nicht gelöst.
- Weitere Prognosedienste wie Solcast.

## Was nicht passieren darf

- Bei gleichem Wetter mehr Netzbezug oder mehr Einspeisung als mit 1.4.4-beta6.
- Ein Akku lädt aus einem anderen, zum Beispiel ein Zendure nachts aus dem Sungrow.
- Die Zuständigkeit springt im Minutentakt zwischen Sungrow und Zendure hin und her.

## Fakten und Randbedingungen

| Akku | Kapazität | Lade-/Entladeleistung | Min | Max |
|---|---|---|---|---|
| Sungrow (DC) | 6,4 kWh | ca. 2,75 kW (BMS, gemessen) | 5 % | 100 % (`sensor.battery_max_soc`) |
| Keller (Zendure) | 8,16 kWh | 2,4 kW | 10 % | 90 % werktags, 100 % am Wochenende (HA-Automation setzt `soc_set`) |
| Wohnzimmer (Zendure) | 5,28 kWh | ca. 2,1 kW | 10 % | 100 % |

- **Wie der Manager steuert:** Er stellt nur die Zendures. Der Sungrow regelt selbst auf Netz 0. Was die Zendures aus dem Hausnetz laden, fehlt dem Sungrow-Akku. Was sie abgeben, muss der Sungrow nicht liefern. Damit lässt sich die Aufteilung ohne Schreibzugriff auf den Sungrow steuern.
- **Verteilung innerhalb der Zendures:** Die vorhandene Logik verteilt schon nach Ladestand. Beim Laden bekommt der leerere mehr, bei kleiner Leistung lädt nur einer. Beim Entladen liefert der vollere, ein zweites Gerät kommt ab etwa 1200 W dazu und geht unter etwa 1000 W wieder aus. Das bleibt so.
- **Prognose:** Open-Meteo Solar Forecast, Entität `sensor.pv_dach_energy_production_today`. Das Attribut `watts` ist ein Dict mit ISO-Zeit in UTC als Schlüssel und der Leistung in W als Wert, in 15-Minuten-Schritten. Forecast.Solar liefert dasselbe Format. Eingestellt: 45°, Azimut 200° (Süd-Südwest), 11,5 kWp, Wirkungsgrad 0,86.
- **Güte der Prognose** (Messdaten 15.10.–14.11.): Der Ertrag des restlichen Tages lag im Mittel etwa 5 kWh daneben, rund 25 %. An 8 von 31 Tagen lag sie grob daneben. Der Fehler hat eine Richtung: An den 16 Tagen mit weniger als 21 kWh Ertrag lag die Tagesprognose im Mittel 44 % zu hoch, an 13 davon zu hoch. An den 15 Tagen mit mehr lag sie 12 % zu niedrig. Über alle Tage gleicht sich das aus. Brauchbar ist sie nur als grobe Stufe, nicht als Feinsteuerung. Den Ertrag des Morgens zur Korrektur heranzuziehen machte sie schlechter, das wird also nicht gemacht.
- **Sungrow-Sensoren im Manager:** `pv_battery` (`sensor.battery_power`, positiv heißt Entladen), `pv_soc`, `pv_load`, `pv_dcpower`, `pv_meter`, `pv_max_soc`. `pv_max_soc` ist auf halk mit `number.battery_max_soc` belegt.
- **Tagesablauf (HA-Automationen):** Um 10:00 schaltet „Zendure laden“ auf `solar_surplus`. Eine Stunde vor Sonnenuntergang schaltet „Zendure entladen“ auf `smart_discharging`. Zwischen Sonnenaufgang und 10:00 lädt deshalb nur der Sungrow. Daran ändert dieses Design nichts; ob „Zendure laden“ früher schalten soll, ist eine eigene Frage.

## Ansätze

1. **Feste Regel nach Füllstand mit festem Vorsprung für den Sungrow.** Einfach und ohne externen Dienst. An klar trüben Tagen verschenkt sie etwas Wirkungsgrad, an sehr sonnigen Tagen hält sie etwas zu wenig Platz frei.
2. **Nur Prognose.** Zu unzuverlässig, siehe oben.
3. **Max-SoC des Sungrow begrenzen (beta6).** Der Wechselrichter übernimmt den Wert nicht, und eine feste Grenze ist zu starr.

Gewählt (Nutzer, 2026-11-14): Ansatz 1. Die Prognose setzt dabei den Vorsprung in drei groben Stufen. Fehlt die Prognose, gilt der feste Vorsprung.

## Design

### Füllstand

Für jeden Akku gilt Füllstand = (SoC − Min) / (Max − Min), auf 0–100 % begrenzt. Für die Zendures zählt ein gemeinsamer Wert, energiegewichtet über die Geräte, die online sind. Das ist eine Entscheidung von mir: So zählt der Keller werktags bei 90 % als voll, und „gleicher Prozentsatz“ heißt gleich viel Platz im Verhältnis zur Größe.

### Laden (Modus `solar_surplus`)

Der **Vorsprung V** gibt an, wie viele Punkte Füllstand der Sungrow vor den Zendures liegen darf.

| Prognose-Stufe | V |
|---|---|
| trüb | 100, der Sungrow lädt allein bis voll (heutiges Verhalten) |
| gemischt, oder keine bzw. veraltete Prognose | Wert von `number.zendure_manager_primary_lead`, Vorgabe 15 |
| sonnig | 0, gleichmäßig laden |
| Vollladung fällig (siehe unten) | 100, gilt auch an sonnigen Tagen |

**Wöchentliche Vollladung** (Nutzer, 2026-11-15: „Am Wochenende 1x mit nachholen“): Ab Samstag 0:00 ist die Vollladung fällig. Sobald der Sungrow einmal ≥ 99 % erreicht, ist sie für diese Woche erledigt, auch mitten am Samstag; der Sonntag hat dann keinen Vorrang mehr. Erreicht er die 99 % am Wochenende nicht, bleibt sie an den folgenden Tagen fällig, bis er einmal voll war. Der nächste Samstag macht sie wieder fällig. Annahme: „nachholen“ heißt auch über den Sonntag hinaus. Unterschied zur bisherigen Logik: Bisher galt der ganze Samstag als fällig, auch nach Erreichen der 99 %. Entscheidung von mir: Der Merker überlebt einen Neustart von Home Assistant, sonst fällt eine nachzuholende Vollladung mit jedem Neustart aus.

**Wer lädt zuerst:**
- Füllstand Sungrow ≤ Füllstand Zendure + V − 5: **Sungrow zuerst**, wie bisher. Der Zendure nimmt nur die Einspeisung über der Reserve (`surplus_offset`).
- Füllstand Sungrow ≥ Füllstand Zendure + V: **Zendure zuerst**. Der Zendure nimmt zusätzlich die Leistung, mit der der Sungrow-Akku gerade lädt (`-pv_battery`, wenn negativ). Die Rückmeldung bleibt wie bisher: Entlädt der Sungrow oder kommt Strom aus dem Netz, nimmt der Zendure zurück. Was über die Zendure-Ladeleistung hinausgeht, lädt automatisch weiter in den Sungrow.
- Dazwischen gilt die letzte Wahl weiter. Die Schwelle zum Zurückwechseln liegt 5 Punkte unter der zum Wechsel. Eine Wahl gilt mindestens 15 Minuten. Entscheidung von mir: Mit 3 Punkten und ohne Haltezeit würde die Zuständigkeit in einem Sonnenfenster etwa alle 4–8 Minuten wechseln.

**Prognose-Stufe**, neu berechnet alle 15 Minuten. Eine neue Stufe gilt erst, wenn zwei Berechnungen hintereinander sie ergeben, also nach 30 Minuten. Entscheidung von mir, damit V nahe einer Schwelle nicht zwischen 100, 15 und 0 springt.
- **R:** Summe über die restlichen 15-Minuten-Werte mit Prognose > 0 von max(0, Prognose-Leistung − erwarteter Hausverbrauch) × 0,25 h. Abgezogen wird nur in den Stunden, in denen die Anlage erzeugt, denn nur dort entsteht Überschuss. Die Prognose geht ohne Aufschlag ein (Nutzer, 2026-11-15).
- **P:** höchste Prognose-Leistung minus Grundlast, über die restlichen 15-Minuten-Werte.
- **Freier Platz:** frei_S = (Max − SoC) × 6,4 kWh beim Sungrow, frei_Z = Summe von (soc_set − SoC) × kWh über die Zendures, die online sind.
- **trüb:** R ≤ frei_S und P ≤ Sungrow-Ladeleistung.
- **sonnig:** P > Ladeleistung aller Zendures, die online sind, oder R ≥ frei_S + frei_Z.
- **gemischt:** alles andere.
- **Hausverbrauch und Grundlast:** gleitender Mittelwert der Hauslast der letzten 24 Stunden, ohne die Zendures (`pv_load` minus Zendure-Netzbezug plus Zendure-Abgabe). Der Mittelwert dient als erwarteter Verbrauch, die Grundlast als Abzug bei P. Die genaue Formel entscheidet der Builder.

### Entladen (nur Modus `smart_discharging`)

- Füllstand Zendure ≥ Füllstand Sungrow + 5: **Zendure deckt die Last**, wie heute einschließlich des Ausgleichs `pv_battery / 2`.
- Füllstand Sungrow ≥ Füllstand Zendure + 5: **Sungrow deckt die Last**, der Zendure gibt 0 ab. Ausnahme: Kann der Sungrow die Last nicht allein decken (Sungrow-Entladung nahe ihrer Grenze von 2,75 kW und trotzdem Netzbezug), deckt der Zendure den Netzbezug.
- Dazwischen gilt die letzte Wahl weiter. Eine Wahl gilt mindestens 15 Minuten.
- In `solar_surplus` bleibt das Entladen wie heute: Der Zendure entlädt nur bei Netzbezug über 50 W, frühestens 2 Minuten nach dem letzten Laden. Entscheidung von mir: Tagsüber würde sonst jede Wolkenlücke zwischen Laden und Entladen wechseln, und nach jedem Wechsel lädt der Zendure 60 Sekunden nicht.
- Innerhalb der Zendures bleibt die Verteilung unverändert.

### Entfällt

Die Primär-Ladegrenze aus beta6 fällt weg: `update_primary_limit`, `number.zendure_manager_primary_limit`, `PRIMARY_WRITE_INTERVAL` und die Sättigungslogik, die die Grenze aufhebt. `pv_max_soc` bleibt als Lesewert für das Maximum des Sungrow.

`surplus_start_soc` (`number.zendure_manager_surplus_start_soc`, auf halk 0) fällt ebenfalls weg. Entscheidung von mir: V ersetzt den Wert. Bliebe er über 0 stehen, würde er „Zendure zuerst“ blockieren.

### Neue Einstellungen

- **Config-Optionen:**
  - Prognose-Entität `pv_forecast`, ein Sensor mit Attribut `watts`.
  - Sungrow-Kapazität in kWh, Vorgabe 6,4.
  - Sungrow-Lade-/Entladeleistung in W, Vorgabe 2750.
  - Sungrow-Min-SoC in %, Vorgabe 5.
- **Zahl im Manager:** `primary_lead`, Vorgabe 15.

### Sichtbar machen

Sensoren am Manager-Gerät:
- Prognose-Stufe (trüb/gemischt/sonnig/keine)
- R in kWh, P in W
- Vorsprung V
- Füllstand Sungrow und Füllstand Zendure
- wer gerade zuerst lädt bzw. entlädt (Sungrow/Zendure)

### Aus der verlorenen beta7 neu einbauen

Back-off in `power_surplus`: Die Basis ist `max(surplus_seen_input, devices_input())` statt nur `surplus_seen_input`. Am 13.11. um 13:40 meldete ein Gerät noch 53 W, zog aber schon 1411 W, und das Ziel fiel auf 0. Dazu gehört ein Test für genau diesen Fall.

## Prüfung

- **Szenario-Tests:**
  - Stufenbestimmung trüb/gemischt/sonnig, ohne Prognose und mit veralteter Prognose
  - Laden: Sungrow zuerst, Zendure zuerst, Hysterese
  - Vollladung: am Samstag erreicht, am Sonntag nachgeholt, am Montag nachgeholt, nach Neustart weiter fällig
  - Entladen: Auswahl der Quelle, Hysterese, Ausnahme bei hoher Last
  - Geräte offline, SoC unbekannt
- **Nach dem Ausrollen eine Woche beobachten:**
  - Verlauf der Füllstände
  - Einspeisung während der Sonnenfenster
  - Prognose gegen Ertrag, dabei den Wirkungsgrad 0,86 prüfen
  - Wechsel der Zuständigkeit pro Tag

## Dem Builder überlassen

- Namen der Entitäten
- Aktualisierungsrhythmus außerhalb der 15 Minuten
- Formel für Hausverbrauch und Grundlast
- Umgang mit fehlenden Werten, solange in jedem Zweifelsfall das heutige Verhalten gilt (Sungrow zuerst, Zendure deckt die Last)
- Aufteilung in Commits
