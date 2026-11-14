"""State/review behavior tests; injected failures are not live service evidence."""

from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from stratus.inspection.capture import simulated_capture
from stratus.inspection.computation import ComputationUnavailable, CostCalculator, python_costs
from stratus.inspection.loader import freeze, load_mission
from stratus.inspection.review import InspectionSession, ground_snapshot


def proposal(asset="P03", view="overview"):
    return dict(action_type="inspect" if view == "overview" else "follow_up", asset_id=asset,
                view_id=view, reason="Operator review", alternative="Return or stop")


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mission = load_mission()

    def session(self, **kwargs):
        return InspectionSession(self.mission, **kwargs)

    def test_fresh_run_budget_prior_records_and_uninspected_assets(self):
        run = self.session(); data = run.snapshot(); state = data["aircraft_state"]
        self.assertEqual((state["battery_available"], state["position"], state["actions_remaining"]),
                         (100, {"x": 0, "y": 0}, 3))
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(data["uninspected_assets"], ["P03", "P04", "P05"])
        self.assertEqual(len(data["review_queue"]), 2)
        self.assertEqual(data["assessments"][0]["finding"], "unknown_pending_operator_review")
        self.assertNotEqual(run.snapshot()["run_id"], self.session().snapshot()["run_id"])

    def test_actual_recorded_ground_snapshot_retains_source_location_and_time(self):
        data = self.session().snapshot()["ground_context"]
        self.assertEqual((data["mode"], data["status"]), ("recorded_measured", "available"))
        self.assertEqual(len(data["observations"]), 6)
        self.assertEqual(data["source"]["records_checked"], 60)
        self.assertEqual(data["location"]["status"], "unknown")
        self.assertFalse(data["physical_acquisition_performed"])
        self.assertTrue(all(r["acquired_at_utc"].startswith("2026-11-14T11:") for r in data["observations"]))
        self.assertTrue(all(r["quality"]["status"] == "unreviewed" for r in data["observations"]))

    def test_missing_ground_files_do_not_block_initialization(self):
        with tempfile.TemporaryDirectory() as folder:
            mission = replace(self.mission, project_root=Path(folder))
            run = InspectionSession(mission)
            self.assertEqual(run.snapshot()["ground_context"]["status"], "unavailable")
            self.assertEqual(run.state.battery_available, 100)

    def test_changed_ground_hash_is_unavailable_without_fabricated_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "context/ground-measurements").mkdir(parents=True)
            shutil.copy2(self.mission.project_root / "context/hardware-status.json", root / "context/hardware-status.json")
            (root / "context/ground-measurements/observations-20261114.jsonl").write_text('{}\n')
            ground = ground_snapshot(replace(self.mission, project_root=root))
            self.assertEqual(ground["observations"], [])
            self.assertIn("hash", ground["technical_details"]["message"])

    def test_explicit_unavailable_ground_has_same_aircraft_budget(self):
        recorded, missing = self.session(), self.session(ground_mode="unavailable")
        self.assertEqual(recorded.state.snapshot(), missing.state.snapshot())
        for run in (recorded, missing):
            event = run.execute(proposal(), request_id="capture", expected_revision=0)
            self.assertEqual(event["status"], "executed")
        self.assertEqual(recorded.state.battery_available, missing.state.battery_available)
        fields = ("asset_id", "view_id", "assessment_mode", "image_quality", "finding", "flags", "evidence_ref")
        def findings(run):
            return [{key: row[key] for key in fields} for row in run.snapshot()["assessments"]]
        self.assertEqual(findings(recorded), findings(missing))

    def test_capture_commits_one_debit_assessment_and_evidence_reference(self):
        run = self.session(); event = run.execute(proposal(), request_id="inspect-1", expected_revision=0)
        self.assertEqual(event["status"], "executed")
        self.assertAlmostEqual(event["battery_debit"], 20.811388300841898)
        self.assertAlmostEqual(run.state.battery_available, 79.1886116991581)
        self.assertEqual((run.state.actions_used, run.state.actions_remaining, run.state.revision), (1, 2, 1))
        data = run.snapshot()
        self.assertEqual((len(data["assessments"]), len(data["review_queue"]), len(data["events"])), (3, 3, 1))
        self.assertEqual(data["assessments"][-1]["evidence_ref"]["sha256"], event["evidence"]["evidence_ref"]["sha256"])
        self.assertEqual(event["computation"]["mode"], "local_python")
        self.assertEqual(data["uninspected_assets"], ["P04", "P05"])

    def test_concern_is_tentative_replay_and_human_review_stays_pending(self):
        run = self.session(); event = run.execute(proposal(), request_id="concern", expected_revision=0)
        record = event["assessment"]
        self.assertEqual(record["assessment_mode"], "authored_replay_annotation")
        self.assertFalse(record["live_model_output"])
        self.assertIsNone(record["model"])
        self.assertEqual(record["human_review_status"], "pending")
        self.assertIn("tentative_concern", record["flags"])
        self.assertIn("P03", run.snapshot()["incomplete_assets"])

    def test_unclear_evidence_remains_unknown_and_needs_follow_up(self):
        run = self.session(); event = run.execute(proposal("P05"), request_id="unclear", expected_revision=0)
        self.assertEqual((event["assessment"]["image_quality"], event["assessment"]["finding"]), ("unclear", "unknown"))
        asset = next(a for a in run.snapshot()["assets"] if a["asset_id"] == "P05")
        self.assertEqual(asset["coverage_status"], "needs_distinct_follow_up")

    def test_clear_follow_up_updates_current_quality_preserves_prior_unknown(self):
        run = self.session(); event = run.execute(proposal("P02", "follow-up"), request_id="follow", expected_revision=0)
        asset = next(a for a in run.snapshot()["assets"] if a["asset_id"] == "P02")
        self.assertEqual(asset["image_quality"], "clear")
        self.assertEqual(asset["coverage_status"], "captured_pending_human_review")
        self.assertEqual(run.snapshot()["assessments"][1]["finding"], "unknown_pending_operator_review")
        self.assertEqual(event["assessment"]["human_review_status"], "pending")

    def test_unrecognized_assessment_mode_becomes_unknown(self):
        def unavailable(*args, **kwargs):
            result = simulated_capture(*args, **kwargs); result["assessment_mode"] = "unsupported"
            return result
        run = self.session()
        with patch("stratus.inspection.engine.simulated_capture", side_effect=unavailable):
            event = run.execute(proposal(), request_id="unknown", expected_revision=0)
        self.assertEqual(event["assessment"]["finding"], "unknown")
        self.assertEqual(event["assessment"]["assessment_mode"], "unavailable_no_assessment")

    def test_same_request_replay_does_not_recompute_capture_or_duplicate_review(self):
        run = self.session(); p = proposal()
        run.execute(p, request_id="same", expected_revision=0); before = run.snapshot()
        with patch("stratus.inspection.review.execute_computed_action") as execute:
            replay = run.execute(p, request_id="same", expected_revision=0)
            execute.assert_not_called()
        self.assertEqual(replay["status"], "already_processed")
        self.assertEqual(replay["battery_debit"], 0)
        self.assertEqual(run.snapshot(), before)

    def test_concurrent_retries_execute_once(self):
        run = self.session()
        with ThreadPoolExecutor(max_workers=8) as pool:
            events = list(pool.map(lambda _: run.execute(proposal(), request_id="concurrent", expected_revision=0), range(8)))
        self.assertEqual(sum(e["status"] == "executed" for e in events), 1)
        self.assertEqual(sum(e["status"] == "already_processed" for e in events), 7)
        self.assertEqual((run.state.actions_used, len(run.snapshot()["assessments"])), (1, 3))

    def test_request_id_reuse_for_another_action_rejects(self):
        run = self.session(); run.execute(proposal(), request_id="same", expected_revision=0); before = run.snapshot()
        event = run.execute(proposal("P04"), request_id="same", expected_revision=0)
        self.assertEqual(event["code"], "idempotency_key_conflict")
        self.assertEqual(run.snapshot(), before)

    def test_stale_revision_is_rejected_before_computation(self):
        run = self.session(); run.execute(proposal(), request_id="first", expected_revision=0); before = run.snapshot()
        with patch("stratus.inspection.review.execute_computed_action") as execute:
            event = run.execute(proposal("P04"), request_id="stale", expected_revision=0)
            execute.assert_not_called()
        self.assertEqual(event["code"], "stale_state_revision")
        self.assertEqual(run.snapshot(), before)

    def test_another_request_id_cannot_charge_same_view_twice(self):
        run = self.session(); run.execute(proposal(), request_id="first", expected_revision=0); before = run.state.snapshot()
        event = run.execute(proposal(), request_id="another", expected_revision=1)
        self.assertEqual(event["decision"]["code"], "duplicate_view")
        self.assertEqual(run.state.snapshot(), before)
        self.assertEqual(len(run.snapshot()["review_queue"]), 3)

    def test_excluded_and_prior_duplicate_do_not_capture(self):
        run = self.session()
        for asset, code in (("P06", "asset_excluded"), ("P01", "duplicate_view")):
            with patch("stratus.inspection.engine.simulated_capture") as capture:
                event = run.execute(proposal(asset), request_id=asset, expected_revision=0)
                capture.assert_not_called()
            self.assertEqual(event["decision"]["code"], code)
            self.assertEqual((run.state.actions_used, len(run.snapshot()["review_queue"])), (0, 2))

    def test_exhausted_cap_rejects_without_assessment(self):
        run = self.session()
        for revision, asset in enumerate(("P03", "P04", "P05")):
            self.assertEqual(run.execute(proposal(asset), request_id=asset, expected_revision=revision)["status"], "executed")
        before = run.state.snapshot()
        event = run.execute(proposal("P02", "follow-up"), request_id="fourth", expected_revision=3)
        self.assertEqual(event["decision"]["code"], "actions_exhausted")
        self.assertEqual(run.state.snapshot(), before)
        self.assertEqual(len(run.snapshot()["review_queue"]), 5)

    def test_material_computation_mismatch_blocks_capture_and_review(self):
        def mismatch(data):
            reply = dict(python_costs(data), wolfram_version="INJECTED", system_id="test")
            reply["options"][0]["outbound"] += 1
            return reply
        run = self.session(); before = run.state.snapshot()
        with patch("stratus.inspection.engine.simulated_capture") as capture:
            event = run.execute(proposal(), request_id="bad-compute", expected_revision=0, calculator=CostCalculator(runner=mismatch))
            capture.assert_not_called()
        self.assertEqual(event["code"], "numerical_disagreement")
        self.assertEqual(run.state.snapshot(), before)
        self.assertEqual(len(run.snapshot()["review_queue"]), 2)

    def test_timeout_uses_visible_python_fallback_once(self):
        run = self.session(); runner = Mock(side_effect=ComputationUnavailable("timeout", "Injected timeout"))
        event = run.execute(proposal(), request_id="fallback", expected_revision=0, calculator=CostCalculator(runner=runner))
        self.assertEqual(event["status"], "executed")
        self.assertEqual(event["computation"]["mode"], "local_python_fallback")
        self.assertEqual(runner.call_count, 1)

    def test_snapshot_and_returned_event_cannot_mutate_internal_records(self):
        run = self.session(); event = run.execute(proposal(), request_id="one", expected_revision=0)
        before = run.snapshot(); event["assessment"]["finding"] = "fake"
        snapshot = run.snapshot(); snapshot["review_queue"].clear(); snapshot["ground_context"]["observations"].clear()
        snapshot["aircraft_state"]["history"].clear()
        self.assertEqual(run.snapshot(), before)

    def test_stop_replay_does_not_add_assessment_or_charge(self):
        run = self.session(); p = dict(action_type="stop", asset_id=None, view_id=None, reason="Stop", alternative="Review")
        event = run.execute(p, request_id="stop", expected_revision=0)
        self.assertEqual(event["status"], "executed")
        self.assertEqual((run.state.status, run.state.battery_available, len(run.snapshot()["review_queue"])), ("stopped", 100, 2))
        self.assertEqual(run.execute(p, request_id="stop", expected_revision=0)["status"], "already_processed")

    def test_invalid_revision_and_request_id_never_change_state(self):
        run = self.session(); before = run.snapshot()
        for revision, request_id in ((True, "id"), (-1, "id"), (0, "../bad")):
            with self.assertRaises(ValueError): run.execute(proposal(), request_id=request_id, expected_revision=revision)
        self.assertEqual(run.snapshot(), before)

    def test_cli_inspection_preview_does_not_execute(self):
        result = subprocess.run([sys.executable, "-B", "-S", "-m", "stratus.inspection", "--inspect", "P03", "overview"],
                                cwd=self.mission.project_root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["state_before"], data["state_after"])
        self.assertNotIn("execution", data)

    def test_cli_execute_returns_review_and_separate_ground(self):
        result = subprocess.run([sys.executable, "-B", "-S", "-m", "stratus.inspection", "--inspect", "P03", "overview", "--execute"],
                                cwd=self.mission.project_root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["state_after"]["actions_remaining"], 2)
        self.assertEqual(data["run_after"]["ground_context"], data["run_before"]["ground_context"])
        self.assertEqual(len(data["run_after"]["review_queue"]), 3)


if __name__ == "__main__": unittest.main()
