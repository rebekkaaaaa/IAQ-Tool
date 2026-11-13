"""Tests Datenimport (synthetische Dateien in typischen Exportstilen; keine echten Gerätedateien)."""
import io, json, unittest
from datetime import datetime, timedelta
import openpyxl
import iaq_import as imp
from iaq_logic import long_to_samples, filter_usage, usage_defined, OCC_SOURCES

DEV = {d["id"]: d for d in imp.load_devices()}


def room_with(records):
    return {"measurements": records}


class TestImport(unittest.TestCase):
    def test_standard_format_decimal_comma(self):
        data = "timestamp;co2_ppm;temp_c;rh_pct\n2026-11-02 08:00;612;21,4;38,5\n2026-11-02 08:05;655;21,5;38,9\n".encode()
        res = imp.auto_import(data, "x.csv")
        self.assertEqual(res["log"]["vollstaendig"], 2)
        s = long_to_samples(room_with(res["records"]))["samples"]
        self.assertAlmostEqual(s[0]["Temperatur"], 21.4)

    def test_preamble_split_date_fahrenheit(self):
        txt = ("Logger XY\nSerial: 123\n\nDatum;Zeit;CO2 [ppm];Temperatur [°F];Feuchte [%rH]\n"
               "02.11.2026;08:00:00;700;71,6;40\n02.11.2026;08:10:00;720;73,4;41\n")
        res = imp.auto_import(txt.encode("cp1252"), "a.txt")
        s = long_to_samples(room_with(res["records"]))["samples"]
        self.assertEqual(len(s), 2)
        self.assertAlmostEqual(s[0]["Temperatur"], 22.0, places=3)
        self.assertIn("Temperatur: °F → °C", res["log"]["umrechnungen"])

    def test_ambiguous_us_date_needs_choice(self):
        data = b"Time,Carbon dioxide(ppm),Temperature(\xc2\xb0C),Relative humidity(%)\n03/04/2026 10:00,800,22,45\n03/04/2026 10:05,810,22,45\n03/04/2026 10:10,820,22,45\n"
        with self.assertRaises(ValueError):
            imp.auto_import(data, "b.csv")
        res = imp.auto_import(data, "b.csv", overrides={"dt_format": "MM/TT/JJJJ hh:mm[:ss] (US)"})
        self.assertEqual(res["log"]["von"], "2026-03-04 10:00")
        res = imp.auto_import(data, "b.csv", overrides={"dt_format": "TT/MM/JJJJ hh:mm[:ss]"})
        self.assertEqual(res["log"]["von"], "2026-04-03 10:00")

    def test_missing_unit_must_be_confirmed(self):
        data = b"timestamp,co2,temp,rh\n2026-10-30 10:30,910,22.3,44\n"          # zu wenige Werte zum Ableiten
        with self.assertRaises(ValueError):
            imp.auto_import(data, "c.csv")
        res = imp.auto_import(data, "c.csv", overrides={"units": {"co2": "ppm", "temp": "°C", "rh": "%"}})
        self.assertEqual(res["log"]["vollstaendig"], 1)

    def test_utc_iso_converted_to_local(self):
        data = b"time;co2_ppm;temp_c;rh_pct\n2026-11-02T07:00:00Z;600;21;40\n2026-07-01T06:00:00Z;600;24;50\n"
        res = imp.auto_import(data, "d.csv")
        self.assertEqual(res["log"]["von"], "2026-07-01 08:00")   # Sommerzeit UTC+2
        self.assertEqual(res["log"]["bis"], "2026-11-02 08:00")   # Winterzeit UTC+1

    def test_xlsx_datetime_cells(self):
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["Messdaten Raum 1"]); ws.append(["Datum/Zeit", "CO2 (ppm)", "Temp. (°C)", "r.F. (%)"])
        t0 = datetime(2026, 11, 2, 8)
        for i in range(3):
            ws.append([t0 + timedelta(minutes=5 * i), 600 + i, 21.0, 40.0])
        buf = io.BytesIO(); wb.save(buf)
        res = imp.auto_import(buf.getvalue(), "e.xlsx")
        self.assertEqual(res["log"]["vollstaendig"], 3)

    def test_json_nested(self):
        recs = [{"timestamp": 1793606400000 + i * 300000, "co2": [650 + i, 30], "temperature": [21.2, 0.5], "humidity": [39, 2]} for i in range(3)]
        res = imp.auto_import(json.dumps(recs).encode(), "f.json",
                              overrides={"units": {"co2": "ppm", "temp": "°C", "rh": "%"}})
        self.assertEqual(res["log"]["vollstaendig"], 3)

    def test_high_frequency_requires_averaging(self):
        rows = ["timestamp;co2_ppm;temp_c;rh_pct"] + [f"2026-11-02 08:00:{s:02d};{600+s};21;40" for s in range(0, 60, 10)]
        data = "\n".join(rows).encode()
        with self.assertRaises(ValueError):
            imp.auto_import(data, "g.csv")
        res = imp.auto_import(data, "g.csv", average_min=1)
        self.assertEqual(res["log"]["messpunkte"], 1)
        self.assertAlmostEqual(res["records"][0]["value"], 625.0)

    def test_device_range_exclusion(self):
        d = DEV["belimo-p-22rth-1u00a-2"]          # CO₂-Messbereich 0–2000 ppm laut Gerätematrix
        data = b"timestamp;co2_ppm;temp_c;rh_pct\n2026-11-02 08:00;2500;21;40\n2026-11-02 08:05;900;21;40\n"
        res = imp.auto_import(data, "h.csv", device=d)
        self.assertEqual(res["log"]["vollstaendig"], 1)
        self.assertTrue(any("Messbereich" in k for k in res["log"]["ausschluesse"]))

    def test_device_coverage(self):
        self.assertFalse(imp.device_coverage(DEV["wabool-6011"])["temp"])
        self.assertTrue(all(imp.device_coverage(DEV["aranet-tdspc0h3"]).values()))

    def test_smart_ambiguous_date_resolved_by_series(self):
        rows = ["Time,Carbon dioxide(ppm),Temperature(°C),Relative humidity(%)"]
        t0 = datetime(2026, 3, 4, 23, 0)          # über Mitternacht: 04.03. → 05.03.
        for i in range(12):
            t = t0 + timedelta(minutes=10 * i)
            rows.append(f"{t:%m/%d/%Y %H:%M},{700+i},22,45")
        res = imp.auto_import("\n".join(rows).encode(), "s.csv")
        self.assertEqual(res["log"]["von"], "2026-03-04 23:00")
        self.assertTrue(any("automatisch bestimmt" in x for x in res["log"]["bereinigung"]))

    def test_smart_unit_inference(self):
        rows = ["timestamp,co2,temp,rh"] + [f"2026-11-02 08:{m:02d},{600+m},{70+m/10:.1f},0.{40+m}" for m in range(0, 30, 5)]
        res = imp.auto_import("\n".join(rows).encode(), "u.csv")
        s = long_to_samples(room_with(res["records"]))["samples"]
        self.assertAlmostEqual(s[0]["Temperatur"], (70 - 32) * 5 / 9, places=2)   # °F erkannt
        self.assertAlmostEqual(s[0]["Relative Feuchte"], 40.0)                     # Anteil → %

    def test_cleaning_sort_duplicates_sentinel_gap(self):
        rows = ["timestamp;co2_ppm;temp_c;rh_pct", "2026-11-02 08:10;650;21;40", "2026-11-02 08:00;600;21;40",
                "2026-11-02 08:05;-999;21;40", "2026-11-02 08:05;-999;21;40", "2026-11-02 08:15;660;21;40", "2026-11-02 12:15;700;21;40"]
        res = imp.auto_import("\n".join(rows).encode(), "k.csv")
        lg = res["log"]
        self.assertTrue(any("sortiert" in x for x in lg["bereinigung"]))
        self.assertTrue(any("Doppelzeilen" in x for x in lg["bereinigung"]))
        self.assertTrue(any("Fehlercode" in k for k in lg["ausschluesse"]))
        self.assertTrue(any("Datenlücke" in x for x in lg["hinweise"]))
        self.assertEqual(lg["vollstaendig"], 4)

    def test_presence_and_usage_filter(self):
        data = b"timestamp;presence\n2026-11-02 08:00;0\n2026-11-02 08:15;1\n2026-11-02 08:30;1\n2026-11-02 08:45;0\n"
        out = imp.parse_presence(data, "p.csv")
        self.assertEqual(out["intervals"], [["2026-11-02 08:15", "2026-11-02 08:45"]])
        room = {"occupancy_source": OCC_SOURCES[1], "occupancy_intervals": out["intervals"]}
        self.assertTrue(usage_defined(room))
        smp = [{"timestamp": datetime(2026, 11, 2, 8, m)} for m in (0, 15, 30, 45)]
        self.assertEqual([x["timestamp"].minute for x in filter_usage(smp, room)], [15, 30])


if __name__ == "__main__":
    unittest.main()


class TestBelegungsplan(unittest.TestCase):
    def test_blocks_persons_absences(self):
        from iaq_logic import persons_at, usage_label
        room = {"occupancy_source": OCC_SOURCES[0], "absences": "2026-11-04; 09.11.2026 bis 10.11.2026",
                "usage_blocks": [{"days": ["Mo", "Di", "Mi", "Do", "Fr"], "start": "08:00", "end": "12:00", "persons": 4},
                                 {"days": ["Mo", "Di", "Mi", "Do", "Fr"], "start": "13:00", "end": "17:00", "persons": 2},
                                 {"days": ["Fr"], "start": "12:00", "end": "13:00", "persons": 0}]}
        smp = [{"timestamp": datetime(2026, 11, d, h)} for d in (2, 4, 6, 9) for h in (7, 9, 12, 14)]
        got = [(x["timestamp"].day, x["timestamp"].hour) for x in filter_usage(smp, room)]
        self.assertEqual(got, [(2, 9), (2, 14), (6, 9), (6, 14)])   # 4.11. und 9.11. abwesend, Fr 12–13 Uhr 0 Personen
        self.assertEqual(persons_at(datetime(2026, 11, 2, 9), room), 4)
        self.assertIn("Mo–Fr 08:00–12:00, 4 P.", usage_label(room))

    def test_legacy_schedule(self):
        room = {"usage_days": ["Mo"], "usage_start": "08:00", "usage_end": "17:00"}
        self.assertTrue(usage_defined(room))
