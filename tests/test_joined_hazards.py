"""Focused Part 13 checks of the real fleet join; no sockets or live services.

These checks do not invoke the blocked Part 12 benchmark or full regression
suite. All numerical providers here are local or explicitly injected doubles.
"""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest

from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import FleetCalculator, digest
from stratus.inspection.fleet_service import FleetService
from stratus.inspection.ground import GroundFeed
from stratus.inspection.loader import load_mission
from stratus.hazards.integration import LiveFleetHazards, publish_registry
from stratus.hazards.fleet_adapter import assess_fleet_path, fleet_registry
from stratus.hazards.core import HazardRegistry


def resources(core):
    return {i: (deepcopy(d['position']), d['battery'], d['actions_used']) for i, d in core.data['drones'].items()}


def local_service(size=2):
    service = SimpleNamespace(lock=threading.RLock(), core=FleetSession(size, 11, calculator=FleetCalculator('local')))
    return service, LiveFleetHazards(service)


class JoinedFleetHazardsTests(unittest.TestCase):
    def test_two_real_assignments_invalidated_without_debit(self):
        service, controller = local_service()
        core = service.core
        core.allocate()
        old = deepcopy(core.data['assignments'])
        before = resources(core)
        impact = controller.report(controller.event())
        self.assertEqual((impact['assessed_count'], impact['affected_count']), (2, 2))
        self.assertEqual(resources(core), before)
        self.assertEqual(core.data['assignments'], {})
        for did, a in old.items():
            self.assertEqual(core.commit_capture(did, a['assignment_id'])['status'], 'rejected')
        self.assertEqual(core.metrics()['captures'], 0)

    def test_fifty_real_records_assessed_and_unaffected_work_continues(self):
        service, controller = local_service(50)
        core = service.core
        core.allocate()
        impact = controller.report(controller.event())
        self.assertEqual(impact['assessed_count'], 50)
        self.assertGreaterEqual(impact['affected_count'], 2)
        self.assertLess(impact['affected_count'], 50)
        self.assertEqual(len({a['drone_id'] for a in impact['assessments']}), 50)
        core.run_to_end()
        self.assertGreater(core.metrics()['captures'], 0)
        self.assertEqual({d.get('hazard_checked_revision') for d in core.data['drones'].values()}, {core.data['hazards']['revision']})
        self.assertGreaterEqual(core.data['hazards']['revision'], 1)
        core.assert_invariants()

    def test_affected_travel_holds_last_waypoint_and_cannot_auto_reallocate(self):
        service, controller = local_service()
        core = service.core
        core.advance(1)
        did = next(i for i, d in core.data['drones'].items() if d['status'] == 'traveling')
        before = resources(core)
        impact = controller.report(controller.event())
        self.assertIn(did, impact['review_required_drone_ids'])
        self.assertTrue(core.data['drones'][did]['hazard_review_required'])
        self.assertEqual(core.data['drones'][did]['status'], 'held')
        self.assertEqual(resources(core), before)
        core.allocate()
        self.assertNotIn(did, core.data['assignments'])
        core._return(core.data['drones'][did])
        self.assertEqual(core.data['drones'][did]['status'], 'held')

    def test_report_before_capture_does_not_rewind_arrival_or_refund_energy(self):
        service, controller = local_service()
        core = service.core
        for _ in range(20):
            core.advance(1)
            inspecting = [i for i, d in core.data['drones'].items() if d['status'] == 'inspecting']
            if inspecting:
                break
        did = inspecting[0]
        old = deepcopy(core.data['assignments'][did])
        before = resources(core)
        controller.report(controller.event())
        self.assertEqual(core.commit_capture(did, old['assignment_id'])['status'], 'rejected')
        self.assertEqual(resources(core), before)
        self.assertLess(core.data['drones'][did]['battery'], 100)
        self.assertEqual(core.data['drones'][did]['actions_used'], 0)

    def test_reported_return_intersection_is_not_commanded(self):
        service, controller = local_service()
        core = service.core
        for _ in range(150):
            core.advance(1)
            returning = [i for i, d in core.data['drones'].items() if d['status'] == 'returning']
            if returning:
                break
        self.assertTrue(returning)
        did = returning[0]
        d = core.data['drones'][did]
        x, y = (d['position']['x'] + d['launch']['x']) / 2, (d['position']['y'] + d['launch']['y']) / 2
        rect = dict(x_min=x-.05, x_max=x+.05, y_min=y-.05, y_max=y+.05, buffer_m=.01)
        before = resources(core)
        impact = controller.report(controller.event(rectangle=rect))
        self.assertIn(did, impact['review_required_drone_ids'])
        self.assertEqual(resources(core), before)
        self.assertFalse(any(e[2] == 'return' and e[3] == did for e in core.data['queue']))

    def test_actual_reallocation_checks_both_segments_and_new_numeric_revision(self):
        service, controller = local_service()
        core = service.core
        core.allocate()
        old = deepcopy(core.data['assignments'])
        first_key = core.data['allocations'][-1]['calculation']['cache_key']
        controller.report(controller.event())
        chosen = core.allocate()
        self.assertTrue(chosen)
        allocation = core.data['allocations'][-1]
        self.assertEqual(allocation['shortlist']['hazard_revision'], 1)
        self.assertNotEqual(first_key, allocation['calculation']['cache_key'])
        for did, a in core.data['assignments'].items():
            p = core._path(core.data['drones'][did], core.data['tasks'][a['task_id']], a['origin'])
            self.assertEqual(assess_fleet_path(p, core.data['hazards'])['state'], 'clear')
            self.assertEqual(a['hazard_revision'], 1)
            self.assertNotEqual(a['task_id'], old[did]['task_id'])

    def test_save_reopen_exact_active_hazard_two_and_fifty(self):
        for size in (2, 50):
            with self.subTest(size=size), tempfile.TemporaryDirectory(prefix='stratus-joined-hazard-') as directory:
                service, controller = local_service(size)
                core = service.core
                core.allocate()
                controller.report(controller.event())
                core.advance(5)
                core.data.update(paused=True, status='paused')
                before = deepcopy(core.data)
                file = Path(directory) / 'joined.json'
                core.save(file)
                restored = FleetSession.load(file)
                self.assertEqual(restored.data, before)
                self.assertEqual(restored.outcome_digest(), core.outcome_digest())
                self.assertEqual(restored.data['hazards']['revision'], 1)

    def test_forged_registry_rejected_even_with_new_outer_checksum(self):
        with tempfile.TemporaryDirectory(prefix='stratus-joined-hazard-') as directory:
            service, controller = local_service()
            core = service.core
            core.allocate()
            controller.report(controller.event())
            file = Path(directory) / 'joined.json'
            core.save(file)
            saved = json.loads(file.read_text())
            saved['payload']['hazards']['hazards'][0]['state'] = 'cleared'
            saved['sha256'] = digest(saved['payload'])
            file.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                FleetSession.load(file)

    def test_route_digest_prevents_an_altered_proposal(self):
        service, _ = local_service()
        core = service.core
        core.allocate()
        did = next(iter(core.data['assignments']))
        a = core.data['assignments'][did]
        a['route_signature'] = '0' * 64
        self.assertEqual(core.check_assignment(core.data['drones'][did], a, 'assigned'), 'route_signature_changed')

    def test_legacy_empty_registry_save_acquires_route_digest_without_reset(self):
        with tempfile.TemporaryDirectory(prefix='stratus-joined-hazard-') as directory:
            core = FleetSession(2, calculator=FleetCalculator('local'))
            core.allocate()
            file = Path(directory) / 'legacy.json'
            core.save(file)
            saved = json.loads(file.read_text())
            for a in saved['payload']['assignments'].values():
                a.pop('route_signature')
            saved['sha256'] = digest(saved['payload'])
            file.write_text(json.dumps(saved))
            restored = FleetSession.load(file)
            self.assertEqual(resources(restored), resources(core))
            self.assertEqual(restored.data['hazards']['revision'], 0)
            self.assertTrue(all(a['route_signature'] for a in restored.data['assignments'].values()))

    def test_explicit_clearance_retains_history_and_does_not_refill_budgets(self):
        service, controller = local_service()
        core = service.core
        core.allocate()
        controller.report(controller.event())
        before = resources(core)
        controller.report(controller.event('clear', source='operator_report', notes='Operator reviewed the synthetic area and explicitly cleared it'))
        self.assertEqual(resources(core), before)
        self.assertEqual(core.data['hazards']['revision'], 2)
        self.assertEqual(core.data['hazards']['hazards'][0]['state'], 'cleared')

    def test_old_history_branch_and_future_time_rejected_atomically(self):
        service, controller = local_service()
        core = service.core
        event = controller.event()
        event['effective_sim_time'] = core.data['clock'] + 1
        before = deepcopy(core.data)
        with self.assertRaises(ValueError):
            controller.report(event)
        self.assertEqual(core.data, before)

    def test_live_expiry_marks_review_and_retains_restriction_without_debit(self):
        from stratus.hazards.integration import review_due_reports
        service, controller = local_service()
        core = service.core
        core.allocate()
        controller.report(controller.event())
        core.data['clock'] = 31
        before = resources(core)
        review_due_reports(core)
        self.assertEqual(resources(core), before)
        self.assertEqual(core.data['hazards']['revision'], 2)
        self.assertEqual(core.data['hazards']['hazards'][0]['state'], 'review_required')
        self.assertEqual(core.data['hazards']['hazards'][0]['rectangle']['buffer_m'], 0.1)
        review_due_reports(core)
        self.assertEqual(core.data['hazards']['revision'], 2)


class JoinedFleetServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stratus-live-hazard-service-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        mission = load_mission()
        recorded = json.loads((mission.project_root / 'docs/evidence/inspection-0.0.2/part11/browser-recorded-export.json').read_text())
        ground = GroundFeed(mission, recorded)
        self.addCleanup(ground.close)
        self.app = SimpleNamespace(mission=replace(mission, project_root=root), ground=ground, computation_preference='local')
        for name in ('P04-overview.png', 'P05-overview.png'):
            target = root / 'evidence/inspection/images' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mission.project_root / 'evidence/inspection/images' / name, target)
        self.service = FleetService(self.app)
        self.controller = self.service.reported_hazards()

    def call(self, operation, **extra):
        d = self.service.core.data
        return self.controller.dispatch(operation, dict(run_id=d['run_id'], state_revision=d['state_revision'], **extra))

    def test_same_authoritative_service_store_and_stale_ui_tokens(self):
        self.assertEqual(self.controller.snapshot()['run_id'], self.service.snapshot()['run_id'])
        token = deepcopy(self.controller.snapshot())
        self.call('prepare', drone_id='D001')
        self.assertTrue(self.service.core.data['assignments'])
        with self.assertRaises(ValueError):
            self.controller.dispatch('report-example', dict(run_id=token['run_id'], state_revision=token['state_revision']))

    def test_real_service_prepare_report_reject_replan_save_open(self):
        self.call('prepare', drone_id='D001')
        self.call('report-example')
        result = self.call('execute', drone_id='D001')
        self.assertIn('REJECTED', result['message'])
        self.call('replan')
        self.service.core.advance(5)
        before = resources(self.service.core)
        saved = self.call('save')['saved_name']
        self.call('reopen', name=saved)
        self.assertEqual(resources(self.service.core), before)
        self.assertEqual(self.service.core.data['hazards']['revision'], 1)
        self.assertTrue(self.service.core.data['paused'])

    def test_report_contains_real_hazard_sources_and_all_fifty_records(self):
        self.call('reset', size=50, confirm_reset=True)
        self.call('prepare', drone_id='D001')
        self.call('report-example')
        result = self.call('report')
        files = list((self.service.root / 'saved-runs/reports').glob('*.html'))
        self.assertEqual(len(files), 1)
        document = files[0].read_text()
        self.assertIn('D050', document)
        self.assertIn('Reported temporary obstructions', document)
        self.assertIn('synthetic_event', document)
        self.assertNotIn('fixture host preview', document.lower())

    def test_new_fleet_requires_confirmation_and_does_not_show_an_old_proposal(self):
        self.call('prepare', drone_id='D001')
        with self.assertRaises(ValueError):
            self.call('reset', size=50, confirm_reset=False)
        self.call('reset', size=50, confirm_reset=True)
        self.assertEqual(self.controller.snapshot()['proposals'], {})
        self.assertEqual(len(self.service.core.data['drones']), 50)

    def test_ground_loss_does_not_erase_reported_crane_or_change_aircraft_resources(self):
        self.call('prepare', drone_id='D001')
        self.call('report-example')
        before = resources(self.service.core)
        self.app.ground.select('unavailable')
        d = self.service.core.data
        self.service.command(dict(action='context', run_id=d['run_id'], state_revision=d['state_revision']))
        self.assertEqual(resources(self.service.core), before)
        self.assertEqual(self.service.core.data['hazards']['revision'], 1)


if __name__ == '__main__':
    unittest.main()
