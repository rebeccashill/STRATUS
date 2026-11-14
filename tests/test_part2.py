"""Behavioral checks for the Part 2 evidence boundary and malformed inputs."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from stratus.inspection.capture import simulated_capture
from stratus.inspection.loader import DEFAULT_MISSION, MissionValidationError, load_mission

ROOT = Path(__file__).resolve().parents[1]
FIXED_CLOCK = datetime(2026, 11, 13, 20, 30, tzinfo=timezone.utc)


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class Part2Tests(unittest.TestCase):
    def setUp(self):
        # Mutations only touch a disposable copy of newly authored inputs.
        temporary_base = Path(tempfile.gettempdir()).resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="stratus-part2-", dir=temporary_base)
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(temporary_base))
        self.addCleanup(self.temporary.cleanup)
        shutil.copytree(ROOT / "evidence/inspection", self.root / "evidence/inspection")
        self.mission_path = self.root / DEFAULT_MISSION
        self.mission_path.parent.mkdir(parents=True)
        self.mission_path.write_bytes((ROOT / DEFAULT_MISSION).read_bytes())
        self.doc = json.loads(self.mission_path.read_text(encoding="utf-8"))
        self.manifest_path = self.root / "evidence/inspection/manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.annotations_path = self.root / "evidence/inspection/annotations.json"

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def load(self):
        return load_mission(project_root=self.root)

    def test_valid_mission_preserves_entire_input_and_two_priors_without_spending(self):
        before = self.mission_path.read_bytes()
        mission = self.load()
        self.assertEqual(thaw(mission.document), self.doc)
        self.assertEqual(self.mission_path.read_bytes(), before)
        self.assertEqual(len(mission.document["assets"]), 6)
        self.assertEqual(len(mission.document["prior_records"]), 2)
        self.assertEqual(len(mission.evidence_by_view), 12)
        self.assertEqual(mission.document["initial_state"]["actions_remaining"], 3)
        self.assertEqual(mission.document["initial_state"]["battery_available"], 100)
        for prior in mission.document["prior_records"]:
            self.assertFalse(prior["consumes_new_action"])
            ref = mission.evidence_by_view[(prior["asset_id"], prior["view_id"])].record
            self.assertEqual(prior["evidence_ref"], ref["evidence_id"])
            self.assertEqual(prior["source_class"], ref["source_label"])

    def test_loaded_inputs_cannot_be_mutated(self):
        mission = self.load()
        with self.assertRaises(TypeError):
            mission.document["initial_state"]["actions_remaining"] = 0
        with self.assertRaises(TypeError):
            mission.evidence_by_view[("P01", "overview")].record["source_label"] = "actual_photo"

    def test_clear_unclear_concern_and_distinct_follow_up(self):
        mission = self.load()
        clear = simulated_capture(mission, "P01", "overview")
        blurred = simulated_capture(mission, "P02", "overview")
        follow = simulated_capture(mission, "P02", "follow-up")
        concern = simulated_capture(mission, "P03", "overview")
        self.assertEqual(clear["image_quality"], "clear")
        self.assertEqual(blurred["image_quality"], "unclear")
        self.assertEqual(blurred["finding"], "unknown")
        self.assertEqual(follow["image_quality"], "clear")
        self.assertNotEqual(blurred["evidence_ref"]["evidence_id"], follow["evidence_ref"]["evidence_id"])
        self.assertNotEqual(blurred["evidence_ref"]["sha256"], follow["evidence_ref"]["sha256"])
        self.assertEqual(concern["finding"], "apparent_concern_review_required")
        self.assertFalse(concern["annotation"]["live_model_output"])
        self.assertEqual(concern["annotation"]["human_review_status"], "pending")

    def test_traceable_response_and_no_state_transition(self):
        mission = self.load()
        before = thaw(mission.document)
        response = simulated_capture(mission, "P03", "overview", requested_at=FIXED_CLOCK)
        self.assertEqual(response["timestamp"], FIXED_CLOCK.isoformat())
        self.assertEqual(response["timestamp_kind"], "response_created_at_not_camera_capture")
        self.assertEqual(response["scenario_id"], self.doc["scenario_id"])
        self.assertEqual(response["source_label"], "synthetic")
        self.assertFalse(response["real_flight"])
        self.assertFalse(response["state_transition_applied"])
        self.assertTrue(response["evidence_ref"]["rights_note"])
        self.assertEqual(thaw(mission.document), before)

    def test_same_case_returns_identical_evidence_for_independent_planners(self):
        a, b = self.load(), self.load()
        for asset, view in a.evidence_by_view:
            first = simulated_capture(a, asset, view, requested_at=FIXED_CLOCK)
            second = simulated_capture(b, asset, view, requested_at=FIXED_CLOCK)
            self.assertEqual(first, second)

    def test_unknown_asset_view_case_and_excluded_panel_are_unknown(self):
        mission = self.load()
        for asset, view, scenario in (("P99", "overview", None), ("P01", "absent", None),
                                      ("P01", "overview", "another-case"), ("P06", "overview", None)):
            with self.subTest(asset=asset, view=view, scenario=scenario):
                result = simulated_capture(mission, asset, view, scenario_id=scenario)
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["finding"], "unknown")
                self.assertIsNone(result["evidence_ref"])
                self.assertIsNone(result["annotation"])

    def test_missing_after_load_never_replays_clear_annotation(self):
        mission = self.load()
        (self.root / "evidence/inspection/images/P01-overview.png").unlink()
        result = simulated_capture(mission, "P01", "overview")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["image_quality"], "unknown")
        self.assertEqual(result["finding"], "unknown")
        self.assertIsNone(result["annotation"])
        self.assertIn("evidence_unavailable", result["reason"])

    def test_unreadable_after_load_is_explicitly_unknown(self):
        mission = self.load()
        with patch("stratus.inspection.capture.check_image", side_effect=PermissionError("image unreadable")):
            result = simulated_capture(mission, "P01", "overview")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["finding"], "unknown")
        self.assertIn("unreadable", result["reason"])

    def test_changed_valid_png_after_load_is_unknown(self):
        mission = self.load()
        image = self.root / "evidence/inspection/images/P01-overview.png"
        image.write_bytes((self.root / "evidence/inspection/images/P03-overview.png").read_bytes())
        result = simulated_capture(mission, "P01", "overview")
        self.assertEqual(result["finding"], "unknown")
        self.assertIn("SHA-256", result["reason"])

    def test_corrupt_png_after_load_is_unknown(self):
        mission = self.load()
        (self.root / "evidence/inspection/images/P01-overview.png").write_bytes(b"not an image")
        result = simulated_capture(mission, "P01", "overview")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["finding"], "unknown")

    def test_missing_image_rejected_at_load(self):
        (self.root / self.manifest["entries"][0]["image_path"]).unlink()
        with self.assertRaisesRegex(MissionValidationError, "P01/overview.*missing"):
            self.load()

    def test_structurally_corrupt_png_rejected_even_with_matching_digest(self):
        data = (self.root / self.manifest["entries"][0]["image_path"]).read_bytes()[:90]
        (self.root / self.manifest["entries"][0]["image_path"]).write_bytes(data)
        self.manifest["entries"][0]["sha256"] = hashlib.sha256(data).hexdigest()
        self.write(self.manifest_path, self.manifest)
        with self.assertRaisesRegex(MissionValidationError, "unreadable.*truncated"):
            self.load()

    def test_duplicate_asset_and_prior_ids_rejected(self):
        for field in ("assets", "prior_records"):
            with self.subTest(field=field):
                doc = copy.deepcopy(self.doc)
                doc[field].append(copy.deepcopy(doc[field][0]))
                self.write(self.mission_path, doc)
                with self.assertRaisesRegex(MissionValidationError, "duplicate"):
                    self.load()

    def test_duplicate_manifest_ids_and_views_rejected(self):
        for field in ("evidence_id", "view"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                duplicate = copy.deepcopy(manifest["entries"][0])
                if field == "view":
                    duplicate["evidence_id"] += "-another-id"
                manifest["entries"].append(duplicate)
                self.write(self.manifest_path, manifest)
                with self.assertRaisesRegex(MissionValidationError, "duplicate"):
                    self.load()

    def test_unknown_asset_view_and_prior_references_rejected(self):
        for field, value in (("asset_id", "P99"), ("view_id", "unknown")):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest["entries"][0][field] = value
                self.write(self.manifest_path, manifest)
                with self.assertRaisesRegex(MissionValidationError, "unknown"):
                    self.load()
        self.write(self.manifest_path, self.manifest)
        self.doc["prior_records"][0]["evidence_ref"] = "not-a-known-reference"
        self.write(self.mission_path, self.doc)
        with self.assertRaisesRegex(MissionValidationError, "evidence reference"):
            self.load()

    def test_missing_views_and_annotations_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["entries"].pop()
        self.write(self.manifest_path, manifest)
        with self.assertRaisesRegex(MissionValidationError, "missing evidence"):
            self.load()
        self.write(self.manifest_path, self.manifest)
        annotations = json.loads(self.annotations_path.read_text(encoding="utf-8"))
        annotations["annotations"].pop()
        self.write(self.annotations_path, annotations)
        with self.assertRaisesRegex(MissionValidationError, "every evidence ID"):
            self.load()

    def test_path_escape_and_absolute_paths_rejected(self):
        for value in ("../outside.png", "/outside.png", "C:/outside.png", "images\\outside.png"):
            with self.subTest(value=value):
                manifest = copy.deepcopy(self.manifest)
                manifest["entries"][0]["image_path"] = value
                self.write(self.manifest_path, manifest)
                with self.assertRaisesRegex(MissionValidationError, "project-relative"):
                    self.load()

    def test_costs_reject_negative_nonfinite_boolean_and_missing_values(self):
        for key in ("travel_energy_per_m", "capture_energy_per_action", "return_reserve"):
            for value in (-1, float("inf"), float("nan"), 10**400, True, None):
                with self.subTest(key=key, value=value):
                    doc = copy.deepcopy(self.doc)
                    doc["energy_model"][key] = value
                    self.write(self.mission_path, doc)
                    with self.assertRaisesRegex(MissionValidationError, "nonnegative|non-finite|finite"):
                        self.load()

    def test_invalid_battery_capacity_and_balance_rejected(self):
        for key, values in (("battery_available", (-1, 101, True, float("inf"))),
                            ("initial_battery_capacity", (0, -1, True))):
            for value in values:
                with self.subTest(key=key, value=value):
                    doc = copy.deepcopy(self.doc)
                    doc["initial_state" if key == "battery_available" else "energy_model"][key] = value
                    self.write(self.mission_path, doc)
                    with self.assertRaises(MissionValidationError):
                        self.load()

    def test_missing_units_and_nonfinite_coordinates_rejected(self):
        doc = copy.deepcopy(self.doc)
        del doc["coordinate_frame"]["unit"]
        self.write(self.mission_path, doc)
        with self.assertRaisesRegex(MissionValidationError, "coordinate_frame.unit"):
            self.load()
        doc = copy.deepcopy(self.doc)
        doc["assets"][0]["position"]["x"] = float("inf")
        self.write(self.mission_path, doc)
        with self.assertRaisesRegex(MissionValidationError, "non-finite"):
            self.load()

    def test_action_budget_and_prior_action_consumption_rejected(self):
        for key, value in (("actions_remaining", -1), ("actions_remaining", 4), ("actions_used", True)):
            with self.subTest(key=key, value=value):
                doc = copy.deepcopy(self.doc)
                doc["initial_state"][key] = value
                self.write(self.mission_path, doc)
                with self.assertRaises(MissionValidationError):
                    self.load()
        self.doc["prior_records"][0]["consumes_new_action"] = True
        self.write(self.mission_path, self.doc)
        with self.assertRaisesRegex(MissionValidationError, "cannot consume"):
            self.load()

    def test_rights_scenario_and_live_assessment_mislabels_rejected(self):
        for field, value in (("rights_note", ""), ("source_label", "actual_photo"), ("scenario_id", "different")):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest["entries"][0][field] = value
                self.write(self.manifest_path, manifest)
                with self.assertRaises(MissionValidationError):
                    self.load()
        self.write(self.manifest_path, self.manifest)
        annotations = json.loads(self.annotations_path.read_text(encoding="utf-8"))
        annotations["annotations"][0]["live_model_output"] = True
        self.write(self.annotations_path, annotations)
        with self.assertRaisesRegex(MissionValidationError, "never live inference"):
            self.load()

    def test_malformed_duplicate_key_and_missing_json_rejected(self):
        for value in ("{", '{"schema_version":"0.0.1","schema_version":"other"}', "[]"):
            with self.subTest(value=value):
                self.mission_path.write_text(value, encoding="utf-8")
                with self.assertRaises(MissionValidationError):
                    self.load()
        self.mission_path.unlink()
        with self.assertRaisesRegex(MissionValidationError, "cannot read"):
            self.load()

    def test_cli_success_and_readable_errors_without_tracebacks(self):
        for args, code in (([], 0), (["--capture", "P03", "overview"], 0),
                           (["--capture", "P99", "overview"], 3),
                           (["--mission", str(self.root / "missing.json")], 2)):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "-B", "-S", "-m", "stratus.inspection", *args],
                                        cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.mission_path.write_text("{", encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-S", "-m", "stratus.inspection", "--mission", str(self.mission_path)],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Cannot load mission", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
