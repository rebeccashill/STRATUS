"""Durable budget, evidence, original ground provenance and retry checks."""

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from stratus.inspection.loader import freeze, load_mission
from stratus.inspection.computation import ComputationUnavailable, CostCalculator
from stratus.inspection.operator import operator_summary, render_summary
from stratus.inspection.persistence import digest
from stratus.inspection.review import InspectionSession


def proposal(asset="P03", view="overview"):
    return dict(action_type="inspect" if view == "overview" else "follow_up", asset_id=asset,
                view_id=view, reason="Persistence verification", alternative="Return or stop")


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.mission = load_mission()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.json"
        self.run = InspectionSession(self.mission)

    def capture_save(self):
        self.run.execute(proposal(), request_id="first", expected_revision=0)
        self.run.save(self.path)
        return InspectionSession.load(self.mission, self.path)

    def mutate(self, callback):
        doc = json.loads(self.path.read_text()); callback(doc["payload"])
        doc["sha256"] = digest(doc["payload"])
        self.path.write_text(json.dumps(doc), encoding="utf-8")

    def test_exact_round_trip_preserves_original_ground_and_state(self):
        restored = self.capture_save()
        self.assertEqual(restored.snapshot(), self.run.snapshot())
        self.assertEqual(restored.state.actions_remaining, 2)
        self.assertAlmostEqual(restored.state.battery_available, 79.1886116991581)

    def test_load_never_acquires_ground_captures_or_calls_external_compute(self):
        self.capture_save()
        with patch("stratus.inspection.review.ground_snapshot", side_effect=AssertionError("new ground read")), \
             patch("stratus.inspection.engine.simulated_capture", side_effect=AssertionError("new capture")), \
             patch("stratus.inspection.computation.LocalWolfram.__call__", side_effect=AssertionError("external compute")):
            restored = InspectionSession.load(self.mission, self.path)
        self.assertEqual(restored.snapshot()["ground_context"], self.run.snapshot()["ground_context"])

    def test_retry_after_reload_does_not_debit_or_add_finding(self):
        restored = self.capture_save(); before = restored.snapshot()
        event = restored.execute(proposal(), request_id="first", expected_revision=0)
        self.assertEqual(event["status"], "already_processed")
        self.assertEqual(restored.snapshot(), before)

    def test_resume_new_action_retains_prior_debit_and_can_save(self):
        restored = self.capture_save(); old = restored.state.battery_available
        event = restored.execute(proposal("P04"), request_id="second", expected_revision=1)
        self.assertEqual(event["status"], "executed")
        self.assertEqual(restored.state.actions_remaining, 1)
        self.assertLess(restored.state.battery_available, old)
        restored.save(self.path)
        self.assertEqual(InspectionSession.load(self.mission, self.path).snapshot(), restored.snapshot())

    def test_rejected_and_read_only_proposals_saved(self):
        self.run.propose(proposal("P06")); self.run.propose(proposal())
        self.run.execute(proposal("P06"), request_id="excluded", expected_revision=0)
        self.run.save(self.path)
        data = json.loads(self.path.read_text())["payload"]
        self.assertEqual(len(data["proposal_audit"]), 2)
        self.assertEqual(data["run"]["events"][0]["status"], "rejected")
        restored = InspectionSession.load(self.mission, self.path)
        self.assertEqual(restored.state.actions_used, 0)
        self.assertEqual(restored.execute(proposal("P06"), request_id="excluded", expected_revision=0)["original_status"], "rejected")

    def test_stale_loaded_process_cannot_overwrite_newer_checkpoint(self):
        first = self.capture_save(); stale = InspectionSession.load(self.mission, self.path)
        first.execute(proposal("P04"), request_id="second", expected_revision=1); first.save(self.path)
        raw = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed"): stale.save(self.path)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_new_run_cannot_overwrite_an_existing_run(self):
        self.capture_save(); raw = self.path.read_bytes()
        with self.assertRaises(ValueError): InspectionSession(self.mission).save(self.path)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_interrupted_atomic_write_keeps_previous_file(self):
        restored = self.capture_save(); raw = self.path.read_bytes()
        with patch("stratus.inspection.persistence.os.replace", side_effect=OSError("Injected disk failure")):
            with self.assertRaises(OSError): restored.save(self.path)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse(list(self.path.parent.glob(".stratus-*.tmp")))
        self.assertFalse(self.path.with_name("run.json.lock").exists())

    def test_active_writer_lock_is_not_deleted(self):
        lock = self.path.with_name("run.json.lock"); lock.write_text("another writer")
        with self.assertRaisesRegex(ValueError, "lock"): self.run.save(self.path)
        self.assertTrue(lock.exists())

    def test_truncated_duplicate_and_checksum_failures_rejected(self):
        for raw in ('{', '{"format":"a","format":"b"}', '{"format":"stratus-run-1","payload":{},"sha256":"bad"}'):
            self.path.write_text(raw)
            with self.assertRaises(ValueError): InspectionSession.load(self.mission, self.path)

    def test_reset_budget_rejected_even_with_recomputed_checksum(self):
        self.capture_save()
        self.mutate(lambda p: p["run"]["aircraft_state"].update(battery_available=100, actions_remaining=3))
        with self.assertRaisesRegex(ValueError, "budget"): InspectionSession.load(self.mission, self.path)

    def test_duplicate_finding_rejected_even_with_recomputed_checksum(self):
        self.capture_save()
        self.mutate(lambda p: p["run"]["review_queue"].append(copy.deepcopy(p["run"]["review_queue"][-1])))
        with self.assertRaises(ValueError): InspectionSession.load(self.mission, self.path)

    def test_lost_request_receipt_rejected(self):
        self.capture_save(); self.mutate(lambda p: p["requests"].clear())
        with self.assertRaises(ValueError): InspectionSession.load(self.mission, self.path)

    def test_changed_computation_reference_rejected(self):
        self.capture_save()
        self.mutate(lambda p: p["run"]["events"][0]["computation"]["normalized_input"].update(battery_available=999))
        with self.assertRaises(ValueError): InspectionSession.load(self.mission, self.path)

    def test_mission_revision_or_geometry_change_rejected(self):
        self.capture_save(); doc = dict(self.mission.document); doc["revision"] = "another-version"
        with self.assertRaisesRegex(ValueError, "mission"): InspectionSession.load(replace(self.mission, document=freeze(doc)), self.path)

    def test_unavailable_ground_stays_unavailable_on_reload(self):
        run = InspectionSession(self.mission, ground_mode="unavailable"); run.save(self.path)
        restored = InspectionSession.load(self.mission, self.path)
        self.assertEqual(restored.snapshot()["ground_context"], run.snapshot()["ground_context"])
        self.assertEqual(operator_summary(restored)["ground"]["availability"], "Unavailable")

    def test_ground_age_increases_without_refreshing_original_times(self):
        restored = self.capture_save(); now = datetime(2026,11,14,14,tzinfo=timezone.utc)
        before = restored.snapshot()["ground_context"]
        a = operator_summary(restored, now=now); b = operator_summary(restored, now=now+timedelta(hours=1))
        self.assertEqual(b["ground"]["oldest_age_seconds"]-a["ground"]["oldest_age_seconds"], 3600)
        self.assertEqual(restored.snapshot()["ground_context"], before)
        self.assertEqual(b["ground"]["availability"], "Recorded")

    def test_operator_summary_shows_change_hold_reason_and_no_driver_error(self):
        self.capture_save(); summary = operator_summary(self.run); text = render_summary(summary)
        self.assertIn("P03/overview", text); self.assertIn("2", text)
        self.assertEqual(summary["next_action"]["type"], "hold")
        self.assertIn("Recorded", text); self.assertIn("minutes old", text)
        self.assertNotIn("technical_details", text)

    def test_frozen_input_paths_cannot_be_overwritten(self):
        for path in (self.mission.mission_path, self.mission.project_root / "context/new.json",
                     self.mission.project_root / "evidence/new.json"):
            with self.assertRaises(ValueError): self.run.save(path)

    def test_operator_view_keeps_computation_fallback_visible(self):
        def failure(_): raise ComputationUnavailable("timeout", "Injected timeout")
        self.run.execute(proposal(), request_id="fallback", expected_revision=0, calculator=CostCalculator(runner=failure))
        self.run.save(self.path)
        restored = InspectionSession.load(self.mission, self.path)
        self.assertIn("local Python fallback", render_summary(operator_summary(restored)))

    def test_cli_save_open_and_continue_keeps_budgets(self):
        command = [sys.executable,"-B","-S","-m","stratus.inspection"]
        def cli(*args):
            p = subprocess.run(command+list(args), cwd=self.mission.project_root, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode,0,p.stderr); return p.stdout
        first = json.loads(cli("--inspect","P03","overview","--execute","--save",str(self.path),"--request-id","cli-first"))
        self.assertEqual(first["state_after"]["actions_remaining"],2)
        opened = json.loads(cli("--load",str(self.path),"--run-state"))
        self.assertEqual(opened["aircraft_state"],first["state_after"])
        self.assertIn("Recorded",cli("--load",str(self.path),"--summary"))
        retried = json.loads(cli("--load",str(self.path),"--inspect","P03","overview","--execute",
                                "--request-id","cli-first","--expected-revision","0"))
        self.assertEqual(retried["execution"]["status"],"already_processed")
        self.assertEqual(retried["state_after"],first["state_after"])


if __name__ == "__main__": unittest.main()
