"""Reproducible hazard-only evidence. Fixture checks never claim Part 12 integration."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.hazards.core import CONTRACT, HazardRegistry, assess_path
from stratus.hazards.fixtures import crane_event, fleet_paths, return_only
from stratus.hazards.harness import FixtureFleetHost
from stratus.hazards.preview import report_html
from stratus.inspection.computation import CostCalculator

FOLDER = ROOT / "docs/evidence/inspection-0.0.2/part13"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def resources(host):
    return {i: {k: deepcopy(d[k]) for k in ("battery", "actions_used", "actions_remaining", "position")} for i, d in host.drones.items()}


def run_fixture(size, report=True):
    host = FixtureFleetHost(size)
    before = resources(host)
    old = [host.prepare(i) for i in ("D001", "D002")]
    impact = host.report() if report else None
    rejected = [host.execute(i, "before-replan-" + i) for i in ("D001", "D002")]
    if report:
        assert all(x["status"] == "rejected" for x in rejected)
        assert before == resources(host)
    changes = host.replan() if report else []
    executed = []
    for i in ("D001", "D002"):
        host.prepare(i)
        # No-report branch already committed these tasks above.
        result = host.execute(i, "after-replan-" + i)
        if report:
            assert result["status"] == "executed", result
        executed.append(result)
    if size == 50:
        host.prepare("D050")
        unaffected = host.execute("D050", "unaffected-D050")
        assert unaffected["status"] == "executed"
    else:
        unaffected = None
    saved = host.snapshot()
    restored = FixtureFleetHost.restore(saved)
    assert restored.snapshot() == saved
    assert restored.fingerprint() == host.fingerprint()
    name = f"fixture-{size}-{'reported' if report else 'no-report'}"
    write(FOLDER / (name + ".json"), {"mode": host.mode, "part12_joined": False,
          "initial_resources": before, "old_proposals": old, "impact": impact,
          "pre_replan_attempts": rejected, "reassignments": changes, "post_replan_attempts": executed,
          "unaffected_example": unaffected, "saved_state": saved, "exact_reopen": True,
          "comparison_limit": "No-report toy crossings are not predicted real collisions"})
    (FOLDER / (name + ".html")).write_text(report_html(saved), encoding="utf-8")
    return {"size": size, "mode": host.mode, "part12_joined": False,
            "report_present": report, "assessed": impact["assessed_count"] if impact else 0,
            "affected": impact["affected_count"] if impact else 0,
            "assessment_seconds": impact["duration_seconds"] if impact else None,
            "stale_rejections": sum(x["status"] == "rejected" for x in rejected) if report else 0,
            "reassigned": len(changes), "executed_receipts": len(host.receipts), "exact_reopen": True}


def live_wolfram():
    calculator = CostCalculator("wolfram")
    host = FixtureFleetHost(2, calculator=calculator)
    before = host.prepare("D001")
    host.report()
    rejected = host.execute("D001", "live-stale")
    assert rejected["status"] == "rejected"
    host.replan()
    after = host.prepare("D001")
    result = host.execute("D001", "live-replanned")
    assert result["status"] == "executed", result
    fifty = FixtureFleetHost(50, calculator=calculator)
    impact = fifty.report()
    selected = fifty.prepare("D050")
    fifty_result = fifty.execute("D050", "live-unaffected")
    assert fifty_result["status"] == "executed", fifty_result
    proposals = [before, after, selected]
    passed = all(p["numerical"]["mode"] in ("wolfram_local", "cached_wolfram_local") for p in proposals)
    evidence = {"status": "passed" if passed else "local fallback; live checks incomplete",
                "host_mode": host.mode, "part12_joined": False,
                "scope": "Three selected single-drone numerical batches inside explicit 2/50 fixture hosts; not the Part 12 fleet batch",
                "before_report": before, "stale_rejection": rejected, "after_replan": after,
                "replanned_receipt": result, "fifty_record_impact": impact,
                "fifty_selected_numerical": selected, "fifty_selected_receipt": fifty_result,
                "request_counts": {"local_kernel_calls": calculator.local_kernel_calls, "cloud_requests": 0, "alpha_calls": 0},
                "cloud_service_credit_consumption": "Not inferred; no account usage fetched"}
    write(FOLDER / "wolfram-evidence.json", evidence)
    return {k: evidence[k] for k in ("status", "scope", "request_counts")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wolfram", action="store_true")
    args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    protected = list((ROOT / "stratus/inspection").glob("*.py")) + list((ROOT / "stratus/inspection/missions").glob("*.json"))
    digest = lambda: {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    before = digest()
    with (FOLDER / "hazard-tests.txt").open("w", encoding="utf-8") as stream:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_hazard*.py")
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("Hazard tests failed; inspect hazard-tests.txt")
    ui = subprocess.run(["node", "--test", "tests/frontend_hazards.test.cjs", "tests/frontend_clarity.test.cjs", "tests/frontend_races.test.cjs"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    (FOLDER / "frontend-tests.txt").write_text(ui.stdout + ui.stderr, encoding="utf-8")
    if ui.returncode:
        raise SystemExit("Frontend checks failed")
    fixtures = []
    for size in (2, 50):
        write(ROOT / f"context/hazards/crane-{size}-v1.json", {"schema_version": CONTRACT,
              "source": "newly authored synthetic contract fixture", "paths": fleet_paths(size), "event": crane_event()})
        for reported in (False, True):
            fixtures.append(run_fixture(size, reported))
    registry = HazardRegistry()
    registry.apply(crane_event())
    return_check = assess_path(return_only(1), registry)
    assert return_check["state"] == "blocked" and [x["leg"] for x in return_check["intersections"]] == ["return"]
    write(FOLDER / "blocked-return.json", return_check)
    if args.wolfram:
        numerical = live_wolfram()
    elif (FOLDER / "wolfram-evidence.json").is_file():
        prior = json.loads((FOLDER / "wolfram-evidence.json").read_text(encoding="utf-8"))
        numerical = {k: prior[k] for k in ("status", "scope", "request_counts")}
        numerical["record_kind"] = "Previously captured actual calls in this task; not repeated in this verification"
    else:
        numerical = {"status": "not run; explicit local-only verification"}
    after = digest()
    assert before == after, "An existing protected source changed during verification"
    summary = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "contract": CONTRACT,
               "hazard_tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)},
               "frontend_check_exit_code": ui.returncode, "fixtures": fixtures, "blocked_return": return_check,
               "wolfram": numerical, "protected_source_sha256": after, "protected_sources_unchanged": True,
               "part12_modules_available": (ROOT / "stratus/fleet").is_dir(),
               "part12_joined_app_verified": False,
               "browser_preview_verified": False,
               "network_test_blocker": "Windows socket PermissionError WinError 10013; localhost preview unreachable in both browsers",
               "existing_suite_observation": {"run": 242, "errors": 10, "failures": 0,
                   "note": "Earlier full-suite invocation: ten existing HTTP tests failed on blocked socket connections; not counted as passing"},
               "claim": "Independent hazard module and explicit fixture host only; joined fleet acceptance remains pending"}
    write(FOLDER / "verification.json", summary)
    write(FOLDER / "source-checksums.json", {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in list((ROOT / "stratus/hazards").glob("*.py")) + list((ROOT / "stratus/inspection/web").glob("hazards.*"))})
    print(json.dumps({"hazard_tests": summary["hazard_tests"], "fixtures": fixtures, "wolfram": numerical,
                      "part12_joined_app_verified": False}, indent=2), flush=True)


if __name__ == "__main__":
    main()
