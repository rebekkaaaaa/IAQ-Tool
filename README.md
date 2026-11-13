# IAQ Assessment Tool · Bachelor-Thesis P6 · V14

**Grundlage:** P6-Projektauftrag «Entwicklung eines standardisierten IAQ-Nachweismodells für Büro- und Verwaltungsflächen», S. 7–9, sowie die reduzierte Tabelle `P6_Mindestdatensatz_IAQ_reduziert.xlsx`.

## Installation / Streamlit Community Cloud

Im **Hauptverzeichnis** des bestehenden GitHub-Repositories folgende Dateien hochladen oder ersetzen:

- `app.py` (ersetzen)
- `iaq_logic.py` (ersetzen)
- `iaq_report.py` (ersetzen; Reportingvorlage V10)
- `demo_data.py` (**neu**; synthetisches Beispielprojekt zum Testen)
- `bewertungsregeln.json` (mitgelieferte Regelmatrix ersetzen)
- `requirements.txt` (bei Bedarf mitgelieferte Version übernehmen)

Die Streamlit-Startdatei bleibt `app.py`. Die übrigen Dateien `MESSSTRATEGIEN_P6.md` und `test_iaq_logic.py` sind Dokumentation/Tests und nicht für den Livebetrieb erforderlich.

## Neu in V14 – Berichtsaufbau

| Seite | Inhalt |
|---|---|
| 1 | Zusammenfassung: Gebäude und Standort, Anzahl Gebäude und Räume, Zeitraum, Gesamtergebnis, Ergebnis je Fokusthema, effektive Messwerte (Min/Median/P95/Max), Handlungsbedarf |
| 2–4 | Allgemeine Angaben (fix): Projekt und Gebäude · Bewertungsgrundlagen · Messgeräte, Datenqualität, Quellen, Freigabe |
| ab 5 | Raumblätter, 2 Räume je Seite: Raumnummer, Einordnung, Kriterien erfüllt/nicht erfüllt, Kennwerte, Auffälligkeiten |

Seiten = 4 + ⌈Räume / 2⌉; höchstens 50 Räume (29 Seiten). Beispiel: 10 Räume = 9 Seiten.
Mehrere Gebäude: Seite 1 «Weitere untersuchte Gebäude», je Raum Gebäude wählen. Leere Vorlage mit Platzhaltern: Seite 5 der App.

## Neu in V13

- **Messart statt Nachweiszweck:** ein Dropdown mit den bekannten Begriffen Stichprobenmessung / Messkampagne / Langzeitmessung (Monitoring). Alte Projektdateien werden automatisch umgeschlüsselt.
- **Gerätematrix integriert** (`devices.json`, 27 Geräte des Messgeräteprojekts): Gerät je Raum wählen; Warnung, wenn das Gerät nicht CO₂, Temperatur und Feuchte misst; Genauigkeit im Raum hinterlegt; Werte ausserhalb des Gerätemessbereichs werden beim Import ausgeschlossen.
- **Automatischer Datenimport** (`iaq_import.py`): CSV/TXT/XLSX/JSON, Kopfzeile und Vorspann, Trennzeichen, Dezimalkomma, Datums-/Zeitformat, UTC → Lokalzeit, °F/K → °C, Vol.-% → ppm, Mittelung bei Intervallen < 1 min. Unklare Fälle (mehrdeutiges Datum, fehlende Einheit) müssen bestätigt werden. Jeder Import wird protokolliert. Details: `DATENIMPORT.md`.
- **IAQ-Standardformat** für externe Geräte, mit Vorlage zum Herunterladen.
- **Automatische Bereinigung:** mehrdeutiges Datum über die Zeitreihe entschieden, fehlende Einheiten über eindeutige Wertebereiche, Sortierung, Doppelzeilen, Fehlercodes; Hinweise zu Lücken, eingefrorenen Werten, Messbereichsende, Zeitumstellung.
- **Nutzung:** Belegungsplan mit wenigen Angaben (Tage, Von–Bis, Personen, Abwesenheiten) oder Präsenz-/Personenzählsensor (CSV). Die Nutzungszeit steuert die 10 %-Regel.

## Pflicht für die Grundbewertung

- Raum-ID/Bezeichnung
- Bewertungsprofil (SIA, SECO/ArGV 3, Minergie-ECO 2023.1, BT)
- Heiz- oder Kühlperiode (Betriebsfall)
- Lüftungsart; bei Hybrid aktueller Betriebsmodus
- Messart: Stichprobenmessung, Messkampagne oder Langzeitmessung (Monitoring)
- Pro Messzeitpunkt **Datum/Uhrzeit, CO₂ [ppm], Lufttemperatur [°C], relative Feuchte [%]**

Ein Messzeitpunkt ist nur vollständig, wenn alle drei Sensorwerte vorhanden, numerisch, plausibel und mit demselben Zeitstempel verknüpft sind. Doppelte Parameterwerte zum selben Zeitpunkt werden ausgeschlossen; keine stillschweigende Interpolation.

## Bedingt erforderlich für belastbarere Aussagen

Für Messreihen: Beginn, Ende, Sollintervall, Datenlücken. Für nutzungszeitbezogene Aussagen: tatsächlich belegte Zeiten / Protokoll. Für einen repräsentativen Mehrraumnachweis: Raumauswahl und technische Randbedingungen. Für SIA-IDA-2: Aussen-CO₂ (sonst ausgewiesene 400-ppm-Annahme). Für die Übertragbarkeit von Messkampagnen auf längere Zeiträume: gesonderte Prüfung der Repräsentativität. Raumfläche, zusätzliche Raumdaten etc. sind nicht für jede **Grundbewertung** Pflicht.

## Bewertungslogik und Grenzen

- **SECO/ArGV 3** (Wegleitung Art. 16, Stand Aug. 2020): CO₂ < 1'000 ppm (Abb. 316-4), Lufttemperatur Winter 21–23 °C / Sommer 23–26 °C (Abb. 316-1), relative Feuchte **Winter 30–50 % / Sommer 40–60 %** (Abb. 316-2, Schweizer Mittelland) sowie Schwülegrenze ab 24 °C < 60 %, ab 26 °C < 55 %, ab 28 °C < 50 % (S. 316-3). V8 verwendete 30–60 % (physiologischer Optimalbereich laut Fliesstext); V9 folgt den periodenspezifischen Vorgaben der Abbildung. Ausschliesslich **Orientierungs-Screening**, keine Feststellung gesetzlicher Nichtkonformität.
- **BT:** eigenes Orientierungsscreening mit denselben drei Zielbereichen; Quellen/Szenarien aus `bewertungsregeln.json`. Der ergänzende SIA-CO₂-Vergleich erscheint getrennt und ist kein zusätzliches BT-Ziel.
- **SIA 382/1:2025:** CO₂-IDA-2-Vergleich nur bei mechanischer Lüftung bzw. entsprechendem Hybridmodus, innen ≤ aussen + 800 ppm; ohne Aussenmesswert explizite Annahme 400 ppm. Temperatur der Sensoren ist Lufttemperatur, **nicht operative Temperatur**, deshalb keine automatische IEQ-II-Temperaturkonformität.
- **Minergie-ECO 2023.1:** keine eigenständigen allgemeinen Betriebsgrenzwerte für CO₂, Temperatur und r. F. Bei mechanischer Lüftung erscheint der SIA-CO₂-Klassenvergleich als **separat gekennzeichneter Ergänzungswert**; aus den drei Kernparametern wird **keine ECO-Zertifizierung** abgeleitet.

Das Screening zählt **vollständige Messzeitpunkte** ausserhalb von Referenzwerten – für alle Messpunkte und, falls strukturiert erfasst (Wochentage + Von/Bis), separat für die **Nutzungszeit**. Keine Zeitgewichtung, keine rechtliche oder Labelkonformität.

## Neu in V9

- **Nutzungszeit strukturiert** (Wochentage, Von/Bis) → Screening «Nur Nutzungszeit».
- **CO₂-Klassen nach SECO Abb. 316-4** (< 1'000 · 1'000–1'400 · > 1'400–2'000 · ≥ 2'000 ppm) als Anteil der Messpunkte.
- **Einordnung je Raum** gemäss Projektauftrag S. 9, ohne zusätzliche Toleranzannahmen: *Nicht bewertbar* (Pflichtlücke) · *Weiterführende Abklärung empfohlen* (CO₂ ≥ 2'000 ppm, SECO Abb. 316-4) · *Abweichungen festgestellt* (≥ 1 Messpunkt ausserhalb) · *Referenzwerte im Messzeitraum eingehalten*.
- **Kennwerte**: Min, P5, Median, Mittel, P95, Max (Perzentile Hyndman & Fan 1996, Typ 7); Zeitabdeckung, Median-Intervall, grösste Lücke.
- **Reportingvorlage** (`iaq_report.py`): druckfertiges A4-HTML, im Browser «Als PDF drucken».

## Reportingvorlage V10 – Umfang wächst nicht proportional

| Räume | Seiten | Aufbau |
|---|---|---|
| 1 | 2 | S. 1 Übersicht (Nachweisrahmen, Einordnung, Kennzahlen, Kennwerte, CO₂-/IDA-Klassen, Referenzwerte, Aussagegrenze) · S. 2 Detail (Zeitverläufe, Screening, Raumsteckbrief, Datenqualität, Regeln, Quellen, Freigabe) |
| 2–3 | 4 | Übersicht · Raummatrix + ESG-Kennzahlen · Raumprofile (3 je Seite) · Methodik/Quellen/Freigabe |
| 4–6 | 5 | dito |
| 7–9 | 6 | dito |
| 10–30 | 7 | max. 12 Raumprofile, priorisiert nach Einordnung und CO₂-P95; übrige Räume nur in der Raummatrix |
| 31–60 / 61–90 | 8 / 9 | Raummatrix über 2 bzw. 3 Seiten |

Seite 1 ist immer die standardisierte Übersicht. Bericht im Browser öffnen → «Als PDF drucken (A4)».

## Neu in V12

- Bericht (V14): Schrift ≥ 12 pt (ausser Quellen und Seitenfuss); Seite 1 Zusammenfassung, Seiten 2–4 allgemeine Angaben, danach 2 Räume je Seite, max. 50 Räume.
- Minergie-ECO-Werte im Vorgabenkatalog v2023.1 verifiziert (inkl. Passivmessung).
- Messpositionierung nach Bacher (2025): Messhöhe, Anzahl Geräte je Fläche, Positionscheck als Hinweise.
- Kompatibilität: kein veralteter Streamlit-Parameter mehr (`use_container_width` entfernt).

## IAQ-Nachweismodell nach Fokusthemen (seit V11)

| Fokusthema | Kriterium | Quelle |
|---|---|---|
| Luftqualität | Zeitanteil über IDA 2 (ΔCO₂ > 800 ppm) ≤ 10 %, nie IDA 4; Abklärung bei CO₂ ≥ 2'000 ppm | SIA 382/1:2025 Ziff. 2.2.5.4/2.2.5.6, Tab. 18; SECO Abb. 316-4 |
| Thermischer Komfort | Heizperiode 21–23 °C, Kühlperiode 23–26 °C, keine Zeittoleranz | SECO Abb. 316-1 |
| Raumluftfeuchte | < 30 % r. F. bei 21 °C (−1 %/100 m über 800 m ü. M.) bzw. > 15,2 g/m³ je ≤ 10 % der Nutzungszeit | SIA 180:2014 Ziff. 3.5.1.3/3.5.1.4, Anhang A.1 |
| Datenbasis | Jahresbezug = Messung über ein Nutzungsjahr; sonst Indikation | Bezug der 10 %-Regel («jährliche Nutzungszeit») |

- Alle Lüftungsarten: IDA-Klassierung gemäss SIA 382/1:2025 Tab. 18, Fussnote 3.
- Zeitanteile zeitgewichtet (Gewicht = Abstand zum nächsten Punkt, max. ein Messintervall; keine Interpolation).
- Volumenbezogene Feuchte ν = φ · p_sat(θ) / (R_v · T), p_sat nach SIA 180 Anhang A.1, R_v = 461,5 J/(kg·K); geprüft gegen Tabelle A.1.
- **Neu Pflicht für die Feuchtebewertung:** Höhenlage des Gebäudes (Seite 1 · Objektangaben).
- Profilvergleich (SECO/SIA/ECO/BT) bleibt als Messpunkt-Screening erhalten.
- Bericht V11: Seite 1 «Ergebnis auf einen Blick» mit Fokusthemen, Handlungsbedarf und Räume × Themen; Seite 2 Raummatrix + ESG-Kennzahlen nach Fokusthema.

Vollständige Quellenprüfung aller Zahlen: `QUELLENPRUEFUNG.md`.

## Datenimport

Empfohlenes CSV-Breitformat (eine Zeile = ein Messzeitpunkt):

```csv
timestamp,co2,temp,rh
2026-10-30 10:30,850,22.0,45
2026-10-30 10:35,925,22.3,46
```

Alternativ bleibt der V7-Import im Langformat möglich (`timestamp,parameter,value,unit`). Ein früher exportiertes V6/V7-Projekt kann über die **JSON-Importfunktion** übernommen werden. Früher freie Nachweiszweck-Texte müssen einmalig einem der strukturierten P6-Nachweiszwecke zugeordnet werden.

## Test

```bash
python -m unittest -v test_iaq_logic.py
```

Die Fachlogik wurde mit automatisierten Tests geprüft. Ein vollständiger Deployment- und Browser-Laufzeittest auf Streamlit Community Cloud ist damit **nicht** ersetzt.
