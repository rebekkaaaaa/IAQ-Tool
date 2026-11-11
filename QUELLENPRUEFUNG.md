# Quellenprüfung aller Zahlen im Tool (Stand V12, 11.11.2026)

| Wert im Tool | Quelle und Fundstelle | Status |
|---|---|---|
| CO₂ < 1'000 ppm gut; ≥ 2'000 ppm hygienisch inakzeptabel | SECO Wegleitung ArGV 3 Art. 16 (Aug. 2020), Abb. 316-4, S. 316-5 | geprüft |
| Lufttemperatur 21–23 °C / 23–26 °C | SECO Abb. 316-1 | geprüft |
| r. F. Winter 30–50 %, Sommer 40–60 % | SECO Abb. 316-2 | geprüft |
| Schwülegrenze 24 °C < 60 %, 26 °C < 55 %, 28 °C < 50 % | SECO S. 316-3 | geprüft |
| IDA-Grenzen ΔCO₂ 550 / 800 / 1'350 ppm | SIA 382/1:2025 Tab. 18 | geprüft |
| Aussenluft 400 ppm (Bezugswert) | SIA 382/1:2025 Tab. 18, Fn. 2 | geprüft |
| IDA für alle Lüftungsarten | SIA 382/1:2025 Tab. 18, Fn. 3 | geprüft |
| 10 % der jährlichen Nutzungszeit, max. eine IDA-Kategorie tiefer | SIA 382/1:2025 Ziff. 2.2.5.6 | geprüft |
| r. F. < 30 % max. 10 %; −1 %/100 m über 800 m ü. M.; Bezug 21 °C | SIA 180:2014 Ziff. 3.5.1.3, Fn. 2 | geprüft |
| > 15,2 g/m³ max. 10 % | SIA 180:2014 Ziff. 3.5.1.4 | geprüft |
| p_sat-Formel | SIA 180:2014 Anhang A.1 (SN EN ISO 13788) | geprüft, Tabelle reproduziert |
| R_v = 461,5 J/(kg·K) | physikalische Konstante | numerisch bestätigt; Literaturzitat ergänzen |
| Perzentile Typ 7 | Hyndman & Fan (1996) | geprüft |
| Plausibilitätsgrenzen CO₂ 250–10'000 ppm, T −10–50 °C, r. F. 0–100 % | Projektfestlegung | **ohne Quelle** – mit Experte/Sensordatenblatt belegen |
| Messdauer/Intervall der Strategien | Projektvorschlag | **ohne Quelle** – mit Experte festlegen |
| Lückenregeln 1,5× / 3× Intervall | Projektkonvention | als Darstellungsregel ausweisen |
| Formaldehyd ≤ 60 µg/m³ aktiv / ≤ 30 passiv; TVOC ≤ 1'000 aktiv / ≤ 500 passiv; Radon ≤ 100 (Neubau) / ≤ 300 Bq/m³ (Erneuerung) | Minergie-ECO Vorgabenkatalog v2023.1, Vorgaben 120.03, 120.05, 110.04, 110.50 | geprüft; im Tool nur dokumentiert (Zertifizierungsmessung nach Baufertigstellung) |
| GRESB TC5.2, Level(s) 4.1 | GRESB 2026; JRC 2021 | geprüft, keine Erfüllungsaussage |
| Messhöhe 0,75–1,25 m; 1 Messgerät je 50 m²; nicht an Tür, Fenster, Zuluft, Personen | Bacher (2025), FHNW-Thesis EUT-P6-24HS, Kap. 9 (1 Gerät/50 m² dort aus BMK-Richtlinie Innenraumluft Teil 7 zitiert) | geprüft; im Tool als Hinweis, nicht als Bewertung |
| Messbereich, Genauigkeit, Exportformat je Gerät | Gerätematrix Messgeräteprojekt (`devices.json`, 27 Geräte; Herstellerangaben) | übernommen, nicht einzeln gegen Datenblätter geprüft |
| Import-Umrechnungen °F→°C, K→°C, Vol.-%→ppm | physikalische Definition (1 Vol.-% = 10 000 ppm) | eindeutig |
| Spaltenlayout der Geräteexporte | – | **offen:** je Gerät eine Original-Exportdatei nötig |
