"""IAQ-Assessment-Tool P6 · V12 · Fokusthemen, 10 %-Regel nach SIA 180/382-1, standardisierter A4-Bericht (2–9 Seiten)."""
import html
import io
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from iaq_logic import (
    CORE, CORE_ORDER, PERIODS, PROFILES, PURPOSES, STRATEGIES, STRATEGY_INFO, VENTS,
    PROFILE_BT, PROFILE_ECO, PROFILE_SECO, PROFILE_SIA,
    conditional_hints, effective_ventilation, import_measurements,
    long_to_samples, measurement_records, required_issues, screening,
    WEEKDAYS, room_status, evaluate_room, usage_defined, filter_usage, STATUS_OK, STATUS_DEV, STATUS_CHECK, STATUS_NA, STATUS_NAPP, TOPICS,
)
from iaq_report import build_report, page_plan
from demo_data import build_demo_project

st.set_page_config(page_title="IAQ-Nachweismodell | P6", page_icon="🏢", layout="wide")
RULES = json.loads((Path(__file__).parent / "bewertungsregeln.json").read_text(encoding="utf-8"))


def new_project():
    return {
        "schema_version": 12, "demo": False,
        "building": {"name": "", "object_id": "", "location": "", "owner": "", "altitude_m": "", "operating_hours": "", "notes": ""},
        "report": {"report_no": "", "version": "1.0", "author": ""},
        "assessment": {"basis": PROFILE_BT, "period": PERIODS[0], "purpose": "", "notes": ""},
        "rooms": [], "step_notes": {},
    }


def new_room(number: int):
    return {
        "id": str(uuid4())[:8], "name": f"Raum {number}", "use": "Büro",
        "ventilation": VENTS[0], "ventilation_mode": "",
        "active_cooling": False, "strategy": STRATEGIES[1], "purpose": "",
        "start_date": "", "end_date": "", "measurement_interval_min": None,
        "usage_times": "", "usage_days": [], "usage_start": "", "usage_end": "", "occupancy_log": "", "occupancy": None,
        "area_m2": None, "floor": "", "measurement_position": "", "sensor_height_m": "", "sensor_count": "", "position_check": False,
        "device_id": "", "device_model": "", "calibration": "",
        "data_gaps": "", "maintenance": "", "ventilation_notes": "",
        "outdoor_co2_ppm": None, "selection_reason": "", "conditions": "",
        "strategy_deviation": "", "measurements": [], "notes": "",
        "heating_system": "", "cooling_system": "", "recirculation": "",
        "control_type": "", "sensors_available": "", "window_ventilation": "",
    }


def migrate(raw):
    """Alte V6/V7-JSON-Projekte erhalten; fehlende Pflichtfelder als Lücken anzeigen."""
    if not isinstance(raw, dict) or not isinstance(raw.get("rooms"), list) or not isinstance(raw.get("assessment"), dict):
        raise ValueError("Keine gültige IAQ-Projektdatei")
    p = new_project()
    p["building"].update({k: v for k, v in raw.get("building", {}).items() if k in p["building"]})
    a = raw["assessment"]
    p["assessment"]["basis"] = {"SIA 382/1": PROFILE_SIA}.get(a.get("basis"), a.get("basis", PROFILE_BT))
    p["assessment"]["period"] = a.get("period", PERIODS[0])
    p["assessment"]["purpose"] = a.get("purpose") if a.get("purpose") in PURPOSES else ""
    p["assessment"]["notes"] = a.get("notes", "")
    p["report"].update({k: v for k, v in (raw.get("report") or {}).items() if k in p["report"]})
    p["demo"] = bool(raw.get("demo"))
    if p["assessment"]["basis"] not in PROFILES or p["assessment"]["period"] not in PERIODS:
        raise ValueError("Unbekanntes Bewertungsprofil oder unbekannte Periode")
    for idx, old in enumerate(raw["rooms"], 1):
        if not isinstance(old, dict):
            raise ValueError("Ungültiger Raumdatensatz")
        r = new_room(idx)
        r.update({k: v for k, v in old.items() if k in r})
        r["id"] = str(r.get("id") or uuid4().hex[:8])
        if r["strategy"] not in STRATEGIES:
            r["strategy"] = ""
        if not isinstance(r.get("measurements"), list):
            r["measurements"] = []
        p["rooms"].append(r)
    return p


def get_room(room_id):
    return next((x for x in st.session_state.project["rooms"] if x["id"] == room_id), None)


def esc(value):
    return html.escape(str("–" if value is None or value == "" else value))


def display_assessment(room, assessment):
    result = screening(room, assessment, RULES)
    required = required_issues(room, assessment)
    if required:
        st.error("**Grundbewertung noch nicht möglich:** " + "; ".join(required))
    else:
        st.success("**Minimaldatensatz vollständig:** raumweise Grundbewertung möglich.")
    parsed = result["data"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Vollständige Messpunkte", parsed["vollstaendig"])
    c2.metric("Zeitpunkte im Datensatz", parsed["zeitpunkte"])
    c3.metric("Unvollständige Zeitpunkte", parsed["zeitpunkte"] - parsed["vollstaendig"])
    st.caption(result["note"])
    ev = evaluate_room(room, assessment, RULES, st.session_state.project.get("building", {}))
    show = {STATUS_OK: st.success, STATUS_DEV: st.warning, STATUS_CHECK: st.error, STATUS_NA: st.info}[ev["status"]]
    show(f"**Gesamteinordnung: {ev['status']}** (Bezug: {ev['bezug']})")
    if not required:
        st.markdown("**IAQ-Nachweismodell – Fokusthemen** (10 %-Regel nach SIA 180 Ziff. 3.5.1.3/4 und SIA 382/1 Ziff. 2.2.5.6)")
        st.dataframe(pd.DataFrame([{"Fokusthema": t, "Einordnung": ev["topics"][t]["status"], "Begründung": ev["topics"][t]["text"],
                                    "Quelle": ev["topics"][t].get("src", "")} for t in TOPICS]), hide_index=True)
        if not ev["jahr"]:
            st.caption("Kein Jahresbezug: Die 10 %-Regel bezieht sich auf die jährliche Nutzungszeit eines typischen Jahres – das Ergebnis ist eine Indikation für den Messzeitraum.")
    if result["rows"] and not required:
        st.markdown("**Profilvergleich (Messpunktanteile) – alle Messpunkte**")
        st.dataframe(pd.DataFrame(result["rows"]), hide_index=True)
        if usage_defined(room):
            use = screening(room, assessment, RULES, "nutzung")
            st.markdown("**Nur Nutzungszeit**")
            if use["rows"]:
                st.dataframe(pd.DataFrame(use["rows"]), hide_index=True)
            else:
                st.info("Keine vollständigen Messpunkte innerhalb der erfassten Nutzungszeit.")
    elif not result["rows"] and not required:
        st.info("Für das gewählte Profil ist mit diesen drei Sensorparametern kein direkter normativer Vergleich möglich. Siehe Quellenhinweis oben.")
    if parsed["issues"]:
        with st.expander(f"Unvollständige / fehlerhafte Daten ({len(parsed['issues'])})"):
            for issue in parsed["issues"][:70]:
                st.write("• " + issue)
            if len(parsed["issues"]) > 70:
                st.caption("Weitere Fehler im Datensatz vorhanden.")
    hints = conditional_hints(room, assessment, parsed)
    if hints:
        with st.expander(f"Hinweise für einen belastbaren Nachweis ({len(hints)})"):
            for hint in hints:
                st.write("• " + hint)
    return result


if "project" not in st.session_state:
    st.session_state.project = new_project()
p = st.session_state.project
b, a = p["building"], p["assessment"]
st.title("IAQ Assessment Tool · Bachelor-Thesis P6")
st.caption("V12 · Fokusthemen, 10 %-Regel, standardisierter A4-Bericht · wissenschaftliches Screening, keine Zertifizierung")
if p.get("demo"):
    st.warning("**Beispielprojekt mit synthetischen Daten geladen** – nur zum Testen. Berichte werden als BEISPIELDATEN gekennzeichnet. Neues Projekt: Seite 6 · Datensicherung.")

with st.sidebar:
    page = st.radio("Navigation", ["Übersicht", "1 · Nachweisrahmen", "2 · Räume & Messstrategie", "3 · Messwerte", "4 · Qualitätsprüfung", "5 · Nachweis & Reporting", "6 · Datensicherung"], label_visibility="collapsed")
    st.divider()
    st.caption(f"{a.get('basis', '')} · {a.get('period', '')}")
    st.caption(f"{len(p['rooms'])} Raum/Räume")

if page == "Übersicht":
    st.subheader("Arbeitsstand")
    c1, c2, c3 = st.columns(3)
    c1.metric("Räume", len(p["rooms"]))
    c2.metric("Vollständige Messpunkte", sum(len(long_to_samples(r)["samples"]) for r in p["rooms"]))
    c3.metric("Räume mit Minimaldatensatz", sum(not required_issues(r, a) for r in p["rooms"]))
    st.markdown("**Ablauf:** Nachweiszweck wählen → Räume und Lüftungsart erfassen → Messstrategie wählen → Zeitstempel und drei IAQ-Parameter importieren → Datenqualität prüfen → Screening / Bericht.")
    st.info("**Pflicht:** Raum-ID, Profil, Heiz-/Kühlperiode, Lüftungsart, Messstrategie, Nachweiszweck und je Messpunkt Datum/Uhrzeit, CO₂, Lufttemperatur, relative Feuchte. Weitere Angaben sind je nach Nachweiszweck bedingt erforderlich.")
    with st.expander("Tool testen ohne Messdaten: synthetisches Beispielprojekt laden"):
        st.caption("Erzeugt Räume mit künstlichen Messreihen (5 Arbeitstage, 5-min-Intervall; letzter Raum als Stichprobe). Ersetzt das aktuelle Projekt.")
        n_demo = st.select_slider("Anzahl Räume", options=[1, 2, 3, 6, 12, 20], value=3)
        if st.button("Beispielprojekt laden"):
            st.session_state.project = build_demo_project(n_demo)
            st.rerun()
    if p["rooms"]:
        st.dataframe(pd.DataFrame([{"Raum": r["name"], "Strategie": r.get("strategy"), "Vollständige Punkte": len(long_to_samples(r)["samples"]), "Pflichtlücken": len(required_issues(r, a))} for r in p["rooms"]]), hide_index=True)

elif page == "1 · Nachweisrahmen":
    st.subheader("Nachweiszweck und Regelprofil · Pflicht")
    c1, c2 = st.columns(2)
    with c1:
        a["basis"] = st.selectbox("Bewertungsprofil *", PROFILES, index=PROFILES.index(a.get("basis")) if a.get("basis") in PROFILES else 0)
        a["period"] = st.selectbox("Betriebsfall *", PERIODS, index=PERIODS.index(a.get("period")) if a.get("period") in PERIODS else 0)
    with c2:
        choices = ["Bitte auswählen"] + PURPOSES
        old = a.get("purpose")
        choice = st.selectbox("Nachweiszweck *", choices, index=choices.index(old) if old in choices else 0)
        a["purpose"] = "" if choice == choices[0] else choice
        a["notes"] = st.text_input("Besonderheiten zum Nachweis (freiwillig)", a.get("notes", ""))
    with st.expander("Bewertungslogik und Gültigkeitsbereich"):
        if a["basis"] == PROFILE_SIA:
            st.write("**SIA 382/1:2025:** IDA-2-Vergleich für alle Lüftungsarten (Tab. 18, Fussnote 3): CO₂ innen ≤ CO₂ aussen + 800 ppm. Ohne Aussenwert gilt der Bezugswert 400 ppm (Tab. 18, Fussnote 2). Operative Temperatur wird nicht aus Lufttemperatur geschätzt.")
        elif a["basis"] == PROFILE_SECO:
            st.write("**SECO / ArGV 3 (Wegleitung Art. 16, Aug. 2020):** Orientierungs-Screening: CO₂ < 1'000 ppm (Abb. 316-4), Lufttemperatur Heizperiode 21–23 °C / Kühlperiode 23–26 °C (Abb. 316-1), relative Feuchte Winter 30–50 % / Sommer 40–60 % (Abb. 316-2) und Schwülegrenze (S. 316-3). Kein automatischer Gesetzesverstoss bei Abweichung.")
        elif a["basis"] == PROFILE_ECO:
            st.write("**Minergie-ECO 2023.1:** Kein eigenständiger allgemeiner Betriebsgrenzwert für diese drei Sensormessgrössen. Schadstoffnachweise (z. B. Formaldehyd, TVOC, Radon) erfordern gesonderte Messverfahren und Zertifizierungsvoraussetzungen.")
        else:
            st.write("**BT:** Projektspezifisches Screening mit SECO-Orientierungswerten. Ergänzende SIA-IDA-2-Klasse und ECO-Schadstoffnachweis sind getrennt dokumentiert; keine pauschale Kombination aller Zahlen zu rechtlichen Grenzwerten.")
    if a["purpose"] == PURPOSES[2]:
        st.warning("Ein langfristiger oder saisonaler Nachweis ist mit einer Momentaufnahme oder einzelnen Messwoche nicht belastbar. Auch kontinuierliches Monitoring erfordert geeignete Zeitabdeckung und Saisontrennung.")
    st.caption("Nachweiszweck bestimmt die Aussagekraft, nicht automatisch die gesetzlichen Anforderungen. Das Profil bestimmt den Referenzvergleich.")
    st.divider()
    with st.expander("Objektangaben (für Bericht; Höhenlage nötig für Feuchtebewertung)", expanded=not b.get("altitude_m")):
        b["name"] = st.text_input("Gebäudebezeichnung", b.get("name", ""))
        b["location"] = st.text_input("Standort", b.get("location", ""))
        b["object_id"] = st.text_input("Objekt-ID", b.get("object_id", ""))
        b["operating_hours"] = st.text_input("Übliche Betriebszeiten", b.get("operating_hours", ""))
        b["owner"] = st.text_input("Auftraggeber / Betreiber", b.get("owner", ""))
        b["altitude_m"] = st.text_input("Höhenlage [m ü. M.] (für die Feuchtegrenze nach SIA 180, Ziff. 3.5.1.3)", b.get("altitude_m", ""))
    rep = p.setdefault("report", {"report_no": "", "version": "1.0", "author": ""})
    with st.expander("Berichtsangaben (erscheinen auf Seite 1 des Berichts)"):
        rep["report_no"] = st.text_input("Bericht-Nr.", rep.get("report_no", ""))
        rep["version"] = st.text_input("Version", rep.get("version", "1.0"))
        rep["author"] = st.text_input("Erstellt durch", rep.get("author", ""))

elif page == "2 · Räume & Messstrategie":
    st.subheader("Raum und Messstrategie")
    if st.button("+ Raum hinzufügen", type="primary"):
        existing = {r.get("name", "") for r in p["rooms"]}
        number = 1
        while f"Raum {number}" in existing:
            number += 1
        p["rooms"].append(new_room(number))
        st.rerun()
    if not p["rooms"]:
        st.info("Bitte zunächst einen Raum anlegen.")
    else:
        selected = st.selectbox("Raum auswählen", [r["id"] for r in p["rooms"]], format_func=lambda rid: f"{get_room(rid)['name']} · {rid}")
        r = get_room(selected)
        c1, c2 = st.columns(2)
        with c1:
            r["name"] = st.text_input("Raum-ID / Name *", r.get("name", ""), key=f"roomname_{selected}")
            r["ventilation"] = st.selectbox("Lüftungsart *", VENTS, index=VENTS.index(r["ventilation"]) if r.get("ventilation") in VENTS else 0, key=f"vent_{selected}")
            if r["ventilation"] == VENTS[2]:
                modes = ["Bitte auswählen", "Mechanisch", "Natürlich"]
                old = r.get("ventilation_mode", "")
                opt = st.selectbox("Betriebsmodus der hybriden Lüftung *", modes, index=modes.index(old) if old in modes else 0, key=f"vm_{selected}")
                r["ventilation_mode"] = "" if opt == "Bitte auswählen" else opt
            if a["period"] == "Kühlperiode":
                r["active_cooling"] = st.checkbox("Aktive Raumkühlung vorhanden / in Betrieb", value=bool(r.get("active_cooling")), key=f"cool_{selected}")
            else:
                r["active_cooling"] = False
        with c2:
            r["strategy"] = st.selectbox("Messstrategie *", STRATEGIES, index=STRATEGIES.index(r.get("strategy")) if r.get("strategy") in STRATEGIES else 0, key=f"strategy_{selected}")
            st.info(STRATEGY_INFO[r["strategy"]]["vorschlag"])
            st.caption("**Aussagegrenze:** " + STRATEGY_INFO[r["strategy"]]["aussage"])
        st.caption("* = Pflicht für die raumweise Grundbewertung. Für saisonübergreifendes Monitoring separate Betriebsfälle ausweisen.")
        if a["purpose"] == PURPOSES[2] and r["strategy"] != STRATEGIES[2]:
            st.warning("Für langfristige Verlaufs- oder Saisonaussagen ist diese Strategie allein nicht geeignet.")
        with st.expander("Bedingt erforderlich: Nutzungszeit, Messkampagne und Rückverfolgbarkeit"):
            c3, c4 = st.columns(2)
            with c3:
                r["start_date"] = st.text_input("Messbeginn (JJJJ-MM-TT)", r.get("start_date", ""), key=f"begin_{selected}")
                r["end_date"] = st.text_input("Messende (JJJJ-MM-TT)", r.get("end_date", ""), key=f"end_{selected}")
                r["measurement_interval_min"] = st.number_input("Sollintervall (Minuten, 0 = nicht angegeben)", min_value=0, max_value=1440, value=int(r.get("measurement_interval_min") or 0), key=f"interval_{selected}") or None
                st.caption("Tatsächliche Nutzungszeit (strukturiert, für nutzungszeitbezogene Auswertung)")
                r["usage_days"] = st.multiselect("Nutzungstage", WEEKDAYS, default=[d for d in r.get("usage_days", []) if d in WEEKDAYS], key=f"udays_{selected}")
                cu1, cu2 = st.columns(2)
                r["usage_start"] = cu1.text_input("Von (HH:MM)", r.get("usage_start", ""), key=f"ustart_{selected}", placeholder="08:00")
                r["usage_end"] = cu2.text_input("Bis (HH:MM)", r.get("usage_end", ""), key=f"uend_{selected}", placeholder="17:00")
                if (r["usage_days"] or r["usage_start"] or r["usage_end"]) and not usage_defined(r):
                    st.warning("Nutzungszeit unvollständig/ungültig: Tage wählen und Von < Bis im Format HH:MM.")
                r["occupancy"] = st.text_input("Belegung / Personenanzahl", r.get("occupancy") or "", key=f"occ_{selected}", placeholder="z. B. 6 Arbeitsplätze, Sitzungen bis 10 Personen")
                r["usage_times"] = st.text_input("Bemerkung zur Nutzung (Ausnahmen, Ferien etc.)", r.get("usage_times", ""), key=f"usage_{selected}")
                r["occupancy_log"] = st.text_input("Nutzungs-/Belegungsprotokoll oder Verweis", r.get("occupancy_log", ""), key=f"occupancy_{selected}")
                r["data_gaps"] = st.text_input("Datenlücken/Ausfälle (ggf. 'keine')", r.get("data_gaps", ""), key=f"gaps_{selected}")
            with c4:
                r["measurement_position"] = st.text_input("Messposition (z. B. Raummitte, Tisch)", r.get("measurement_position", ""), key=f"pos_{selected}")
                cp1, cp2 = st.columns(2)
                r["sensor_height_m"] = cp1.text_input("Messhöhe [m] (empf. 0,75–1,25)", str(r.get("sensor_height_m") or ""), key=f"sh_{selected}")
                r["sensor_count"] = cp2.text_input("Anzahl Messgeräte (empf. 1 je 50 m²)", str(r.get("sensor_count") or ""), key=f"sc_{selected}")
                r["position_check"] = st.checkbox("Nicht an Tür, Fenster, Zuluft oder direkt bei Personen (Bacher 2025)", value=bool(r.get("position_check", False)), key=f"pc_{selected}")
                r["device_id"] = st.text_input("Messgerät / Seriennummer", r.get("device_id", ""), key=f"device_{selected}")
                r["calibration"] = st.text_input("Prüfung / Kalibrierung", r.get("calibration", ""), key=f"cal_{selected}")
                r["ventilation_notes"] = st.text_input("Lüftungs- / Fensterbetrieb", r.get("ventilation_notes", ""), key=f"ventnotes_{selected}")
                r["selection_reason"] = st.text_input("Raumauswahlgrund (Mehrraumnachweis)", r.get("selection_reason", ""), key=f"reason_{selected}")
                st.caption("Gebäudetechnische Randbedingungen (bei belastbarer Mehrraumbewertung dokumentieren)")
                r["heating_system"] = st.text_input("Heizsystem (z. B. Heizkörper/Bodenheizung)", r.get("heating_system", ""), key=f"heat_{selected}")
                r["cooling_system"] = st.text_input("Kühlsystem / Kühlbetrieb", r.get("cooling_system", ""), key=f"cooling_system_{selected}")
                r["window_ventilation"] = st.text_input("Fensterlüftung möglich?", r.get("window_ventilation", ""), key=f"window_{selected}")
                r["recirculation"] = st.text_input("Umluftsystem vorhanden?", r.get("recirculation", ""), key=f"recirc_{selected}")
                r["control_type"] = st.text_input("Lüftungs-/Kühlregelung", r.get("control_type", ""), key=f"control_{selected}")
                r["sensors_available"] = st.text_input("Vorhandene Sensorik / Betriebsdaten", r.get("sensors_available", ""), key=f"sensors_{selected}")
                raw_out = str(r.get("outdoor_co2_ppm") or "")
                out = st.text_input("CO₂ Aussenluft [ppm] (für SIA-Klassengrenze)", raw_out, key=f"out_{selected}")
                if out.strip():
                    try:
                        r["outdoor_co2_ppm"] = float(out.replace(",", "."))
                    except ValueError:
                        st.warning("CO₂ Aussenluft: bitte numerischen Wert eingeben")
                        r["outdoor_co2_ppm"] = None
                else:
                    r["outdoor_co2_ppm"] = None
        with st.expander("Freiwillige Zusatzangaben"):
            r["use"] = st.text_input("Raumtyp / Nutzung", r.get("use", ""), key=f"use_{selected}", placeholder="Einzelbüro, Grossraumbüro, Sitzungszimmer …")
            r["area_m2"] = st.text_input("Raumfläche (m²)", str(r.get("area_m2") or ""), key=f"area_{selected}")
            r["notes"] = st.text_area("Besondere Ereignisse / Besonderheiten", r.get("notes", ""), key=f"notes_{selected}")
            if r["strategy"] == STRATEGIES[2]:
                r["maintenance"] = st.text_area("Wartungen / Änderungen", r.get("maintenance", ""), key=f"maint_{selected}")
        with st.expander("Raum löschen"):
            if st.button("Raum inklusive Messwerte endgültig löschen", key=f"delete_{selected}"):
                p["rooms"] = [x for x in p["rooms"] if x["id"] != selected]
                st.rerun()

elif page == "3 · Messwerte":
    st.subheader("Messwerte erfassen · vier Pflichtangaben je Messpunkt")
    if not p["rooms"]:
        st.warning("Bitte zuerst einen Raum anlegen.")
    else:
        rid = st.selectbox("Raum", [r["id"] for r in p["rooms"]], format_func=lambda rid: get_room(rid)["name"])
        r = get_room(rid)
        with st.form(f"single_{rid}", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            ts = c1.text_input("Datum + Uhrzeit *", placeholder="2026-10-30 10:30")
            co2 = c2.text_input("CO₂ [ppm] *")
            temp = c3.text_input("Lufttemperatur [°C] *")
            rh = c4.text_input("Relative Feuchte [%] *")
            add = st.form_submit_button("Vollständigen Messpunkt speichern", type="primary")
        if add:
            try:
                r["measurements"].extend(measurement_records(ts, co2, temp, rh))
                st.success("Messpunkt mit allen drei Parametern gespeichert.")
            except ValueError as exc:
                st.error(str(exc))
        st.divider()
        st.markdown("**CSV-Import**")
        st.caption("Bevorzugt eine Zeile pro Zeitpunkt mit `timestamp,co2,temp,rh`. Vorhandene V7-Dateien im Langformat `timestamp,parameter,value,unit` werden ebenfalls akzeptiert.")
        example = pd.DataFrame([{"timestamp": "2026-10-30 10:30", "co2": 850, "temp": 22.0, "rh": 45.0}])
        st.download_button("CSV-Vorlage herunterladen", example.to_csv(index=False).encode("utf-8-sig"), file_name="iaq_3parameter_vorlage.csv", mime="text/csv")
        uploaded = st.file_uploader("CSV auswählen", type=["csv"], key=f"csv_{rid}")
        if uploaded is not None:
            try:
                df = pd.read_csv(io.BytesIO(uploaded.getvalue()), sep=None, engine="python", encoding="utf-8-sig", dtype=str)
                st.dataframe(df.head(8), hide_index=True)
                if st.button("CSV importieren", key=f"csv_add_{rid}"):
                    new, errs = import_measurements(df)
                    r["measurements"].extend(new)
                    st.success(f"{len(new) // 3 if {'co2','temp','rh'}.issubset(set(df.columns.str.lower())) else len(new)} Zeilen / Messwertgruppen übernommen ({len(new)} Einzelwerte).")
                    if errs:
                        st.warning(f"{len(errs)} CSV-Zeilen nicht übernommen. Beispiele: " + "; ".join(errs[:4]))
            except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
                st.error(f"Import nicht möglich: {exc}")
        with st.expander("Freiwillig: zusätzliche Schadstoffmessungen dokumentieren (keine automatische ECO-Zertifizierung)"):
            with st.form(f"additional_{rid}", clear_on_submit=True):
                extra_param = st.selectbox("Schadstoff", ["Formaldehyd", "TVOC", "Radon"])
                extra_ts = st.text_input("Messzeitpunkt (JJJJ-MM-TT HH:MM)", key=f"ex_ts_{rid}")
                extra_val = st.text_input("Messwert", key=f"ex_val_{rid}")
                if st.form_submit_button("Zusatzwert speichern"):
                    from iaq_logic import parse_timestamp
                    dt = parse_timestamp(extra_ts)
                    try:
                        v = float(extra_val.replace(",", "."))
                    except ValueError:
                        v = float("nan")
                    if dt is None or not (0 <= v < float("inf")):
                        st.error("Messzeitpunkt und nichtnegativen Zahlenwert eingeben.")
                    else:
                        unit = "Bq/m³" if extra_param == "Radon" else "µg/m³"
                        r["measurements"].append({"timestamp": dt.strftime("%Y-%m-%d %H:%M"), "parameter": extra_param, "value": v, "unit": unit, "note": "Nur Dokumentation, Messverfahren separat nachweisen"})
                        st.success("Zusatzwert dokumentiert (ohne Zertifizierungsbewertung).")
        st.divider()
        parsed = long_to_samples(r)
        st.write(f"**{parsed['vollstaendig']} vollständige Messpunkte** aus {parsed['zeitpunkte']} Zeitpunkten")
        if parsed["samples"]:
            view = pd.DataFrame(parsed["samples"])
            view["timestamp"] = view["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(view.rename(columns={"timestamp": "Zeitstempel", "CO₂": "CO₂ [ppm]", "Temperatur": "Temperatur [°C]", "Relative Feuchte": "r. F. [%]"}), hide_index=True)
        if r.get("measurements"):
            with st.expander("Rohdaten / ungültige und unvollständige Einzelwerte"):
                st.dataframe(pd.DataFrame(r["measurements"]), hide_index=True)
            if st.button("Alle Messwerte dieses Raums löschen", key=f"clear_{rid}"):
                r["measurements"] = []
                st.rerun()

elif page == "4 · Qualitätsprüfung":
    st.subheader("Pflichtangaben und bedingte Nachweisanforderungen")
    st.caption("Pflichtstatus bezieht sich auf eine grundlegende raumbezogene Beurteilung; methodische Nachweisanforderungen hängen vom gewählten Nachweiszweck ab.")
    if not p["rooms"]:
        st.info("Noch keine Räume vorhanden.")
    for r in p["rooms"]:
        with st.expander(f"{r.get('name')} · {len(required_issues(r, a))} Pflichtlücken", expanded=True):
            display_assessment(r, a)

elif page == "5 · Nachweis & Reporting":
    st.subheader("Raumauswertung und Gebäudeübersicht")
    st.caption("Der Bericht hält Nachweiszweck, Messstrategie, Datenqualität, Quellen und zulässige Aussage fest.")
    if not p["rooms"]:
        st.info("Noch keine Räume vorhanden.")
    else:
        rid = st.selectbox("Einzelraum", [r["id"] for r in p["rooms"]], format_func=lambda rid: get_room(rid)["name"])
        r = get_room(rid)
        display_assessment(r, a)
        parsed = long_to_samples(r)
        if parsed["samples"]:
            with st.expander("Deskriptive Messwerte und Zeitverlauf"):
                df = pd.DataFrame(parsed["samples"]).set_index("timestamp")
                stats = []
                for param, unit in CORE.items():
                    stats.append({"Parameter": param, "Minimum": round(df[param].min(), 2), "Mittel": round(df[param].mean(), 2), "Maximum": round(df[param].max(), 2), "Einheit": unit})
                st.dataframe(pd.DataFrame(stats), hide_index=True)
                for param, unit in CORE.items():
                    st.markdown(f"**{param} [{unit}]**")
                    st.line_chart(df[[param]])
                st.caption("Mittelwerte sind nicht zeitgewichtet; für unterschiedliche Messintervalle können die Punktanteile verzerrt sein.")
        st.download_button("Einzelraumbericht (A4, 2 Seiten) herunterladen", build_report(p, RULES, [r], demo=bool(p.get("demo"))).encode("utf-8"), file_name=f"iaq_raumbericht_{r['id']}.html", mime="text/html")
        st.divider()
        st.markdown("**Gebäudeübergreifend: Räume getrennt ausweisen**")
        rows = []
        for rm in p["rooms"]:
            result = screening(rm, a, RULES)
            rows.append({"Raum": rm["name"], "Strategie": rm.get("strategy"), "Vollständige Messpunkte": result["samples"], "Pflichtlücken": len(required_issues(rm, a)), "Einordnung": room_status(rm, a, RULES, p["building"])["status"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.warning("Keine pauschale Gebäudekonformität aus Einzelraum-Screenings ableiten. Repräsentative Raumauswahl, Nutzungszeitabdeckung und Vergleichbarkeit sind getrennt nachzuweisen.")
        plan = page_plan(len(p["rooms"]))
        st.info(f"**Gesamtbericht: {plan['pages']} Seiten** für {len(p['rooms'])} Raum/Räume · Schrift ≥ 12 pt. 1 Raum = 2 Seiten; 2–10 Räume = 4–6 Seiten; bis 66 Räume höchstens 9 Seiten (max. 6 Raumprofile, übrige in der Raummatrix).")
        if st.button("Gesamtbericht erstellen / aktualisieren", type="primary"):
            with st.spinner("Bericht wird erstellt …"):
                st.session_state["_report"] = {"html": build_report(p, RULES, demo=bool(p.get("demo"))),
                                               "zeit": datetime.now().strftime("%d.%m.%Y %H:%M")}
        rep_state = st.session_state.get("_report")
        if rep_state:
            st.caption(f"Stand des Berichts: {rep_state['zeit']} – nach Datenänderungen neu erstellen.")
            st.download_button("IAQ-Bericht (A4, alle Räume) herunterladen", rep_state["html"].encode("utf-8"), file_name="iaq_bericht.html", mime="text/html")
            st.caption("Datei im Browser öffnen → «Als PDF drucken (A4)» (Chrome/Edge: Ränder «Standard», Hintergrundgrafiken an).")
            with st.expander("Vorschau Bericht", expanded=False):
                components.html(rep_state["html"], height=1100, scrolling=True)

elif page == "6 · Datensicherung":
    st.subheader("Projekt sichern und importieren")
    st.download_button("Projekt als JSON speichern", json.dumps(p, ensure_ascii=False, indent=2).encode("utf-8"), file_name="iaq_p6_projekt.json", mime="application/json", type="primary")
    export = []
    for r in p["rooms"]:
        for sample in long_to_samples(r)["samples"]:
            export.append({"raum_id": r["id"], "raum": r["name"], "timestamp": sample["timestamp"].strftime("%Y-%m-%d %H:%M"), "co2": sample["CO₂"], "temp": sample["Temperatur"], "rh": sample["Relative Feuchte"]})
    if export:
        st.download_button("Vollständige Messpunkte als CSV", pd.DataFrame(export).to_csv(index=False).encode("utf-8-sig"), file_name="iaq_p6_messpunkte.csv", mime="text/csv")
    if st.button("Neues leeres Projekt beginnen (aktuelles verwerfen)"):
        st.session_state.project = new_project()
        st.rerun()
    st.divider()
    upload = st.file_uploader("Projekt-JSON hochladen (auch V6–V9)", type=["json"])
    if upload and st.button("Projekt aus JSON laden"):
        try:
            imported = migrate(json.loads(upload.getvalue().decode("utf-8")))
            st.session_state.project = imported
            for key in list(st.session_state.keys()):
                if key != "project":
                    del st.session_state[key]
            st.rerun()
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            st.error(f"Projektdatei konnte nicht geladen werden: {exc}")

st.divider()
st.caption("P6 · Projektauftrag 2026/27, S. 7–9. Messstrategien sind methodische Vorschläge. Keine automatische Rechts- oder Labelkonformitätsbestätigung.")
