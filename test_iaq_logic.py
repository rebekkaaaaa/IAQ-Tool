import json
import unittest
from pathlib import Path
from datetime import datetime
import pandas as pd
from iaq_logic import (
    filter_usage, room_status, co2_classes, time_stats, percentile, STATUS_OK, STATUS_DEV, STATUS_CHECK, STATUS_NA,
    measurement_records, long_to_samples, required_issues, screening, import_measurements,
    conditional_hints, PURPOSES, PROFILE_BT, PROFILE_SIA, PROFILE_ECO,
    VENTS, STRATEGIES, PERIODS,
)

RULES = json.loads((Path(__file__).parent / 'bewertungsregeln.json').read_text(encoding='utf8'))


def room():
    return {'name':'Raum 1','ventilation':VENTS[0], 'ventilation_mode':'', 'active_cooling':False,
            'strategy':STRATEGIES[1], 'measurements': [], 'measurement_interval_min':5,
            'start_date':'2026-10-30','end_date':'2026-10-30', 'data_gaps':'keine',
            'usage_times':'Mo-Fr 08-17', 'occupancy_log':'2 Personen',
            'measurement_position':'1.2 m', 'device_id':'X'}


def assess(profile=PROFILE_BT):
    return {'basis':profile,'period':PERIODS[0],'purpose':PURPOSES[1]}

class TestLogic(unittest.TestCase):
    def test_complete_point_required(self):
        r=room(); r['measurements']=measurement_records('2026-10-30 10:30', 950,22,45)
        self.assertEqual(len(long_to_samples(r)['samples']),1)
        self.assertEqual(required_issues(r,assess()),[])
    def test_empty_measurement_no_pass(self):
        self.assertTrue(any('Messpunkt' in x for x in required_issues(room(),assess())))
    def test_missing_t_rh_not_complete(self):
        r=room();r['measurements']=[{'timestamp':'2026-10-30 10:30','parameter':'CO₂','value':950,'unit':'ppm'}]
        self.assertEqual(long_to_samples(r)['vollstaendig'],0)
        self.assertTrue(any('unvollständig' in x for x in long_to_samples(r)['issues']))
    def test_multiple_values_duplicate_rejected(self):
        r=room();r['measurements']=measurement_records('2026-10-30 10:30', 950,22,45)
        r['measurements'] += [{'timestamp':'2026-10-30 10:30','parameter':'CO₂','value':900,'unit':'ppm'}]
        self.assertEqual(long_to_samples(r)['vollstaendig'],0)
    def test_bt_screening_boundary(self):
        # SECO Abb. 316-2: Heizperiode 30–50 % r. F.
        r=room();r['measurements']=measurement_records('2026-10-30 10:30', 1000,23,50)
        r['measurements']+=measurement_records('2026-10-30 10:35', 900,24,51)
        rows=screening(r,assess(),RULES)['rows']
        self.assertEqual([x['Ausserhalb'] for x in rows],[1,1,1,0,0])
        self.assertEqual([x['Anteil [%]'] for x in rows],[50.0,50.0,50.0,0.0,0.0])
    def test_sia_outdoor_reference(self):
        r=room();r['measurements']=measurement_records('2026-10-30 10:30', 1250,22,45)
        r['outdoor_co2_ppm']=500
        res=screening(r,assess(PROFILE_SIA), RULES)
        self.assertEqual(res['rows'][0]['Ausserhalb'],0)
        r['outdoor_co2_ppm']=None
        res=screening(r,assess(PROFILE_SIA), RULES)
        self.assertEqual(res['rows'][0]['Ausserhalb'],1)
        self.assertIn('nicht gemessen',res['rows'][0]['Quelle'])
    def test_sia_natural_not_applicable(self):
        r=room();r['ventilation']=VENTS[1];r['measurements']=measurement_records('2026-10-30 10:30',900,22,45)
        res=screening(r,assess(PROFILE_SIA),RULES)
        self.assertEqual(len(res['rows']),1)          # alle Lüftungsarten (Tab. 18, Fn. 3)
    def test_eco_no_core_limits(self):
        r=room();r['measurements']=measurement_records('2026-10-30 10:30',900,22,45)
        self.assertEqual(len(screening(r,assess(PROFILE_ECO),RULES)['rows']),1)
        self.assertIn('SIA-Ergänzungswert', screening(r,assess(PROFILE_ECO),RULES)['rows'][0]['Typ'])
    def test_hybrid_without_mode_required(self):
        r=room();r['ventilation']=VENTS[2];r['measurements']=measurement_records('2026-10-30 10:30',900,22,45)
        self.assertTrue(any('hybrid' in x for x in required_issues(r, assess())))
    def test_strategic_purpose_mismatch(self):
        r=room();r['strategy']=STRATEGIES[0]
        hints=conditional_hints(r,{'basis':PROFILE_BT,'period':PERIODS[0],'purpose':PURPOSES[2]})
        self.assertTrue(any('nicht belastbar' in x for x in hints))
    def test_wide_csv_and_long_csv(self):
        wide=pd.DataFrame([{'timestamp':'2026-10-30 10:30','co2':'910','temp':'22,3','rh':'44'}])
        vals,errs=import_measurements(wide)
        self.assertEqual((len(vals),len(errs)),(3,0))
        long=pd.DataFrame(vals)
        vals2,errs2=import_measurements(long)
        self.assertEqual((len(vals2),len(errs2)),(3,0))
    def test_invalid_units_and_values(self):
        r=room();r['measurements']=measurement_records('2026-10-30 10:30',950,22,45)
        r['measurements'][0]['unit']='mg/m3'
        self.assertEqual(long_to_samples(r)['vollstaendig'],0)
        with self.assertRaises(ValueError):
            measurement_records('2026-10-30 10:30', 950, 22, 105)

    def test_schwuele_summer(self):
        r=room();r['measurements']=measurement_records('2026-07-01 10:00',800,25,58)
        r['measurements']+=measurement_records('2026-07-01 10:05',800,26,55)
        a={'basis':PROFILE_BT,'period':PERIODS[1],'purpose':PURPOSES[1]}
        rows={x['Parameter']:x for x in screening(r,a,RULES)['rows']}
        self.assertEqual(rows['Relative Feuchte']['Ausserhalb'],0)
        self.assertEqual(rows['r. F. Schwülegrenze']['Ausserhalb'],1)
    def test_usage_filter(self):
        r=room()
        r['measurements']=measurement_records('2026-11-02 07:55',800,22,40)  # Montag
        r['measurements']+=measurement_records('2026-11-02 08:00',900,22,40)
        r['measurements']+=measurement_records('2026-11-02 17:00',950,22,40)
        r['measurements']+=measurement_records('2026-11-07 10:00',950,22,40)  # Samstag
        from iaq_logic import long_to_samples as l
        self.assertIsNone(filter_usage(l(r)['samples'],r))
        r.update(usage_days=['Mo','Di','Mi','Do','Fr'],usage_start='08:00',usage_end='17:00')
        self.assertEqual(len(filter_usage(l(r)['samples'],r)),1)
    def test_status_rules(self):
        r=room();r['measurements']=measurement_records('2026-10-30 10:30',900,22,40)
        self.assertEqual(room_status(r,assess(),RULES)['status'],STATUS_OK)
        r['measurements']+=measurement_records('2026-10-30 10:35',1300,22,40)   # ΔCO₂ 900 > 800 während 50 %
        self.assertEqual(room_status(r,assess(),RULES)['status'],STATUS_DEV)
        r['measurements']+=measurement_records('2026-10-30 10:40',2000,22,40)
        self.assertEqual(room_status(r,assess(),RULES)['status'],STATUS_CHECK)
        self.assertEqual(room_status(room(),assess(),RULES)['status'],STATUS_NA)
    def test_ten_percent_rule_co2(self):
        from iaq_logic import evaluate_room
        r=room()
        for i in range(20):   # 2 von 20 Punkten (10 %) über IDA 2 -> zulässig; 3 (15 %) -> Abweichung
            r['measurements']+=measurement_records(f'2026-10-30 10:{i*2:02d}',1250 if i<2 else 800,22,40)
        r['measurement_interval_min']=2
        self.assertEqual(evaluate_room(r,assess(),RULES)['topics']['Luftqualität']['status'],STATUS_OK)
        r['measurements']+=measurement_records('2026-10-30 10:40',1250,22,40)
        r['measurements']+=measurement_records('2026-10-30 10:42',1250,22,40)
        self.assertEqual(evaluate_room(r,assess(),RULES)['topics']['Luftqualität']['status'],STATUS_DEV)
    def test_humidity_sia180(self):
        from iaq_logic import evaluate_room, abs_humidity, p_sat
        self.assertAlmostEqual(p_sat(21),2486,delta=1)            # SIA 180 Tab. A.1
        self.assertAlmostEqual(abs_humidity(21,30),5.5,delta=0.05) # SIA 180 Ziff. 3.5.1.3 Fn. 2
        self.assertAlmostEqual(abs_humidity(24,70),15.2,delta=0.05) # Ziff. 3.5.1.4 Fn. 3
        r=room()
        for i in range(10):
            r['measurements']+=measurement_records(f'2026-10-30 10:{i*5:02d}',800,21,25 if i<2 else 40)
        ev=evaluate_room(r,assess(),RULES,{})
        self.assertEqual(ev['topics']['Raumluftfeuchte']['status'],STATUS_NA)       # Höhenlage fehlt
        ev=evaluate_room(r,assess(),RULES,{'altitude_m':400})
        self.assertEqual(ev['topics']['Raumluftfeuchte']['status'],STATUS_DEV)      # 20 % < 30 %
        ev=evaluate_room(r,assess(),RULES,{'altitude_m':1800})
        self.assertEqual(ev['topics']['Raumluftfeuchte']['status'],STATUS_OK)       # Grenze 20 %
    def test_co2_classes_and_stats(self):
        s=[{'CO₂':v,'timestamp':datetime(2026,1,1,8,i*5)} for i,v in enumerate([999,1000,1400,1401,2000])]
        self.assertEqual(co2_classes(s),[20.0,40.0,20.0,20.0])
        self.assertEqual(percentile([1,2,3,4],0.5),2.5)
        ts=time_stats(s,5)
        self.assertEqual((ts['erwartet'],round(ts['abdeckung_pct'])),(5,100))

    def test_ida_classes(self):
        from iaq_logic import ida_classes
        s=[{'CO₂':v} for v in (950,951,1200,1201,1750,1751)]
        self.assertEqual([round(x,2) for x in ida_classes(s,400)],[round(100/6,2),round(200/6,2),round(200/6,2),round(100/6,2)])

    def test_report_page_plan_and_build(self):
        from iaq_report import page_plan, build_report
        from demo_data import build_demo_project
        self.assertEqual(page_plan(1)['pages'], 2)
        self.assertTrue(all(page_plan(n)['pages'] <= 9 for n in range(1, 67)))
        for n in (1, 3):
            h = build_report(build_demo_project(n), RULES, demo=True)
            self.assertEqual(h.count("<section class='page'>"), page_plan(n)['pages'])
            self.assertIn('BEISPIELDATEN', h)

if __name__ == '__main__': unittest.main()
