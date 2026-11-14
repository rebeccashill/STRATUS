"""Reopened ground history and asynchronous recovery; fixtures are injected, not hardware evidence."""

import copy
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest

from stratus.inspection.computation import CostCalculator
from stratus.inspection.dashboard import Dashboard
from stratus.inspection.ground import GroundFeed, historical_snapshot
from stratus.inspection.loader import load_mission
from stratus.inspection.review import InspectionSession, ground_snapshot
from stratus.inspection.workflow import AdaptiveWorkflow


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load_mission()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('evidence', 'context'):
            shutil.copytree(self.original.project_root/name, self.root/name,
                            ignore=shutil.ignore_patterns('live', 'examples'))
        target = self.root/'stratus/inspection/missions'; target.mkdir(parents=True)
        shutil.copy2(self.original.mission_path, target/self.original.mission_path.name)
        (self.root/'saved-runs').mkdir()
        shutil.copy2(self.original.project_root/'saved-runs/first-inspection.json',
                     self.root/'saved-runs/first-inspection.json')
        self.mission = load_mission(project_root=self.root)
        self.recorded = ground_snapshot(self.mission)
        self.injected_live = copy.deepcopy(self.recorded)
        self.injected_live.update(mode='live_measured', physical_acquisition_performed=True)
        for row in self.injected_live['observations']:
            row['source_mode'] = 'live_measured'
        self.calls = []
        self.reader = SimpleNamespace(sample=lambda: self.calls.append('HARDWARE'), close=lambda: None)

    def test_saved_live_is_recorded_stale_without_retiming_or_new_observation_ids(self):
        original = copy.deepcopy(self.injected_live)
        history = historical_snapshot(original)
        self.assertEqual(history['mode'], 'recorded_measured')
        self.assertFalse(history['physical_acquisition_performed'])
        self.assertEqual(original, self.injected_live)
        for old, row in zip(original['observations'], history['observations']):
            expected = dict(old, source_mode='recorded_measured')
            self.assertEqual(row, expected)
        self.assertTrue(all(s['status'] == 'stale' for s in history['sensor_states'].values()))

    def test_dashboard_reopen_displays_its_own_context_and_never_polls_usb(self):
        core = InspectionSession(self.mission); flow = AdaptiveWorkflow(core)
        calc = CostCalculator('local')
        plan = flow.plan(self.injected_live, calc, asset='P05', view='overview')
        flow.execute(plan['plan_id'], calc)
        saved_context = copy.deepcopy(flow.data['contexts'])
        path = self.root/'saved-runs/reopen.json'; core.save(path)
        app = Dashboard(self.mission, checkpoint=path, reader=self.reader); self.addCleanup(app.close)
        state = app.state()
        self.assertEqual(state['run']['aircraft_state']['actions_remaining'], 2)
        self.assertEqual(state['ground']['mode'], 'recorded_measured')
        self.assertEqual(state['ground']['restored_snapshot_id'], plan['ground_context_id'])
        self.assertEqual(app.workflow.data['contexts'], saved_context)
        self.assertEqual(self.calls, [])
        for row, original in zip(state['ground']['observations'], self.injected_live['observations']):
            self.assertEqual(row, dict(original, source_mode='recorded_measured'))

    def test_loading_a_different_run_replaces_panel_context_without_budget_reset(self):
        core = InspectionSession(self.mission); flow = AdaptiveWorkflow(core)
        ground = copy.deepcopy(self.recorded)
        for row in ground['observations']:
            if row['variable'] == 'temperature': row['value'] = 27.25
        p = flow.plan(ground, CostCalculator('local'), asset='P05', view='overview')
        flow.execute(p['plan_id'], CostCalculator('local'))
        core.save(self.root/'saved-runs/different.json')
        app = Dashboard(self.mission, reader=self.reader); self.addCleanup(app.close)
        app.load('different.json')
        result = app.state()
        temperature = next(r for r in result['ground']['observations'] if r['variable'] == 'temperature')
        self.assertEqual(temperature['value'], 27.25)
        self.assertEqual(result['run']['aircraft_state'], core.state.snapshot())
        self.assertEqual(self.calls, [])

    def test_late_live_response_cannot_replace_reopened_context(self):
        entered, release = threading.Event(), threading.Event()
        def sample():
            entered.set(); release.wait(2); return self.injected_live
        reader = SimpleNamespace(sample=sample, close=lambda: None)
        feed = GroundFeed(self.mission, self.recorded, reader=reader); self.addCleanup(feed.close)
        feed.select('live'); self.assertTrue(entered.wait(2))
        expected = copy.deepcopy(self.recorded)
        expected['restored_snapshot_id'] = 'saved-record-id'
        feed.restore(expected); release.set(); feed.close()
        self.assertEqual(feed.snapshot()['mode'], 'recorded_measured')
        self.assertEqual(feed.snapshot()['restored_snapshot_id'], 'saved-record-id')
        self.assertEqual(feed.snapshot()['observations'], expected['observations'])

    def test_latest_good_sample_is_the_recorded_recovery_option(self):
        stopped = threading.Event()
        feed = None
        def sample():
            feed._stop.set(); stopped.set(); return self.injected_live
        feed = GroundFeed(self.mission, self.recorded, reader=SimpleNamespace(sample=sample, close=lambda: None))
        self.addCleanup(feed.close)
        feed.select('live'); self.assertTrue(stopped.wait(2)); feed._thread.join(2)
        recovered = feed.select('recorded')
        self.assertEqual(recovered['mode'], 'recorded_measured')
        self.assertEqual([r['observation_id'] for r in recovered['observations']],
                         [r['observation_id'] for r in self.injected_live['observations']])
        self.assertTrue(all(s['status'] == 'stale' for s in recovered['sensors']))

    def test_reprocessing_same_sample_never_adds_a_capture_or_duplicate_finding(self):
        core = InspectionSession(self.mission); flow = AdaptiveWorkflow(core)
        before = core.snapshot()
        for _ in range(3): flow.plan(self.recorded, CostCalculator('local'))
        self.assertEqual(core.snapshot(), before)
        expected_ids = {r['observation_id'] for r in self.recorded['observations']}
        observed = {r['observation_id'] for c in flow.data['contexts'].values() for r in c['observations']}
        self.assertEqual(observed, expected_ids)
        for c in flow.data['contexts'].values():
            self.assertEqual(len(c['observations']), len({r['observation_id'] for r in c['observations']}))


if __name__ == '__main__': unittest.main()
