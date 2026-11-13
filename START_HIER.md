# Start: IAQ-Tool V14 testen und online stellen

## Wichtig: Die ZIP-Datei selbst nicht hochladen

Streamlit Community Cloud startet Apps aus einem **GitHub-Repository**, nicht aus einer ZIP-Datei.
Die Dateien müssen entpackt im **Hauptordner** des Repositories liegen.

## A · Online (Streamlit Community Cloud)

1. ZIP auf dem Computer entpacken.
2. Im bestehenden GitHub-Repository: **Add file → Upload files**, alle entpackten Dateien hineinziehen
   (bestehende Dateien werden ersetzt), unten **Commit changes**.
   Benötigt werden: `app.py`, `iaq_logic.py`, `iaq_report.py`, `iaq_import.py`, `demo_data.py`, `bewertungsregeln.json`, `devices.json`, `import_profiles.json`, `requirements.txt`.
   **Neu in V14:** Bericht neu aufgebaut (`iaq_report.py`). **Neu in V13:** `iaq_import.py`, `devices.json` (Gerätematrix), `import_profiles.json`; `requirements.txt` ergänzt (openpyxl, tzdata) – unbedingt mit ersetzen.
3. Bestehende App: baut sich nach dem Commit automatisch neu (1–3 Minuten).
   Neue App: share.streamlit.io → **Create app** → Repository, Branch `main`, Main file `app.py`;
   unter *Advanced settings* Python **3.12** wählen (lokal mit 3.11, 3.12 und 3.13 geprüft).
4. Falls die App einen Fehler zeigt: rechts unten **Manage app → Reboot**; bleibt der Fehler, die Meldung kopieren.

## B · Lokal

1. Python 3.11 oder neuer installieren.
2. Im entpackten Ordner: `pip install -r requirements.txt`
3. `streamlit run app.py` – der Browser öffnet http://localhost:8501.

## Erster Test

1. Seite **Übersicht** → «Tool testen ohne Messdaten» → Anzahl Räume wählen → **Beispielprojekt laden**.
2. Seite **5 · Nachweis & Reporting** → «Gesamtbericht erstellen» → herunterladen → im Browser öffnen → «Als PDF drucken (A4)», Hintergrundgrafiken einschalten.
3. Für echte Projekte: **Höhenlage** unter Seite 1 · Objektangaben eintragen (nötig für die Feuchtebewertung nach SIA 180).

Fachlogik prüfen: `python -m unittest -v test_iaq_logic test_iaq_import` (36 Tests).

## Geprüft (13.11.2026, V14)

- Alle sieben App-Seiten inkl. Datei- und Präsenzimport sowie Belegungsplan mit einer Streamlit-Attrappe durchlaufen; Code kompiliert mit Python 3.11, 3.12, 3.13.
- Berichte mit 1–66 Räumen automatisch auf Überlauf und Schriftgrösse geprüft (≥ 12 pt ausser Quellen und Seitenfuss).
- Import mit synthetischen Dateien in typischen Exportstilen getestet (CSV/TXT/XLSX/JSON, °F, UTC, Vorspann, Datum+Zeit getrennt, Sekundendaten).
- **Nicht geprüft:** echter Streamlit-Lauf; **echte Exportdateien der Geräte** (liegen noch nicht vor).
