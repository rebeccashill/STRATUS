import copy
import json
import unittest

from stratus.hazards.core import FRAME, HazardRegistry, assess_path, assess_fleet, intersects
from stratus.hazards.fixtures import crane_event, fleet_paths, path, return_only


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.rect = crane_event()["rectangle"]

    def test_crossing(self):
        self.assertTrue(intersects({"x": 0, "y": 0}, {"x": 50, "y": 0}, self.rect))

    def test_touching_buffered_boundary(self):
        self.assertTrue(intersects({"x": 0, "y": 6}, {"x": 50, "y": 6}, self.rect))

    def test_outside(self):
        self.assertFalse(intersects({"x": 0, "y": 7}, {"x": 50, "y": 7}, self.rect))

    def test_zero_length_inside(self):
        self.assertTrue(intersects({"x": 25, "y": 0}, {"x": 25, "y": 0}, self.rect))

    def test_zero_length_outside(self):
        self.assertFalse(intersects({"x": 0, "y": 0}, {"x": 0, "y": 0}, self.rect))

    def test_endpoint_inside(self):
        self.assertTrue(intersects({"x": 0, "y": 0}, {"x": 25, "y": 0}, self.rect))

    def test_backward_segment(self):
        self.assertTrue(intersects({"x": 50, "y": 0}, {"x": 0, "y": 0}, self.rect))

    def test_invalid_shapes(self):
        for key, value in (("x_min", float("nan")), ("buffer_m", -1), ("x_min", 40), ("buffer_m", True)):
            with self.subTest(key=key, value=value):
                bad = {**self.rect, key: value}
                with self.assertRaises(ValueError):
                    intersects({"x": 0, "y": 0}, {"x": 50, "y": 0}, bad)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = HazardRegistry()

    def test_empty_registry_clear(self):
        self.assertEqual(assess_path(path(), self.registry)["state"], "clear")

    def test_report_and_immutable_snapshot(self):
        event = crane_event()
        self.registry.apply(event)
        event["rectangle"]["x_min"] = -999
        snapshot = self.registry.snapshot()
        snapshot["hazards"].clear()
        self.assertEqual(self.registry.revision, 1)
        self.assertEqual(len(self.registry.snapshot()["hazards"]), 1)

    def test_duplicate_and_old_revision_do_not_mutate(self):
        event = crane_event()
        self.registry.apply(event)
        before = self.registry.snapshot()
        for bad in (event, crane_event(0, action="amend")):
            with self.assertRaises(ValueError):
                self.registry.apply(bad)
            self.assertEqual(before, self.registry.snapshot())

    def test_amend_clear_and_replay(self):
        self.registry.apply(crane_event())
        self.registry.apply(crane_event(1, action="amend", effective=2))
        self.registry.apply(crane_event(2, action="clear", effective=3, source="operator_report", notes="Operator reviewed and cleared authored area"))
        self.assertEqual(assess_path(path(hazard_revision=3), self.registry)["state"], "clear")
        self.assertEqual(HazardRegistry.restore(self.registry.snapshot()).snapshot(), self.registry.snapshot())

    def test_expiry_is_not_clearance(self):
        self.registry.apply(crane_event())
        self.registry.expire(32)
        snap = self.registry.snapshot()
        self.assertEqual(snap["hazards"]["crane-001"]["state"], "review_required")
        self.assertEqual(assess_path(path(hazard_revision=2), self.registry)["state"], "blocked")
        self.registry.expire(40)
        self.assertEqual(self.registry.revision, 2)

    def test_bad_frame_rejected_atomically(self):
        event = crane_event()
        event["coordinate_frame"] = {"name": "GPS", "unit": "degrees"}
        with self.assertRaises(ValueError):
            self.registry.apply(event)
        self.assertEqual(self.registry.revision, 0)

    def test_backward_time_rejected(self):
        self.registry.apply(crane_event(effective=10))
        with self.assertRaises(ValueError):
            self.registry.apply(crane_event(1, action="amend", effective=1))

    def test_observation_must_not_follow_report(self):
        e = crane_event()
        e["observed_at_utc"] = "2026-11-15T20:00:00Z"
        with self.assertRaises(ValueError):
            self.registry.apply(e)

    def test_unknown_source_is_not_detection(self):
        e = crane_event()
        e["source"] = "bme280_detected_crane"
        with self.assertRaises(ValueError):
            self.registry.apply(e)

    def test_forged_saved_registry_rejected(self):
        self.registry.apply(crane_event())
        s = self.registry.snapshot()
        s["hazards"]["crane-001"]["state"] = "cleared"
        with self.assertRaises(ValueError):
            HazardRegistry.restore(s)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.registry = HazardRegistry()
        self.registry.apply(crane_event())

    def test_checks_both_legs(self):
        result = assess_path(path(hazard_revision=1), self.registry)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual({x["leg"] for x in result["intersections"]}, {"outbound", "return"})

    def test_clear_target_but_return_blocked(self):
        result = assess_path(return_only(1), self.registry)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual([x["leg"] for x in result["intersections"]], ["return"])

    def test_stale_and_invalid_are_never_clear(self):
        bad = path(hazard_revision=1)
        bad["outbound"][0]["x"] = float("inf")
        for value in (path(), bad, {}, None):
            self.assertEqual(assess_path(value, self.registry)["state"], "review_required")

    def test_mismatched_segment_endpoints(self):
        p = path(hazard_revision=1)
        p["outbound"][1] = {"x": 1, "y": 1}
        self.assertEqual(assess_path(p, self.registry)["state"], "review_required")

    def test_fifty_assessed_two_affected(self):
        result = assess_fleet(fleet_paths(50, 1), self.registry)
        self.assertEqual((result["assessed_count"], result["affected_count"]), (50, 2))
        self.assertEqual({x["hazard_revision"] for x in result["assessments"]}, {1})

    def test_duplicate_drone_not_silently_skipped(self):
        p = path(hazard_revision=1)
        with self.assertRaises(ValueError):
            assess_fleet([p, copy.deepcopy(p)], self.registry)

    def test_assessment_is_pure(self):
        p, before = path(hazard_revision=1), self.registry.snapshot()
        original = copy.deepcopy(p)
        assess_path(p, self.registry)
        self.assertEqual(original, p)
        self.assertEqual(before, self.registry.snapshot())

    def test_malformed_registry_never_clear(self):
        r = self.registry.snapshot()
        r["hazards"]["crane-001"]["rectangle"]["x_min"] = float("nan")
        self.assertEqual(assess_path(path(hazard_revision=1), r)["state"], "review_required")


if __name__ == "__main__":
    unittest.main()
