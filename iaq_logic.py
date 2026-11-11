"""Testbare IAQ-Erfassungs- und Screening-Logik für die P6-Bachelor-Thesis.

Methodische Projektregeln, keine gesetzliche Konformitätsprüfung.
Messwerte basieren auf Lufttemperatur; operative Temperatur wird nicht geschätzt.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
from typing import Any

CORE = {"CO₂": "ppm", "Temperatur": "°C", "Relative Feuchte": "%"}
CORE_ORDER = tuple(CORE)
STRATEGIES = ["Stichproben- / Kontrollmessung", "Temporäre Messkampagne", "Kontinuierliches Monitoring"]
PURPOSES = [
    "Ersteinschätzung / Kontrolle",
    "Dokumentierte IAQ-Performance im Messzeitraum",
    "Langfristiger Verlauf / saisonale Entwicklung",
    "Orientierungswertvergleich / Abklärungsbedarf",
]
STRATEGY_INFO = {
    STRATEGIES[0]: {
        "zweck": "Zustand zum Messzeitpunkt beschreiben und Auffälligkeiten feststellen.",
        "vorschlag": "Einzelmessung oder kurze Messreihe während tatsächlicher Nutzung; genaue Uhrzeit erfassen.",
        "aussage": "Momentaufnahme. Keine Aussage über Wochen-, Saison- oder Jahresqualität.",
    },
    STRATEGIES[1]: {
        "zweck": "IAQ-Verlauf unter dokumentierten Betriebsbedingungen erfassen.",
        "vorschlag": "Projektvorschlag (nicht normativ): fünf Arbeitstage, alle fünf Minuten; Nutzungsphasen und Abweichungen festhalten.",
        "aussage": "Gilt für den gemessenen Zeitraum. Eine Übertragung auf das Jahr erfordert gesonderte Repräsentativitätsprüfung.",
    },
    STRATEGIES[2]: {
        "zweck": "Wiederkehrende Auffälligkeiten und längerfristige Entwicklungen erfassen.",
        "vorschlag": "Projektvorschlag (nicht normativ): mehrmonatige Messung, typischerweise alle 5–15 Minuten; Wartung, Datenlücken und Nutzungszeiten dokumentieren.",
        "aussage": "Gilt für tatsächlich erfasste Zeiten und Saisons; ein Jahresnachweis erfordert geeignete Jahresabdeckung und Methode.",
    },
}
PROFILE_SIA = "SIA 382/1:2025"
PROFILE_SECO = "SECO / ArGV 3"
PROFILE_ECO = "Minergie-ECO"
PROFILE_BT = "Bachelor-Thesis – eigenes Bewertungsmodell"
PROFILES = [PROFILE_SIA, PROFILE_SECO, PROFILE_ECO, PROFILE_BT]
VENTS = ["Mechanische Lüftung", "Natürliche Lüftung / Fensterlüftung", "Kombinierte / hybride Lüftung"]
PERIODS = ["Heizperiode", "Kühlperiode"]


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def normalize_param(value: Any) -> str | None:
    s = str(value or "").strip().lower().replace(" ", "").replace("_", "")
    aliases = {
        "co₂": "CO₂", "co2": "CO₂", "kohlenstoffdioxid": "CO₂",
        "temperatur": "Temperatur", "temp": "Temperatur", "lufttemperatur": "Temperatur",
        "relativefeuchte": "Relative Feuchte", "relfeuchte": "Relative Feuchte",
        "r.f.": "Relative Feuchte", "rf": "Relative Feuchte", "rh": "Relative Feuchte",
        "feuchte": "Relative Feuchte", "relativeluftfeuchte": "Relative Feuchte",
    }
    return aliases.get(s)


def valid_value(param: str, value: Any) -> tuple[float | None, str | None]:
    try:
        v = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None, "kein Zahlenwert"
    if not math.isfinite(v):
        return None, "nicht endlicher Zahlenwert"
    # Reine Plausibilitätsfilter für Büro-Sensormessungen (Projektannahmen, keine Normgrenzen).
    limits = {"CO₂": (250, 10000), "Temperatur": (-10, 50), "Relative Feuchte": (0, 100)}
    if param in limits:
        lo, hi = limits[param]
        if not lo <= v <= hi:
            return None, f"ausserhalb des technischen Plausibilitätsbereichs {lo}–{hi}"
    return v, None


def long_to_samples(room: dict) -> dict:
    """Alle drei Kernwerte mit identischem Zeitstempel bilden einen gültigen Messpunkt.

    Ungültige und unvollständige Zeitpunkte sind sichtbar; es gibt keine Interpolation.
    """
    grouped: dict[datetime, dict] = defaultdict(dict)
    issues: list[str] = []
    seen: set[tuple[datetime, str]] = set()
    for idx, m in enumerate(room.get("measurements", []), start=1):
        param = normalize_param(m.get("parameter"))
        if param is None:  # Zusatzparameter bleiben in Originaldaten erhalten, nicht im Kernscreening
            continue
        ts = parse_timestamp(m.get("timestamp"))
        if ts is None:
            issues.append(f"Zeile {idx}: fehlender oder ungültiger Zeitstempel")
            continue
        unit = str(m.get("unit", "") or CORE[param]).strip()
        if unit != CORE[param]:
            issues.append(f"{ts:%d.%m.%Y %H:%M} · {param}: Einheit {unit!r} statt {CORE[param]}")
            continue
        value, reason = valid_value(param, m.get("value"))
        if reason:
            issues.append(f"{ts:%d.%m.%Y %H:%M} · {param}: {reason}")
            continue
        key = (ts, param)
        if key in seen:
            issues.append(f"{ts:%d.%m.%Y %H:%M} · {param}: mehrfach erfasst; Zeitpunkt ausgeschlossen")
            grouped[ts][param] = None
        elif param not in grouped[ts]:
            grouped[ts][param] = value
        seen.add(key)
    samples = []
    for ts, vals in sorted(grouped.items()):
        missing = [p for p in CORE if vals.get(p) is None]
        if missing:
            issues.append(f"{ts:%d.%m.%Y %H:%M}: unvollständiger Messpunkt ({', '.join(missing)})")
        else:
            samples.append({"timestamp": ts, **{k: vals[k] for k in CORE}})
    return {"samples": samples, "issues": issues, "zeitpunkte": len(grouped), "vollstaendig": len(samples)}


def effective_ventilation(room: dict) -> str | None:
    v = room.get("ventilation")
    if v == VENTS[0]:
        return "Mechanisch"
    if v == VENTS[1]:
        return "Natürlich"
    if v == VENTS[2]:
        mode = str(room.get("ventilation_mode", "")).strip().lower()
        if mode == "mechanisch":
            return "Hybrid – mechanischer Modus"
        if mode in ("natürlich", "natuerlich"):
            return "Hybrid – natürlicher Modus"
    return None


def match_bt_rule(rules: list, period: str, room: dict) -> dict | None:
    vent = effective_ventilation(room)
    cooling = bool(room.get("active_cooling")) if period == "Kühlperiode" else False
    return next((r for r in rules if r["periode"] == period and r["lueftung"] == vent and r["aktive_kuehlung"] == cooling), None)


def _num(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def required_issues(room: dict, assessment: dict) -> list[str]:
    """Nur für eine einfache Kernmesspunkt-Bewertung wirklich notwendige Angaben."""
    issues = []
    if not (room.get("name") or "").strip():
        issues.append("Raum-ID / Raumbezeichnung fehlt")
    if room.get("ventilation") not in VENTS:
        issues.append("Lüftungsart fehlt")
    elif room.get("ventilation") == VENTS[2] and effective_ventilation(room) is None:
        issues.append("Aktueller hybrider Lüftungsmodus fehlt")
    if assessment.get("period") not in PERIODS:
        issues.append("Heiz-/Kühlperiode fehlt")
    if assessment.get("basis") not in PROFILES:
        issues.append("Bewertungsprofil fehlt")
    if room.get("strategy") not in STRATEGIES:
        issues.append("Messstrategie fehlt")
    if not assessment.get("purpose") or assessment.get("purpose") not in PURPOSES:
        issues.append("Nachweiszweck fehlt")
    if not long_to_samples(room)["samples"]:
        issues.append("Kein vollständiger Messpunkt mit Zeitstempel, CO₂, Temperatur und r. F.")
    return issues


def conditional_hints(room: dict, assessment: dict, parsed: dict | None = None) -> list[str]:
    """Nur dann kritisch, wenn aus der Messung ein weitergehender Nachweis abgeleitet wird."""
    parsed = parsed or long_to_samples(room)
    hints = []
    strat = room.get("strategy")
    purpose = assessment.get("purpose")
    if strat != STRATEGIES[0]:
        if not room.get("measurement_interval_min"):
            hints.append("Aufzeichnungsintervall für Messreihe fehlt")
        if not room.get("start_date") or not room.get("end_date"):
            hints.append("Geplanter Messbeginn / Messende nicht dokumentiert")
        if not str(room.get("data_gaps", "")).strip():
            hints.append("Ausfälle und Datenlücken nicht dokumentiert")
    if purpose in (PURPOSES[1], PURPOSES[2]) or strat == STRATEGIES[2]:
        if not usage_defined(room):
            hints.append("Nutzungszeit (Wochentage + Von/Bis) nicht strukturiert erfasst: keine nutzungszeitbezogene Auswertung")
        if not str(room.get("occupancy_log", "")).strip():
            hints.append("Belegungs-/Nutzungsprotokoll fehlt: Repräsentativität ungeprüft")
    if purpose == PURPOSES[2] and strat != STRATEGIES[2]:
        hints.append("Langfristiger Nachweiszweck mit dieser Messstrategie nicht belastbar")
    if strat == STRATEGIES[2] and assessment.get("period") in PERIODS:
        hints.append("Saisonübergreifende Reihen getrennt nach Betriebsfall prüfen; globales Profil gilt nur für gewählten Betriebsfall")
    if strat != STRATEGIES[0] and len(parsed["samples"]) < 2:
        hints.append("Für Zeitverläufe sind mindestens zwei vollständige Zeitpunkte erforderlich")
    if len(parsed["samples"]) > 1 and room.get("measurement_interval_min"):
        expected = float(room["measurement_interval_min"])
        deltas = [(b["timestamp"] - a["timestamp"]).total_seconds() / 60 for a, b in zip(parsed["samples"], parsed["samples"][1:])]
        if any(d > 1.5 * expected for d in deltas):
            hints.append("Zeitlücken > 1,5 × Sollintervall: Zeitabdeckung prüfen")
    if parsed["issues"]:
        hints.append("Unvollständige/ungültige Messpunkte vorhanden; Ausschlüsse dokumentieren")
    if assessment.get("basis") == PROFILE_SIA and effective_ventilation(room) in ("Mechanisch", "Hybrid – mechanischer Modus"):
        if room.get("outdoor_co2_ppm") is None:
            hints.append("Aussen-CO₂ nicht gemessen: SIA-IDA-2-Vergleich nur mit 400-ppm-Annahme")
    if purpose in (PURPOSES[1], PURPOSES[2]) and not str(room.get("selection_reason", "")).strip():
        hints.append("Raumauswahlgrund fehlt: keine nachgewiesene Repräsentativität der Mehrraumauswahl")
    if purpose in (PURPOSES[1], PURPOSES[2]) and not str(room.get("heating_system", "")).strip():
        hints.append("Gebäudetechnische Randbedingungen unvollständig (z. B. Heizsystem / Regelung)")
    if not str(room.get("measurement_position", "")).strip():
        hints.append("Sensorposition nicht dokumentiert: Repräsentativität eingeschränkt")
    # Messpositionierung nach Bacher (2025), FHNW-Thesis EUT-P6-24HS: Messhöhe 0,75–1,25 m; 1 Messgerät je 50 m²
    h = _num(room.get("sensor_height_m"))
    if h is None:
        hints.append("Messhöhe nicht erfasst (empfohlen 0,75–1,25 m; Bacher 2025)")
    elif not 0.75 <= h <= 1.25:
        hints.append(f"Messhöhe {h:g} m ausserhalb der Empfehlung 0,75–1,25 m (Bacher 2025)")
    area, n_dev = _num(room.get("area_m2")), _num(room.get("sensor_count"))
    if area:
        need = math.ceil(area / 50)
        if n_dev is None:
            hints.append(f"Anzahl Messgeräte nicht erfasst: bei {area:g} m² empfohlen {need} (1 je 50 m²; Bacher 2025)")
        elif n_dev < need:
            hints.append(f"{n_dev:g} Messgerät(e) für {area:g} m²: empfohlen {need} (1 je 50 m²; Bacher 2025)")
    if not room.get("position_check"):
        hints.append("Positionierung nicht bestätigt: Abstand zu Tür, Fenster, Zuluft und Personen prüfen (Bacher 2025)")
    if not str(room.get("device_id", "")).strip() and not str(room.get("device_model", "")).strip():
        hints.append("Messgerät nicht identifiziert: Rückverfolgbarkeit eingeschränkt")
    return list(dict.fromkeys(hints))


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _hm(value: Any):
    try:
        return datetime.strptime(str(value).strip(), "%H:%M").time()
    except (ValueError, TypeError):
        return None


def usage_defined(room: dict) -> bool:
    """Strukturierte Nutzungszeit (Wochentage + Von/Bis) ist erfasst."""
    s, e = _hm(room.get("usage_start")), _hm(room.get("usage_end"))
    return bool(room.get("usage_days")) and s is not None and e is not None and s < e


def usage_label(room: dict) -> str:
    if not usage_defined(room):
        return "nicht strukturiert erfasst"
    days = [d for d in WEEKDAYS if d in room["usage_days"]]
    return f"{', '.join(days)} {room['usage_start']}–{room['usage_end']}"


def filter_usage(samples: list, room: dict) -> list | None:
    """Messpunkte innerhalb der erfassten Nutzungszeit (Beginn inklusive, Ende exklusive).

    None, wenn keine strukturierte Nutzungszeit erfasst ist. Es wird nichts geschätzt.
    """
    if not usage_defined(room):
        return None
    s, e = _hm(room["usage_start"]), _hm(room["usage_end"])
    days = set(room["usage_days"])
    return [x for x in samples if WEEKDAYS[x["timestamp"].weekday()] in days and s <= x["timestamp"].time() < e]


def percentile(values: list, q: float) -> float:
    """Lineare Interpolation zwischen Rangwerten (Hyndman & Fan 1996, Typ 7; Standard in numpy/pandas)."""
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def describe(samples: list) -> dict:
    out = {}
    for param in CORE:
        v = [s[param] for s in samples]
        if not v:
            continue
        out[param] = {"min": min(v), "p5": percentile(v, 0.05), "median": percentile(v, 0.5),
                      "mittel": sum(v) / len(v), "p95": percentile(v, 0.95), "max": max(v)}
    return out


def time_stats(samples: list, interval_min: Any = None) -> dict:
    """Faktische Zeitabdeckung der vollständigen Messpunkte (keine Annahmen)."""
    if not samples:
        return {}
    ts = [s["timestamp"] for s in samples]
    deltas = [(b - a).total_seconds() / 60 for a, b in zip(ts, ts[1:])]
    res = {"beginn": ts[0], "ende": ts[-1], "dauer_h": (ts[-1] - ts[0]).total_seconds() / 3600,
           "tage": len({t.date() for t in ts}), "n": len(ts),
           "median_intervall_min": percentile(deltas, 0.5) if deltas else None,
           "max_luecke_min": max(deltas) if deltas else None,
           "soll_intervall_min": None, "erwartet": None, "abdeckung_pct": None}
    if interval_min and deltas:
        iv = float(interval_min)
        expected = int(round((ts[-1] - ts[0]).total_seconds() / 60 / iv)) + 1
        res.update({"soll_intervall_min": iv, "erwartet": expected,
                    "abdeckung_pct": min(100.0, len(ts) / expected * 100)})
    return res


CO2_CLASS_LABELS = ["< 1'000 ppm · gut bis sehr gut", "1'000–1'400 ppm · mässig",
                    "> 1'400–2'000 ppm · niedrig", "≥ 2'000 ppm · hygienisch inakzeptabel"]
CO2_CLASS_SOURCE = "SECO, Wegleitung ArGV 3, Art. 16 (Aug. 2020), Abb. 316-4"


def co2_classes(samples: list) -> list[float]:
    """Anteil Messpunkte je CO₂-Klasse nach SECO Abb. 316-4.

    Grenzwerte: 1'000 ppm gehört wie im Zielwert (< 1'000) zur 2. Klasse; 2'000 ppm zur
    4. Klasse ('spätestens ab Erreichen von 2'000 ppm', S. 316-5).
    """
    if not samples:
        return [0.0, 0.0, 0.0, 0.0]
    counts = [0, 0, 0, 0]
    for s in samples:
        c = s["CO₂"]
        counts[0 if c < 1000 else 1 if c <= 1400 else 2 if c < 2000 else 3] += 1
    return [x / len(samples) * 100 for x in counts]


IDA_LABELS = ["IDA 1 · hoch (ΔCO₂ ≤ 550)", "IDA 2 · mittel (> 550…≤ 800)", "IDA 3 · moderat (> 800…≤ 1'350)", "IDA 4 · niedrig (> 1'350)"]
IDA_SOURCE = "SIA 382/1:2025, Ziff. 1.7.4.3, Tab. 18"


def outdoor_reference(room: dict) -> tuple[float, bool]:
    """Aussenluft-CO₂: gemessener Wert oder 400 ppm (Bezugswert der Tab. 18, Fussnote 2). (Wert, gemessen?)"""
    raw = room.get("outdoor_co2_ppm")
    if raw is not None:
        v, err = valid_value("CO₂", raw)
        if not err:
            return v, True
    return 400.0, False


def ida_classes(samples: list, outdoor: float = 400.0) -> list[float]:
    """Anteil Messpunkte je IDA-Klasse nach ΔCO₂ = innen − aussen (SIA 382/1:2025, Tab. 18).

    Tab. 18, Fussnote 3: Aussenluft kann mechanisch und/oder natürlich zugeführt werden –
    die Klassierung ist daher beschreibend für alle Lüftungsarten verwendbar.
    ΔCO₂ ≤ 0 wird IDA 1 zugeordnet (Innenwert nicht über Aussenwert).
    """
    if not samples:
        return [0.0, 0.0, 0.0, 0.0]
    counts = [0, 0, 0, 0]
    for s in samples:
        d = s["CO₂"] - outdoor
        counts[0 if d <= 550 else 1 if d <= 800 else 2 if d <= 1350 else 3] += 1
    return [x / len(samples) * 100 for x in counts]


def _schwuele_out(s: dict, limits: list) -> bool:
    for t_from, rh_max in sorted(limits, reverse=True):
        if s["Temperatur"] >= t_from:
            return s["Relative Feuchte"] >= rh_max
    return False


def screening(room: dict, assessment: dict, rules: list, subset: str = "alle") -> dict:
    """Zählung vollständiger Messpunkte ausserhalb eines anwendbaren Referenzwerts.

    subset = "alle" oder "nutzung" (nur strukturiert erfasste Nutzungszeit).
    Keine Zeitgewichtung, keine Zertifizierung, keine Rechtskonformität.
    """
    parsed = long_to_samples(room)
    samples = parsed["samples"]
    if subset == "nutzung":
        samples = filter_usage(samples, room) or []
    basis = assessment.get("basis")
    target = match_bt_rule(rules, assessment.get("period"), room)
    results = []
    note = "Anzahl vollständiger Messzeitpunkte; keine zeitgewichtete Auswertung und kein Rechtsnachweis."
    if not samples:
        return {"samples": 0, "rows": [], "note": "Keine auswertbaren vollständigen Messpunkte.", "data": parsed, "subset": subset}
    if basis in (PROFILE_SECO, PROFILE_BT) and target:
        checks = [
            ("CO₂", "< 1'000 ppm", lambda s: s["CO₂"] >= target["co2_target_exclusive"], target["quellen"]["co2"]),
            ("Temperatur", f'{target["temp_min"]:g}–{target["temp_max"]:g} °C', lambda s: s["Temperatur"] < target["temp_min"] or s["Temperatur"] > target["temp_max"], target["quellen"]["temp"]),
            ("Relative Feuchte", f'{target["rh_min"]:g}–{target["rh_max"]:g} %', lambda s: s["Relative Feuchte"] < target["rh_min"] or s["Relative Feuchte"] > target["rh_max"], target["quellen"]["rh"]),
        ]
        if target.get("rh_schwuele"):
            checks.append(("r. F. Schwülegrenze", "ab 24 °C < 60 %, ab 26 °C < 55 %, ab 28 °C < 50 %",
                           lambda s: _schwuele_out(s, target["rh_schwuele"]), target["quellen"].get("rh_schwuele", target["quellen"]["rh"])))
        for param, label, out, source in checks:
            bad = sum(bool(out(s)) for s in samples)
            results.append({"Parameter": param, "Referenz": label, "Ausserhalb": bad, "Messpunkte": len(samples), "Anteil [%]": round(bad / len(samples) * 100, 1), "Typ": "Orientierungswert", "Quelle": source})
    elif basis == PROFILE_SIA:
        pass  # SIA ist unten im zusätzlichen Referenzvergleich berücksichtigt.
    elif basis == PROFILE_ECO:
        note += " ECO 2023 besitzt keine eigenen Betriebsgrenzen für CO₂, T und r. F.; Schadstoff-Zertifizierung wird nicht aus diesen Werten abgeleitet."
    # Für SIA selbst und als **getrennte** SIA-Ergänzung bei BT/ECO:
    if basis in (PROFILE_SIA, PROFILE_BT, PROFILE_ECO):
        outdoor_raw = room.get("outdoor_co2_ppm")
        outdoor, error = valid_value("CO₂", outdoor_raw) if outdoor_raw is not None else (400.0, None)
        if error:
            note += " Ungültige Aussenluftkonzentration; kein SIA-IDA-Vergleich."
        else:
            # Alle Lüftungsarten: SIA 382/1:2025, Tab. 18, Fussnote 3 (Aussenluft mechanisch und/oder natürlich)
            threshold = outdoor + 800
            bad = sum(s["CO₂"] > threshold for s in samples)
            src = "SIA 382/1:2025, Tab. 18; Obergrenze IDA 2: ΔCO₂ ≤ 800 ppm; alle Lüftungsarten (Fussnote 3)"
            if outdoor_raw is None:
                src += "; Aussenluft 400 ppm (Bezugswert Tab. 18, Fussnote 2; nicht gemessen)"
            kind = "IDA-2-Klassengrenze, orientierender Vergleich" if basis == PROFILE_SIA else "SIA-Ergänzungswert"
            results.append({"Parameter": "CO₂ (SIA zusätzlich)" if basis != PROFILE_SIA else "CO₂", "Referenz": f"≤ {threshold:g} ppm (aussen + 800)", "Ausserhalb": bad, "Messpunkte": len(samples), "Anteil [%]": round(bad / len(samples) * 100, 1), "Typ": kind, "Quelle": src})
        if basis == PROFILE_SIA:
            note += " Lufttemperatur ist nicht operative Temperatur; keine automatische IEQ-II-Temperaturprüfung."
    if subset == "nutzung":
        note += f" Bezug: Nutzungszeit ({usage_label(room)})."
    return {"samples": len(samples), "rows": results, "note": note, "data": parsed, "subset": subset}


STATUS_OK = "Anforderungen im Messzeitraum eingehalten"
STATUS_DEV = "Abweichungen festgestellt"
STATUS_CHECK = "Weiterführende Abklärung empfohlen"
STATUS_NA = "Nicht bewertbar"
STATUS_NAPP = "Nicht anwendbar"
STATUS_ORDER = [STATUS_CHECK, STATUS_DEV, STATUS_OK, STATUS_NA]

# ---------------------------------------------------------------- IAQ-Nachweismodell P6 (Fokusthemen)
# Zeitanteile beziehen sich auf die Nutzungszeit. Die Normen formulieren die 10 %-Regel für die
# «jährliche Nutzungszeit in einem typischen Jahr» – ein Jahresnachweis setzt daher eine Messung
# über ein Nutzungsjahr voraus; kürzere Messungen liefern eine Indikation für diesen Zeitraum.
TOL_SHARE = 10.0                    # % der jährlichen Nutzungszeit
R_V = 461.5                         # J/(kg·K), spezifische Gaskonstante Wasserdampf
RH_DESIGN_T = 21.0                  # °C, Auslegungswert Raumlufttemperatur Winter Büro (SIA 180, Ziff. 3.5.1.3, Fn. 2)
NU_UPPER = 15.2                     # g/m³ (SIA 180, Ziff. 3.5.1.4)
YEAR_DAYS = 365
SRC_CO2_RULE = "SIA 382/1:2025, Ziff. 2.2.5.4 und 2.2.5.6, Tab. 18"
SRC_CO2_CHECK = "SECO Wegleitung ArGV 3, Art. 16, Abb. 316-4"
SRC_RH_LOW = "SIA 180:2014, Ziff. 3.5.1.3"
SRC_RH_HIGH = "SIA 180:2014, Ziff. 3.5.1.4"
SRC_T = "SECO Wegleitung ArGV 3, Art. 16, Abb. 316-1"
TOPICS = ["Luftqualität", "Thermischer Komfort", "Raumluftfeuchte", "Datenbasis"]


def p_sat(theta: float) -> float:
    """Wasserdampf-Sättigungsdruck in Pa (SIA 180:2014, Anhang A.1, nach SN EN ISO 13788)."""
    if theta >= 0:
        return 610.5 * math.exp(17.269 * theta / (237.3 + theta))
    return 610.5 * math.exp(21.875 * theta / (265.5 + theta))


def abs_humidity(theta: float, rh: float) -> float:
    """Volumenbezogene Raumluftfeuchte ν in g/m³ = φ · p_sat / (R_v · T)."""
    return rh / 100 * p_sat(theta) / (R_V * (theta + 273.15)) * 1000


def rh_lower_limit(altitude_m: float) -> float:
    """Untere r.-F.-Grenze: 30 % bis 800 m ü.M., darüber −1 % pro 100 m (SIA 180, Ziff. 3.5.1.3)."""
    return 30.0 - max(0.0, (altitude_m - 800.0) / 100.0)


def sample_weights(samples: list, interval_min: Any = None) -> list[float]:
    """Zeitgewicht je Messpunkt in Minuten: Abstand zum nächsten Punkt, höchstens ein Messintervall
    (Sollintervall, sonst Median-Intervall). Lücken werden nicht aufgefüllt (keine Interpolation)."""
    if not samples:
        return []
    ts = [s["timestamp"] for s in samples]
    deltas = [(b - a).total_seconds() / 60 for a, b in zip(ts, ts[1:])]
    cap = float(interval_min) if interval_min else (percentile(deltas, 0.5) if deltas else 1.0)
    return [min(d, cap) for d in deltas] + [cap]


def _share(samples: list, weights: list, pred) -> float:
    tot = sum(weights)
    return sum(w for s, w in zip(samples, weights) if pred(s)) / tot * 100 if tot else 0.0


def evaluate_room(room: dict, assessment: dict, rules: list, building: dict | None = None) -> dict:
    """Fokusthemen-Bewertung nach IAQ-Nachweismodell P6 (Profil-unabhängig, alle Lüftungsarten)."""
    building = building or {}
    req = required_issues(room, assessment)
    parsed = long_to_samples(room)
    allp = parsed["samples"]
    out = {"required": req, "topics": {}, "status": STATUS_NA, "gruende": [], "kurz": [], "bezug": "–", "jahr": False, "kpi": {}}
    if req:
        out["gruende"] = req
        out["kurz"] = req[:1]
        for t in TOPICS:
            out["topics"][t] = {"status": STATUS_NA, "text": "Pflichtangaben fehlen", "kpi": None}
        return out
    weights_all = sample_weights(allp, room.get("measurement_interval_min"))
    wmap = {s["timestamp"]: w for s, w in zip(allp, weights_all)}
    use = filter_usage(allp, room)
    base = use if use else allp
    w = [wmap[s["timestamp"]] for s in base]
    out["bezug"] = "Nutzungszeit " + usage_label(room) if use else "gesamte Messzeit (Nutzungszeit nicht erfasst)"
    ts = time_stats(allp, room.get("measurement_interval_min"))
    span_days = (ts["ende"] - ts["beginn"]).days + 1 if ts else 0
    out["jahr"] = span_days >= YEAR_DAYS
    zeit = "jährliche Nutzungszeit" if out["jahr"] else f"Nutzungszeit im Messzeitraum ({span_days} Tage, Indikation)"
    period = assessment.get("period")
    vent = effective_ventilation(room)
    mech = vent in ("Mechanisch", "Hybrid – mechanischer Modus")
    cooled = bool(room.get("active_cooling")) and period == "Kühlperiode"

    # Luftqualität: IDA 2 mit 10 %-Regel; ≥ 2'000 ppm -> Abklärung
    outdoor, measured = outdoor_reference(room)
    sh_ida2 = _share(base, w, lambda s: s["CO₂"] - outdoor > 800)
    sh_ida4 = _share(base, w, lambda s: s["CO₂"] - outdoor > 1350)
    sh_lt1000 = _share(base, w, lambda s: s["CO₂"] < 1000)
    co2_max = max(s["CO₂"] for s in base)
    kurz = f"{sh_ida2:.1f} % der Zeit über IDA 2"
    if co2_max >= 2000:
        st, txt = STATUS_CHECK, f"CO₂-Maximum {co2_max:.0f} ppm ≥ 2'000 ppm ({SRC_CO2_CHECK})"
        kurz = f"CO₂-Maximum {co2_max:.0f} ppm"
    elif sh_ida2 > TOL_SHARE or sh_ida4 > 0:
        st = STATUS_DEV
        txt = (f"{sh_ida2:.1f} % der {zeit} über IDA 2 (zulässig ≤ {TOL_SHARE:g} %)" if sh_ida2 > TOL_SHARE
               else f"{sh_ida4:.1f} % der {zeit} in IDA 4 (zulässig: höchstens eine Kategorie tiefer, IDA 3)")
    else:
        st, txt = STATUS_OK, f"{sh_ida2:.1f} % der {zeit} über IDA 2 (≤ {TOL_SHARE:g} %, max. IDA 3)"
    out["topics"]["Luftqualität"] = {"status": st, "text": txt, "kpi": 100 - sh_ida2, "kurz": kurz,
                                     "kpi_label": "Anteil Nutzungszeit in IDA 1–2", "lt1000": sh_lt1000,
                                     "src": SRC_CO2_RULE + "; " + SRC_CO2_CHECK,
                                     "aussen": f"{outdoor:g} ppm {'gemessen' if measured else '(Bezugswert Tab. 18, Fn. 2)'}"}

    # Thermischer Komfort: SECO-Orientierungsbereich, keine normative Zeittoleranz
    rule = match_bt_rule(rules, period, room)
    if rule:
        sh_t = _share(base, w, lambda s: s["Temperatur"] < rule["temp_min"] or s["Temperatur"] > rule["temp_max"])
        st = STATUS_OK if sh_t == 0 else STATUS_DEV
        txt = f"{sh_t:.1f} % der {zeit} ausserhalb {rule['temp_min']:g}–{rule['temp_max']:g} °C (keine Toleranz)"
        out["topics"]["Thermischer Komfort"] = {"status": st, "text": txt, "kpi": 100 - sh_t,
                                                "kurz": f"{sh_t:.1f} % der Zeit ausserhalb {rule['temp_min']:g}–{rule['temp_max']:g} °C",
                                                "kpi_label": "Anteil Nutzungszeit im Bereich", "src": SRC_T}
    else:
        out["topics"]["Thermischer Komfort"] = {"status": STATUS_NA, "text": "kein Referenzbereich", "kpi": None, "src": SRC_T}

    # Raumluftfeuchte: SIA 180 Ziff. 3.5.1.3 (untere Grenze) und 3.5.1.4 (obere Grenze), je max. 10 %
    parts, devs, kpis, missing = [], [], [], False
    low_app = period == "Heizperiode" or mech
    high_app = cooled or mech
    alt = building.get("altitude_m")
    if low_app:
        try:
            alt_v = float(str(alt).replace(",", ".")) if alt not in (None, "") else None
        except ValueError:
            alt_v = None
        if alt_v is None:
            parts.append("untere Grenze nicht bewertbar: Höhenlage fehlt")
            missing = True
        else:
            lim = rh_lower_limit(alt_v)
            nu_lo = abs_humidity(RH_DESIGN_T, lim)
            sh = _share(base, w, lambda s: abs_humidity(s["Temperatur"], s["Relative Feuchte"]) < nu_lo)
            kpis.append(100 - sh)
            parts.append(f"{sh:.1f} % unter {lim:g} % r. F. bei 21 °C (ν < {nu_lo:.2f} g/m³)")
            if sh > TOL_SHARE:
                devs.append("untere Grenze")
    if high_app:
        sh = _share(base, w, lambda s: abs_humidity(s["Temperatur"], s["Relative Feuchte"]) > NU_UPPER)
        kpis.append(100 - sh)
        parts.append(f"{sh:.1f} % über {NU_UPPER:g} g/m³")
        if sh > TOL_SHARE:
            devs.append("obere Grenze")
    if not low_app and not high_app:
        out["topics"]["Raumluftfeuchte"] = {"status": STATUS_NAPP, "text": "Raum weder beheizt, gekühlt noch mechanisch belüftet (SIA 180, Ziff. 3.5.1.3/3.5.1.4)", "kpi": None,
                                            "src": SRC_RH_LOW + "; " + SRC_RH_HIGH}
    else:
        if devs:
            st = STATUS_DEV
        elif missing:
            st = STATUS_NA
        elif kpis:
            st = STATUS_OK
        else:
            st = STATUS_NA
        out["topics"]["Raumluftfeuchte"] = {"status": st, "text": f"{'; '.join(parts)} der {zeit} (zulässig je ≤ {TOL_SHARE:g} %)",
                                            "kurz": ("Grenze " + " und ".join(devs) + " > 10 % verfehlt") if devs else "; ".join(parts),
                                            "kpi": min(kpis) if kpis else None, "kpi_label": "Anteil Nutzungszeit innerhalb der Grenzen",
                                            "src": SRC_RH_LOW + "; " + SRC_RH_HIGH}

    # Datenbasis: beschreibend, keine Bewertung
    cov = ts.get("abdeckung_pct") if ts else None
    out["topics"]["Datenbasis"] = {"status": "Jahresbezug" if out["jahr"] else "Teilzeitraum",
                                   "text": f"{span_days} Tage, {len(allp)} vollständige Messpunkte" + (f", Abdeckung {cov:.1f} %" if cov is not None else ""),
                                   "kpi": cov, "tage": span_days}
    ranked = [out["topics"][t]["status"] for t in TOPICS[:3]]
    for s_ in STATUS_ORDER:
        if s_ in ranked:
            out["status"] = s_
            break
    if all(r in (STATUS_NAPP,) for r in ranked):
        out["status"] = STATUS_NA
    out["gruende"] = [f"{t}: {out['topics'][t]['text']}" for t in TOPICS[:3] if out["topics"][t]["status"] in (STATUS_CHECK, STATUS_DEV)]
    out["kurz"] = [f"{t}: {out['topics'][t].get('kurz', '')}" for t in TOPICS[:3] if out["topics"][t]["status"] in (STATUS_CHECK, STATUS_DEV)]
    return out


def room_status(room: dict, assessment: dict, rules: list, building: dict | None = None) -> dict:
    """Gesamteinordnung je Raum = ungünstigstes Fokusthema (Projektauftrag S. 9)."""
    ev = evaluate_room(room, assessment, rules, building)
    return {"status": ev["status"], "gruende": ev["gruende"], "bezug": ev["bezug"], "result": ev}


def measurement_records(timestamp: str, co2: Any, temp: Any, rh: Any) -> list[dict]:
    dt = parse_timestamp(timestamp)
    if dt is None:
        raise ValueError("Datum/Uhrzeit bitte als JJJJ-MM-TT HH:MM erfassen.")
    out = []
    for param, value in (("CO₂", co2), ("Temperatur", temp), ("Relative Feuchte", rh)):
        v, reason = valid_value(param, value)
        if reason:
            raise ValueError(f"{param}: {reason}")
        out.append({"timestamp": dt.strftime("%Y-%m-%d %H:%M"), "parameter": param, "value": v, "unit": CORE[param], "note": ""})
    return out


def import_measurements(csv_data) -> tuple[list[dict], list[str]]:
    """Pandas-DataFrame: entweder breit timestamp,co2,temp,rh oder lang timestamp,parameter,value,unit."""
    df = csv_data.copy()
    df.columns = [str(x).strip().lower().replace(" ", "").replace("_", "") for x in df.columns]
    new_entries = []
    errors = []
    if {"timestamp", "co2", "temp", "rh"}.issubset(df.columns):
        for idx, row in df.iterrows():
            try:
                new_entries.extend(measurement_records(str(row["timestamp"]), row["co2"], row["temp"], row["rh"]))
            except ValueError as exc:
                errors.append(f"Zeile {idx+2}: {exc}")
    elif {"timestamp", "parameter", "value"}.issubset(df.columns):
        for idx, row in df.iterrows():
            param = normalize_param(row["parameter"])
            if param is None:
                errors.append(f"Zeile {idx+2}: unbekannte Kernmessgrösse")
                continue
            ts = parse_timestamp(row["timestamp"])
            unit = str(row.get("unit", CORE[param]) or CORE[param]).strip()
            value, error = valid_value(param, row["value"])
            if ts is None or error or unit != CORE[param]:
                errors.append(f"Zeile {idx+2}: Zeitstempel, Einheit oder Zahlenwert ungültig")
                continue
            new_entries.append({"timestamp": ts.strftime("%Y-%m-%d %H:%M"), "parameter": param, "value": value, "unit": unit, "note": ""})
    else:
        raise ValueError("Erwartet: timestamp,co2,temp,rh (breit) oder timestamp,parameter,value,unit (lang).")
    return new_entries, errors
