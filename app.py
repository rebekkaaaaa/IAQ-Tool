"""IAQ-Assessment-Tool P6 · V13 · Messart, geräteabhängiger Datenimport, Nutzung aus Kalender/Präsenzsensor, A4-Bericht (2–9 Seiten)."""
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
    WEEKDAYS, OCC_SOURCES, LEGACY_STRATEGIES, usage_label, room_status, evaluate_room, usage_defined, filter_usage, STATUS_OK, STATUS_DEV, STATUS_CHECK, STATUS_NA, STATUS_NAPP, TOPICS,
)
from iaq_report import build_report, page_plan
import iaq_import as imp
from demo_data import build_demo_project

st.set_page_config(page_title="IAQ-Nachweismodell | P6", page_icon="🏢", layout="wide")
RULES = json.loads((Path(__file__).parent / "bewertungsregeln.json").read_text(encoding="utf-8"))
DEVICES = imp.load_devices()
DEV_BY_ID = {d["id"]: d for d in DEVICES}
PROFILES_IMP = imp.load_profiles()
EXTERN = "Externes / anderes Gerät (IAQ-Standardformat)"


def new_project():
    return {
        "schema_version": 13, "demo": False,
        "building": {"name": "", "object_id": "", "location": "", "owner": "", "altitude_m": "", "operating_hours": "", "notes": ""},
        "report": {"report_no": "", "version": "1.0", "author": ""},
        "assessment": {"basis": PROFILE_BT, "period": PERIODS[0], "purpose": "", "default_strategy": STRATEGIES[1], "notes": ""},
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
        "device_id": "", "device_model": "", "device_ref": "", "calibration": "", "import_log": [],
        "occupancy_source": OCC_SOURCES[0], "occupancy_intervals": [], "occupancy_import_log": {},
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
    ds = LEGACY_STRATEGIES.get(a.get("default_strategy"), a.get("default_strategy"))
    p["assessment"]["default_strategy"] = ds if ds in STRATEGIES else STRATEGIES[1]
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
        r["strategy"] = LEGACY_STRATEGIES.get(r.get("strategy"), r.get("strategy"))
        if r["strategy"] not in STRATEGIES:
            r["strategy"] = ""
        if r.get("occupancy_source") not in OCC_SOURCES:
            r["occupancy_source"] = OCC_SOURCES[0]
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
    page = st.radio("Navigation", ["Übersicht", "1 · Projekt & Bewertung", "2 · Räume & Messart", "3 · Messwerte & Nutzung", "4 · Qualitätsprüfung", "5 · Nachweis & Reporting", "6 · Datensicherung"], label_visibility="collapsed")
    st.divider()
    st.caption(f"{a.get('basis', '')} · {a.get('period', '')}")
    st.caption(f"{len(p['rooms'])} Raum/Räume")

if page == "Übersicht":
    st.subheader("Arbeitsstand")
    c1, c2, c3 = st.columns(3)
    c1.metric("Räume", len(p["rooms"]))
    c2.metric("Vollständige Messpunkte", sum(len(long_to_samples(r)["samples"]) for r in p["rooms"]))
    c3.metric("Räume mit Minimaldatensatz", sum(not required_issues(r, a) for r in p["rooms"]))
    st.markdown("**Ablauf:** Bewertungsprofil wählen → Räume, Lüftungsart, Messart und Messgerät erfassen → Gerätedatei importieren (wird automatisch vereinheitlicht) → Nutzung aus Zeitplan, Kalender oder Präsenzsensor → Qualitätsprüfung → Bericht.")
    st.info("**Pflicht:** Raum-ID, Profil, Heiz-/Kühlperiode, Lüftungsart, Messart und je Messpunkt Datum/Uhrzeit, CO₂, Lufttemperatur, relative Feuchte. Weitere Angaben sind je nach Messart bedingt erforderlich.")
    with st.expander("Tool testen ohne Messdaten: synthetisches Beispielprojekt laden"):
        st.caption("Erzeugt Räume mit künstlichen Messreihen (5 Arbeitstage, 5-min-Intervall; letzter Raum als Stichprobe). Ersetzt das aktuelle Projekt.")
        n_demo = st.select_slider("Anzahl Räume", options=[1, 2, 3, 6, 12, 20], value=3)
        if st.button("Beispielprojekt laden"):
            st.session_state.project = build_demo_project(n_demo)
            st.rerun()
    if p["rooms"]:
        st.dataframe(pd.DataFrame([{"Raum": r["name"], "Messart": r.get("strategy"), "Vollständige Punkte": len(long_to_samples(r)["samples"]), "Pflichtlücken": len(required_issues(r, a))} for r in p["rooms"]]), hide_index=True)

elif page == "1 · Projekt & Bewertung":
    st.subheader("Bewertungsprofil und Messart · Pflicht")
    c1, c2 = st.columns(2)
    with c1:
        a["basis"] = st.selectbox("Bewertungsprofil *", PROFILES, index=PROFILES.index(a.get("basis")) if a.get("basis") in PROFILES else 0)
        a["period"] = st.selectbox("Betriebsfall *", PERIODS, index=PERIODS.index(a.get("period")) if a.get("period") in PERIODS else 0)
    with c2:
        ds = a.get("default_strategy") if a.get("default_strategy") in STRATEGIES else STRATEGIES[1]
        a["default_strategy"] = st.selectbox("Messart (Vorgabe für neue Räume) *", STRATEGIES, index=STRATEGIES.index(ds),
                                             help="Die Messart kann pro Raum angepasst werden (Seite 2).")
        a["notes"] = st.text_input("Besonderheiten zum Nachweis (freiwillig)", a.get("notes", ""))
    st.dataframe(pd.DataFrame([{"Messart": k, "Zweck": v["zweck"], "Aussagekraft": v["aussage"]} for k, v in STRATEGY_INFO.items()]), hide_index=True)
    st.caption("Der Nachweis bestätigt die Einhaltung der Vorgaben im **Normalbetrieb**. Wo die Norm es vorsieht, sind Abweichungen in höchstens 10 % der Nutzungszeit zulässig (SIA 382/1:2025 Ziff. 2.2.5.6; SIA 180:2014 Ziff. 3.5.1.3/3.5.1.4). Ein Jahresnachweis setzt deshalb eine Langzeitmessung über ein Jahr Normalbetrieb voraus.")
    with st.expander("Bewertungslogik und Gültigkeitsbereich"):
        if a["basis"] == PROFILE_SIA:
            st.write("**SIA 382/1:2025:** IDA-2-Vergleich für alle Lüftungsarten (Tab. 18, Fussnote 3): CO₂ innen ≤ CO₂ aussen + 800 ppm. Ohne Aussenwert gilt der Bezugswert 400 ppm (Tab. 18, Fussnote 2). Operative Temperatur wird nicht aus Lufttemperatur geschätzt.")
        elif a["basis"] == PROFILE_SECO:
            st.write("**SECO / ArGV 3 (Wegleitung Art. 16, Aug. 2020):** Orientierungs-Screening: CO₂ < 1'000 ppm (Abb. 316-4), Lufttemperatur Heizperiode 21–23 °C / Kühlperiode 23–26 °C (Abb. 316-1), relative Feuchte Winter 30–50 % / Sommer 40–60 % (Abb. 316-2) und Schwülegrenze (S. 316-3). Kein automatischer Gesetzesverstoss bei Abweichung.")
        elif a["basis"] == PROFILE_ECO:
            st.write("**Minergie-ECO 2023.1:** Kein eigenständiger allgemeiner Betriebsgrenzwert für diese drei Sensormessgrössen. Schadstoffnachweise (z. B. Formaldehyd, TVOC, Radon) erfordern gesonderte Messverfahren und Zertifizierungsvoraussetzungen.")
        else:
            st.write("**BT:** Projektspezifisches Screening mit SECO-Orientierungswerten. Ergänzende SIA-IDA-2-Klasse und ECO-Schadstoffnachweis sind getrennt dokumentiert; keine pauschale Kombination aller Zahlen zu rechtlichen Grenzwerten.")
    st.caption("Die Messart bestimmt die Aussagekraft, das Bewertungsprofil den Referenzvergleich.")
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

elif page == "2 · Räume & Messart":
    st.subheader("Raum, Messart und Messgerät")
    if st.button("+ Raum hinzufügen", type="primary"):
        existing = {r.get("name", "") for r in p["rooms"]}
        number = 1
        while f"Raum {number}" in existing:
            number += 1
        nr = new_room(number)
        nr["strategy"] = a.get("default_strategy") if a.get("default_strategy") in STRATEGIES else STRATEGIES[1]
        p["rooms"].append(nr)
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
            r["strategy"] = st.selectbox("Messart *", STRATEGIES, index=STRATEGIES.index(r.get("strategy")) if r.get("strategy") in STRATEGIES else 0, key=f"strategy_{selected}")
            st.info(STRATEGY_INFO[r["strategy"]]["vorschlag"])
            st.caption("**Aussagegrenze:** " + STRATEGY_INFO[r["strategy"]]["aussage"])
        st.caption("* = Pflicht für die raumweise Grundbewertung. Für saisonübergreifendes Monitoring separate Betriebsfälle ausweisen.")
        with c2:
            dev_opts = [""] + [d["id"] for d in DEVICES] + ["extern"]
            cur = r.get("device_ref") or ("extern" if r.get("device_model") and not r.get("device_ref") else "")
            sel = st.selectbox("Messgerät (Gerätematrix)", dev_opts, index=dev_opts.index(cur) if cur in dev_opts else 0, key=f"devsel_{selected}",
                               format_func=lambda x: "Bitte auswählen" if x == "" else (EXTERN if x == "extern" else f"{DEV_BY_ID[x]['geraete_nr']} · {imp.device_label(DEV_BY_ID[x])}"))
            if sel == "extern":
                r["device_ref"] = ""
                r["device_model"] = st.text_input("Hersteller und Modell", r.get("device_model", "") if not DEV_BY_ID.get(r.get("device_ref")) else "", key=f"devext_{selected}")
            elif sel:
                d = DEV_BY_ID[sel]
                r["device_ref"], r["device_model"] = sel, imp.device_label(d)
                cov = imp.device_coverage(d)
                if not all(cov.values()):
                    st.error("Gerät misst nicht alle drei Pflichtgrössen: fehlt " + ", ".join(imp.PARAM_NAME[k] for k, v in cov.items() if not v) + ". Zweites Gerät nötig.")
                st.caption(f"Genauigkeit (Hersteller): {imp.device_accuracy(d) or 'k. A.'} · Datenformat: {d.get('daten_format') or 'k. A.'}")
            else:
                r["device_ref"] = ""
        with st.expander("Bedingt erforderlich: Nutzungszeit, Messzeitraum und Rückverfolgbarkeit"):
            c3, c4 = st.columns(2)
            with c3:
                r["start_date"] = st.text_input("Messbeginn (JJJJ-MM-TT)", r.get("start_date", ""), key=f"begin_{selected}")
                r["end_date"] = st.text_input("Messende (JJJJ-MM-TT)", r.get("end_date", ""), key=f"end_{selected}")
                r["measurement_interval_min"] = st.number_input("Sollintervall (Minuten, 0 = nicht angegeben)", min_value=0, max_value=1440, value=int(r.get("measurement_interval_min") or 0), key=f"interval_{selected}") or None
                st.caption("Nutzungszeit als Zeitplan (alternativ Kalender/Präsenzsensor auf Seite 3)")
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
                r["device_id"] = st.text_input("Seriennummer Messgerät", r.get("device_id", ""), key=f"device_{selected}")
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

elif page == "3 · Messwerte & Nutzung":
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
        st.markdown("**Datei vom Messgerät importieren** · wird automatisch vereinheitlicht (Lokalzeit, ppm, °C, %)")
        dev = DEV_BY_ID.get(r.get("device_ref"))
        prof = PROFILES_IMP.get(r.get("device_ref")) if dev else None
        if dev:
            rngs = ", ".join(f"{imp.PARAM_NAME[k]} {rg[0]:g}–{rg[1]:g} {imp.CANON_UNIT[k]}" for k in imp.PARAMS if (rg := imp.device_range(dev, k)))
            st.info(f"**Messgerät:** {imp.device_label(dev)} · Exportformat laut Gerätematrix: {dev.get('daten_format') or 'k. A.'}  \n"
                    f"Messbereich (Werte ausserhalb werden ausgeschlossen): {rngs or 'k. A.'}")
            st.caption("Geprüftes Importprofil vorhanden." if prof else
                       "Für dieses Gerät liegt noch keine geprüfte Beispieldatei vor: Spalten, Datumsformat und Einheiten werden automatisch erkannt – Zuordnung unten kontrollieren.")
        else:
            st.info("Kein Gerät aus der Gerätematrix gewählt (Seite 2). Externe Geräte: Datei im **IAQ-Standardformat** liefern.")
        with st.expander("IAQ-Standardformat für externe Geräte (Vorgabe)"):
            st.dataframe(pd.DataFrame(imp.STANDARD_SPEC, columns=["Spalte", "Inhalt und Einheit"]), hide_index=True)
            st.markdown("\n".join(f"- {x}" for x in imp.STANDARD_RULES))
            st.download_button("Vorlage IAQ-Standardformat (CSV)", imp.standard_template_csv(), file_name="IAQ_Standardformat_Vorlage.csv", mime="text/csv")
        uploaded = st.file_uploader("Gerätedatei (CSV, TXT, XLSX, JSON)", type=["csv", "txt", "xlsx", "json"], key=f"devfile_{rid}")
        if uploaded is not None:
            data = uploaded.getvalue()
            try:
                table = imp.read_table(data, uploaded.name)
            except Exception as exc:  # noqa: BLE001 – Meldung für Nutzer
                table = None
                st.error(f"Datei nicht lesbar: {exc}")
            if table and {"parameter", "value"} <= {str(h).strip().lower() for h in table["headers"]}:
                df = pd.DataFrame(table["rows"], columns=table["headers"]).astype(str)
                if st.button("Langformat (V7) importieren", key=f"long_{rid}"):
                    new, errs = import_measurements(df)
                    r["measurements"].extend(new)
                    st.success(f"{len(new)} Einzelwerte übernommen.")
                table = None
            if table:
                mp = imp.detect_mapping(table, prof)
                hdrs = table["headers"]
                st.caption(f"Erkannt: {table['meta'].get('format')} · Kopfzeile Nr. {table['meta'].get('header_row')} · {len(table['rows'])} Datenzeilen"
                           + (f" · Trennzeichen «{table['meta']['delimiter']}»" if table["meta"].get("delimiter") else "")
                           + (f" · Blatt «{table['meta']['sheet']}»" if table["meta"].get("sheet") else ""))
                for n in mp["notes"]:
                    st.caption(n)
                opts = [None] + list(range(len(hdrs)))
                fmt_col = lambda i: "– nicht vorhanden –" if i is None else f"{hdrs[i]}"
                cc = st.columns(5)
                labels = [("timestamp", "Zeitstempel"), ("date", "Datum (separat)"), ("time", "Uhrzeit (separat)"), ("co2", "CO₂"), ("temp", "Temperatur")]
                for col_, (k, lab) in zip(cc, labels):
                    cur = mp["columns"][k]
                    mp["columns"][k] = col_.selectbox(lab, opts, index=opts.index(cur), format_func=fmt_col, key=f"map_{k}_{rid}")
                cr = st.columns(5)
                cur = mp["columns"]["rh"]
                mp["columns"]["rh"] = cr[0].selectbox("Relative Feuchte", opts, index=opts.index(cur), format_func=fmt_col, key=f"map_rh_{rid}")
                fm = imp.mapping_formats(table, mp)
                dt_fmt = d_fmt = None
                if "dt" in fm:
                    choices = fm["dt"] or list(imp.DT_FORMATS)
                    dt_fmt = cr[1].selectbox("Datumsformat", choices, key=f"dtf_{rid}",
                                             help="Mehrere Einträge = Datei ist mehrdeutig (z. B. 03/04/2026). Bitte bewusst wählen.")
                    if not fm["dt"]:
                        cr[1].warning("Zeitformat nicht automatisch erkannt.")
                    elif len(fm["dt"]) > 1:
                        cr[1].warning("Datumsformat mehrdeutig – bitte bestätigen.")
                elif "date" in fm:
                    d_fmt = cr[1].selectbox("Datumsformat", fm["date"] or list(imp.D_FORMATS), key=f"df_{rid}")
                tz = cr[2].radio("Zeitbasis der Datei", ["Lokalzeit", "UTC"], index=0 if mp["tz"] == "Lokalzeit" else 1, key=f"tz_{rid}")
                avg_opts = [None, 1, 5, 10, 15]
                avg = cr[3].selectbox("Mittelung", avg_opts, format_func=lambda x: "keine (Originalintervall)" if x is None else f"{x}-min-Mittelwerte", key=f"avg_{rid}",
                                      help="Nur nötig bei Intervallen unter 1 Minute (Projektvorschlag: 5 min). Es werden keine Lücken gefüllt.")
                units, unconfirmed = {}, []
                cu = st.columns(3)
                for col_, k in zip(cu, imp.PARAMS):
                    det = mp["units"].get(k)
                    ch = imp.UNIT_CHOICES[k]
                    units[k] = col_.selectbox(f"Einheit {imp.PARAM_NAME[k]} in der Datei", ch, index=ch.index(det) if det in ch else 0, key=f"unit_{k}_{rid}")
                    if det is None:
                        unconfirmed.append(imp.PARAM_NAME[k])
                    elif det not in ch:
                        col_.error(f"Einheit «{det}» nicht eindeutig umrechenbar – Gerät auf ppm/°C/% umstellen.")
                ok_units = True
                if unconfirmed:
                    ok_units = st.checkbox("Einheiten geprüft: Datei enthält keine Einheitsangabe für " + ", ".join(unconfirmed) + " – gewählte Einheit gemäss Geräteeinstellung/Datenblatt bestätigt", key=f"uconf_{rid}")
                if ok_units:
                    try:
                        res = imp.convert(table, mp, dt_format=dt_fmt, date_format=d_fmt, units=units, tz_mode=tz, device=dev, average_min=avg)
                    except ValueError as exc:
                        res = None
                        st.warning(str(exc))
                    if res:
                        lg = res["log"]
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Datenzeilen", lg["rohzeilen"])
                        m2.metric("Messpunkte", lg["messpunkte"])
                        m3.metric("davon vollständig", lg["vollstaendig"])
                        m4.metric("Zeitraum", f"{(lg['von'] or '')[:10]} – {(lg['bis'] or '')[:10]}")
                        if lg["umrechnungen"]:
                            st.caption("Umrechnung: " + "; ".join(lg["umrechnungen"]))
                        if lg["ausschluesse"]:
                            st.dataframe(pd.DataFrame([{"Ausschluss / Bereinigung": k, "Anzahl": v} for k, v in lg["ausschluesse"].items()]), hide_index=True)
                        prev = pd.DataFrame(res["records"][:60]).pivot_table(index="timestamp", columns="parameter", values="value", aggfunc="first").head(8)
                        st.dataframe(prev)
                        replace = st.checkbox("Bestehende Messwerte dieses Raums ersetzen", value=False, key=f"repl_{rid}")
                        if st.button("Vereinheitlichte Daten übernehmen", type="primary", key=f"take_{rid}"):
                            if replace:
                                r["measurements"] = [m for m in r["measurements"] if m.get("parameter") not in CORE]
                            r["measurements"].extend(res["records"])
                            r.setdefault("import_log", []).append({"datei": uploaded.name, "importiert": datetime.now().strftime("%Y-%m-%d %H:%M"), **lg})
                            if not r.get("start_date") and lg["von"]:
                                r["start_date"], r["end_date"] = lg["von"][:10], lg["bis"][:10]
                            if not r.get("measurement_interval_min") and lg["median_intervall_s"] and not avg:
                                r["measurement_interval_min"] = max(1, round(lg["median_intervall_s"] / 60))
                            st.success(f"{lg['vollstaendig']} vollständige Messpunkte übernommen; Importprotokoll gespeichert.")
        if r.get("import_log"):
            with st.expander(f"Importprotokoll ({len(r['import_log'])} Import/e)"):
                st.dataframe(pd.DataFrame([{"Datei": x.get("datei"), "Gerät": x.get("geraet"), "Importiert": x.get("importiert"), "Von": x.get("von"), "Bis": x.get("bis"),
                                            "Messpunkte": x.get("messpunkte"), "Vollständig": x.get("vollstaendig"), "Ausschlüsse": sum((x.get("ausschluesse") or {}).values()),
                                            "Umrechnung": "; ".join(x.get("umrechnungen") or []) or "–"} for x in r["import_log"]]), hide_index=True)
        st.divider()
        st.markdown("**Nutzung / Belegung**")
        osrc = r.get("occupancy_source") if r.get("occupancy_source") in OCC_SOURCES else OCC_SOURCES[0]
        r["occupancy_source"] = st.radio("Quelle der Nutzungszeit", OCC_SOURCES, index=OCC_SOURCES.index(osrc), horizontal=True, key=f"osrc_{rid}")
        smp = long_to_samples(r)["samples"]
        span = (smp[0]["timestamp"], smp[-1]["timestamp"]) if smp else (None, None)
        if r["occupancy_source"] == OCC_SOURCES[1]:
            st.caption("Export des Raumkalenders, z. B. Outlook: Kalender → Freigeben/Speichern als .ics. Gezählt werden gebuchte Termine (Serien inkl. Ausnahmen); ganztägige und abgesagte Termine nicht. "
                       "Hinweis: Eine Buchung belegt nicht, dass der Raum tatsächlich genutzt wurde.")
            ics = st.file_uploader("Kalenderdatei (.ics)", type=["ics"], key=f"ics_{rid}")
            if ics is not None and st.button("Kalender einlesen", key=f"icsgo_{rid}"):
                try:
                    out = imp.parse_ics(ics.getvalue(), *span)
                    r["occupancy_intervals"], r["occupancy_import_log"] = out["intervals"], {"datei": ics.name, **out["log"]}
                    st.success(f"{out['log']['intervalle']} Belegungsintervalle ({out['log']['stunden']} h) im Messzeitraum übernommen.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Kalender nicht lesbar: {exc}")
        elif r["occupancy_source"] == OCC_SOURCES[2]:
            st.caption("Datei mit Zeitstempel und Präsenz (0/1, belegt/frei) oder Personenzahl je Zeile, z. B. Trendexport der Gebäudeautomation. Belegt = Wert > 0.")
            pres = st.file_uploader("Präsenzdaten (CSV, XLSX)", type=["csv", "txt", "xlsx"], key=f"pres_{rid}")
            if pres is not None and st.button("Präsenzdaten einlesen", key=f"presgo_{rid}"):
                try:
                    out = imp.parse_presence(pres.getvalue(), pres.name)
                    r["occupancy_intervals"], r["occupancy_import_log"] = out["intervals"], {"datei": pres.name, **out["log"]}
                    st.success(f"{out['log']['intervalle']} Belegungsintervalle ({out['log']['stunden']} h) übernommen.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Präsenzdaten nicht lesbar: {exc}")
        else:
            st.caption("Zeitplan wird auf Seite 2 erfasst (Wochentage + Von/Bis).")
        used = filter_usage(smp, r)
        st.write(f"**Nutzungszeit:** {usage_label(r)}" + (f" · {len(used)} von {len(smp)} Messpunkten in der Nutzungszeit" if used is not None and smp else ""))
        st.divider()
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
