"""Geräteunabhängiger Datenimport für CO₂, Lufttemperatur und relative Feuchte (P6).

Ziel: Exporte unterschiedlicher Messgeräte werden einheitlich eingelesen
(Zeit = Lokalzeit Europe/Zurich, CO₂ in ppm, Temperatur in °C, r. F. in %),
damit Räume und Geräte untereinander vergleichbar bleiben.

Grundsätze
- Nichts wird geschätzt oder interpoliert. Unklare Angaben (Datumsformat,
  Einheit ohne Angabe in der Datei) müssen bestätigt werden.
- Nur physikalisch eindeutige Umrechnungen: °F → °C, K → °C, Vol.-% → ppm.
- Messbereich des Geräts aus der Gerätematrix (devices.json) wird geprüft.
- Jeder Import erzeugt ein Protokoll (Rückverfolgbarkeit).

Zusätzlich: Belegungsintervalle aus Präsenz-/Personenzählsensor (CSV/XLSX).
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
PARAMS = ("co2", "temp", "rh")
PARAM_NAME = {"co2": "CO₂", "temp": "Temperatur", "rh": "Relative Feuchte"}
CANON_UNIT = {"co2": "ppm", "temp": "°C", "rh": "%"}
UNIT_CHOICES = {"co2": ["ppm", "Vol.-%"], "temp": ["°C", "°F", "K"], "rh": ["%", "Anteil (0–1)"]}
DEVICE_RANGE_KEY = {"co2": "co2_ppm", "temp": "temperatur_c", "rh": "luftfeuchte_pct"}

# IAQ-Standardformat für externe Geräte (Vorgabe des Tools)
STANDARD_COLUMNS = ["timestamp", "co2_ppm", "temp_c", "rh_pct"]
STANDARD_SPEC = [
    ("timestamp", "Datum und Uhrzeit, ISO 8601: JJJJ-MM-TT HH:MM oder JJJJ-MM-TT HH:MM:SS. Lokalzeit Schweiz, "
                  "oder mit Zeitzonenangabe (z. B. 2026-11-02T08:00:00+01:00 bzw. …Z für UTC)."),
    ("co2_ppm", "CO₂-Konzentration in ppm (Zahl, ohne Einheit im Feld)."),
    ("temp_c", "Lufttemperatur in °C."),
    ("rh_pct", "Relative Luftfeuchte in % (0–100, nicht als Anteil 0–1)."),
]
STANDARD_RULES = [
    "Datei: CSV (UTF-8), Trennzeichen Semikolon oder Komma; alternativ XLSX (erstes Tabellenblatt).",
    "Eine Kopfzeile mit genau diesen Spaltennamen, danach eine Zeile pro Zeitpunkt.",
    "Alle drei Messgrössen eines Zeitpunkts in derselben Zeile (gleicher Zeitstempel).",
    "Dezimalpunkt oder Dezimalkomma; keine Tausendertrennzeichen.",
    "Fehlende Werte leer lassen (nicht 0 eintragen); keine interpolierten Werte.",
    "Rohdaten des Geräts, unverändert (keine gleitenden Mittelwerte).",
    "Aufzeichnungsintervall mind. 1 Minute; kürzere Intervalle werden beim Import gemittelt.",
]

# ---------------------------------------------------------------------------
# Gerätematrix
# ---------------------------------------------------------------------------


def load_devices(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else HERE / "devices.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("id")]


def load_profiles(path: str | Path | None = None) -> dict:
    """Gerätespezifische Importprofile (nur aus geprüften Beispieldateien)."""
    p = Path(path) if path else HERE / "import_profiles.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and not k.startswith("_")}


def device_label(d: dict) -> str:
    return f"{d.get('hersteller', '')} {d.get('modell', '')}".strip()


def device_coverage(d: dict) -> dict:
    p = d.get("parameter") or {}
    return {k: bool(p.get(DEVICE_RANGE_KEY[k])) for k in PARAMS}


def device_range(d: dict | None, key: str):
    if not d:
        return None
    r = (d.get("parameter") or {}).get(DEVICE_RANGE_KEY[key])
    if not r or r.get("min") is None or r.get("max") is None:
        return None
    return float(r["min"]), float(r["max"])


def device_accuracy(d: dict | None) -> str:
    """Kurzangabe Genauigkeit laut Gerätematrix (Herstellerangaben)."""
    if not d:
        return ""
    g = d.get("genauigkeit") or {}
    parts = []
    if g.get("co2_ppm") is not None or g.get("co2_pct") is not None:
        s = " ".join(x for x in [f"±{g['co2_ppm']:g} ppm" if g.get("co2_ppm") is not None else "",
                                  f"±{g['co2_pct']:g} %" if g.get("co2_pct") is not None else ""] if x)
        parts.append(f"CO₂ {s}")
    if g.get("temperatur_c") is not None:
        parts.append(f"T ±{g['temperatur_c']:g} K")
    if g.get("luftfeuchte_pct") is not None:
        parts.append(f"r. F. ±{g['luftfeuchte_pct']:g} %")
    return ", ".join(parts)


def device_interval_s(d: dict | None):
    dl = (d or {}).get("datenlogger") or {}
    return dl.get("intervall_min_s"), dl.get("intervall_max_s")


# ---------------------------------------------------------------------------
# Datei lesen
# ---------------------------------------------------------------------------


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "UTF-16"
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc), enc.upper()
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "LATIN-1"


def _norm(h: Any) -> str:
    s = str(h or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("₂", "2"), ("°", "deg"), ("µ", "u")):
        s = s.replace(a, b)
    return s


def _col_role(header: Any) -> str | None:
    """Rolle einer Spalte aus dem Spaltennamen (Deutsch/Englisch/Französisch)."""
    h = _norm(header)
    flat = re.sub(r"[^a-z0-9%]", "", h)
    if not flat:
        return None
    if re.search(r"dewpoint|taupunkt|absolut|abs\.?hum|g/m3|gm3|operativ|pm\d|voc|radon|pressure|druck|hpa|batter|signal|rssi", h + flat):
        return None
    if re.search(r"co2|carbondioxide|kohlen(stoff)?dioxid|dioxydedecarbone", flat):
        return "co2"
    if re.search(r"humid|feuchte|^rh|rh$|^rf|rf$|relhum|humidite|%rh|rh%", flat):
        return "rh"
    if re.search(r"temp|^t$|^t\(|^tdeg|degc$|degf$", flat) or re.fullmatch(r"t\s*\[.*\]", h):
        return "temp"
    if re.search(r"timestamp|datetime|datumzeit|datumuhrzeit|zeitstempel|dateheure|datetimeutc|localtime", flat):
        return "timestamp"
    if re.fullmatch(r"(datum|date|day|tag)(\(.*\)|.*)?", flat) and not re.search(r"time|zeit|uhr|heure", flat):
        return "date"
    if re.search(r"^(time|zeit|uhrzeit|heure)", flat):
        return "time_or_ts"
    if re.search(r"^(date|datum)", flat):
        return "timestamp"
    return None


def _header_unit(header: Any, role: str) -> str | None:
    h = _norm(header)
    if role == "co2":
        if "ppm" in h:
            return "ppm"
        if re.search(r"vol|%", h):
            return "Vol.-%"
        if re.search(r"mg/m|mgm3|ug/m", h):
            return "mg/m³"
    if role == "temp":
        if re.search(r"degf|fahrenheit|\bf\b|\[f\]|\(f\)", h):
            return "°F"
        if re.search(r"degc|celsius|\[c\]|\(c\)|\bc\b", h):
            return "°C"
        if re.search(r"kelvin|\[k\]|\(k\)", h):
            return "K"
    if role == "temp" and re.search(r"[_\s]c$", h):
        return "°C"
    if role == "rh" and re.search(r"%|pct|percent|prozent", h):
        return "%"
    return None


def _split(lines: list[str], delim: str) -> list[list[str]]:
    return [row for row in csv.reader(lines, delimiter=delim)]


def _find_header(rows: list[list[Any]]) -> int | None:
    best, best_score = None, 0
    for i, row in enumerate(rows[:60]):
        roles = {_col_role(c) for c in row}
        score = len(roles & {"co2", "temp", "rh"}) * 2 + (1 if roles & {"timestamp", "date", "time_or_ts"} else 0)
        if score > best_score and roles & {"co2", "temp", "rh"}:
            best, best_score = i, score
    return best


def read_table(data: bytes, filename: str = "") -> dict:
    """Liest CSV/TXT, XLSX oder JSON in eine Tabelle {headers, rows, meta}."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        return _read_xlsx(data)
    if name.endswith(".json") or data.lstrip()[:1] in (b"[", b"{"):
        return _read_json(data)
    text, enc = _decode(data)
    lines = [ln for ln in text.splitlines()]
    sample = [ln for ln in lines[:80] if ln.strip()]
    delim = None
    best = -1
    for d in (";", "\t", ",", "|"):
        counts = [ln.count(d) for ln in sample]
        if not counts or max(counts) == 0:
            continue
        common = statistics.mode(counts)
        score = sum(1 for c in counts if c == common) * (1 if common else 0) + common * 0.01
        if score > best:
            best, delim = score, d
    if delim is None:
        raise ValueError("Trennzeichen der Datei nicht erkennbar.")
    rows = _split(lines, delim)
    h = _find_header(rows)
    if h is None:
        raise ValueError("Keine Kopfzeile mit CO₂-, Temperatur- oder Feuchtespalte gefunden.")
    headers = [str(x).strip() for x in rows[h]]
    body = [r for r in rows[h + 1:] if any(str(c).strip() for c in r)]
    return {"headers": headers, "rows": body,
            "meta": {"format": "CSV/TXT", "encoding": enc, "delimiter": {"\t": "Tab"}.get(delim, delim),
                     "header_row": h + 1, "skipped_lines": h}}


def _read_xlsx(data: bytes) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        h = _find_header(rows)
        if h is not None:
            headers = [str(x).strip() if x is not None else "" for x in rows[h]]
            body = [r for r in rows[h + 1:] if any(c not in (None, "") for c in r)]
            return {"headers": headers, "rows": body,
                    "meta": {"format": "XLSX", "sheet": ws.title, "header_row": h + 1, "skipped_lines": h}}
    raise ValueError("In keinem Tabellenblatt eine Kopfzeile mit CO₂, Temperatur oder Feuchte gefunden.")


def _read_json(data: bytes) -> dict:
    obj = json.loads(_decode(data)[0])
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if not lists:
            raise ValueError("JSON enthält keine Liste von Messpunkten.")
        obj = max(lists, key=len)
    if not isinstance(obj, list) or not obj or not isinstance(obj[0], dict):
        raise ValueError("JSON enthält keine Liste von Messpunkten.")

    def flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(flat(v, key + "."))
            elif isinstance(v, list) and v and not isinstance(v[0], (dict, list)):
                out[key] = v[0]  # z. B. [Wert, Unsicherheit]: erster Eintrag = Messwert
            else:
                out[key] = v
        return out
    recs = [flat(x) for x in obj if isinstance(x, dict)]
    headers = list(dict.fromkeys(k for r in recs for k in r))
    return {"headers": headers, "rows": [[r.get(h) for h in headers] for r in recs],
            "meta": {"format": "JSON", "header_row": 0, "skipped_lines": 0}}


# ---------------------------------------------------------------------------
# Zeit und Zahlen
# ---------------------------------------------------------------------------

DT_FORMATS = {
    "JJJJ-MM-TT hh:mm[:ss]": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"],
    "TT.MM.JJJJ hh:mm[:ss]": ["%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M"],
    "TT/MM/JJJJ hh:mm[:ss]": ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p",
                              "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"],
    "MM/TT/JJJJ hh:mm[:ss] (US)": ["%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"],
}
D_FORMATS = {"JJJJ-MM-TT": ["%Y-%m-%d", "%Y/%m/%d"], "TT.MM.JJJJ": ["%d.%m.%Y", "%d.%m.%y"],
             "TT/MM/JJJJ": ["%d/%m/%Y", "%d-%m-%Y"], "MM/TT/JJJJ (US)": ["%m/%d/%Y"]}
T_FORMATS = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%H:%M:%S.%f"]
ISO_KEY = "ISO 8601 mit Zeitzone"
EPOCH_KEY = "Unix-Zeit"
EXCEL_KEY = "Excel-Datum"


def _try(fmts, s):
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _is_iso_tz(s: str) -> bool:
    return bool(re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$", s))


def detect_dt_formats(values: list[Any], kind: str = "dt") -> list[str]:
    """Alle Formate, mit denen jeder Stichprobenwert lesbar ist."""
    vals = [v for v in values if v not in (None, "")][:300]
    if not vals:
        return []
    if all(isinstance(v, datetime) for v in vals):
        return ["Excel-Zelle (Datum/Zeit)"]
    if kind == "time" and all(isinstance(v, time) for v in vals):
        return ["Excel-Zelle (Datum/Zeit)"]
    if kind == "date" and all(isinstance(v, (date, datetime)) for v in vals):
        return ["Excel-Zelle (Datum/Zeit)"]
    strs = [str(v).strip() for v in vals]
    if kind == "time":
        return ["hh:mm[:ss]"] if all(_try(T_FORMATS, s) for s in strs) else []
    if kind == "date":
        return [k for k, f in D_FORMATS.items() if all(_try(f, s) for s in strs)]
    if all(_is_iso_tz(s.replace(" ", "T", 1)) for s in strs):
        return [ISO_KEY]
    nums = [float(s) if re.fullmatch(r"[+-]?\d+(\.\d+)?", s) else None for s in strs]
    if all(n is not None for n in nums):
        if all(1e9 <= n < 1e11 for n in nums):
            return [EPOCH_KEY + " (Sekunden)"]
        if all(1e12 <= n < 1e14 for n in nums):
            return [EPOCH_KEY + " (Millisekunden)"]
        if all(20000 <= n < 80000 for n in nums):
            return [EXCEL_KEY]
        return []
    strs = [s.replace("T", " ", 1) for s in strs]
    return [k for k, f in DT_FORMATS.items() if all(_try(f, s) for s in strs)]


def _to_local_naive(dt: datetime, tz_mode: str) -> datetime:
    if dt.tzinfo is None:
        if tz_mode == "UTC":
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            return dt
    return dt.astimezone(LOCAL_TZ).replace(tzinfo=None)


def parse_dt(v: Any, fmt: str, tz_mode: str = "Lokalzeit") -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return _to_local_naive(v, tz_mode)
    s = str(v).strip()
    if fmt == ISO_KEY:
        try:
            return _to_local_naive(datetime.fromisoformat(s.replace(" ", "T", 1).replace("Z", "+00:00")), tz_mode)
        except ValueError:
            return None
    if fmt.startswith(EPOCH_KEY):
        n = _num(s)
        if n is None:
            return None
        if "Milli" in fmt:
            n /= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).astimezone(LOCAL_TZ).replace(tzinfo=None)
    if fmt == EXCEL_KEY:
        n = _num(s)
        return None if n is None else _to_local_naive(datetime(1899, 12, 30) + timedelta(days=n), tz_mode)
    dt = _try(DT_FORMATS.get(fmt, []), s.replace("T", " ", 1))
    return None if dt is None else _to_local_naive(dt, tz_mode)


def _parse_date(v, fmt):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    d = _try(D_FORMATS.get(fmt, []), str(v).strip())
    return d.date() if d else None


def _parse_time(v):
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    if isinstance(v, (int, float)) and 0 <= v < 1:  # Excel-Tagesanteil
        return (datetime(2000, 1, 1) + timedelta(days=float(v))).time()
    t = _try(T_FORMATS, str(v).strip())
    return t.time() if t else None


# Typische Fehler-/Platzhalterwerte von Loggern (werden nur ausgeschlossen, wenn sie nicht dem Messbereichsende des Geräts entsprechen)
SENTINELS = {-9999.0, -999.0, 9999.0, 99999.0, 65535.0, 32767.0, -32768.0}
NA_TOKENS = {"", "-", "--", "---", "na", "n/a", "nan", "null", "none", "k.a.", "#n/a", "err", "error"}


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    s = str(v).strip().replace(" ", "").replace(" ", "").replace("'", "").replace("’", "")
    if s.lower() in NA_TOKENS:
        return None
    m = re.match(r"^[+-]?[\d.,]+(e[+-]?\d+)?", s.lower())
    if not m:
        return None
    s = m.group(0)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Zuordnung erkennen
# ---------------------------------------------------------------------------


def detect_mapping(table: dict, profile: dict | None = None) -> dict:
    headers, rows = table["headers"], table["rows"]
    col = {k: None for k in ("timestamp", "date", "time", *PARAMS)}
    units = {k: None for k in PARAMS}
    notes = []
    if profile and profile.get("columns"):
        for role, name in profile["columns"].items():
            if name in headers and role in col:
                col[role] = headers.index(name)
        units.update({k: v for k, v in (profile.get("units") or {}).items() if k in units})
        notes.append(f"Geräteprofil angewendet ({profile.get('quelle', 'ohne Quellenangabe')}).")
    for i, h in enumerate(headers):
        role = _col_role(h)
        if role in PARAMS and col[role] is None:
            col[role] = i
            units[role] = units[role] or _header_unit(h, role)
        elif role == "timestamp" and col["timestamp"] is None:
            col["timestamp"] = i
        elif role == "date" and col["date"] is None:
            col["date"] = i
        elif role == "time_or_ts":
            vals = [r[i] for r in rows[:50] if i < len(r)]
            if detect_dt_formats(vals, "time") and col["time"] is None:
                col["time"] = i
            elif col["timestamp"] is None:
                col["timestamp"] = i
    if col["timestamp"] is not None and col["date"] is not None and col["time"] is not None:
        col["timestamp"] = None
    if col["date"] is not None and col["time"] is None and col["timestamp"] is None:
        col["timestamp"], col["date"] = col["date"], None
    tz = "UTC" if any("utc" in _norm(h) for h in headers if h) else "Lokalzeit"
    if tz == "UTC":
        notes.append("Spaltenname enthält «UTC»: Zeitangaben werden von UTC in Schweizer Lokalzeit umgerechnet.")
    return {"columns": col, "units": units, "tz": tz, "notes": notes}


def mapping_formats(table: dict, mapping: dict) -> dict:
    c, rows = mapping["columns"], table["rows"]
    get = lambda i: [r[i] for r in rows[:300] if i is not None and i < len(r)]
    if c["timestamp"] is not None:
        return {"dt": detect_dt_formats(get(c["timestamp"]), "dt")}
    if c["date"] is not None:
        return {"date": detect_dt_formats(get(c["date"]), "date"), "time": detect_dt_formats(get(c["time"]), "time")}
    return {}



# ---------------------------------------------------------------------------
# Automatische Bereinigung: eindeutige Ableitungen statt Rückfragen
# ---------------------------------------------------------------------------

# Plausibilitätsfenster für Innenraumluft in Büros, nur zur Unterscheidung der Einheit.
# Die Fenster überlappen nicht; liegt der Median in keinem oder die Werte streuen über
# zwei Fenster, wird nicht abgeleitet (Bestätigung nötig).
UNIT_WINDOWS = {
    "temp": [("°C", 5, 40), ("°F", 41, 104), ("K", 278, 313)],
    "co2": [("ppm", 250, 10000), ("Vol.-%", 0.025, 1.0)],
    "rh": [("%", 1.5, 100), ("Anteil (0–1)", 0.0, 1.0)],
}


def infer_unit(key: str, values: list[float]) -> str | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    lo, hi = min(vals), max(vals)
    hits = [u for u, a, b in UNIT_WINDOWS[key] if a <= lo and hi <= b]
    if key == "rh" and len(hits) == 2:   # 0–1 liegt in beiden Fenstern: nur «Anteil», wenn alle ≤ 1
        hits = ["Anteil (0–1)"] if hi <= 1.0 else ["%"]
    return hits[0] if len(hits) == 1 else None


def resolve_dt_format(values: list[Any], candidates: list[str], tz_mode: str = "Lokalzeit") -> tuple[str | None, str]:
    """Mehrdeutiges Datumsformat über die Zeitreihe selbst entscheiden.

    Messgeräte schreiben chronologisch und in festem Intervall. Gewählt wird das Format,
    bei dem die Zeitpunkte in Dateireihenfolge aufsteigen und die Abstände am regelmässigsten
    sind. Ist kein Format klar besser, bleibt die Entscheidung beim Nutzer.
    """
    if len(candidates) <= 1:
        return (candidates[0] if candidates else None), ""
    scores = {}
    for f in candidates:
        ts = [parse_dt(v, f, tz_mode) for v in values[:2000] if v not in (None, "")]
        ts = [t for t in ts if t]
        if len(ts) < 3:
            continue
        d = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
        mono = sum(1 for x in d if x >= 0) / len(d)
        pos = [x for x in d if x > 0]
        med = statistics.median(pos) if pos else 0
        reg = sum(1 for x in d if med and abs(x - med) <= 0.1 * med) / len(d)
        scores[f] = (round(mono, 4), round(reg, 4))
    if not scores:
        return None, ""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
        return ranked[0][0], f"Datumsformat automatisch bestimmt: {ranked[0][0]} (chronologische, regelmässige Zeitreihe)"
    return None, ""


def column_values(table: dict, idx: int | None, n: int = 2000) -> list:
    return [r[idx] for r in table["rows"][:n] if idx is not None and idx < len(r)]


def smart_defaults(table: dict, mapping: dict) -> dict:
    """Leitet Datumsformat und fehlende Einheiten ab, wo dies eindeutig ist."""
    out = {"dt_format": None, "date_format": None, "units": {}, "notes": [], "open": []}
    fm = mapping_formats(table, mapping)
    c = mapping["columns"]
    if "dt" in fm:
        f, note = resolve_dt_format(column_values(table, c["timestamp"]), fm["dt"], mapping.get("tz", "Lokalzeit"))
        out["dt_format"] = f
        if note:
            out["notes"].append(note)
        if f is None:
            out["open"].append("Datumsformat")
    elif "date" in fm:
        cands = fm["date"]
        if len(cands) > 1:
            vals = [f"{d} {t}" for d, t in zip(column_values(table, c["date"]), column_values(table, c["time"]))]
            dmap = {"JJJJ-MM-TT": "JJJJ-MM-TT hh:mm[:ss]", "TT.MM.JJJJ": "TT.MM.JJJJ hh:mm[:ss]", "TT/MM/JJJJ": "TT/MM/JJJJ hh:mm[:ss]", "MM/TT/JJJJ (US)": "MM/TT/JJJJ hh:mm[:ss] (US)"}
            f, note = resolve_dt_format(vals, [dmap[x] for x in cands], mapping.get("tz", "Lokalzeit"))
            inv = {v: k for k, v in dmap.items()}
            out["date_format"] = inv.get(f)
            if note:
                out["notes"].append(note)
            if f is None:
                out["open"].append("Datumsformat")
        else:
            out["date_format"] = cands[0] if cands else None
    for k in PARAMS:
        if mapping["units"].get(k):
            continue
        u = infer_unit(k, [_num(v) for v in column_values(table, c[k])])
        if u:
            out["units"][k] = u
            out["notes"].append(f"Einheit {PARAM_NAME[k]} aus dem Wertebereich abgeleitet: {u}")
        else:
            out["open"].append(f"Einheit {PARAM_NAME[k]}")
    return out


# ---------------------------------------------------------------------------
# Umrechnen und bereinigen
# ---------------------------------------------------------------------------


def _convert_unit(key: str, v: float, unit: str) -> float:
    if key == "temp" and unit == "°F":
        return (v - 32) * 5 / 9
    if key == "temp" and unit == "K":
        return v - 273.15
    if key == "co2" and unit == "Vol.-%":
        return v * 10000
    if key == "rh" and unit == "Anteil (0–1)":
        return v * 100
    return v


def convert(table: dict, mapping: dict, *, dt_format: str | None = None, date_format: str | None = None,
            units: dict | None = None, tz_mode: str | None = None, device: dict | None = None,
            average_min: int | None = None) -> dict:
    """Erzeugt einheitliche Messpunkte (ein Zeitpunkt = CO₂ + T + r. F.) und ein Importprotokoll."""
    c = mapping["columns"]
    units = {**mapping["units"], **(units or {})}
    tz_mode = tz_mode or mapping.get("tz", "Lokalzeit")
    missing = [PARAM_NAME[k] for k in PARAMS if c[k] is None]
    if missing:
        raise ValueError("Spalte nicht gefunden: " + ", ".join(missing) + ". Spalten manuell zuordnen.")
    if c["timestamp"] is None and (c["date"] is None or c["time"] is None):
        raise ValueError("Keine Zeitspalte gefunden.")
    for k in PARAMS:
        if units.get(k) not in UNIT_CHOICES[k]:
            raise ValueError(f"Einheit für {PARAM_NAME[k]} unklar ({units.get(k) or 'nicht angegeben'}): bitte bestätigen.")
    excl: dict[str, int] = {}

    def ex(reason):
        excl[reason] = excl.get(reason, 0) + 1

    pts, sat, actions, hints = [], {}, [], []
    for r in table["rows"]:
        cell = lambda i: r[i] if i is not None and i < len(r) else None
        if c["timestamp"] is not None:
            ts = parse_dt(cell(c["timestamp"]), dt_format or "", tz_mode)
        else:
            d, t = _parse_date(cell(c["date"]), date_format or ""), _parse_time(cell(c["time"]))
            ts = _to_local_naive(datetime.combine(d, t), tz_mode) if d and t else None
        if ts is None:
            ex("Zeitstempel nicht lesbar")
            continue
        vals = {}
        for k in PARAMS:
            raw = cell(c[k])
            v = _num(raw)
            if v is None:
                vals[k] = None
                if raw not in (None, "") and str(raw).strip().lower() not in NA_TOKENS:
                    ex(f"{PARAM_NAME[k]}: kein Zahlenwert")
                continue
            if v in SENTINELS and not (device_range(device, k) and v == device_range(device, k)[1]):
                ex(f"{PARAM_NAME[k]}: Fehlercode des Geräts ({v:g})")
                vals[k] = None
                continue
            v = _convert_unit(k, v, units[k])
            rng = device_range(device, k)
            if rng and abs(v - rng[1]) < 1e-9:
                sat[k] = sat.get(k, 0) + 1
            if rng and not (rng[0] - 1e-9 <= v <= rng[1] + 1e-9):
                ex(f"{PARAM_NAME[k]}: ausserhalb Messbereich des Geräts ({rng[0]:g}–{rng[1]:g} {CANON_UNIT[k]})")
                v = None
            vals[k] = v
        pts.append((ts, vals))
    if any(b[0] < a[0] for a, b in zip(pts, pts[1:])):
        actions.append("Zeilen chronologisch sortiert (Datei nicht in Zeitreihenfolge)")
    pts.sort(key=lambda x: x[0])
    uniq, seen = [], set()
    for ts, vals in pts:
        key = (ts, tuple(vals[k] for k in PARAMS))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((ts, vals))
    if len(uniq) < len(pts):
        actions.append(f"{len(pts) - len(uniq)} identische Doppelzeilen entfernt")
    pts = uniq
    raw_n = len(pts)
    deltas = [(b[0] - a[0]).total_seconds() for a, b in zip(pts, pts[1:]) if b[0] > a[0]]
    median_s = statistics.median(deltas) if deltas else None
    if average_min is None and median_s is not None and median_s < 60:
        raise ValueError(f"Aufzeichnungsintervall ca. {median_s:g} s (< 1 min): bitte Mittelungsintervall wählen.")
    # Raster: Minute (Originalauflösung) oder Mittelwert je N Minuten (ohne Lückenfüllung)
    step = int(average_min or 1)
    bins: dict[datetime, dict[str, list[float]]] = {}
    for ts, vals in pts:
        base = ts.replace(second=0, microsecond=0)
        base -= timedelta(minutes=(base.hour * 60 + base.minute) % step)
        b = bins.setdefault(base, {k: [] for k in PARAMS})
        for k in PARAMS:
            if vals[k] is not None:
                b[k].append(vals[k])
    dup = sum(1 for b in bins.values() if any(len(b[k]) > 1 for k in PARAMS)) if step == 1 else 0
    if dup and not average_min:
        ex("Mehrere Werte innerhalb derselben Minute: gemittelt")
    records = []
    complete = 0
    for ts, b in sorted(bins.items()):
        stamp = ts.strftime("%Y-%m-%d %H:%M")
        have = all(b[k] for k in PARAMS)
        complete += have
        for k in PARAMS:
            if b[k]:
                v = sum(b[k]) / len(b[k])
                records.append({"timestamp": stamp, "parameter": PARAM_NAME[k], "value": round(v, 3 if k != "co2" else 1),
                                "unit": CANON_UNIT[k], "note": f"Mittel aus {len(b[k])} Werten" if len(b[k]) > 1 else ""})
    conv = [f"{PARAM_NAME[k]}: {units[k]} → {CANON_UNIT[k]}" for k in PARAMS if units[k] != CANON_UNIT[k]]
    # Hinweise (keine Datenänderung)
    for k, n in sat.items():
        hints.append(f"{PARAM_NAME[k]}: {n}× Messbereichsende des Geräts erreicht – tatsächlicher Wert evtl. höher (Werte bleiben enthalten)")
    if median_s:
        gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(pts, pts[1:]) if (b[0] - a[0]).total_seconds() > 3 * median_s]
        if gaps:
            hints.append(f"{len(gaps)} Datenlücke(n) > 3 × Intervall, längste {max(gaps) / 3600:.1f} h – nicht aufgefüllt; unter «Datenlücken» dokumentieren")
    run_start, frozen = None, 0.0
    for a, b in zip(pts, pts[1:]):
        same = all(a[1][k] is not None and a[1][k] == b[1][k] for k in PARAMS)
        if same:
            run_start = run_start or a[0]
            frozen = max(frozen, (b[0] - run_start).total_seconds())
        else:
            run_start = None
    if frozen >= 24 * 3600:
        hints.append(f"Alle drei Werte bis {frozen / 3600:.0f} h unverändert – Gerät/Logger prüfen (eingefrorene Werte?)")
    if tz_mode == "Lokalzeit":
        dst = sum(1 for ts, _ in pts if ts.month == 10 and ts.weekday() == 6 and ts.day > 24 and ts.hour == 2)
        if dst and any(b[0] == a[0] for a, b in zip(pts, pts[1:])):
            hints.append("Zeitumstellung (Ende Sommerzeit): doppelte Stunde 02:00–03:00 in Lokalzeit; besser UTC-Export verwenden")
    log = {
        "rohzeilen": len(table["rows"]), "zeitpunkte_gelesen": raw_n, "messpunkte": len(bins), "vollstaendig": complete,
        "ausschluesse": excl, "umrechnungen": conv, "zeitzone": tz_mode,
        "bereinigung": actions, "hinweise": hints,
        "mittelung_min": average_min, "median_intervall_s": median_s,
        "von": pts[0][0].strftime("%Y-%m-%d %H:%M") if pts else None,
        "bis": pts[-1][0].strftime("%Y-%m-%d %H:%M") if pts else None,
        "geraet": device_label(device) if device else "Externes Gerät (IAQ-Standardformat)",
        "spalten": {k: (table["headers"][i] if i is not None else None) for k, i in c.items()},
        "einheiten": {k: units[k] for k in PARAMS},
    }
    return {"records": records, "log": log}


def auto_import(data: bytes, filename: str, device: dict | None = None, profile: dict | None = None,
                average_min: int | None = None, overrides: dict | None = None) -> dict:
    """Komplettablauf; wirft ValueError mit verständlicher Meldung, wenn eine Bestätigung fehlt."""
    table = read_table(data, filename)
    mapping = detect_mapping(table, profile)
    ov = overrides or {}
    if ov.get("columns"):
        mapping["columns"].update(ov["columns"])
    sd = smart_defaults(table, mapping)
    dt_fmt = ov.get("dt_format") or sd["dt_format"]
    d_fmt = ov.get("date_format") or sd["date_format"]
    fm = mapping_formats(table, mapping)
    if "dt" in fm and not dt_fmt:
        raise ValueError("Datumsformat nicht eindeutig (" + " / ".join(fm["dt"]) + "): bitte wählen.")
    units = {**sd["units"], **(ov.get("units") or {})}
    res = convert(table, mapping, dt_format=dt_fmt, date_format=d_fmt, units=units,
                  tz_mode=ov.get("tz"), device=device, average_min=average_min)
    res["table_meta"] = table["meta"]
    res["log"]["bereinigung"] = sd["notes"] + res["log"]["bereinigung"]
    return res


# ---------------------------------------------------------------------------
# Nutzung: Präsenz-/Personenzählsensor
# ---------------------------------------------------------------------------

def merge_intervals(ivals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for a, b in sorted(ivals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def parse_presence(data: bytes, filename: str = "", max_gap_min: int | None = None) -> dict:
    """Belegung aus Präsenz-/Personenzählsensor.

    Erwartet je Zeile Zeitstempel + Präsenz (0/1, true/false, belegt/frei) oder Personenzahl.
    Belegt = Wert > 0 bzw. «belegt». Ein Zeitpunkt gilt bis zum nächsten Zeitpunkt; ist dieser weiter
    entfernt als max_gap_min (Standard: 2 × Medianintervall), endet das Intervall nach einem Medianintervall.
    """
    try:
        table = read_table(data, filename)
    except ValueError:
        table = None
    if table is None or not table["headers"]:
        text, _ = _decode(data)
        rows = list(csv.reader(text.splitlines(), delimiter=";" if text.count(";") > text.count(",") else ","))
        table = {"headers": rows[0], "rows": rows[1:], "meta": {}}
    hdr = table["headers"]
    ti = next((i for i, h in enumerate(hdr) if _col_role(h) in ("timestamp", "time_or_ts", "date")), 0)
    pi = next((i for i, h in enumerate(hdr) if re.search(r"praes|presen|occup|belegt|belegung|anwes|person|count|anzahl|people", _norm(h))), None)
    if pi is None:
        pi = 1 if len(hdr) > 1 else None
    if pi is None:
        raise ValueError("Keine Präsenz-/Belegungsspalte gefunden (z. B. «presence», «belegt», «personen»).")
    fmts = detect_dt_formats([r[ti] for r in table["rows"][:300] if ti < len(r)], "dt")
    if not fmts:
        raise ValueError("Zeitstempel der Präsenzdaten nicht lesbar.")
    if len(fmts) > 1:
        raise ValueError("Datumsformat der Präsenzdaten mehrdeutig (" + " / ".join(fmts) + ").")
    tz = "UTC" if "utc" in _norm(hdr[ti]) else "Lokalzeit"
    pts, sat, actions, hints = [], {}, [], []
    for r in table["rows"]:
        if max(ti, pi) >= len(r):
            continue
        ts = parse_dt(r[ti], fmts[0], tz)
        raw = str(r[pi]).strip().lower()
        if ts is None:
            continue
        if raw in ("true", "ja", "yes", "belegt", "occupied", "present", "anwesend", "on"):
            occ = True
        elif raw in ("false", "nein", "no", "frei", "unoccupied", "free", "absent", "abwesend", "off"):
            occ = False
        else:
            n = _num(raw)
            if n is None:
                continue
            occ = n > 0
        pts.append((ts, occ))
    pts.sort()
    if len(pts) < 2:
        raise ValueError("Zu wenige lesbare Präsenzwerte.")
    deltas = [(b[0] - a[0]).total_seconds() / 60 for a, b in zip(pts, pts[1:]) if b[0] > a[0]]
    med = statistics.median(deltas) if deltas else 15
    gap = max_gap_min or 2 * med
    ivals = []
    for (t, occ), (t2, _) in zip(pts, pts[1:] + [(pts[-1][0] + timedelta(minutes=med), None)]):
        if occ:
            stop = t2 if (t2 - t).total_seconds() / 60 <= gap else t + timedelta(minutes=med)
            ivals.append((t, stop))
    merged = merge_intervals(ivals)
    return {"intervals": [[a.strftime("%Y-%m-%d %H:%M"), b.strftime("%Y-%m-%d %H:%M")] for a, b in merged],
            "log": {"werte": len(pts), "median_intervall_min": med, "intervalle": len(merged),
                    "stunden": round(sum((b - a).total_seconds() for a, b in merged) / 3600, 1),
                    "spalten": {"zeit": hdr[ti], "praesenz": hdr[pi]}}}


def standard_template_csv() -> bytes:
    rows = [";".join(STANDARD_COLUMNS), "2026-11-02 08:00;612;21.4;38.5", "2026-11-02 08:05;655;21.5;38.9"]
    return ("\n".join(rows) + "\n").encode("utf-8-sig")
