"""IAQ-Nachweis · Berichtsvorlage A4 (druckfertiges HTML) · P6 V14.

Aufbau (fix, unabhängig vom Ergebnis):
  Seite 1      Zusammenfassung: Gebäude, Standort, Zeitraum, Gesamtergebnis, effektive Messwerte, Handlungsbedarf
  Seiten 2–4   Allgemeine Angaben: Projekt und Gebäude · Bewertungsgrundlagen · Messung, Datenqualität, Freigabe
  ab Seite 5   Raumblätter, 2 Räume je Seite (Raumnummer, Erfüllung der Kriterien, Auffälligkeiten)
Seiten = 4 + ⌈Räume / 2⌉, höchstens 50 Räume (29 Seiten).
Schrift mindestens 12 pt (ausgenommen Quellenverzeichnis und Seitenfuss).

Vorlage: build_report(..., template_rooms=7) erzeugt denselben Bericht mit Platzhaltern statt Werten.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date

from iaq_logic import (
    CORE, STATUS_CHECK, STATUS_DEV, STATUS_NA, STATUS_NAPP, STATUS_OK, STATUS_ORDER,
    STRATEGIES, TOPICS, TOL_SHARE, co2_classes, conditional_hints, describe,
    effective_ventilation, evaluate_room, filter_usage, long_to_samples, sample_weights, time_stats,
)

MAX_ROOMS = 50
ROOMS_PER_PAGE = 2
FIXED_PAGES = 4
MAX_ACTIONS = 5
NA = "nicht erfasst"

CSSK = {STATUS_OK: "ok", STATUS_DEV: "dev", STATUS_CHECK: "chk", STATUS_NA: "na", STATUS_NAPP: "na"}
VERDICT = {STATUS_OK: "Kriterien erfüllt", STATUS_DEV: "Kriterien nicht erfüllt",
           STATUS_CHECK: "Abklärung erforderlich", STATUS_NA: "Nicht bewertbar"}
MET = {STATUS_OK: "erfüllt", STATUS_DEV: "nicht erfüllt", STATUS_CHECK: "Abklärung", STATUS_NA: "nicht bewertbar",
       STATUS_NAPP: "nicht anwendbar"}

TOPIC_INFO = {
    "Luftqualität": {"krit": f"CO₂: höchstens {TOL_SHARE:g} % der Nutzungszeit über IDA 2, nie IDA 4; Abklärung ab 2'000 ppm",
                     "kurz": f"≤ {TOL_SHARE:g} % über IDA 2", "quelle": "SIA 382/1:2025 Ziff. 2.2.5.6, Tab. 18; SECO Abb. 316-4"},
    "Thermischer Komfort": {"krit": "Lufttemperatur Heizperiode 21–23 °C, Kühlperiode 23–26 °C, ohne Zeittoleranz",
                            "kurz": "21–23 / 23–26 °C", "quelle": "SECO Wegleitung ArGV 3, Abb. 316-1"},
    "Raumluftfeuchte": {"krit": f"r. F. unter 30 % (bei 21 °C) bzw. über 15,2 g/m³ je höchstens {TOL_SHARE:g} % der Nutzungszeit",
                        "kurz": "≥ 30 % r. F., ≤ 15,2 g/m³", "quelle": "SIA 180:2014 Ziff. 3.5.1.3, 3.5.1.4"},
    "Datenbasis": {"krit": "Jahresbezug bei Messung über ein Nutzungsjahr, sonst Indikation für den Messzeitraum",
                   "kurz": "≥ 1 Jahr Messdauer", "quelle": "SIA 180 / SIA 382/1: «jährliche Nutzungszeit»"},
}

SOURCES = [
    "SIA 382/1:2025 (SN 546382/1) Lüftungs- und Klimaanlagen: Ziff. 1.7.4.3, Tab. 18; Ziff. 2.2.5.4, 2.2.5.6.",
    "SIA 180:2014 (SN 520180) Wärmeschutz, Feuchteschutz und Raumklima in Gebäuden: Ziff. 3.5.1.3, 3.5.1.4, Anhang A.1.",
    "SECO (2020). Wegleitung zur ArGV 3, Art. 16 Raumklima: Abb. 316-1, 316-2, 316-4, S. 316-3.",
    "Bacher, L. (2025). Entwicklung eines Leitfadens zur Messung von CO₂. Bachelor-Thesis EUT-P6-24HS, FHNW.",
    "Minergie-ECO (2023). Vorgabenkatalog v2023.1, Vorgaben 110.04, 110.50, 120.03, 120.05.",
    "Hyndman, R. J. & Fan, Y. (1996). Sample Quantiles in Statistical Packages. The American Statistician, 50(4).",
    "GRESB (2026). Real Estate Reference Guide, TC5.2. · Dodd, Donatello & Cordella (2021). Level(s) indicator 4.1, JRC.",
]


# ---------------------------------------------------------------- Formatierung

def e(v) -> str:
    return html.escape(NA if v is None or str(v).strip() == "" else str(v))


def fnum(v, d=0) -> str:
    return "–" if v is None else f"{v:,.{d}f}".replace(",", "'")


def fpct(v) -> str:
    return "–" if v is None else (f"{v:.0f} %" if v in (0, 100) else f"{v:.1f} %")


def fdt(dt) -> str:
    return "–" if not dt else dt.strftime("%d.%m.%Y")


def natkey(s) -> list:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", str(s or ""))]


def page_plan(n: int) -> dict:
    """Seitenplan: 4 feste Seiten + 2 Räume je Seite, höchstens 50 Räume."""
    n = max(0, min(int(n), MAX_ROOMS))
    room_pages = math.ceil(n / ROOMS_PER_PAGE)
    return {"rooms": n, "fixed": FIXED_PAGES, "room_pages": room_pages, "pages": FIXED_PAGES + room_pages}


# ---------------------------------------------------------------- Gebäude

def buildings_of(project: dict) -> list[dict]:
    """Hauptgebäude + weitere Gebäude (Name; Standort; Höhe m ü. M.; Objekt-ID), je Zeile."""
    main = dict(project.get("building") or {})
    out = [main]
    for line in str(project.get("buildings_extra") or "").splitlines():
        parts = [x.strip() for x in line.split(";")]
        if parts and parts[0]:
            out.append({"name": parts[0], "location": parts[1] if len(parts) > 1 else "",
                        "altitude_m": parts[2] if len(parts) > 2 else "", "object_id": parts[3] if len(parts) > 3 else ""})
    return out


def building_for(project: dict, room: dict) -> dict:
    name = str(room.get("building") or "").strip()
    for b in buildings_of(project):
        if name and str(b.get("name") or "").strip() == name:
            return b
    return project.get("building") or {}


# ---------------------------------------------------------------- Datenmodell (echte Werte)

def room_bundle(room, assessment, rules, building) -> dict:
    parsed = long_to_samples(room)
    samples = parsed["samples"]
    usage = filter_usage(samples, room)
    basis = usage if usage else samples
    ev = evaluate_room(room, assessment, rules, building)
    return {"room": room, "parsed": parsed, "samples": samples, "basis": basis, "ev": ev, "st": ev["status"],
            "stats": describe(basis) if basis else {}, "time": time_stats(samples, room.get("measurement_interval_min")),
            "co2cls": co2_classes(basis) if basis else [0, 0, 0, 0], "required": ev["required"],
            "hints": conditional_hints(room, assessment, parsed), "vent": effective_ventilation(room) or room.get("ventilation"),
            "building": building}


def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _count_text(items: list, limit: int = 3) -> str:
    c: dict[str, int] = {}
    for x in items:
        if x:
            c[x] = c.get(x, 0) + 1
    parts = [f"{k} ({v})" for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:limit]]
    return ", ".join(parts) + (" …" if len(c) > limit else "") if parts else NA


def _topic_result(b, t) -> str:
    tp = b["ev"]["topics"].get(t, {})
    st = tp.get("status")
    if t == "Datenbasis":
        return f"{tp['tage']} Messtage" if tp.get("tage") else "–"
    if st in (STATUS_NA, STATUS_NAPP) or tp.get("kpi") is None:
        return "–"
    return fpct(tp["kpi"])


def _findings(b) -> list[str]:
    ev, out = b["ev"], []
    out += [k for k in ev.get("kurz", []) if k]
    c = b["stats"].get("CO₂")
    if c and c["max"] >= 2000 and not any("2'000" in x or "2000" in x for x in out):
        out.append(f"CO₂-Spitze {fnum(c['max'])} ppm (≥ 2'000 ppm)")
    out += b["required"][:2]
    out += [h for h in b["hints"] if "Positionierung" in h or "Messhöhe" in h or "Messgeräte" in h or "Nutzung" in h][:2]
    out = list(dict.fromkeys(out))
    return out or ["Keine Auffälligkeiten in den bewerteten Kriterien."]


def build_model(project: dict, rules: list, rooms: list | None = None, meta: dict | None = None) -> dict:
    a = project["assessment"]
    rooms = (project["rooms"] if rooms is None else rooms)[:MAX_ROOMS]
    meta = {"date": date.today().strftime("%d.%m.%Y"), **(project.get("report") or {}), **(meta or {})}
    bs = [room_bundle(r, a, rules, building_for(project, r)) for r in rooms]
    bs.sort(key=lambda b: natkey(b["room"].get("name")))
    n = len(bs)
    # Gebäude
    blds = []
    for bd in buildings_of(project):
        cnt = sum(1 for b in bs if b["building"] is bd or (str(b["building"].get("name")) == str(bd.get("name"))))
        if cnt or bd is buildings_of(project)[0]:
            blds.append({"name": bd.get("name"), "location": bd.get("location"), "object_id": bd.get("object_id"),
                         "altitude_m": bd.get("altitude_m"), "owner": bd.get("owner"), "hours": bd.get("operating_hours"), "rooms": cnt})
    blds = [x for x in blds if x["rooms"]] or blds[:1]
    starts = [b["time"]["beginn"] for b in bs if b["time"]]
    ends = [b["time"]["ende"] for b in bs if b["time"]]
    start, end = (min(starts), max(ends)) if starts else (None, None)
    days = (end - start).days + 1 if start else None
    n_eval = sum(1 for b in bs if b["st"] != STATUS_NA)
    n_ok = sum(1 for b in bs if b["st"] == STATUS_OK)
    n_need = sum(1 for b in bs if b["st"] in (STATUS_DEV, STATUS_CHECK))
    worst = next((s for s in STATUS_ORDER if any(b["st"] == s for b in bs)), STATUS_NA)
    if not n:
        overall = ("na", "Keine Räume erfasst", "")
    elif n_need:
        overall = (CSSK[worst], f"{n_need} von {n} Räumen erfüllen die Kriterien nicht", f"{n_ok} Räume erfüllt · {n - n_eval} nicht bewertbar")
    elif n_ok == n:
        overall = ("ok", f"Alle {n} Räume erfüllen die Kriterien im Messzeitraum", "")
    else:
        overall = ("na", f"{n_ok} von {n} Räumen erfüllen die Kriterien", f"{n - n_eval} Räume nicht bewertbar")
    jahr = sum(1 for b in bs if b["ev"]["jahr"])
    # Fokusthemen
    topics = []
    for t in TOPICS[:3]:
        sts = [b["ev"]["topics"].get(t, {}).get("status") for b in bs]
        kp = [b["ev"]["topics"].get(t, {}).get("kpi") for b in bs]
        kp = [x for x in kp if x is not None]
        topics.append({"name": t, "krit": TOPIC_INFO[t]["kurz"], "ok": sts.count(STATUS_OK), "nok": sts.count(STATUS_DEV),
                       "chk": sts.count(STATUS_CHECK), "na": sts.count(STATUS_NA) + sts.count(STATUS_NAPP),
                       "kpi": (f"{fpct(_median(kp))} ({fpct(min(kp))} – {fpct(max(kp))})" if kp else "–")})
    allb = [s for b in bs for s in b["basis"]]
    st_all = describe(allb) if allb else {}
    values = [{"param": p, "unit": u, **({k: fnum(st_all[p][k], 0 if p == "CO₂" else 1) for k in ("min", "median", "p95", "max")}
                                       if p in st_all else {k: "–" for k in ("min", "median", "p95", "max")})} for p, u in CORE.items()]
    hours = sum(sum(sample_weights(b["basis"], b["room"].get("measurement_interval_min"))) for b in bs if b["basis"]) / 60
    pts = sum(len(b["samples"]) for b in bs)
    need = sorted([b for b in bs if b["st"] in (STATUS_DEV, STATUS_CHECK)], key=lambda b: (STATUS_ORDER.index(b["st"]), natkey(b["room"].get("name"))))
    actions = [{"room": b["room"].get("name"), "css": CSSK[b["st"]], "label": VERDICT[b["st"]],
                "text": "; ".join(_findings(b)[:2])} for b in need]
    # Allgemeine Angaben
    def cnt_strat(s):
        return sum(1 for b in bs if b["room"].get("strategy") == s)
    devmap: dict[str, dict] = {}
    try:
        import iaq_import as imp
        devdb = {d["id"]: d for d in imp.load_devices()}
    except Exception:  # noqa: BLE001
        imp, devdb = None, {}
    for b in bs:
        r = b["room"]
        name = str(r.get("device_model") or "").strip() or "nicht angegeben"
        d = devmap.setdefault(name, {"name": name, "rooms": 0, "acc": "", "range": ""})
        d["rooms"] += 1
        dev = devdb.get(r.get("device_ref"))
        if dev and imp:
            d["acc"] = imp.device_accuracy(dev) or "k. A."
            d["range"] = ", ".join(f"{imp.PARAM_NAME[k]} {rg[0]:g}–{rg[1]:g}" for k in imp.PARAMS if (rg := imp.device_range(dev, k)))
    heights = [float(str(b["room"].get("sensor_height_m")).replace(",", ".")) for b in bs
               if re.fullmatch(r"\d+([.,]\d+)?", str(b["room"].get("sensor_height_m") or "").strip())]
    excl = sum(sum((lg.get("ausschluesse") or {}).values()) for b in bs for lg in (b["room"].get("import_log") or []))
    conv = sorted({c for b in bs for lg in (b["room"].get("import_log") or []) for c in (lg.get("umrechnungen") or [])})
    covs = [b["time"].get("abdeckung_pct") for b in bs if b["time"]]
    general = {
        "scope": [
            ("Anzahl Gebäude · Räume", f"{len(blds)} · {n}"),
            ("Messzeitraum", f"{fdt(start)} – {fdt(end)} ({days or '–'} Tage)"),
            ("Messart", " · ".join(f"{s}: {cnt_strat(s)}" for s in STRATEGIES if cnt_strat(s)) or NA),
            ("Lüftungsart", _count_text([b["vent"] for b in bs])),
            ("Raumnutzung", _count_text([b["room"].get("use") for b in bs])),
            ("Nutzungszeit erfasst", f"{sum(1 for b in bs if filter_usage(b['samples'], b['room']) is not None)} von {n} Räumen"),
            ("Bewertungsprofil · Betriebsfall", f"{a.get('basis') or NA} · {a.get('period') or NA}"),
            ("Besonderheiten", a.get("notes") or "keine"),
        ],
        "devices": list(devmap.values())[:5], "devices_more": max(0, len(devmap) - 5),
        "setup": [
            ("Messhöhe", f"{min(heights):g}–{max(heights):g} m" if heights else NA),
            ("Positionierung bestätigt", f"{sum(1 for b in bs if b['room'].get('position_check'))} von {n} Räumen"),
            ("Kalibrierung dokumentiert", f"{sum(1 for b in bs if str(b['room'].get('calibration') or '').strip())} von {n} Räumen"),
        ],
        "quality": [
            ("Vollständige Messpunkte", fnum(pts)),
            ("Messstunden in der Nutzungszeit", fnum(hours)),
            ("Zeitabdeckung (Median der Räume)", fpct(_median(covs))),
            ("Beim Import ausgeschlossene Werte", fnum(excl)),
            ("Einheiten umgerechnet", "; ".join(conv[:3]) or "keine"),
            ("Räume mit Jahresbezug", f"{jahr} von {n}"),
            ("Räume mit offenen Angaben", f"{sum(1 for b in bs if b['hints'] or b['required'])} von {n}"),
        ],
    }
    # Raumblätter
    room_rows = []
    for b in bs:
        r, t = b["room"], b["time"]
        c, T, H = (b["stats"].get(k) for k in ("CO₂", "Temperatur", "Relative Feuchte"))
        room_rows.append({
            "no": r.get("name"), "desc": " · ".join(x for x in [r.get("use"), f"Geschoss {r['floor']}" if r.get("floor") else "",
                                                             f"{fnum(float(r['area_m2']))} m²" if r.get("area_m2") not in (None, "") else "",
                                                             b["building"].get("name") if len(blds) > 1 else ""] if x),
            "css": CSSK.get(b["st"], "na"), "verdict": VERDICT.get(b["st"], b["st"]),
            "topics": [{"name": tt, "krit": TOPIC_INFO[tt]["kurz"], "result": _topic_result(b, tt),
                        "met": (("Jahresbezug" if b["ev"]["topics"].get(tt, {}).get("status") == "Jahresbezug" else "Indikation")
                                if b["st"] != STATUS_NA else "nicht bewertbar")
                        if tt == "Datenbasis" else MET.get(b["ev"]["topics"].get(tt, {}).get("status"), "–"),
                        "css": ("ok" if b["ev"]["topics"].get(tt, {}).get("status") == "Jahresbezug" else "na") if tt == "Datenbasis"
                        else CSSK.get(b["ev"]["topics"].get(tt, {}).get("status"), "na")} for tt in TOPICS],
            "values": [("CO₂ Median / P95 / Max", f"{fnum(c['median'])} / {fnum(c['p95'])} / {fnum(c['max'])} ppm" if c else "–"),
                       ("Temperatur Min – Max", f"{fnum(T['min'], 1)} – {fnum(T['max'], 1)} °C" if T else "–"),
                       ("Rel. Feuchte Min – Max", f"{fnum(H['min'], 1)} – {fnum(H['max'], 1)} %" if H else "–")],
            "findings": _findings(b),
            "info": f"{fdt(t.get('beginn'))} – {fdt(t.get('ende'))} · {r.get('strategy') or NA} · {b['vent'] or NA} · Gerät: {r.get('device_model') or NA}" if t
                    else f"keine Messwerte · {r.get('strategy') or NA}",
        })
    return {"meta": meta, "title": blds[0].get("name") if blds else project.get("building", {}).get("name"),
            "buildings": blds, "period": f"{fdt(start)} – {fdt(end)}", "days": f"{days} Tage" if days else "–",
            "n_rooms": str(n), "n_buildings": str(len(blds)), "overall": overall, "jahr": f"{jahr} von {n}",
            "points": fnum(pts), "hours": fnum(hours), "messart": " · ".join(s for s in STRATEGIES if cnt_strat(s)) or NA,
            "profile": f"{a.get('basis') or NA} · {a.get('period') or NA}", "period_case": a.get("period") or NA,
            "status_counts": [(VERDICT[s], CSSK[s], str(sum(1 for b in bs if b["st"] == s))) for s in (STATUS_OK, STATUS_DEV, STATUS_CHECK, STATUS_NA)],
            "topics": topics, "values": values, "actions": actions, "general": general, "rooms": room_rows, "template": False}


# ---------------------------------------------------------------- Datenmodell (Vorlage mit Platzhaltern)

def P(label: str) -> str:
    return f"⟨{label}⟩"


def template_model(n_rooms: int = 7, n_buildings: int = 1) -> dict:
    n = max(1, min(int(n_rooms), MAX_ROOMS))
    blds = [{"name": P(f"Gebäudebezeichnung {i + 1}" if n_buildings > 1 else "Gebäudebezeichnung"), "location": P("Strasse Nr., PLZ Ort"),
             "object_id": P("Objekt-ID"), "altitude_m": P("Höhe"), "owner": P("Eigentümer / Betreiber"), "hours": P("Betriebszeiten"),
             "rooms": P("Anzahl Räume")} for i in range(n_buildings)]
    gen = {
        "scope": [("Anzahl Gebäude · Räume", f"{n_buildings} · {n}"), ("Messzeitraum", f"{P('TT.MM.JJJJ')} – {P('TT.MM.JJJJ')} ({P('Anzahl')} Tage)"),
                  ("Messart", P("Stichprobenmessung / Messkampagne / Langzeitmessung: Anzahl Räume je Messart")),
                  ("Lüftungsart", P("Lüftungsarten mit Anzahl Räumen")), ("Raumnutzung", P("Nutzungen mit Anzahl Räumen")),
                  ("Nutzungszeit erfasst", f"{P('Anzahl')} von {n} Räumen"), ("Bewertungsprofil · Betriebsfall", f"{P('Profil')} · {P('Heiz- oder Kühlperiode')}"),
                  ("Besonderheiten", P("Besonderheiten zum Nachweis oder «keine»"))],
        "devices": [{"name": P("Hersteller Modell"), "rooms": P("Anzahl"), "acc": P("Genauigkeit CO₂ / T / r. F. laut Gerätematrix"),
                     "range": P("Messbereich")}], "devices_more": 0,
        "setup": [("Messhöhe", P("von–bis m")), ("Positionierung bestätigt", f"{P('Anzahl')} von {n} Räumen"),
                  ("Kalibrierung dokumentiert", f"{P('Anzahl')} von {n} Räumen")],
        "quality": [("Vollständige Messpunkte", P("Anzahl")), ("Messstunden in der Nutzungszeit", P("Stunden")),
                    ("Zeitabdeckung (Median der Räume)", P("%")), ("Beim Import ausgeschlossene Werte", P("Anzahl")),
                    ("Einheiten umgerechnet", P("z. B. °F → °C oder «keine»")), ("Räume mit Jahresbezug", f"{P('Anzahl')} von {n}"),
                    ("Räume mit offenen Angaben", f"{P('Anzahl')} von {n}")],
    }
    rooms = [{"no": P(f"Raumnummer {i + 1}"), "desc": f"{P('Nutzung')} · Geschoss {P('Nr.')} · {P('Fläche')} m²",
              "css": "ph", "verdict": P("Einordnung Raum"),
              "topics": [{"name": t, "krit": TOPIC_INFO[t]["kurz"],
                          "result": (f"{P('Anz.')} Messtage" if t == "Datenbasis" else P("%")),
                          "met": P("Bezug") if t == "Datenbasis" else P("Bewertung"), "css": "ph"} for t in TOPICS],
              "values": [("CO₂ Median / P95 / Max", f"{P('ppm')} / {P('ppm')} / {P('ppm')} ppm"),
                         ("Temperatur Min – Max", f"{P('°C')} – {P('°C')} °C"), ("Rel. Feuchte Min – Max", f"{P('%')} – {P('%')} %")],
              "findings": [P("Auffälligkeit 1, z. B. «Luftqualität: 14 % der Nutzungszeit über IDA 2»"),
                           P("Auffälligkeit 2 oder «Keine Auffälligkeiten in den bewerteten Kriterien.»")],
              "info": f"{P('TT.MM.JJJJ')} – {P('TT.MM.JJJJ')} · {P('Messart')} · {P('Lüftungsart')} · Gerät: {P('Hersteller Modell')}"}
             for i in range(n)]
    return {"meta": {"report_no": P("Berichtsnr."), "version": P("Version"), "date": P("Datum"), "author": P("Verfasser/in")},
            "title": blds[0]["name"], "buildings": blds, "period": f"{P('TT.MM.JJJJ')} – {P('TT.MM.JJJJ')}", "days": f"{P('Anzahl')} Tage",
            "n_rooms": str(n), "n_buildings": str(n_buildings),
            "overall": ("ph", f"{P('Anzahl')} von {n} Räumen erfüllen die Kriterien nicht", f"{P('Anzahl')} Räume erfüllt · {P('Anzahl')} nicht bewertbar"),
            "jahr": f"{P('Anz.')} von {n}", "points": P("Anzahl"), "hours": P("Stunden"),
            "messart": P("Messart(en)"), "period_case": P("Periode"), "need_n": f"{P('Anzahl')} Räume", "profile": f"{P('Bewertungsprofil')} · {P('Heiz- oder Kühlperiode')}",
            "status_counts": [(VERDICT[s], CSSK[s], P("Anzahl")) for s in (STATUS_OK, STATUS_DEV, STATUS_CHECK, STATUS_NA)],
            "topics": [{"name": t, "krit": TOPIC_INFO[t]["kurz"], "ok": P("Anz."), "nok": P("Anz."), "chk": P("Anz."), "na": P("Anz."),
                        "kpi": f"{P('Median %')} ({P('min')} – {P('max')})"} for t in TOPICS[:3]],
            "values": [{"param": p, "unit": u, "min": P("Wert"), "median": P("Wert"), "p95": P("Wert"), "max": P("Wert")} for p, u in CORE.items()],
            "actions": [{"room": P("Raumnummer"), "css": "ph", "label": P("Einordnung"), "text": P("wichtigste Auffälligkeit des Raums")} for _ in range(3)],
            "general": gen, "rooms": rooms, "template": True}


# ---------------------------------------------------------------- Gestaltung

CSS = """
@page{size:A4;margin:13mm 15mm 14mm 15mm;@bottom-left{content:'IAQ-Nachweis Innenraumluftqualität · Vorlage P6 V14';font:8pt Arial;color:#667085}@bottom-right{content:'Seite ' counter(page) ' von ' counter(pages);font:8pt Arial;color:#667085}}
*{box-sizing:border-box}
:root{--ink:#101828;--muted:#475467;--line:#d0d5dd;--soft:#f5f7fa;--accent:#1d3a5f;
--ok:#1f7a4d;--dev:#b54708;--chk:#b42318;--na:#667085;--ph:#6941c6}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;font:12pt/1.35 Arial,"Helvetica Neue",sans-serif;color:var(--ink);background:#e4e7ec}
.page{width:210mm;height:297mm;margin:8mm auto;background:#fff;padding:13mm 15mm 14mm;box-shadow:0 1px 6px rgba(0,0,0,.16);position:relative;overflow:hidden}
@media print{body{background:#fff}.page{margin:0;box-shadow:none;width:auto;height:270mm;padding:0;break-after:page}.page:last-child{break-after:auto}.noprint{display:none}}
h1{font-size:19pt;margin:0;color:var(--accent);line-height:1.15;font-weight:700}
h2{font-size:14pt;color:var(--accent);margin:0 0 2mm;padding-bottom:1mm;border-bottom:1px solid var(--line)}
h3{font-size:12pt;margin:0 0 1.5mm}
p{margin:0 0 2mm}.muted{color:var(--muted)}
section>*:last-child{margin-bottom:0}
table{width:100%;border-collapse:collapse;margin:0 0 4mm;font-size:12pt;table-layout:fixed}
th,td{border-bottom:1px solid var(--line);padding:1.3mm 1.8mm;text-align:left;vertical-align:top;overflow:hidden}
th{font-weight:700;color:var(--muted);border-bottom:1.5px solid var(--accent)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.c,th.c{text-align:center}
.kv td:first-child{color:var(--muted);width:40%}
.one{white-space:nowrap;text-overflow:ellipsis}
.clamp2{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--accent);padding-bottom:2.5mm;margin-bottom:4mm}
.top .meta{text-align:right;color:var(--muted);line-height:1.4}
.kicker{font-weight:700;color:var(--muted);letter-spacing:.4px;text-transform:uppercase}
.run{display:flex;justify-content:space-between;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:1.5mm;margin-bottom:4mm}
.run b{color:var(--accent)}.run span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.run span+span{flex:0 0 auto;margin-left:4mm}
.facts{border-top:1px solid var(--line)}.facts td{padding:.6mm 1.6mm}.facts td.k{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.result{border-left:5px solid var(--na);background:var(--soft);padding:2mm 4mm;margin-bottom:3mm}
.result .big{font-size:15pt;font-weight:700;line-height:1.2}
.result.ok{border-color:var(--ok)}.result.dev{border-color:var(--dev)}.result.chk{border-color:var(--chk)}.result.ph{border-color:var(--ph)}
.counts{display:flex;flex-wrap:wrap;column-gap:5mm;margin-top:1.2mm}
.st{display:inline-flex;align-items:center;gap:1.6mm;white-space:nowrap}
.st i{display:inline-block;width:3mm;height:3mm;border-radius:.6mm;background:var(--na);flex:0 0 3mm}
.st.ok i{background:var(--ok)}.st.dev i{background:var(--dev)}.st.chk i{background:var(--chk)}.st.ph i{background:var(--ph)}
.st.ok{color:var(--ok)}.st.dev{color:var(--dev)}.st.chk{color:var(--chk)}.st.na{color:var(--na)}.st.ph{color:var(--ph)}
.st b{font-weight:700}
.need{border:1.5px solid var(--line);padding:1.6mm 3.5mm;margin-bottom:2mm}
.need h3{color:var(--accent)}
.need table{margin:0}.need td{border-bottom:1px solid #eaecf0;padding:.8mm 1.6mm}
.foot{color:var(--muted);border-top:1px solid var(--line);padding-top:1.5mm}
.room{border:1.5px solid var(--line);padding:3mm 3.6mm;height:123mm;margin-bottom:5mm;overflow:hidden}
.room .rh{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--accent);padding-bottom:1.5mm;margin-bottom:2mm}
.room .no{font-size:17pt;font-weight:700;color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:105mm}
.room .verdict{font-size:13pt}
.room table{margin-bottom:2mm}
.room ul{margin:0 0 1mm;padding-left:5mm}.room li{margin-bottom:.3mm}
.vals{display:grid;grid-template-columns:repeat(3,1fr);gap:3mm;margin-bottom:2mm}
.vals div{background:var(--soft);padding:1.3mm 2mm}.vals span{display:block;color:var(--muted)}.vals b{white-space:nowrap}
.info{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ph-note{border:1.5px dashed var(--ph);color:var(--ph);padding:2mm 3mm;margin-bottom:3mm}
.sig{display:grid;grid-template-columns:1fr 1fr;gap:12mm;margin-top:8mm}
.sig div{border-top:1px solid var(--ink);padding-top:1.2mm;color:var(--muted)}
.src{font-size:8.5pt;color:var(--muted);padding-left:4.5mm;margin:0 0 3mm}.src li{margin-bottom:.3mm}
.p1{line-height:1.28}.p1 table{margin-bottom:3mm}.p1 h2{margin-bottom:1.5mm}.p1 th,.p1 td{padding-top:1mm;padding-bottom:1mm}
.printbtn{position:fixed;right:16px;top:16px;background:#1d3a5f;color:#fff;border:0;padding:9px 14px;border-radius:6px;font:700 13px Arial;cursor:pointer;z-index:9}
.demo{position:absolute;top:4mm;right:15mm;font-size:9pt;font-weight:700;color:var(--chk);letter-spacing:.5px}
@media print{.demo{top:-8mm;right:0}}
"""


def st(css, text, bold=False) -> str:
    return f"<span class='st {css}'><i></i>{'<b>' if bold else ''}{e(text)}{'</b>' if bold else ''}</span>"


def _top(M, kicker, demo):
    m = M["meta"]
    loc = M["buildings"][0].get("location") if len(M["buildings"]) == 1 else f"{len(M['buildings'])} Gebäude"
    return (("<div class='demo'>BEISPIELDATEN – SYNTHETISCH</div>" if demo else "")
            + f"<div class='top'><div><div class='kicker'>{e(kicker)}</div><h1>{e(M['title'])}</h1><div class='muted'>{e(loc)}</div></div>"
              f"<div class='meta'>Bericht {e(m.get('report_no'))} · Version {e(m.get('version'))}<br>{e(m.get('date'))}<br>{e(m.get('author'))}</div></div>")


def _run(M, title, right=None):
    return (f"<div class='run'><span><b>{e(title)}</b> · {e(M['title'])}</span>"
            f"<span>{e(right) if right else 'Bericht ' + e(M['meta'].get('report_no'))}</span></div>")


def _kv(rows):
    return "<table class='kv'>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows) + "</table>"


# ---------------------------------------------------------------- Seite 1

def _page1(M, demo):
    blds = M["buildings"]
    bld = (f"{blds[0].get('name') or NA}, {blds[0].get('location') or NA}" if len(blds) == 1
           else "; ".join(f"{b.get('name')} ({b.get('location') or NA})" for b in blds[:3]) + (" …" if len(blds) > 3 else ""))
    full = [("Gebäude / Standort", bld), ("Zeitraum", f"{M['period']} ({M['days']})"), ("Messart", M["messart"])]
    pairs = [("Gebäude", M["n_buildings"]), ("Räume", M["n_rooms"]),
             ("Messpunkte", M["points"]), ("Messstunden", M["hours"]),
             ("Jahresbezug", f"{M['jahr']} Räumen"), ("Betriebsfall", M.get("period_case", ""))]
    facts = ("".join(f"<tr><td class='k'>{e(k)}</td><td colspan='3' class='one'><b>{e(v)}</b></td></tr>" for k, v in full)
             + "".join(f"<tr><td class='k'>{e(pairs[i][0])}</td><td class='one'><b>{e(pairs[i][1])}</b></td>"
                       f"<td class='k'>{e(pairs[i + 1][0])}</td><td class='one'><b>{e(pairs[i + 1][1])}</b></td></tr>" for i in range(0, len(pairs), 2)))
    css, big, sub = M["overall"]
    short = {VERDICT[STATUS_OK]: "erfüllt", VERDICT[STATUS_DEV]: "nicht erfüllt", VERDICT[STATUS_CHECK]: "Abklärung", VERDICT[STATUS_NA]: "nicht bewertbar"}
    counts = "".join(f"<span>{st(c, f'{short[lab]}: {v}')}</span>" for lab, c, v in M["status_counts"])
    trows = "".join(f"<tr><td><b>{e(t['name'])}</b><br><span class='muted'>{e(t['krit'])}</span></td>"
                    f"<td class='c'>{e(t['ok'])}</td><td class='c'>{e(t['nok'])}</td><td class='c'>{e(t['chk'])}</td><td class='c'>{e(t['na'])}</td>"
                    f"<td class='n'>{e(t['kpi']).replace(' (', '<br><span class=muted>(', 1)}{'</span>' if ' (' in t['kpi'] else ''}</td></tr>" for t in M["topics"])
    vrows = "".join(f"<tr><td>{e(v['param'])} [{e(v['unit'])}]</td><td class='n'>{e(v['min'])}</td><td class='n'>{e(v['median'])}</td>"
                    f"<td class='n'>{e(v['p95'])}</td><td class='n'>{e(v['max'])}</td></tr>" for v in M["values"])
    acts = M["actions"]
    if acts:
        arows = "".join(f"<tr><td class='one'><b>{e(x['room'])}</b></td><td class='one'>{st(x['css'], short.get(x['label'], x['label']))}</td>"
                        f"<td class='one'>{e(x['text'])}</td></tr>" for x in acts[:MAX_ACTIONS])
        more = f"<p class='muted' style='margin:1.2mm 0 0'>+ {len(acts) - MAX_ACTIONS} {'weiterer Raum' if len(acts) - MAX_ACTIONS == 1 else 'weitere Räume'} mit Handlungsbedarf (Raumblätter).</p>" if len(acts) > MAX_ACTIONS else ""
        cnt = M.get("need_n") or f"{len(acts)} {'Raum' if len(acts) == 1 else 'Räume'}"
        need = (f"<div class='need'><h3>Handlungsbedarf ({e(cnt)})</h3><table><colgroup><col style='width:27%'><col style='width:20%'><col></colgroup>"
                f"{arows}</table>{more}</div>")
    else:
        need = "<div class='need'><h3>Handlungsbedarf</h3><p style='margin:0'>Kein Raum mit Abweichung oder Abklärungsbedarf in den bewerteten Kriterien.</p></div>"
    ph = ("<div class='ph-note'>Vorlage: Werte in ⟨ ⟩ setzt das Tool aus den erfassten Daten ein.</div>" if M["template"] else "")
    return f"""<section class='page p1'>{_top(M, 'IAQ-Nachweis · Zusammenfassung', demo)}{ph}
<table class='facts'><colgroup><col style='width:25%'><col style='width:25%'><col style='width:25%'><col style='width:25%'></colgroup>{facts}</table>
<div class='result {css}'><div class='big'>{e(big)}</div><div class='counts'>{counts}</div></div>
<h2>Ergebnis nach Fokusthema</h2>
<table><colgroup><col style='width:33%'><col style='width:11%'><col style='width:12%'><col style='width:14%'><col style='width:9%'><col style='width:21%'></colgroup>
<tr><th>Fokusthema · Kriterium</th><th class='c'>erfüllt</th><th class='c'>verfehlt</th><th class='c'>Abklärung</th><th class='c'>n. b.</th><th class='n'>Zeitanteil*</th></tr>{trows}</table>
<h2>Effektive Messwerte (alle Räume, Nutzungszeit)</h2>
<table><colgroup><col style='width:36%'><col><col><col><col></colgroup><tr><th>Messgrösse</th><th class='n'>Minimum</th><th class='n'>Median</th><th class='n'>P95</th><th class='n'>Maximum</th></tr>{vrows}</table>
{need}
<p class='foot'>* Anteil Nutzungszeit im Kriterium: Median (Spanne). n. b. = nicht bewertbar. Grundlagen S. 2–4.</p>
</section>"""


# ---------------------------------------------------------------- Seiten 2–4

def _page2(M):
    rows = "".join(f"<tr><td class='one'><b>{e(b.get('name'))}</b></td><td class='one'>{e(b.get('location'))}</td><td class='one'>{e(b.get('object_id'))}</td>"
                   f"<td class='n'>{e(b.get('altitude_m'))}</td><td class='n'>{e(b.get('rooms'))}</td></tr>" for b in M["buildings"][:6])
    b0 = M["buildings"][0]
    more = [("Eigentümer / Betreiber", b0.get("owner")), ("Übliche Betriebszeiten", b0.get("hours"))]
    m = M["meta"]
    rep = [("Berichtsnummer · Version", f"{m.get('report_no') or NA} · {m.get('version') or NA}"), ("Erstellt am", m.get("date")), ("Verfasser/in", m.get("author"))]
    return f"""<section class='page'>{_run(M, 'Allgemeine Angaben 1/3 · Projekt und Gebäude')}
<h2>Gebäude</h2>
<table><colgroup><col style='width:27%'><col style='width:33%'><col style='width:16%'><col style='width:13%'><col style='width:11%'></colgroup>
<tr><th>Gebäude</th><th>Standort</th><th>Objekt-ID</th><th class='n'>m ü. M.</th><th class='n'>Räume</th></tr>{rows}</table>
{_kv(more)}
<h2>Untersuchungsumfang</h2>{_kv(M['general']['scope'])}
<h2>Bericht</h2>{_kv(rep)}
</section>"""


def _page3():
    crit = "".join(f"<tr><td><b>{e(t)}</b></td><td>{e(TOPIC_INFO[t]['krit'])}</td><td>{e(TOPIC_INFO[t]['quelle'])}</td></tr>" for t in TOPICS)
    defs = [("ok", VERDICT[STATUS_OK], "Alle anwendbaren Kriterien in der Nutzungszeit des Messzeitraums eingehalten."),
            ("dev", VERDICT[STATUS_DEV], "Mindestens ein Kriterium verfehlt (z. B. mehr als 10 % der Nutzungszeit ausserhalb)."),
            ("chk", VERDICT[STATUS_CHECK], "CO₂ ≥ 2'000 ppm (SECO: hygienisch inakzeptabel) oder IDA 4: Ursache klären."),
            ("na", VERDICT[STATUS_NA], "Pflichtangaben oder Messwerte fehlen; keine Aussage möglich.")]
    drows = "".join(f"<tr><td>{st(c, n, True)}</td><td>{e(t)}</td></tr>" for c, n, t in defs)
    return f"""<section class='page'>
<div class='run'><span><b>Allgemeine Angaben 2/3 · Bewertungsgrundlagen</b></span><span></span></div>
<h2>Kriterien je Fokusthema</h2>
<table><colgroup><col style='width:23%'><col style='width:45%'><col style='width:32%'></colgroup><tr><th>Fokusthema</th><th>Kriterium</th><th>Quelle</th></tr>{crit}</table>
<h2>Einordnung eines Raums</h2>
<table><colgroup><col style='width:38%'><col></colgroup>{drows}</table>
<h2>Bewertungsregeln</h2>
<table class='kv'>
<tr><td>Gesamtergebnis Raum</td><td>Ungünstigstes Ergebnis aus Luftqualität, Thermischem Komfort und Raumluftfeuchte.</td></tr>
<tr><td>10 %-Regel</td><td>Nur wo die Norm sie nennt (CO₂: SIA 382/1 Ziff. 2.2.5.6; Feuchte: SIA 180 Ziff. 3.5.1.3/3.5.1.4). Der Nachweis bestätigt die Vorgaben im Normalbetrieb; zulässig sind Abweichungen in höchstens 10 % der Nutzungszeit eines Jahres.</td></tr>
<tr><td>Zeitbezug</td><td>Anteile zeitgewichtet über die Nutzungszeit (Belegungsplan oder Präsenzsensor); ohne Nutzungszeit über die gesamte Messzeit.</td></tr>
<tr><td>Lüftungsarten</td><td>IDA-Klassen für alle Lüftungsarten (SIA 382/1:2025 Tab. 18, Fussnote 3).</td></tr>
</table>
</section>"""


def _page4(M):
    g = M["general"]
    drows = "".join(f"<tr><td class='one'><b>{e(d['name'])}</b></td><td class='n'>{e(d['rooms'])}</td><td>{e(d['acc'] or 'k. A.')}</td></tr>" for d in g["devices"])
    more = f"<p class='muted'>{g['devices_more']} weitere Gerätetypen im Tool.</p>" if g["devices_more"] else ""
    m = M["meta"]
    return f"""<section class='page'>
<div class='run'><span><b>Allgemeine Angaben 3/3 · Messung, Datenqualität und Freigabe</b></span><span>Bericht {e(m.get('report_no'))}</span></div>
<h2>Messgeräte</h2>
<table><colgroup><col style='width:38%'><col style='width:12%'><col></colgroup><tr><th>Gerät</th><th class='n'>Räume</th><th>Genauigkeit (Herstellerangabe)</th></tr>{drows}</table>{more}
{_kv(g['setup'])}
<h2>Datenbasis und Datenqualität</h2>{_kv(g['quality'])}
<h2>Quellen</h2><ol class='src'>{''.join(f'<li>{e(s)}</li>' for s in SOURCES)}</ol>
<div class='sig'><div>Erstellt: {e(m.get('author'))}, Datum</div><div>Geprüft / freigegeben, Datum</div></div>
</section>"""


# ---------------------------------------------------------------- Raumblätter

def _room(R):
    trows = "".join(f"<tr><td><b>{e(t['name'])}</b></td><td class='one'>{e(t['krit'])}</td><td class='one'>{e(t['result'])}</td><td>{st(t['css'], t['met'])}</td></tr>"
                    for t in R["topics"])
    vals = "".join(f"<div><span>{e(k)}</span><b>{e(v)}</b></div>" for k, v in R["values"])
    fnd = R["findings"]
    fl = "".join(f"<li><div class='clamp2'>{e(x)}</div></li>" for x in fnd[:3]) + (f"<li class='muted'>{len(fnd) - 3} weitere im Tool</li>" if len(fnd) > 3 else "")
    return f"""<div class='room'><div class='rh'><div><div class='no'>{e(R['no'])}</div><div class='muted one'>{e(R['desc'] or '')}</div></div>
<div class='verdict'>{st(R['css'], R['verdict'], True)}</div></div>
<table><colgroup><col style='width:25%'><col style='width:31%'><col style='width:21%'><col style='width:23%'></colgroup>
<tr><th>Fokusthema</th><th>Kriterium</th><th>Zeitanteil*</th><th>Bewertung</th></tr>{trows}</table>
<div class='vals'>{vals}</div>
<h3>Auffälligkeiten</h3><ul>{fl}</ul>
<div class='info'>{e(R['info'])}</div></div>"""


def _room_pages(M):
    rs = M["rooms"]
    out = []
    for k in range(0, len(rs), ROOMS_PER_PAGE):
        out.append(f"<section class='page'>{_run(M, f'Raumblätter {k // ROOMS_PER_PAGE + 1}/{math.ceil(len(rs) / ROOMS_PER_PAGE)}', '* Zeitanteil = Anteil Nutzungszeit im Kriterium')}"
                   + "".join(_room(R) for R in rs[k:k + ROOMS_PER_PAGE]) + "</section>")
    return "".join(out)


# ---------------------------------------------------------------- Zusammenbau

def render(M: dict, demo: bool = False) -> str:
    body = _page1(M, demo) + _page2(M) + _page3() + _page4(M) + _room_pages(M)
    return (f"<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>IAQ-Nachweis – {e(M['title'])}</title><style>{CSS}</style></head><body>"
            f"<button class='printbtn noprint' onclick='window.print()'>Als PDF drucken (A4)</button>{body}</body></html>")


def build_report(project: dict | None = None, rules: list | None = None, rooms: list | None = None, meta: dict | None = None,
                 demo: bool = False, template_rooms: int | None = None, template_buildings: int = 1) -> str:
    """Bericht als HTML (A4; im Browser «Als PDF drucken»). Mit template_rooms: Vorlage mit Platzhaltern."""
    if template_rooms:
        return render(template_model(template_rooms, template_buildings))
    return render(build_model(project, rules or [], rooms, meta), demo=demo)
