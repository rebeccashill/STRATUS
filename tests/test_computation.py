"""Behavior tests. Injected responses are explicitly not live Wolfram evidence."""

import copy
from dataclasses import replace
import math
import subprocess
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from stratus.inspection.actions import Proposal
from stratus.inspection.computation import (CONTRACT, MODEL, ComputationUnavailable,
    CostCalculator, LocalWolfram, compute_mission_options, execute_computed_action,
    mission_input, normalize_input, python_costs)
from stratus.inspection.engine import execute_action, initial_state
from stratus.inspection.loader import load_mission


def fixture():
    return dict(contract_version=CONTRACT, model_version=MODEL, mission_id="toy",
        mission_revision="fixture-1", state_revision=0,
        position=dict(point_id="current", x=20, y=0), launch=dict(point_id="launch", x=0, y=0),
        distance_unit="m", energy_unit="simulated_energy_unit", battery_available=100,
        capture_cost=5, travel_energy_per_distance=0.5, return_reserve=15, remaining_actions=3,
        candidates=[dict(asset_id="P03", view_id="overview", x=40, y=0)])


def injected_reply(data):
    return dict(python_costs(data), wolfram_version="INJECTED TEST RESPONSE", system_id="test")


class ComputationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mission = load_mission()

    def test_fixture_boundaries_and_exhaustion(self):
        for available, margin, feasible in ((100, 50, True), (50, 0, True), (49, -1, False)):
            data = fixture(); data["battery_available"] = available
            option = python_costs(data)["options"][0]
            self.assertEqual((option["margin"], option["feasible"]), (margin, feasible))
        data = fixture(); data["remaining_actions"] = 0
        self.assertFalse(python_costs(data)["options"][0]["feasible"])

    def test_invalid_numeric_and_counts_never_call_runner(self):
        for field, value in (("battery_available", True), ("capture_cost", -1),
                ("return_reserve", math.nan), ("battery_available", math.inf),
                ("battery_available", 10 ** 1000), ("remaining_actions", 1.0),
                ("state_revision", True), ("remaining_actions", -1)):
            with self.subTest(field=field, value=str(value)[:30]):
                data = fixture(); data[field] = value
                runner = Mock(); calculator = CostCalculator(runner=runner)
                with self.assertRaises(ValueError): calculator.compute(data)
                runner.assert_not_called()

    def test_contract_units_extra_fields_and_duplicates_rejected(self):
        mutations = [("model_version", "unapproved-formula"), ("distance_unit", "feet"),
                     ("energy_unit", "Wh"), ("mission_revision", ""), ("program", "2+2")]
        for field, value in mutations:
            data = fixture(); data[field] = value
            with self.assertRaises(ValueError): normalize_input(data)
        data = fixture(); data["candidates"] *= 2
        with self.assertRaises(ValueError): normalize_input(data)
        data = fixture(); data["position"]["x"] = "1+1"
        with self.assertRaises(ValueError): normalize_input(data)

    def test_equivalent_units_share_cache_without_aliasing(self):
        runner = Mock(side_effect=injected_reply); calculator = CostCalculator(runner=runner)
        first = calculator.compute(fixture())
        first["output"]["options"][0]["margin"] = 999
        km = fixture(); km["distance_unit"] = "km"; km["travel_energy_per_distance"] = 500
        for point in (km["position"], km["launch"], *km["candidates"]):
            point["x"] /= 1000; point["y"] /= 1000
        second = calculator.compute(km)
        self.assertEqual(first["cache_key"], second["cache_key"])
        self.assertEqual(second["mode"], "cached_wolfram_local")
        self.assertEqual(second["output"]["options"][0]["margin"], 50)
        self.assertEqual(runner.call_count, 1)

    def test_state_revision_budget_reserve_and_geometry_invalidate_cache(self):
        runner = Mock(side_effect=injected_reply); calculator = CostCalculator(runner=runner)
        baseline = calculator.compute(fixture())["cache_key"]
        for field, value in (("state_revision", 1), ("mission_revision", "fixture-2"),
                             ("battery_available", 99), ("return_reserve", 16)):
            data = fixture(); data[field] = value
            self.assertNotEqual(calculator.compute(data)["cache_key"], baseline)
        data = fixture(); data["candidates"][0]["x"] = 41
        self.assertNotEqual(calculator.compute(data)["cache_key"], baseline)
        self.assertEqual(runner.call_count, 6)

    def test_candidate_order_is_canonical(self):
        data = fixture(); data["candidates"].append(dict(asset_id="P02", view_id="overview", x=30, y=0))
        runner = Mock(side_effect=injected_reply); calculator = CostCalculator(runner=runner)
        first = calculator.compute(data); data["candidates"].reverse()
        self.assertEqual(calculator.compute(data)["cache_key"], first["cache_key"])
        self.assertEqual(runner.call_count, 1)

    def test_transport_failure_falls_back_once_without_cache(self):
        for code in ("timeout", "quota", "access_denied", "runtime_missing"):
            runner = Mock(side_effect=ComputationUnavailable(code, "Injected transport failure"))
            calculator = CostCalculator(runner=runner)
            result = calculator.compute(fixture())
            self.assertEqual(result["mode"], "local_python_fallback")
            self.assertEqual(result["failure"]["code"], code)
            self.assertEqual(result["output"]["options"][0]["margin"], 50)
            self.assertTrue(result["execution_permitted"])
            self.assertEqual(runner.call_count, 1)
            self.assertEqual(calculator.cache, {})
            self.assertEqual(result["request_counts"]["cloud_requests"], 0)

    def test_invalid_responses_fall_back(self):
        for variant in ("missing", "nan", "identity", "boolean_revision", "duplicate", "unknown"):
            reply = injected_reply(fixture())
            if variant == "missing": reply.pop("options")
            if variant == "nan": reply["options"][0]["margin"] = math.nan
            if variant == "identity": reply["mission_id"] = "other"
            if variant == "boolean_revision": reply["state_revision"] = False
            if variant == "duplicate": reply["options"] *= 2
            if variant == "unknown": reply["options"][0]["asset_id"] = "other"
            with self.subTest(variant=variant):
                result = CostCalculator(runner=lambda _: reply).compute(fixture())
                self.assertEqual(result["mode"], "local_python_fallback")

    def test_material_mismatch_blocks_and_is_not_cached(self):
        def mismatch(data):
            reply = injected_reply(data); reply["options"][0]["margin"] += 1
            return reply
        calculator = CostCalculator(runner=mismatch)
        result = calculator.compute(fixture())
        self.assertEqual(result["mode"], "wolfram_disagreement")
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(calculator.cache, {})

    def test_tolerance_never_relaxes_feasibility_sign(self):
        def near_boundary(data):
            reply = injected_reply(data); reply["options"][0].update(margin=-1e-12, feasible=False)
            return reply
        data = fixture(); data["battery_available"] = 50
        result = CostCalculator(runner=near_boundary).compute(data)
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(result["disagreements"][0]["field"], "feasible")

    def test_compute_is_read_only_and_keeps_action_rules(self):
        state = initial_state(self.mission); before = state.snapshot()
        result = compute_mission_options(self.mission, state, CostCalculator(runner=injected_reply))
        checks = {(i["asset_id"], i["view_id"]): i for i in result["action_checks"]}
        self.assertEqual(checks["P01", "overview"]["code"], "duplicate_view")
        self.assertEqual(checks["P06", "overview"]["code"], "asset_excluded")
        self.assertEqual(checks["P03", "follow-up"]["code"], "prior_view_required")
        self.assertEqual(state.snapshot(), before)
        self.assertFalse(result["state_transition_applied"])

    def test_contradictory_near_zero_margin_blocks_even_if_boolean_matches(self):
        def contradictory(data):
            reply = injected_reply(data); reply["options"][0]["margin"] = -1e-12
            return reply
        data = fixture(); data["battery_available"] = 50
        result = CostCalculator(runner=contradictory).compute(data)
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(result["disagreements"][0]["field"], "margin_sign")

    def test_mismatch_blocks_execution_without_state_or_capture(self):
        state = initial_state(self.mission)
        def mismatch(data):
            reply = injected_reply(data); reply["options"][0]["outbound"] += 1
            return reply
        with patch("stratus.inspection.computation.execute_action") as commit:
            updated, event = execute_computed_action(self.mission, state,
                Proposal("inspect", "P03", "overview", "Review", "Return"), CostCalculator(runner=mismatch))
            commit.assert_not_called()
        self.assertIs(updated, state)
        self.assertEqual(event["code"], "numerical_disagreement")

    def test_success_and_fallback_preserve_debit_and_duplicate_rules(self):
        state = initial_state(self.mission)
        proposal = Proposal("inspect", "P03", "overview", "Review", "Return")
        reference, _ = execute_action(self.mission, state, proposal)
        for runner in (injected_reply, Mock(side_effect=ComputationUnavailable("timeout", "Injected"))):
            updated, event = execute_computed_action(self.mission, state, proposal, CostCalculator(runner=runner))
            self.assertEqual(updated.battery_available, reference.battery_available)
            self.assertEqual(updated.actions_remaining, 2)
            again, duplicate = execute_computed_action(self.mission, updated, proposal, CostCalculator(runner=runner))
            self.assertIs(again, updated)
            self.assertEqual(duplicate["status"], "rejected")

    def test_exhausted_action_cap_cannot_be_overridden(self):
        state = replace(initial_state(self.mission), actions_used=3, actions_remaining=0)
        runner = Mock(side_effect=injected_reply)
        updated, event = execute_computed_action(self.mission, state,
            Proposal("inspect", "P03", "overview", "Review", "Return"), CostCalculator(runner=runner))
        self.assertIs(updated, state)
        self.assertEqual(event["decision"]["code"], "actions_exhausted")
        runner.assert_not_called()

    def test_python_mode_never_launches_wolfram(self):
        runner = Mock(); result = CostCalculator("local", runner).compute(fixture())
        self.assertEqual(result["mode"], "local_python"); runner.assert_not_called()

    def test_actual_process_timeout_is_bounded_and_labeled(self):
        runner = LocalWolfram(executable=__file__, timeout=1)
        with patch("stratus.inspection.computation.subprocess.run", side_effect=subprocess.TimeoutExpired("injected", 1)) as run:
            with self.assertRaises(ComputationUnavailable) as failure: runner(normalize_input(fixture()))
            self.assertEqual(failure.exception.code, "timeout")
            self.assertEqual(run.call_args.kwargs["timeout"], 1)
            self.assertNotIn("-code", run.call_args.args[0])

    def test_separate_script_launcher_discovers_installed_kernel(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            installed = base / "Wolfram Research/Wolfram/15.0"
            installed.mkdir(parents=True)
            kernel = installed / "WolframKernel.exe"; kernel.write_bytes(b"")
            launcher = base / "Wolfram Research/WolframScript/wolframscript.exe"
            launcher.parent.mkdir(parents=True); launcher.write_bytes(b"")
            with patch.dict(os.environ, {"ProgramFiles": str(base)}, clear=True):
                runner = LocalWolfram(executable=str(launcher))
            self.assertEqual(runner.kernel, str(kernel))


if __name__ == "__main__": unittest.main()
