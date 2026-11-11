# Datenimport · IAQ-Tool V13

## Ziel
Alle Messdaten werden einheitlich eingelesen, damit Räume, Geräte und Gebäude vergleichbar sind:

| Grösse | Einheit im Tool | automatische Umrechnung |
|---|---|---|
| Zeit | Lokalzeit Schweiz (Europe/Zurich), Minutenraster | UTC / ISO mit Zeitzone / Unix-Zeit / Excel-Datum → Lokalzeit |
| CO₂ | ppm | Vol.-% × 10 000 |
| Lufttemperatur | °C | °F, K |
| Relative Feuchte | % | – (Anteil 0–1 wird nicht umgerechnet) |

Nicht umgerechnet wird, was eine Annahme bräuchte (z. B. CO₂ in mg/m³: Druck und Temperatur nötig).

## Ablauf im Tool
1. Seite 2: Messgerät aus der Gerätematrix wählen (oder «Externes Gerät»).
2. Seite 3: Gerätedatei hochladen. Das Tool erkennt Dateityp, Vorspann, Kopfzeile, Trennzeichen, Dezimalkomma, Spalten, Datumsformat, Zeitbasis und Einheiten.
3. Zuordnung kontrollieren. **Bestätigung nötig**, wenn das Datum mehrdeutig ist (03/04/2026) oder die Datei keine Einheit nennt.
4. Vorschau, Ausschlüsse und Umrechnungen prüfen → «Vereinheitlichte Daten übernehmen». Das Importprotokoll wird im Projekt gespeichert.

**Bereinigung (ohne Schätzung):** Werte ausserhalb des Gerätemessbereichs (Gerätematrix) und ausserhalb des technischen Plausibilitätsbereichs werden ausgeschlossen und gezählt; leere Felder bleiben leer; keine Interpolation. Bei Intervallen < 1 min muss ein Mittelungsintervall gewählt werden (1/5/10/15 min).

## IAQ-Standardformat (Vorgabe für externe Geräte)

| Spalte | Inhalt |
|---|---|
| `timestamp` | Datum und Uhrzeit, ISO 8601: JJJJ-MM-TT HH:MM oder JJJJ-MM-TT HH:MM:SS. Lokalzeit Schweiz, oder mit Zeitzonenangabe (z. B. 2026-11-02T08:00:00+01:00 bzw. …Z für UTC). |
| `co2_ppm` | CO₂-Konzentration in ppm (Zahl, ohne Einheit im Feld). |
| `temp_c` | Lufttemperatur in °C. |
| `rh_pct` | Relative Luftfeuchte in % (0–100, nicht als Anteil 0–1). |

- Datei: CSV (UTF-8), Trennzeichen Semikolon oder Komma; alternativ XLSX (erstes Tabellenblatt).
- Eine Kopfzeile mit genau diesen Spaltennamen, danach eine Zeile pro Zeitpunkt.
- Alle drei Messgrössen eines Zeitpunkts in derselben Zeile (gleicher Zeitstempel).
- Dezimalpunkt oder Dezimalkomma; keine Tausendertrennzeichen.
- Fehlende Werte leer lassen (nicht 0 eintragen); keine interpolierten Werte.
- Rohdaten des Geräts, unverändert (keine gleitenden Mittelwerte).
- Aufzeichnungsintervall mind. 1 Minute; kürzere Intervalle werden beim Import gemittelt.

Beispiel:
```
timestamp;co2_ppm;temp_c;rh_pct
2026-11-02 08:00;612;21,4;38,5
2026-11-02 08:05;655;21,5;38,9
```

## Geräte der Gerätematrix

Die Gerätematrix nennt nur das Dateiformat (CSV, XLSX, JSON), **nicht den Spaltenaufbau**. Deshalb arbeitet der Import heute mit automatischer Erkennung. Sobald eine Original-Exportdatei vorliegt, wird ein geprüftes Profil in `import_profiles.json` hinterlegt (dann ohne manuelle Kontrolle).

| Nr. | Gerät | Pflichtgrössen | Datenweg | Profilstatus |
|---|---|---|---|---|
| 1.1 | Airflow 7525 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 1.2 | Testo 440 + 0632 1551 | alle drei | Export xlsx | Beispieldatei fehlt |
| 1.3 | Driesen+Kern 7545 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 1.4 | Rotronic CP 11 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 2.1 | Lascar EL-IOT-CO2 | alle drei | Export CSV | Beispieldatei fehlt |
| 2.2 | Chauvin Arnoux C.A 1510 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 2.3 | IQAir AirVisual Pro | alle drei | Export CSV | Beispieldatei fehlt |
| 2.4 | Trotec BZ30 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 3.1 | Driesen+Kern DKCO2-Light | alle drei | Export CSV | Beispieldatei fehlt |
| 3.2 | Wabool 6011 | fehlt: T, r. F. | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 7.1 | Rototherm AM60 | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 7.2 | Aranet TDSPC0H3 | alle drei | Export CSV | Beispieldatei fehlt |
| 7.3 | Rotronic CO2-Display | alle drei | Datenlogger, Exportformat k. A. | Beispieldatei fehlt |
| 7.4 | Dreson Typ DRE1300 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 7.5 | Driesen+Kern DKCO2-Light-LCD | alle drei | Export CSV | Beispieldatei fehlt |
| 4.1 | Belimo P-22RTH-1U00A-2 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 4.2 | Sauter FMS 117/197 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 4.3 | Siemens QNA2700D.BA2 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 4.4 | Avelon Wisely CarbonSense | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 5.1 | Belimo P-22RTM-1U00D-2 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 5.2 | Testo 162 IAQ | alle drei | Export CSV/PDF | Beispieldatei fehlt |
| 5.3 | S+S Regeltechnik RFTM-LQ-CO2-W | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 6.1 | Belimo 22DTM-11 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 6.2 | Siemens QPM2160 | alle drei | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 6.3 | Sauter EGQ 212 | fehlt: r. F. | kein Logger: Trendexport Gebäudeautomation | Beispieldatei fehlt |
| 9.1 | airQ basic, pro, radon | alle drei | Export JSON | Beispieldatei fehlt |
| 9.2 | Aranet Radon Plus HOME | fehlt: CO₂ | Export CSV | Beispieldatei fehlt |

## Nutzung / Belegung

| Quelle | Datei | Regel |
|---|---|---|
| Zeitplan | – (Seite 2) | Wochentage + Von/Bis |
| Raumkalender | `.ics` (z. B. Outlook-Export) | gebuchte Termine; Serien DAILY/WEEKLY inkl. Ausnahmen; ganztägige und abgesagte Termine zählen nicht |
| Präsenz-/Personenzählsensor | CSV/XLSX: Zeitstempel + Präsenz (0/1, belegt/frei) oder Personenzahl | belegt = Wert > 0; gilt bis zum nächsten Zeitpunkt (max. 2 × Medianintervall) |

Die Nutzungszeit bestimmt, welche Messpunkte in die 10 %-Regel eingehen. CO₂ wird bewusst **nicht** zur Belegungserkennung verwendet (sonst würde die Messgrösse ihre eigene Bewertungsbasis bestimmen).
