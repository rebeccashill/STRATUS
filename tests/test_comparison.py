"""Fair resets, fixed inputs, unique-asset scoring and benchmark limits."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from stratus.inspection.comparison import (ComparisonWorkflow, load_frozen, rank,
    review_clear, run_method)
from stratus.inspection.comparison_checks import boundary_checks, sensor_parity
from stratus.inspection.computation import CostCalculator, compute_mission_options
from stratus.inspection.loader import PROJECT_ROOT, freeze, load_mission
from stratus.inspection.review import InspectionSession

FOLDER=PROJECT_ROOT/'docs/evidence/inspection-0.0.2/part8'


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec,cls.ground,cls.context,cls.receipt=load_frozen(PROJECT_ROOT,FOLDER)
        cls.results={(case['case_id'],method):run_method(PROJECT_ROOT,FOLDER,case['case_id'],method)
                     for case in cls.spec['cases'] for method in cls.spec['methods']}

    def test_all_nine_runs_exist_and_share_one_frozen_ground_snapshot(self):
        self.assertEqual(len(self.results),9)
        self.assertEqual({r['ground_snapshot_id'] for r in self.results.values()},{self.context['snapshot_id']})
        self.assertTrue(all(r['ground_context']==self.context for r in self.results.values()))

    def test_every_method_resets_to_identical_case_inputs_and_prior_records(self):
        for case in self.spec['cases']:
            values=[self.results[case['case_id'],method] for method in self.spec['methods']]
            self.assertEqual(len({r['start_fingerprint'] for r in values}),1)
            self.assertTrue(all(r['initial_state']==values[0]['initial_state'] for r in values))
            self.assertTrue(all(r['initial_assessments']==values[0]['initial_assessments'] for r in values))
            self.assertTrue(all(len(r['initial_assessments'])==2 for r in values))

    def test_coverage_counts_an_asset_once_even_when_follow_up_executes(self):
        result=self.results['unclear','adaptive'];metrics=result['metrics']
        priorities=self.spec['adaptive_weights']['priority_values']
        self.assertEqual(metrics['usable_priority'],sum(priorities[a] for a in set(metrics['usable_assets'])))
        self.assertEqual(metrics['captures'],3)
        assets=[s['event']['proposal']['asset_id'] for s in result['steps'] if s['decision']=='capture']
        self.assertLess(len(set(assets)),len(assets))

    def test_unclear_example_uses_distinct_view_and_original_unknown_stays_unknown(self):
        result=self.results['unclear','adaptive']
        events=[s['event'] for s in result['steps'] if s['decision']=='capture']
        self.assertTrue(any(e['proposal']['action_type']=='follow_up' for e in events))
        p03=[a for a in result['assessments'] if a['asset_id']=='P03']
        self.assertEqual({a['view_id'] for a in p03},{'overview','follow-up'})
        self.assertEqual(next(a for a in p03 if a['view_id']=='overview')['finding'],'unknown')

    def test_low_battery_does_not_fabricate_a_capture_or_priority_gain(self):
        for method in self.spec['methods']:
            result=self.results['low-battery',method]
            self.assertEqual(result['metrics']['captures'],0)
            self.assertEqual(result['metrics']['new_usable_priority_gain'],0)
            self.assertEqual(result['final_state']['actions_remaining'],3)
            self.assertEqual(result['final_state']['battery_available'],20)
            self.assertEqual(result['metrics']['final_status'],'returned')

    def test_capture_cap_reserve_and_exclusions_hold_for_every_method(self):
        for result in self.results.values():
            self.assertLessEqual(result['metrics']['captures'],3)
            self.assertEqual(result['metrics']['violations'],0)
            for step in result['steps']:
                if step['decision']=='capture':
                    self.assertNotEqual(step['event']['proposal']['asset_id'],'P06')
                    self.assertGreaterEqual(step['event']['decision']['costs']['margin'],0)
            self.assertGreaterEqual(result['final_state']['battery_available'],15)

    def test_nearest_ties_and_fixed_route_passes_are_predeclared(self):
        allowed=[{'asset_id':'P04','view_id':'overview','outbound':1},
                 {'asset_id':'P03','view_id':'follow-up','outbound':1}]
        nearest,_=rank('nearest-feasible',allowed,self.spec['fixed_order'],0)
        self.assertEqual(nearest[0]['asset_id'],'P03')
        route,_=rank('fixed-order',allowed,self.spec['fixed_order'],3)
        self.assertEqual(route[0]['asset_id'],'P04')
        wrapped,_=rank('fixed-order',allowed[1:],self.spec['fixed_order'],3)
        self.assertEqual(wrapped[0]['asset_id'],'P03')

    def test_repeated_run_reproduces_choices_and_scores(self):
        again=run_method(PROJECT_ROOT,FOLDER,'unclear','adaptive')
        first=self.results['unclear','adaptive']
        self.assertEqual(again['metrics'],first['metrics'])
        self.assertEqual([s.get('selected') for s in again['steps']],[s.get('selected') for s in first['steps']])

    def test_no_live_hardware_is_contacted_by_comparison(self):
        with (patch('stratus.inspection.ground.HardwareReader.sample',side_effect=AssertionError('USB')),
              patch('stratus.inspection.usb_reader.USBWorkerReader.sample',side_effect=AssertionError('USB'))):
            result=run_method(PROJECT_ROOT,FOLDER,'clear','nearest-feasible')
        self.assertEqual(result['source_mode'],'Recorded')

    def test_context_drift_is_rejected_instead_of_favoring_one_method(self):
        mission=load_mission(PROJECT_ROOT/self.spec['cases'][0]['mission_path'])
        flow=ComparisonWorkflow(InspectionSession(mission),self.context)
        changed=copy.deepcopy(self.ground);changed['observations'][0]['value']+=1
        with self.assertRaisesRegex(ValueError,'drifted'):flow.context(changed)

    def test_adaptive_does_not_peek_at_unseen_image_annotations(self):
        mission=load_mission(PROJECT_ROOT/self.spec['cases'][0]['mission_path'])
        variants=[]
        annotations={key:dict(value) for key,value in mission.annotations_by_id.items()}
        key=next(key for key in annotations if key.endswith(':P03:overview'))
        annotations[key].update(image_quality='unclear',finding='unknown')
        for item in (mission,replace(mission,annotations_by_id=freeze(annotations))):
            flow=ComparisonWorkflow(InspectionSession(item),self.context);review_clear(flow,self.ground)
            _,choices=flow.selection(compute_mission_options(item,flow.session.state,CostCalculator('local')))
            variants.append([(c['asset_id'],c['view_id']) for c in choices])
        self.assertEqual(variants[0],variants[1])

    def test_changed_frozen_input_is_rejected_before_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/FOLDER.relative_to(PROJECT_ROOT)
            shutil.copytree(FOLDER,folder)
            path=folder/'ground-input.json';data=json.loads(path.read_text());data['observations'][0]['value']+=1
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'Frozen comparison input changed'):load_frozen(root,folder)

    def test_raw_sample_normalized_ui_and_report_parity(self):
        result=sensor_parity(PROJECT_ROOT,FOLDER)
        self.assertEqual(result['physical_sample_parity'],'passed using earlier actual hotplug recovery sample')
        self.assertEqual(len(result['rows']),6)
        self.assertTrue(all(r['raw_normalized_ui_report_equal'] for r in result['rows']))

    def test_numerical_boundaries_units_and_service_counts_are_separate(self):
        result=boundary_checks(PROJECT_ROOT,FOLDER)
        self.assertEqual([r['python']['feasible'] for r in result['boundaries']],[False,True,True,False])
        self.assertTrue(result['unit_conversion']['identical_normalized_input'])
        self.assertEqual(result['request_counts'],{'local_kernel_calls':0,'cloud_requests':0,'alpha_calls':0})
        self.assertTrue(all(r['image_accuracy_claim'] is None for r in self.results.values()))


if __name__=='__main__':unittest.main()
