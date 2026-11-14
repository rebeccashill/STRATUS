"""Fleet invariants and failures. Injected providers are not live service evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from stratus.contracts.fleet_v1 import empty_registry,empty_assessment
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import FleetCalculator,python_batch,normalize,digest
from stratus.inspection.computation import ComputationUnavailable,LocalWolfram
from stratus.inspection.fleet_scenario import scenario,annotation
from stratus.inspection.workflow import freeze_context
from stratus.inspection.ground import unavailable
from stratus.inspection.loader import load_mission

def injected(value):return dict(python_batch(value),wolfram_version='INJECTED TEST',system_id='test')
def flight(f):return {k:(d['battery'],d['actions_used'],copy.deepcopy(d['position'])) for k,d in f.data['drones'].items()}

class FleetTests(unittest.TestCase):
    def test_all_integer_sizes_and_invalid_boundaries(self):
        for size in range(2,51):self.assertEqual(len(FleetSession(size).data['drones']),size)
        for value in (1,51,0,-1,True,2.0,'50',None):
            with self.subTest(value=value),self.assertRaises(ValueError):FleetSession(value)

    def test_200_unique_assets_and_independent_D050_state(self):
        s=scenario();self.assertEqual(len(s['assets']),200);self.assertEqual(len({tuple(a['position'].values()) for a in s['assets']}),200)
        f=FleetSession(50);first=copy.deepcopy(f.data['drones']['D001']);f.data['drones']['D050']['reason']='selected D050 only'
        self.assertEqual(f.data['drones']['D001'],first)

    def test_50_drones_act_independently_and_return_with_reserve(self):
        f=FleetSession(50);f.run_to_end();m=f.metrics()
        self.assertEqual((m['drone_participation'],m['captures']),(50,150));self.assertEqual(m['violations'],0)
        self.assertTrue(all(d['actions_used']==3 and d['position']==d['launch'] and d['battery']>=15 for d in f.data['drones'].values()))
        self.assertEqual(len(f.data['evidence']),len({j['task_id'] for j in f.data['journal'] if j['kind']=='capture'}))
        self.assertEqual(m['total_battery_EU'],sum(d['battery'] for d in f.data['drones'].values()))

    def test_shortlist_bound_and_exclusive_ownership(self):
        f=FleetSession(50);batch,_=f.shortlist();self.assertLessEqual(len(batch['pairs']),500)
        for did in f.data['drones']:self.assertLessEqual(sum(p['drone_id']==did for p in batch['pairs']),10)
        selected=f.allocate();self.assertEqual(len(selected),len({p['task_id'] for p in selected}));self.assertEqual(len(selected),len({p['drone_id'] for p in selected}))
        self.assertTrue(f.data['allocations'][0]['ownership_conflicts_skipped'])

    def test_duplicate_receipt_does_not_charge_or_append(self):
        f=FleetSession(2)
        while not f.data['receipts']:f.advance()
        key=next(iter(f.data['receipts']));r=f.data['receipts'][key];before=copy.deepcopy(f.data)
        result=f.commit_capture(r['drone_id'],key[len('capture:'):])
        self.assertEqual(result['status'],'already_processed');self.assertEqual(f.data,before)

    def test_priority_invalidates_old_assignments_without_capture_or_refill(self):
        f=FleetSession(2);f.advance();a=copy.deepcopy(next(iter(f.data['assignments'].values())));f.priority('A001',3)
        before=flight(f);result=f.commit_capture(a['drone_id'],a['assignment_id']);self.assertEqual(result['status'],'rejected');self.assertEqual(flight(f),before)
        self.assertGreater(f.data['fleet_revision'],a['fleet_revision'])

    def test_task_contention_and_numeric_model_tamper_are_rejected(self):
        f=FleetSession(2);f.advance();did=next(iter(f.data['assignments']));a=f.data['assignments'][did];d=f.data['drones'][did]
        before=flight(f);original=a['numeric']['capture'];a['numeric']['capture']=1
        self.assertEqual(f.check_assignment(d,a,a['phase']),'numeric_identity_or_model_changed');a['numeric']['capture']=original
        original_owner=f.data['tasks'][a['task_id']]['owner'];f.data['tasks'][a['task_id']]['owner']='D999'
        self.assertEqual(f.check_assignment(d,a,a['phase']),'ownership_conflict');f.data['tasks'][a['task_id']]['owner']=original_owner
        self.assertEqual(flight(f),before)

    def test_distinct_followup_retains_unknown_and_counts_asset_once(self):
        f=FleetSession(2);asset=next(a for a in f.assets if annotation(11,a,'overview')['image_quality']=='unclear')
        for t in f.data['tasks'].values():
            if t['asset_id']!=asset:t['state']='blocked'
        f.run_to_end();self.assertEqual(f.data['evidence'][asset+':overview']['finding'],'unknown')
        self.assertEqual(f.data['evidence'][asset+':follow-up']['image_quality'],'clear');self.assertEqual(f.metrics()['unique_usable_assets'],1)
        self.assertEqual(f.metrics()['captures'],2)
        with self.assertRaises(ValueError):f.request_view(asset)

    def test_no_feasible_shortlisted_work_stops_without_new_evidence(self):
        f=FleetSession(2)
        for t in f.data['tasks'].values():t['state']='blocked'
        f.run_to_end();self.assertEqual(f.metrics()['captures'],0);self.assertEqual(f.data['status'],'complete')
        before=copy.deepcopy(f.data);f.advance();self.assertEqual(f.data,before)

    def test_unavailable_drone_requeues_only_unfinished_work_and_keeps_costs(self):
        f=FleetSession(5)
        while not any(d['status']=='inspecting' for d in f.data['drones'].values()):f.advance()
        did=next(k for k,d in f.data['drones'].items() if d['status']=='inspecting');before=f.data['drones'][did]['battery'];old=copy.deepcopy(f.data['evidence'])
        f.unavailable(did);f.run_to_end()
        self.assertEqual(f.data['drones'][did]['battery'],before);self.assertEqual(f.data['drones'][did]['status'],'unavailable')
        self.assertTrue(all(f.data['evidence'][k]==v for k,v in old.items()));self.assertTrue(any(d['actions_used'] for k,d in f.data['drones'].items() if k!=did))

    def test_logical_outcome_independent_of_playback_batch_size(self):
        a=FleetSession(5,23);b=FleetSession(5,23)
        while a.data['status']!='complete':a.advance(1)
        while b.data['status']!='complete':b.advance(20)
        self.assertEqual(a.outcome_digest(),b.outcome_digest())

    def test_50_drone_pause_save_reopen_resumes_identically(self):
        a=FleetSession(50,47);a.advance(70)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'fleet.json';a.save(p);b=FleetSession.load(p)
            self.assertTrue(b.data['paused']);self.assertEqual(a.outcome_digest(),b.outcome_digest())
            a.run_to_end();b.run_to_end();self.assertEqual(a.outcome_digest(),b.outcome_digest())

    def test_checksum_semantic_budget_and_position_tamper_are_rejected(self):
        f=FleetSession(2);f.advance(3)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'fleet.json';f.save(p);raw=json.loads(p.read_text())
            for kind in ('checksum','battery','position'):
                changed=copy.deepcopy(raw)
                if kind=='checksum':changed['sha256']='0'*64
                else:
                    d=changed['payload']['drones']['D001']
                    if kind=='battery':d['battery']+=1
                    else:d['position']['x']+=1
                    changed['sha256']=digest(changed['payload'])
                p.write_text(json.dumps(changed))
                with self.subTest(kind=kind),self.assertRaises(ValueError):FleetSession.load(p)

    def test_empty_hazard_contract_and_stale_commit_gate(self):
        f=FleetSession(2);f.advance();a=copy.deepcopy(next(iter(f.data['assignments'].values())));d=f.data['drones'][a['drone_id']];task=f.data['tasks'][a['task_id']]
        path=f._path(d,task);self.assertEqual(empty_assessment(path,empty_registry())['state'],'clear')
        path['coordinate_frame']={'unit':'latlon'};self.assertEqual(empty_assessment(path,empty_registry())['state'],'review_required')
        registry=empty_registry();registry['revision']=1;registry['hazards']=[{'hazard_id':'INJECTED_REPORTED_ZONE'}]
        with self.assertRaises(ValueError):f.set_hazards(registry)
        from stratus.hazards.core import HazardRegistry
        from stratus.hazards.fixtures import crane_event
        from stratus.hazards.fleet_adapter import fleet_registry
        valid=HazardRegistry();valid.apply(crane_event(effective=f.data['clock'],rect={'x_min':-1,'y_min':-1,'x_max':41,'y_max':21,'buffer_m':0}))
        f.set_hazards(fleet_registry(valid));before=flight(f);self.assertEqual(f.commit_capture(a['drone_id'],a['assignment_id'])['status'],'rejected');self.assertEqual(flight(f),before)
        self.assertEqual(f.shortlist()[0]['pairs'],[])

    def test_ground_loss_and_saved_times_do_not_change_flight(self):
        ground=freeze_context(unavailable(load_mission()));f=FleetSession(2,ground=ground);f.advance(2);before=flight(f);f.set_ground(ground)
        self.assertEqual(flight(f),before)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'fleet.json';f.save(p);r=FleetSession.load(p);self.assertEqual(r.data['ground'],ground);self.assertEqual(flight(r),before)

class FleetCostTests(unittest.TestCase):
    def setUp(self):self.batch=FleetSession(2).shortlist()[0]
    def test_typed_identity_cache_and_changed_revision(self):
        calls=[]
        def runner(x):calls.append(x);return injected(x)
        c=FleetCalculator('wolfram',runner);a=c.compute(self.batch);b=c.compute(copy.deepcopy(self.batch))
        self.assertEqual((a['mode'],b['mode']),('wolfram_local','cached_wolfram_local'));self.assertEqual(len(calls),1)
        changed=copy.deepcopy(self.batch);changed['hazard_revision']+=1;c.compute(changed);self.assertEqual(len(calls),2)
    def test_material_missing_duplicate_and_wrong_ID_rows_block(self):
        for kind in ('cost','missing','duplicate','identity'):
            def runner(x):
                r=injected(x)
                if kind=='cost':r['options'][0]['margin']+=2
                elif kind=='missing':r['options'].pop()
                elif kind=='duplicate':r['options'][1]=r['options'][0]
                else:r['options'][0]['drone_id']='D999'
                return r
            r=FleetCalculator('wolfram',runner).compute(self.batch)
            self.assertFalse(r['execution_permitted']);self.assertEqual(r['mode'],'wolfram_disagreement')
    def test_timeout_access_quota_fallback_is_bounded_and_explicit(self):
        for code in ('timeout','quota_exceeded','access_denied'):
            def fail(x):raise ComputationUnavailable(code,'Injected only')
            c=FleetCalculator('wolfram',fail);r=c.compute(self.batch)
            self.assertEqual(c.calls,1);self.assertTrue(r['execution_permitted']);self.assertEqual(r['mode'],'local_python_fallback');self.assertEqual(r['output'],python_batch(self.batch))
    def test_unit_conversion_and_reserve_boundaries(self):
        b=copy.deepcopy(self.batch);b['pairs']=b['pairs'][:1];row=b['pairs'][0]
        row.update(position={'x':0,'y':0},target={'x':6,'y':8},launch={'x':0,'y':0},rate=0.5,capture=5,reserve=15)
        required=30
        for delta,allowed in ((-1e-6,False),(0,True),(1e-6,True)):
            row['battery']=required+delta;self.assertEqual(python_batch(b)['options'][0]['feasible'],allowed)
        km=copy.deepcopy(b)
        for r in km['pairs']:
            r['distance_unit']='km';r['rate']*=1000
            for key in ('position','target','launch'):
                for axis in ('x','y'):r[key][axis]/=1000
        self.assertEqual(normalize(km),normalize(b))
    def test_bounds_nonfinite_and_fixed_script_allowlist(self):
        for n in (float('nan'),float('inf'),True,-1):
            b=copy.deepcopy(self.batch);b['pairs'][0]['battery']=n
            with self.assertRaises(ValueError):python_batch(b)
        b=copy.deepcopy(self.batch);b['pairs']*=26
        with self.assertRaises(ValueError):python_batch(b)
        with self.assertRaises(ValueError):LocalWolfram(script=Path('untrusted.wls'))

if __name__=='__main__':unittest.main()
