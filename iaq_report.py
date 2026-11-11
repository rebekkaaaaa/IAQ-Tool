"""IAQ-Nachweis- und Reportingvorlage (A4, druckfertiges HTML) · P6 V12.

Gestaltung: Schrift mindestens 12 pt (ausgenommen Quellenverzeichnis und Seitenfuss),
klare Hervorhebung von Ergebnis und Handlungsbedarf, Gliederung nach ESG-Fokusthemen.

Umfang (nicht proportional zur Raumzahl):
  1 Raum       → 2 Seiten (Ergebnis · Detail)
  2–10 Räume   → Übersicht · Raummatrix + ESG · Raumprofile (2 je Seite, max. 6) · Methodik  = 4–6 Seiten
  11–66 Räume  → Übersicht · Raummatrix (22 je Seite) · ESG · Raumprofile · Methodik      = 7–9 Seiten
"""
from __future__ import annotations

import html
import math
from datetime import date

from iaq_logic import (
    CORE, STATUS_CHECK, STATUS_DEV, STATUS_NA, STATUS_NAPP, STATUS_OK, STATUS_ORDER,
    STRATEGIES, TOPICS, TOL_SHARE, co2_classes, conditional_hints, describe,
    effective_ventilation, evaluate_room, filter_usage, long_to_samples, match_bt_rule, time_stats,
)

NA = "nicht erfasst"
MAX_PROFILES = 6
PROFILES_PER_PAGE = 2
OVERVIEW_ACTIONS = 3
MATRIX_ROWS = 22
COMBINE_LIMIT = 10          # bis zu dieser Raumzahl Matrix und ESG auf einer Seite
CONTENT_MM = 182            # nutzbare Breite A4 bei 14 mm Rand
CSSK = {STATUS_OK: "ok", STATUS_DEV: "dev", STATUS_CHECK: "chk", STATUS_NA: "na", STATUS_NAPP: "na",
        "Jahresbezug": "ok", "Teilzeitraum": "na"}
SHORT = {STATUS_OK: "Eingehalten", STATUS_DEV: "Abweichung", STATUS_CHECK: "Abklärung", STATUS_NA: "Nicht bewertbar",
         STATUS_NAPP: "Nicht anwendbar", "Jahresbezug": "Jahresbezug", "Teilzeitraum": "Teilzeitraum"}

TOPIC_INFO = {
    "Luftqualität": {"frage": "Wird ausreichend gelüftet?", "krit": f"≤ {TOL_SHARE:g} % der Nutzungszeit über IDA 2, nie IDA 4; Abklärung ab 2'000 ppm",
                     "quelle": "SIA 382/1:2025 Ziff. 2.2.5.6, Tab. 18; SECO Abb. 316-4"},
    "Thermischer Komfort": {"frage": "Ist die Temperatur arbeitsgerecht?", "krit": "Heizperiode 21–23 °C, Kühlperiode 23–26 °C, ohne Zeittoleranz",
                            "quelle": "SECO Wegleitung ArGV 3, Abb. 316-1"},
    "Raumluftfeuchte": {"frage": "Ist die Luft weder zu trocken noch zu feucht?", "krit": f"< 30 % r. F. (21 °C) bzw. > 15,2 g/m³ je ≤ {TOL_SHARE:g} % der Nutzungszeit",
                        "quelle": "SIA 180:2014 Ziff. 3.5.1.3/3.5.1.4"},
    "Datenbasis": {"frage": "Wie belastbar ist die Aussage?", "krit": "Jahresbezug = Messung über ein Nutzungsjahr",
                   "quelle": "SIA 180 / SIA 382/1: «jährliche Nutzungszeit»"},
}

SOURCES = [
    "SIA 382/1:2025 (SN 546382/1) Lüftungs- und Klimaanlagen: Ziff. 1.7.4.3, Tab. 18; Ziff. 2.2.5.4, 2.2.5.6.",
    "SIA 180:2014 (SN 520180) Wärmeschutz, Feuchteschutz und Raumklima in Gebäuden: Ziff. 3.5.1.3, 3.5.1.4, Anhang A.1.",
    "SECO (2020). Wegleitung zur ArGV 3, Art. 16 Raumklima: Abb. 316-1, 316-2, 316-4, S. 316-3.",
    "Bacher, L. (2025). Entwicklung eines Leitfadens zur Messung von CO₂. Bachelor-Thesis EUT-P6-24HS, FHNW (Messhöhe, Gerätedichte).",
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


def fdt(dt, with_time=False) -> str:
    return "–" if not dt else dt.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


VSHORT = {"Mechanisch": "mech.", "Natürlich": "Fenster", "Hybrid – mechanischer Modus": "hybrid mech.",
          "Hybrid – natürlicher Modus": "hybrid nat."}
SSHORT = {STRATEGIES[0]: "Stichprobe", STRATEGIES[1]: "Messkampagne", STRATEGIES[2]: "Langzeitmessung"}


def chip(status: str, label: str | None = None) -> str:
    return f"<span class='chip {CSSK.get(status, 'na')}'>{e(label or SHORT.get(status, status))}</span>"


def tchip(b, t) -> str:
    tp = b["ev"]["topics"].get(t, {})
    st, k = tp.get("status", STATUS_NA), tp.get("kpi")
    if t == "Datenbasis":
        return chip(st, f"{tp.get('tage', '–')} Tage")
    return chip(st, fpct(k) if k is not None else "–")


# ---------------------------------------------------------------- Grafik (Inline-SVG, Schrift ≥ 12 pt)

def series_svg(samples, param, unit, band=None, line=None, width_mm=CONTENT_MM, height_mm=48):
    """Zeitverlauf; Schriftgrösse aus Druckbreite berechnet (12 pt = 4,23 mm).
    > 900 Punkte: Min/Max-Hülle je Zeitfenster. Lücken > 3 × Median-Intervall nicht verbunden."""
    if len(samples) < 2:
        return "<p>Zeitverlauf benötigt mindestens zwei vollständige Messpunkte.</p>"
    W = 1000
    k = W / width_mm
    H = height_mm * k
    fs = 4.45 * k
    pl, pr, pt, pb = 4.2 * fs, 0.6 * fs, 1.6 * fs, 1.5 * fs
    w, h = W - pl - pr, H - pt - pb
    ts = [s["timestamp"] for s in samples]
    vals = [s[param] for s in samples]
    t0, t1 = ts[0], ts[-1]
    span = max((t1 - t0).total_seconds(), 1)
    lo = min(vals + ([band[0]] if band else []) + ([line] if line is not None else []))
    hi = max(vals + ([band[1]] if band else []) + ([line] if line is not None else []))
    pad = (hi - lo) * 0.08 or 1
    vmin, vmax = lo - pad, hi + pad
    X = lambda t: pl + (t - t0).total_seconds() / span * w
    Y = lambda v: pt + (1 - (v - vmin) / (vmax - vmin)) * h
    deltas = sorted((b - a).total_seconds() for a, b in zip(ts, ts[1:]))
    gap = 3 * deltas[len(deltas) // 2]
    o = [f"<svg viewBox='0 0 {W} {H:.0f}' class='chart' style='font-size:{fs:.1f}px' role='img' aria-label='{e(param)}'>"]
    if band:
        o.append(f"<rect x='{pl:.1f}' y='{Y(band[1]):.1f}' width='{w:.1f}' height='{Y(band[0]) - Y(band[1]):.1f}' class='band'/>")
    for v in (lo, hi):
        o.append(f"<line x1='{pl:.1f}' x2='{pl + w:.1f}' y1='{Y(v):.1f}' y2='{Y(v):.1f}' class='grid'/>"
                 f"<text x='{pl - 0.3 * fs:.1f}' y='{Y(v) + 0.35 * fs:.1f}' text-anchor='end' class='ax'>{fnum(v, 0 if abs(v) >= 100 else 1)}</text>")
    if line is not None:
        o.append(f"<line x1='{pl:.1f}' x2='{pl + w:.1f}' y1='{Y(line):.1f}' y2='{Y(line):.1f}' class='ref'/>")
    segs, cur = [], [samples[0]]
    for a, b in zip(samples, samples[1:]):
        if (b["timestamp"] - a["timestamp"]).total_seconds() > gap:
            segs.append(cur)
            cur = []
        cur.append(b)
    segs.append(cur)
    dense = len(samples) > 900
    for seg in segs:
        if dense and len(seg) > 4:
            bins = max(2, int(len(seg) / len(samples) * 420))
            size = len(seg) / bins
            up, dn = [], []
            for i in range(bins):
                ch = seg[int(i * size): int((i + 1) * size)] or [seg[min(int(i * size), len(seg) - 1)]]
                x = X(ch[len(ch) // 2]["timestamp"])
                up.append(f"{x:.1f},{Y(max(c[param] for c in ch)):.1f}")
                dn.append(f"{x:.1f},{Y(min(c[param] for c in ch)):.1f}")
            o.append(f"<polygon points='{' '.join(up + dn[::-1])}' class='env'/>")
        elif len(seg) == 1:
            o.append(f"<circle cx='{X(seg[0]['timestamp']):.1f}' cy='{Y(seg[0][param]):.1f}' r='{0.25 * fs:.1f}' class='dot'/>")
        else:
            o.append("<polyline points='" + " ".join(f"{X(s['timestamp']):.1f},{Y(s[param]):.1f}" for s in seg) + "' class='ln'/>")
    o.append(f"<text x='{pl:.1f}' y='{H - 0.25 * fs:.1f}' class='ax'>{t0:%d.%m.}</text>"
             f"<text x='{pl + w:.1f}' y='{H - 0.25 * fs:.1f}' text-anchor='end' class='ax'>{t1:%d.%m.%Y}</text>"
             f"<text x='{pl:.1f}' y='{1.05 * fs:.1f}' class='ttl'>{e(param)} [{e(unit)}]</text></svg>")
    return "".join(o)


def class_bar(shares) -> str:
    return "<div class='bar'>" + "".join(f"<span class='c{i + 1}' style='width:{s:.2f}%'></span>" for i, s in enumerate(shares) if s > 0) + "</div>"


# ---------------------------------------------------------------- Daten

def room_bundle(room, assessment, rules, building) -> dict:
    parsed = long_to_samples(room)
    samples = parsed["samples"]
    usage = filter_usage(samples, room)
    basis = usage if usage else samples
    ev = evaluate_room(room, assessment, rules, building)
    return {"room": room, "parsed": parsed, "samples": samples, "basis": basis, "ev": ev, "st": ev["status"],
            "rule": match_bt_rule(rules, assessment.get("period"), room),
            "stats": describe(basis) if basis else {}, "time": time_stats(samples, room.get("measurement_interval_min")),
            "co2cls": co2_classes(basis), "required": ev["required"], "hints": conditional_hints(room, assessment, parsed),
            "vent": effective_ventilation(room) or room.get("ventilation")}


def prio(b):
    return (STATUS_ORDER.index(b["st"]), -b["stats"].get("CO₂", {}).get("p95", 0))


def page_plan(n: int) -> dict:
    """Seitenplan (nicht proportional zur Raumzahl)."""
    if n <= 1:
        return {"mode": "einzelraum", "pages": 2, "profiles": n, "matrix_pages": 0, "esg_page": 0}
    combined = n <= COMBINE_LIMIT
    matrix = 1 if combined else math.ceil(n / MATRIX_ROWS)
    profiles = min(n, MAX_PROFILES)
    esg = 0 if combined else 1
    return {"mode": "mehrraum", "profiles": profiles, "matrix_pages": matrix, "esg_page": esg,
            "pages": 1 + matrix + esg + math.ceil(profiles / PROFILES_PER_PAGE) + 1}


def _period(bs):
    s = [b["time"]["beginn"] for b in bs if b["time"]]
    t = [b["time"]["ende"] for b in bs if b["time"]]
    return (min(s), max(t)) if s else (None, None)


def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


# ---------------------------------------------------------------- CSS

CSS = """
@page{size:A4;margin:13mm 14mm 14mm 14mm;@bottom-left{content:'IAQ-Nachweis · Vorlage P6 V12';font:8pt Arial;color:#5d6b7a}@bottom-right{content:'Seite ' counter(page) ' / ' counter(pages);font:8pt Arial;color:#5d6b7a}}
*{box-sizing:border-box}
:root{--ink:#16212e;--muted:#4f5d6b;--line:#cfd7e0;--soft:#f1f4f7;--accent:#1f4e79;
--ok:#1e6b3f;--okbg:#dff1e6;--dev:#7a5200;--devbg:#fdeec4;--chk:#a3170f;--chkbg:#fde1dd;--na:#4f5d6b;--nabg:#e6eaee}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;font:12pt/1.32 Arial,"Helvetica Neue",sans-serif;color:var(--ink);background:#e5e9ee}
.page{width:210mm;height:297mm;margin:8mm auto;background:#fff;padding:13mm 14mm 14mm;box-shadow:0 1px 6px rgba(0,0,0,.18);position:relative;overflow:hidden}
@media print{body{background:#fff}.page{margin:0;box-shadow:none;width:auto;height:270mm;padding:0;break-after:page}.page:last-child{break-after:auto}.noprint{display:none}}
h1{font-size:22pt;margin:0;color:var(--accent);line-height:1.12}
h2{font-size:15pt;color:var(--accent);margin:0 0 2.5mm}
h3{font-size:13pt;margin:3.5mm 0 1.5mm}
p{margin:0 0 2mm}.muted{color:var(--muted)}
table{width:100%;border-collapse:collapse;margin:0 0 3mm;font-size:12pt}
th,td{border-bottom:1px solid var(--line);padding:1.2mm 1.6mm;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:700;border-bottom:1.4px solid #aab6c3}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.kv td:first-child{color:var(--muted);width:42%}
.mx{table-layout:fixed}.mx td{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.page>:last-child{margin-bottom:0}
.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.head{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2.5px solid var(--accent);padding-bottom:2.2mm;margin-bottom:3.5mm}
.head .meta{text-align:right;color:var(--muted);line-height:1.35}
.eyebrow{font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
.run{display:flex;justify-content:space-between;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:1.5mm;margin-bottom:3.5mm}
.banner{border-radius:2.5mm;padding:3mm 4mm;margin-bottom:3.5mm;display:flex;gap:4mm;align-items:center;border:2px solid}
.banner .big{font-size:18pt;font-weight:700;line-height:1.15;margin-bottom:1mm}
.banner.ok{background:var(--okbg);border-color:var(--ok)}.banner.ok .big{color:var(--ok)}
.banner.dev{background:var(--devbg);border-color:#c99400}.banner.dev .big{color:var(--dev)}
.banner.chk{background:var(--chkbg);border-color:var(--chk)}.banner.chk .big{color:var(--chk)}
.banner.na{background:var(--nabg);border-color:var(--na)}
.banner .sign{flex:0 0 13mm;height:13mm;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20pt;font-weight:700;color:#fff}
.banner.ok .sign{background:var(--ok)}.banner.dev .sign{background:#c99400}.banner.chk .sign{background:var(--chk)}.banner.na .sign{background:var(--na)}
.frame{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:2mm;margin-bottom:3.5mm}
.frame div{padding:1.3mm 2.4mm;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.frame div:nth-child(3n){border-right:0}.frame div:nth-last-child(-n+3){border-bottom:0}
.frame span{display:block;color:var(--muted)}.frame b{display:block}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:3mm;margin-bottom:3.5mm}
.tile{border-radius:2.5mm;padding:2.2mm 3mm;border:1.5px solid transparent}
.tile.ok{background:var(--okbg);border-color:#9fd1b2}.tile.dev{background:var(--devbg);border-color:#e7c766}
.tile.chk{background:var(--chkbg);border-color:#f0a59c}.tile.na{background:var(--nabg);border-color:#c3ccd5}
.tile .tt{font-weight:700;font-size:13pt}.tile .tq{color:var(--muted)}
.tile .tv{font-size:16pt;font-weight:700;margin:.6mm 0}
.tile.ok .tv{color:var(--ok)}.tile.dev .tv{color:var(--dev)}.tile.chk .tv{color:var(--chk)}.tile.na .tv{color:var(--na)}
.tile .tk{border-top:1px solid rgba(0,0,0,.15);margin-top:1.4mm;padding-top:1.2mm}
.figs{display:grid;grid-template-columns:repeat(4,1fr);gap:3mm;margin-bottom:3.5mm}
.fig{background:var(--soft);border-radius:2mm;padding:2mm 2.6mm}.fig .v{font-size:16pt;font-weight:700;color:var(--accent)}
.chip{display:inline-block;padding:.3mm 2.2mm;border-radius:6mm;font-weight:700;white-space:nowrap;font-size:12pt}
.chip.ok{background:var(--okbg);color:var(--ok)}.chip.dev{background:var(--devbg);color:var(--dev)}
.chip.chk{background:var(--chkbg);color:var(--chk)}.chip.na{background:var(--nabg);color:var(--na)}
.alert{border:2px solid var(--chk);border-radius:2.5mm;padding:2.6mm 3.4mm;margin-bottom:3.5mm}
.alert h3{margin:0 0 1.5mm;color:var(--chk)}
.alert ul,.note ul{margin:0;padding-left:5mm}.alert li,.note li{margin-bottom:1mm}
.note{background:var(--soft);border-radius:2mm;padding:2.4mm 3.2mm;margin-bottom:3mm}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:4mm}
.chart{width:100%;height:auto;display:block;margin-bottom:2mm}
.chart .band{fill:#1e6b3f;opacity:.12}.chart .ref{stroke:#a3170f;stroke-dasharray:6 4;stroke-width:2}
.chart .grid{stroke:#dfe5eb;stroke-width:1.2}.chart .ln{fill:none;stroke:#1f4e79;stroke-width:2}
.chart .env{fill:#1f4e79;opacity:.55}.chart .dot{fill:#1f4e79}.chart .ax{fill:#4f5d6b}.chart .ttl{font-weight:700;fill:#16212e}
.bar{display:flex;height:5mm;border-radius:1.2mm;overflow:hidden;background:var(--soft);margin:1mm 0}
.bar span{display:block;height:100%}.c1{background:#1e6b3f}.c2{background:#d9a21b}.c3{background:#d0632a}.c4{background:#a3170f}
.card{border:1.5px solid var(--line);border-radius:2.5mm;padding:3mm 3.4mm;height:116mm;margin-bottom:4mm;overflow:hidden}
.card .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5mm}
.card .top b{font-size:14pt}
.card .chips{margin-bottom:2mm;line-height:1.9}
.sig{display:grid;grid-template-columns:1fr 1fr;gap:10mm;margin-top:7mm}
.sig div{border-top:1px solid var(--ink);padding-top:1.2mm;color:var(--muted)}
.src{font-size:8.5pt;color:var(--muted);padding-left:4.5mm;margin:0}.src li{margin-bottom:.3mm}
.printbtn{position:fixed;right:16px;top:16px;background:#1f4e79;color:#fff;border:0;padding:9px 14px;border-radius:6px;font:700 13px Arial;cursor:pointer;z-index:9}
.demo{position:absolute;top:4mm;right:14mm;font-size:9pt;font-weight:700;color:var(--chk);letter-spacing:.5px}
@media print{.demo{top:-8mm;right:0}}
"""


# ---------------------------------------------------------------- Bausteine

def _head(p, meta, demo, eyebrow):
    b = p["building"]
    return (("<div class='demo'>BEISPIELDATEN – SYNTHETISCH</div>" if demo else "")
            + f"<div class='head'><div><div class='eyebrow'>{e(eyebrow)}</div><h1>{e(b.get('name'))}</h1>"
              f"<div class='muted'>{e(b.get('location'))}</div></div>"
              f"<div class='meta'>Bericht {e(meta.get('report_no'))} · V {e(meta.get('version'))}<br>{e(meta.get('date'))}<br>{e(meta.get('author'))}</div></div>")


def _run(p, meta, title):
    return (f"<div class='run'><span><b style='color:var(--accent)'>{e(title)}</b> · {e(p['building'].get('name'))}</span>"
            f"<span>Bericht {e(meta.get('report_no'))}</span></div>")


def _frame(a, bs, building):
    start, end = _period(bs)
    years = sum(1 for b in bs if b["ev"]["jahr"])
    strat = ", ".join(sorted({SSHORT.get(b["room"].get("strategy"), "–") for b in bs}))
    devs = sorted({str(b["room"].get("device_model") or "").strip() for b in bs} - {""})
    dev = (devs[0] if len(devs) == 1 else f"{len(devs)} Gerätetypen") if devs else "nicht angegeben"
    cells = [("Messart", strat), ("Messgerät", dev[:34]), ("Betriebsfall", a.get("period")),
             ("Messzeitraum", f"{fdt(start)} – {fdt(end)}"), ("Jahresbezug", f"{years} von {len(bs)} Räumen"),
             ("Objekt-ID · Höhe", f"{building.get('object_id') or '–'} · {building.get('altitude_m') or '–'} m ü. M.")]
    return "<div class='frame'>" + "".join(f"<div><span>{e(k)}</span><b>{e(v)}</b></div>" for k, v in cells) + "</div>"


SIGN = {"ok": "✓", "dev": "!", "chk": "!", "na": "?"}


def _banner(css, big, sub):
    return f"<div class='banner {css}'><div class='sign'>{SIGN[css]}</div><div><div class='big'>{e(big)}</div><div>{sub}</div></div></div>"


def _tiles(bs, single=False):
    out = []
    n = len(bs)
    for t in TOPICS:
        info = TOPIC_INFO[t]
        tps = [b["ev"]["topics"].get(t, {}) for b in bs]
        sts = [tp.get("status") for tp in tps]
        if t == "Datenbasis":
            ok = sum(1 for s in sts if s == "Jahresbezug")
            css = "ok" if ok == n else "na"
            val = SHORT.get(sts[0], sts[0]) if single else f"{ok} von {n} mit Jahresbezug"
            res = tps[0].get("text", "") if single else "Kürzere Messungen gelten als Indikation."
        else:
            app = [s for s in sts if s != STATUS_NAPP]
            worst = next((s for s in STATUS_ORDER if s in app), STATUS_NAPP)
            css = CSSK.get(worst, "na")
            if single:
                val = SHORT.get(sts[0], sts[0])
                res = tps[0].get("kurz") or tps[0].get("text", "")
            else:
                ok = sum(1 for s in app if s == STATUS_OK)
                val = f"{ok} von {len(app)} eingehalten" if app else "nicht anwendbar"
                med = _median([tp.get("kpi") for tp in tps])
                res = f"Median: {fpct(med)} der Nutzungszeit im Kriterium" if med is not None else ""
        out.append(f"<div class='tile {css}'><div class='tt'>{e(t)}</div>"
                   f"<div class='tv'>{e(val)}</div><div>{e(res)}</div><div class='tk'>{e(info['krit'])}</div></div>")
    return "<div class='tiles'>" + "".join(out) + "</div>"


def _limits(bs):
    lines = []
    short = sum(1 for b in bs if not b["ev"]["jahr"])
    if short:
        lines.append(f"<b>Kein Jahresnachweis:</b> {short} von {len(bs)} Räumen kürzer als ein Nutzungsjahr gemessen – Ergebnis gilt als Indikation für den Messzeitraum.")
    lines.append("Gemessen wird die Lufttemperatur, nicht die empfundene Temperatur. Keine Bescheinigung von Gesetz-, Norm- oder Label-Konformität.")
    return "<div class='note'><b>Aussagegrenze</b><ul>" + "".join(f"<li>{l}</li>" for l in lines) + "</ul></div>"


def _stats(b):
    rows = "".join(f"<tr><td>{e(p)} [{e(u)}]</td>" + "".join(f"<td class='n'>{fnum(b['stats'][p][k], 0 if p == 'CO₂' else 1)}</td>" for k in ("min", "median", "p95", "max")) + "</tr>"
                   for p, u in CORE.items() if p in b["stats"])
    return f"<table><tr><th>Messgrösse (Bezug)</th><th class='n'>Min</th><th class='n'>Median</th><th class='n'>P95</th><th class='n'>Max</th></tr>{rows}</table>"


def _criteria():
    return ("<table><tr><th style='width:24%'>Fokusthema</th><th>Kriterium</th><th style='width:33%'>Quelle</th></tr>"
            + "".join(f"<tr><td><b>{e(t)}</b></td><td>{e(TOPIC_INFO[t]['krit'])}</td><td>{e(TOPIC_INFO[t]['quelle'])}</td></tr>" for t in TOPICS) + "</table>")


def _sources():
    return "<ol class='src'>" + "".join(f"<li>{e(s)}</li>" for s in SOURCES) + "</ol>"


def _sig(meta):
    return f"<div class='sig'><div>Erstellt: {e(meta.get('author'))}, Datum</div><div>Geprüft / freigegeben</div></div>"


# ---------------------------------------------------------------- Einzelraum (2 Seiten)

def _single(p, a, b, meta, demo):
    r, ev, t = b["room"], b["ev"], b["time"]
    css = CSSK.get(b["st"], "na")
    sub = f"{e(r.get('name'))} · Bezug: {e(ev['bezug'])}" + "".join(f"<br><b>{e(k)}</b>" for k in ev["kurz"][:1])
    c = b["stats"].get("CO₂")
    p1 = f"""<section class='page'>{_head(p, meta, demo, 'IAQ-Nachweis · Ergebnis')}
{_banner(css, ev['status'], sub)}
{_frame(a, [b], p['building'])}
{_tiles([b], single=True)}
<div class='figs'><div class='fig'><div class='v'>{fnum(len(b['basis']))}</div>Messpunkte im Bezug</div>
<div class='fig'><div class='v'>{t.get('tage', '–') if t else '–'}</div>Messtage</div>
<div class='fig'><div class='v'>{fnum(c['median']) if c else '–'}</div>CO₂-Median [ppm]</div>
<div class='fig'><div class='v'>{fnum(c['max']) if c else '–'}</div>CO₂-Maximum [ppm]</div></div>
{_limits([b])}
</section>"""
    rule = b["rule"]
    if len(b["samples"]) > 12:
        charts = (series_svg(b["samples"], "CO₂", "ppm", None, 1000, CONTENT_MM, 40)
                  + "<div class='cols'>" + series_svg(b["samples"], "Temperatur", "°C", (rule["temp_min"], rule["temp_max"]) if rule else None, None, 89, 42)
                  + series_svg(b["samples"], "Relative Feuchte", "%", None, None, 89, 42) + "</div>"
                  + "<p class='muted'>Rot gestrichelt: CO₂ 1'000 ppm · grün: Temperaturbereich SECO</p>")
    else:
        charts = ("<table><tr><th>Zeitpunkt</th><th class='n'>CO₂</th><th class='n'>T</th><th class='n'>r. F.</th></tr>"
                  + "".join(f"<tr><td>{fdt(m['timestamp'], True)}</td><td class='n'>{fnum(m['CO₂'])}</td><td class='n'>{fnum(m['Temperatur'], 1)}</td><td class='n'>{fnum(m['Relative Feuchte'], 1)}</td></tr>" for m in b["samples"][:8]) + "</table>")
    dq = [("Vollständige / alle Zeitpunkte", f"{b['parsed']['vollstaendig']} / {b['parsed']['zeitpunkte']}"),
          ("Intervall Soll / Median", f"{fnum(t.get('soll_intervall_min'))} / {fnum(t.get('median_intervall_min'))} min" if t else None),
          ("Zeitabdeckung", fpct(t.get("abdeckung_pct")) if t else None),
          ("Messhöhe · Geräte", f"{r.get('sensor_height_m') or '–'} m · {r.get('sensor_count') or '–'}")]
    open_items = b["required"] + b["hints"]
    oi = "".join(f"<li>{e(x)}</li>" for x in open_items[:3]) + (f"<li>{len(open_items) - 3} weitere im Tool</li>" if len(open_items) > 3 else "")
    p2 = f"""<section class='page'>{_run(p, meta, 'Detail')}
<h2>Zeitverläufe</h2>{charts}
<h2>Messwerte</h2>{_stats(b)}
<div class='cols'><div><h3 style='margin-top:0'>Datenbasis</h3><table class='kv'>{''.join(f'<tr><td>{e(k)}</td><td>{e(v)}</td></tr>' for k, v in dq)}</table></div>
<div>{f"<div class='note'><b>Offene Angaben</b><ul>{oi}</ul></div>" if open_items else ''}</div></div>
{_sources()}{_sig(meta)}
</section>"""
    return p1 + p2


# ---------------------------------------------------------------- Mehrraum

def _overview(p, a, bs, meta, demo):
    n = len(bs)
    need = [b for b in sorted(bs, key=prio) if b["st"] in (STATUS_CHECK, STATUS_DEV)]
    worst = min(bs, key=prio)["st"]
    css = CSSK.get(worst, "na") if need else ("ok" if all(b["st"] == STATUS_OK for b in bs) else "na")
    big = (f"{len(need)} von {n} Räumen mit Handlungsbedarf" if need
           else f"Alle {n} Räume im Messzeitraum eingehalten" if css == "ok" else "Bewertung unvollständig")
    counts = " ".join(chip(s, f"{SHORT[s]} {sum(1 for b in bs if b['st'] == s)}") for s in STATUS_ORDER)
    acts = ""
    if need:
        acts = ("<div class='alert'><h3>Handlungsbedarf – dringlichste Räume</h3><ul>"
                + "".join(f"<li><div class='clamp'>{chip(b['st'])} <b>{e(b['room'].get('name'))}</b>: {e((b['ev']['kurz'] or [''])[0])}</div></li>" for b in need[:OVERVIEW_ACTIONS])
                + (f"<li>{len(need) - OVERVIEW_ACTIONS} weitere: Raummatrix Seite 2</li>" if len(need) > OVERVIEW_ACTIONS else "") + "</ul></div>")
    return f"""<section class='page'>{_head(p, meta, demo, 'IAQ-Nachweis · Ergebnis auf einen Blick')}
{_banner(css, big, counts)}
{_frame(a, bs, p['building'])}
<h2 style='margin-bottom:2mm'>Ergebnis nach Fokusthema</h2>{_tiles(bs)}
{acts}
</section>"""


def _matrix_rows(chunk):
    return "".join(f"<tr><td><b>{e(b['room'].get('name'))}</b></td><td>{e(VSHORT.get(b['vent'], b['vent']))}</td>"
                   + "".join(f"<td>{tchip(b, t)}</td>" for t in TOPICS[:3]) + f"<td>{chip(b['st'], 'nicht bew.' if b['st'] == STATUS_NA else None)}</td></tr>" for b in chunk)


MATRIX_HEAD = "<table class='mx'><colgroup><col style='width:29%'><col style='width:14%'><col style='width:13%'><col style='width:12.5%'><col style='width:12.5%'><col style='width:19%'></colgroup><tr><th>Raum</th><th>Lüftung</th><th>Luftqualität</th><th>Thermik</th><th>Feuchte</th><th>Gesamt</th></tr>"
MATRIX_NOTE = "<p class='muted'>% = Anteil der Nutzungszeit, der das Kriterium erfüllt. Farbe = Einordnung. Sortiert nach Handlungsbedarf.</p>"


def _esg(bs):
    v = [b for b in bs if b["basis"]]
    def rng(vals):
        vals = [x for x in vals if x is not None]
        return f"{fpct(min(vals))} – {fpct(max(vals))}" if vals else "–"
    def cnt(t):
        app = [b for b in bs if b["ev"]["topics"].get(t, {}).get("status") != STATUS_NAPP]
        return f"{sum(1 for b in app if b['ev']['topics'][t]['status'] == STATUS_OK)} von {len(app)}"
    rows = [("Luftqualität", "Räume eingehalten", cnt("Luftqualität")),
            ("", "Nutzungszeit in IDA 1–2", rng([b["ev"]["topics"]["Luftqualität"].get("kpi") for b in v])),
            ("", "Räume mit CO₂ ≥ 2'000 ppm", str(sum(1 for b in bs if b["st"] == STATUS_CHECK))),
            ("Thermischer Komfort", "Räume eingehalten", cnt("Thermischer Komfort")),
            ("", "Nutzungszeit im Bereich", rng([b["ev"]["topics"]["Thermischer Komfort"].get("kpi") for b in v])),
            ("Raumluftfeuchte", "Räume eingehalten", cnt("Raumluftfeuchte")),
            ("Datenbasis", "Räume mit Jahresbezug", f"{sum(1 for b in bs if b['ev']['jahr'])} von {len(bs)}"),
            ("", "Räume mit Langzeitmessung", f"{sum(1 for b in bs if b['room'].get('strategy') == STRATEGIES[2])} von {len(bs)}")]
    return ("<h2>ESG-Kennzahlen nach Fokusthema</h2><table><tr><th style='width:30%'>Fokusthema</th><th>Kennzahl</th><th class='n'>Wert</th></tr>"
            + "".join(f"<tr><td><b>{e(g) if g else ''}</b></td><td>{e(k)}</td><td class='n'><b>{e(x)}</b></td></tr>" for g, k, x in rows) + "</table>"
            "<p class='muted'>Bezug: GRESB 2026 TC5.2 (Innenraumluftqualität, IEQ); EU Level(s) 4.1. Messbeleg, keine Erfüllungsaussage.</p>")


def _matrix_esg_pages(p, bs, meta, plan):
    ordered = sorted(bs, key=prio)
    if plan["esg_page"] == 0:
        return (f"<section class='page'>{_run(p, meta, 'Raummatrix und ESG')}<h2>Räume × Fokusthemen</h2>"
                f"{MATRIX_HEAD}{_matrix_rows(ordered)}</table>{MATRIX_NOTE}{_esg(bs)}</section>")
    out = ""
    for k in range(0, len(ordered), MATRIX_ROWS):
        out += (f"<section class='page'>{_run(p, meta, 'Raummatrix')}<h2>Räume × Fokusthemen{' (Fortsetzung)' if k else ''}</h2>"
                f"{MATRIX_HEAD}{_matrix_rows(ordered[k:k + MATRIX_ROWS])}</table>{MATRIX_NOTE}</section>")
    return out + f"<section class='page'>{_run(p, meta, 'ESG-Kennzahlen')}{_esg(bs)}{_limits(bs)}</section>"


def _card(b, idx):
    r, ev, t = b["room"], b["ev"], b["time"]
    c = b["stats"].get("CO₂")
    kv = [("CO₂ Median / Max", f"{fnum(c['median'])} / {fnum(c['max'])} ppm" if c else "–"),
          ("Lüftung · Strategie", f"{VSHORT.get(b['vent'], b['vent'])} · {SSHORT.get(r.get('strategy'), '–')}"),
          ("Messzeitraum", f"{fdt(t.get('beginn'))} – {fdt(t.get('ende'))}" if t else "–"),
          ("Messhöhe · Geräte", f"{r.get('sensor_height_m') or '–'} m · {r.get('sensor_count') or '–'}")]
    chart = series_svg(b["samples"], "CO₂", "ppm", None, 1000, 88, 50) if len(b["samples"]) > 12 else (
        "<table><tr><th>Zeit</th><th class='n'>CO₂</th></tr>" + "".join(f"<tr><td>{fdt(m['timestamp'], True)}</td><td class='n'>{fnum(m['CO₂'])}</td></tr>" for m in b["samples"][:5]) + "</table>")
    reasons = "".join(f"<li>{e(k)}</li>" for k in ev["kurz"][:2]) or "<li>Alle anwendbaren Kriterien eingehalten.</li>"
    chips = " ".join(f"{e(t_)} {tchip(b, t_)}" for t_ in TOPICS[:3])
    return f"""<div class='card'><div class='top'><b class='clamp'>{idx}. {e(r.get('name'))}</b>{chip(b['st'])}</div>
<div class='chips'>{chips}</div>
<div class='cols'><div><table class='kv'>{''.join(f'<tr><td>{e(k)}</td><td>{e(v)}</td></tr>' for k, v in kv)}</table><ul style='margin:0;padding-left:5mm'>{reasons}</ul></div>
<div>{chart}<div>CO₂-Klassen (SECO): {class_bar(b['co2cls'])}<span class='muted'>&lt; 1'000 ppm: {fpct(b['co2cls'][0])} · ≥ 2'000 ppm: {fpct(b['co2cls'][3])}</span></div></div></div></div>"""


def _profiles(p, bs, meta, plan):
    ordered = sorted(bs, key=prio)[:plan["profiles"]]
    out = []
    for k in range(0, len(ordered), PROFILES_PER_PAGE):
        note = (f"<p class='muted'>{len(ordered)} von {len(bs)} Räumen, priorisiert nach Handlungsbedarf; übrige in der Raummatrix.</p>"
                if len(bs) > len(ordered) and k == 0 else "")
        out.append(f"<section class='page'>{_run(p, meta, 'Raumprofile')}{note}" + "".join(_card(b, k + i + 1) for i, b in enumerate(ordered[k:k + PROFILES_PER_PAGE])) + "</section>")
    return "".join(out)


def _method(p, bs, meta, plan):
    na = [b for b in bs if b["required"]]
    na_html = ("<div class='alert'><h3>Nicht bewertbar</h3><ul>" + "".join(f"<li><b>{e(b['room'].get('name'))}:</b> {e(b['required'][0])}</li>" for b in na[:4]) + "</ul></div>") if na else ""
    lim = _limits(bs) if plan["esg_page"] == 0 else ""
    return f"""<section class='page'>{_run(p, meta, 'Methodik und Freigabe')}
<h2>Bewertungskriterien</h2>{_criteria()}
<div class='note'><b>Einordnung</b><ul>
<li>Gesamt = ungünstigstes Fokusthema (Luftqualität, Thermik, Feuchte).</li>
<li><b>{TOL_SHARE:g} %-Regel</b> nur wo die Norm sie nennt: Der Nachweis bestätigt die Vorgaben im Normalbetrieb; zulässig sind Abweichungen in ≤ 10 % der Nutzungszeit eines Jahres (zeitgewichtet).</li>
<li>IDA-Klassen für alle Lüftungsarten (SIA 382/1:2025 Tab. 18, Fussnote 3).</li></ul></div>
{lim}{na_html}
{_sources()}{_sig(meta)}
</section>"""


def build_report(project: dict, rules: list, rooms: list | None = None, meta: dict | None = None, demo: bool = False) -> str:
    """Bericht als HTML (A4; im Browser «Als PDF drucken»)."""
    a = project["assessment"]
    building = project.get("building", {})
    rooms = project["rooms"] if rooms is None else rooms
    meta = {"date": date.today().strftime("%d.%m.%Y"), **(project.get("report") or {}), **(meta or {})}
    bs = [room_bundle(r, a, rules, building) for r in rooms]
    plan = page_plan(len(bs))
    if not bs:
        body = f"<section class='page'>{_head(project, meta, demo, 'IAQ-Nachweis')}<p>Keine Räume erfasst.</p></section>"
    elif plan["mode"] == "einzelraum":
        body = _single(project, a, bs[0], meta, demo)
    else:
        body = (_overview(project, a, bs, meta, demo) + _matrix_esg_pages(project, bs, meta, plan)
                + _profiles(project, bs, meta, plan) + _method(project, bs, meta, plan))
    return (f"<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>IAQ-Nachweis – {e(project['building'].get('name'))}</title><style>{CSS}</style></head><body>"
            f"<button class='printbtn noprint' onclick='window.print()'>Als PDF drucken (A4)</button>{body}</body></html>")
