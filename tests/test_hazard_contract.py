import copy
import threading
import tempfile
import unittest
from pathlib import Path

from stratus.hazards.core import CONTRACT
from stratus.hazards.fixtures import crane_event
from stratus.hazards.harness import FixtureFleetHost
from stratus.inspection.computation import CostCalculator, ComputationUnavailable, python_costs
from stratus.hazards.fleet_adapter import assess_fleet_path, fleet_path, fleet_registry
from stratus.hazards.core import HazardRegistry
from stratus.hazards.preview import FixturePreview, report_html, mount_routes


class HostContractTests(unittest.TestCase):
    def test_real_part12_contract_empty_and_blocked_registry(self):
        from stratus.hazards.fixtures import path
        registry = HazardRegistry()
        self.assertEqual(assess_fleet_path(fleet_path(path()), fleet_registry(registry))["state"], "clear")
        registry.apply(crane_event())
        result = assess_fleet_path(fleet_path(path(hazard_revision=1)), fleet_registry(registry))
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["checked_revision"], 1)

    def test_part12_contract_unknown_frame_and_forged_history_rejected(self):
        from stratus.hazards.fixtures import path
        registry = HazardRegistry()
        registry.apply(crane_event())
        external = fleet_registry(registry)
        external["hazards"][0]["state"] = "cleared"
        self.assertEqual(assess_fleet_path(fleet_path(path(hazard_revision=1)), external)["state"], "review_required")
        external = fleet_registry(registry)
        proposed = fleet_path(path(hazard_revision=1))
        proposed["coordinate_frame"]["name"] = "unknown-geographic-frame"
        self.assertEqual(assess_fleet_path(proposed, external)["state"], "review_required")

    def test_current_proposal_commits_once(self):
        h = FixtureFleetHost()
        h.prepare("D001")
        first = h.execute("D001", "capture-1")
        fingerprint = h.fingerprint()
        self.assertEqual(first["status"], "executed")
        self.assertEqual(h.execute("D001", "capture-1"), first)
        self.assertEqual(h.fingerprint(), fingerprint)

    def test_report_between_prepare_and_commit_rejects_without_debit(self):
        h = FixtureFleetHost()
        h.prepare("D001")
        before = [(d["battery"], d["actions_used"], d["position"]) for d in h.drones.values()]
        h.report()
        r = h.execute("D001", "stale-capture")
        after = [(d["battery"], d["actions_used"], d["position"]) for d in h.drones.values()]
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(before, after)
        self.assertEqual(h.receipts, {})

    def test_reallocation_passes_hazard_and_budget_gates(self):
        h = FixtureFleetHost()
        h.report()
        changes = h.replan()
        self.assertEqual(len(changes), 2)
        h.prepare("D001")
        r = h.execute("D001", "replanned-1")
        self.assertEqual(r["status"], "executed")
        self.assertEqual(r["hazard_assessment"]["state"], "clear")
        self.assertEqual(h.drones["D002"]["battery"], 100)

    def test_fifty_impact_unaffected_work_continues(self):
        h = FixtureFleetHost(50)
        impact = h.report()
        self.assertEqual((impact["assessed_count"], impact["affected_count"]), (50, 2))
        self.assertEqual(h.drones["D001"]["status"], "held")
        h.prepare("D050")
        self.assertEqual(h.execute("D050", "unaffected-50")["status"], "executed")
        self.assertEqual(h.drones["D001"]["actions_used"], 0)

    def test_in_progress_is_paused_for_review_without_teleport(self):
        h = FixtureFleetHost()
        h.drones["D001"]["in_progress"] = True
        before = copy.deepcopy(h.drones["D001"]["position"])
        h.report()
        self.assertEqual(h.drones["D001"]["status"], "review_required")
        self.assertEqual(h.drones["D001"]["position"], before)
        self.assertNotIn("D001", [x["drone_id"] for x in h.replan()])

    def test_save_reopen_fifty_with_active_hazard(self):
        h = FixtureFleetHost(50)
        h.report()
        h.replan()
        h.prepare("D001")
        h.execute("D001", "once")
        before = h.snapshot()
        restored = FixtureFleetHost.restore(before)
        self.assertEqual(before, restored.snapshot())
        self.assertEqual(h.fingerprint(), restored.fingerprint())
        self.assertEqual(restored.bridge.registry.revision, 1)

    def test_tampered_budget_save_rejected(self):
        saved = FixtureFleetHost().snapshot()
        saved["drones"]["D001"]["battery"] = 99
        with self.assertRaises(ValueError):
            FixtureFleetHost.restore(saved)

    def test_old_run_extension_can_be_empty(self):
        h = FixtureFleetHost()
        h.bridge.restore(None)
        self.assertEqual(h.bridge.registry.revision, 0)

    def test_delayed_clear_or_amend_invalidates_old_result(self):
        h = FixtureFleetHost()
        h.report()
        h.replan()
        h.prepare("D001")
        h.report(crane_event(1, action="clear", effective=2, source="operator_report", notes="Explicit operator clearance"))
        self.assertEqual(h.execute("D001", "late")["status"], "rejected")

    def test_numerical_mismatch_does_not_override_hazard(self):
        def mismatch(data):
            out = python_costs(data)
            out.update(wolfram_version="injected-test-double", system_id="mock-not-a-live-runtime")
            out["options"][0]["outbound"] += 100
            return out
        h = FixtureFleetHost(calculator=CostCalculator("wolfram", runner=mismatch))
        h.prepare("D001")
        self.assertEqual(h.execute("D001", "bad")["status"], "rejected")
        self.assertEqual(h.drones["D001"]["battery"], 100)

    def test_timeout_fallback_still_checks_hazard(self):
        def fail(_):
            raise ComputationUnavailable("timeout", "Injected transport timeout")
        h = FixtureFleetHost(calculator=CostCalculator("wolfram", runner=fail))
        h.report()
        p = h.prepare("D001")
        self.assertEqual(p["numerical"]["mode"], "local_python_fallback")
        self.assertEqual(h.execute("D001", "blocked")["code"], "reported_hazard")

    def test_forged_numerical_input_rejected(self):
        h = FixtureFleetHost()
        h.prepare("D001")
        h.proposals["D001"]["numerical"]["normalized_input"]["battery_available"] = 999
        self.assertEqual(h.execute("D001", "forged")["status"], "rejected")

    def test_two_simultaneous_commits_cannot_both_spend_same_revision(self):
        h = FixtureFleetHost()
        h.prepare("D001")
        results = []
        barrier = threading.Barrier(3)
        def execute(i):
            barrier.wait()
            results.append(h.execute("D001", f"parallel-{i}"))
        threads = [threading.Thread(target=execute, args=(i,)) for i in range(2)]
        for t in threads: t.start()
        barrier.wait()
        for t in threads: t.join(timeout=5)
        self.assertEqual(sum(r["status"] == "executed" for r in results), 1)
        self.assertEqual(h.drones["D001"]["actions_used"], 1)

    def test_independent_objects_and_ground_loss(self):
        h = FixtureFleetHost(50)
        h.report()
        h.ground = {"source_label": "Unavailable", "observed_at_utc": None}
        h.drones["D050"]["battery"] = 90
        self.assertEqual(h.drones["D001"]["battery"], 100)
        self.assertEqual(h.bridge.registry.revision, 1)

    def test_future_task_claim_must_match_current_assignment(self):
        h = FixtureFleetHost()
        h.prepare("D001")
        h.proposals["D001"]["path"]["task_id"] = h.drones["D002"]["task_id"]
        self.assertEqual(h.execute("D001", "wrong-owner")["status"], "rejected")


class PreviewControllerTests(unittest.TestCase):
    def test_direct_controller_prepare_report_reject_replan_reopen(self):
        with tempfile.TemporaryDirectory(prefix="stratus-hazard-test-") as directory:
            preview = FixturePreview(Path(directory))
            preview.dispatch("prepare", {"drone_id": "D001"})
            preview.dispatch("report-example", {})
            result = preview.dispatch("execute", {"drone_id": "D001"})
            self.assertIn("REJECTED", result["message"])
            preview.dispatch("replan", {})
            preview.dispatch("prepare", {"drone_id": "D001"})
            result = preview.dispatch("execute", {"drone_id": "D001"})
            self.assertIn("EXECUTED", result["message"])
            saved = preview.dispatch("save", {})
            reopened = preview.dispatch("reopen", {"name": saved["saved_name"]})
            self.assertEqual(saved["state"], reopened["state"])

    def test_invalid_operator_rectangle_does_not_replace_registry(self):
        with tempfile.TemporaryDirectory(prefix="stratus-hazard-test-") as directory:
            preview = FixturePreview(Path(directory))
            with self.assertRaises(ValueError):
                preview.dispatch("operator-report", {"rectangle": {}, "notes": "Bad input"})
            self.assertEqual(preview.host.bridge.registry.revision, 0)
            with self.assertRaises(ValueError):
                preview.dispatch("reopen", {"name": "../first-inspection.json"})

    def test_report_html_escapes_operator_notes(self):
        host = FixtureFleetHost()
        event = crane_event(notes='<img src=x onerror="bad()">')
        host.report(event)
        document = report_html(host.snapshot())
        self.assertNotIn('<img src=x', document)
        self.assertIn('&lt;img', document)
        self.assertIn('Part 12 fleet integration has not run', document)

    def test_route_origin_rejection_without_opening_a_socket(self):
        class Base:
            def send(self, value, status=200, **kwargs): self.result = (status, value)
        class Server:
            RequestHandlerClass = Base
        server = mount_routes(Server(), lambda name, data: self.fail("Foreign request reached dispatcher"))
        handler = server.RequestHandlerClass()
        handler.path = "/api/hazards/clear"
        handler.headers = {"Host": "127.0.0.1:8773", "Origin": "https://unrelated.example"}
        handler.server = type("Server", (), {"server_port": 8773})()
        handler.do_POST()
        self.assertEqual(handler.result[0], 403)


if __name__ == "__main__":
    unittest.main()
