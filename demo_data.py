"""Synthetische Beispieldaten zum Testen des Tools (keine Messdaten, keine Aussage über reale Räume).

Die Verläufe sind deterministisch erzeugt (fester Zufallsstartwert), damit Tests reproduzierbar sind.
Projekte aus dieser Funktion tragen "demo": True; der Bericht wird dann als BEISPIELDATEN gekennzeichnet.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from iaq_logic import PERIODS, PROFILE_BT, PURPOSES, STRATEGIES, VENTS, measurement_records

ROOM_TYPES = [
    ("Grossraumbüro", VENTS[0], 14, 520, 0.0),
    ("Sitzungszimmer", VENTS[1], 10, 1500, 0.0),
    ("Einzelbüro", VENTS[1], 1, 450, 0.3),
    ("Doppelbüro", VENTS[0], 2, 300, 0.1),
    ("Projektraum", VENTS[2], 6, 800, 0.2),
]


def _series(rng, start, days, iv, amp, sawtooth, t_off):
    out, t, end = [], start, start + timedelta(days=days)
    while t < end:
        if t.weekday() < 5:
            h = t.hour + t.minute / 60
            occ = 8 <= h < 17
            if sawtooth:
                co2 = 450 + (((h - 8) % 3) / 3 * amp if occ else 0)
            else:
                co2 = 430 + (amp * math.sin(math.pi * (h - 8) / 9) if occ else 0)
            co2 = max(410, co2 + rng.gauss(0, 25))
            temp = 21.9 + t_off + (0.8 if occ else -0.7) + rng.gauss(0, 0.15)
            rh = 33 + (5 if occ else 0) + rng.gauss(0, 1)
            out += measurement_records(t.strftime("%Y-%m-%d %H:%M"), round(co2), round(temp, 1), round(rh, 1))
        t += timedelta(minutes=iv)
    return out


def build_demo_project(n_rooms: int = 3, days: int = 5, interval_min: int = 5) -> dict:
    rng = random.Random(7)
    rooms = []
    for i in range(n_rooms):
        name, vent, persons, amp, t_off = ROOM_TYPES[i % len(ROOM_TYPES)]
        floor = 1 + i // len(ROOM_TYPES)
        spot = (i == n_rooms - 1 and n_rooms > 2)            # letzter Raum: Stichprobe
        r = {
            "id": f"demo{i + 1:02d}", "name": f"{floor}.{i + 1:02d} {name}", "use": "Büro", "ventilation": vent,
            "ventilation_mode": "Natürlich" if vent == VENTS[2] else "", "active_cooling": False,
            "strategy": STRATEGIES[0] if spot else STRATEGIES[1], "occupancy": f"{persons} Personen",
            "area_m2": str(12 + persons * 8), "measurement_position": "Raummitte, Tisch", "sensor_height_m": "1.1", "sensor_count": str(1 + (12 + persons * 8) // 50), "position_check": True, "device_id": f"DEMO-{i + 1:03d}",
            "device_model": "Beispielgerät", "calibration": "Prüfangabe Beispiel", "data_gaps": "keine",
            "occupancy_log": "Beispiel", "selection_reason": "Beispiel: Raumtyp " + name,
            "heating_system": "Heizkörper", "cooling_system": "keine", "window_ventilation": "ja", "recirculation": "nein",
            "usage_blocks": [] if spot else [{"days": ["Mo", "Di", "Mi", "Do", "Fr"], "start": "08:00", "end": "17:00", "persons": persons}],
            "absences": "", "occupancy_source": "Belegungsplan (manuell)", "occupancy_intervals": [], "outdoor_co2_ppm": None,
            "measurement_interval_min": None if spot else interval_min,
            "start_date": "2026-11-02", "end_date": "2026-11-06", "usage_times": "", "notes": "",
        }
        if spot:
            r["measurements"] = sum((measurement_records(f"2026-11-09 {h}", c, t, f) for h, c, t, f in
                                     (("09:00", 640, 22.1, 34), ("10:30", 780, 22.4, 35), ("14:00", 860, 22.8, 36))), [])
        else:
            r["measurements"] = _series(rng, datetime(2026, 11, 2), days, interval_min, amp + rng.uniform(-80, 80),
                                        name == "Sitzungszimmer", t_off)
        rooms.append(r)
    return {
        "schema_version": 11, "demo": True,
        "building": {"name": "Verwaltungsgebäude Beispiel", "location": "Musterstrasse 1, 4000 Basel", "object_id": "DEMO-001",
                     "owner": "Beispiel AG", "altitude_m": "260", "operating_hours": "Mo–Fr 07:00–19:00", "notes": ""},
        "assessment": {"basis": PROFILE_BT, "period": PERIODS[0], "purpose": PURPOSES[1], "notes": "Synthetische Beispieldaten"},
        "report": {"report_no": "DEMO-2026-01", "version": "1.0", "author": "R. Lüthi"},
        "rooms": rooms, "step_notes": {},
    }
