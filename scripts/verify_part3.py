"""Save Part 3 observations; a mocked provider never counts as live evidence."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.actions import Proposal  # noqa: E402
from stratus.inspection.agent import run_agent  # noqa: E402
from stratus.inspection.engine import evaluate, execute_action, initial_state, plain  # noqa: E402
from stratus.inspection.loader import DEFAULT_MISSION, freeze, load_mission  # noqa: E402


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Attempt at most two bounded API requests using configured credentials")
    args = parser.parse_args()
    output = ROOT / "docs/evidence/inspection-0.0.1/part3"
    output.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / DEFAULT_MISSION, *sorted((ROOT / "evidence/inspection").rglob("*.json")),
             *sorted((ROOT / "evidence/inspection/images").glob("*.png"))]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    existing_runs = {p.name: p.read_bytes() for p in (ROOT / "saved-runs").glob("*.json")}
    tests = subprocess.run([sys.executable, "-B", "-S", "-m", "unittest", "discover", "-s", "tests", "-v"],
                           cwd=ROOT, capture_output=True, text=True, timeout=45)
    (output / "tests.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests?", tests.stderr)
    if tests.returncode or not match:
        raise RuntimeError("Part 3 tests did not pass; see tests.txt")
    mission = load_mission()
    state = initial_state(mission)
    initial_snapshot = state.snapshot()
    fallback = run_agent(mission, state, mode="fallback")
    save(output / "fallback-proposal.json", fallback)
    rejected = evaluate(mission, state, Proposal("inspect", "P06", "overview", "Test excluded panel", "Return"))
    save(output / "rejected-proposal.json", {"decision": rejected.to_dict(), "state_before": initial_snapshot,
                                            "state_after": state.snapshot(), "state_transition_applied": False})
    doc = plain(mission.document)
    doc["assets"][2]["position"] = {"x": 40, "y": 0}
    doc["initial_state"]["position"] = {"x": 20, "y": 0}
    toy = replace(mission, document=freeze(doc))
    boundaries = []
    for available in (100, 50, 49):
        decision = evaluate(toy, replace(initial_state(toy), battery_available=available),
                            Proposal("inspect", "P03", "overview", "Toy boundary verification", "Return or stop"))
        boundaries.append({"available": available, "decision": decision.to_dict()})
    assert [r["decision"]["costs"]["margin"] for r in boundaries] == [50, 0, -1]
    assert [r["decision"]["allowed"] for r in boundaries] == [True, True, False]
    save(output / "reserve-boundaries.json", {"scope": "authored toy verification case, not the frozen site's geometry",
                                              "outbound": 10, "capture": 5, "return": 20, "reserve": 15,
                                              "cases": boundaries})
    check_state, events = initial_state(mission), []
    for _ in range(4):
        choice = run_agent(mission, check_state, mode="fallback")
        check_state, event = execute_action(mission, check_state, choice["proposal"])
        assert event["status"] == "executed"
        events.append(event)
    assert check_state.actions_used == 3 and check_state.actions_remaining == 0
    assert check_state.status == "returned" and check_state.battery_available >= 15
    save(output / "local-execution-check.json", {
        "scope": "in-memory verification only; not a Part 4 saved inspection run",
        "execution_mode": "deterministic_rule_based", "events": events,
        "state_after": check_state.snapshot(), "real_flight": False,
    })
    sensor_path = ROOT / "context/sensor-decision.json"
    if not sensor_path.exists():
        recorded = datetime.now(timezone.utc)
        save(sensor_path, {
            "recorded_at_utc": recorded.isoformat(), "decision": "skipped",
            "source_mode": "operator_scope_decision_no_measurement",
            "scheduled_cutoff": "2026-11-13T22:00:00-05:00",
            "recorded_after_cutoff": recorded > datetime(2026, 11, 14, 3, tzinfo=timezone.utc),
            "reason": "Optional sensor acquisition is outside the critical path; apply the passed cutoff and continue with local inspection fixtures.",
            "hardware_attempted_in_this_part": False,
            "electrical_or_driver_compatibility": "not_checked; no live-hardware compatibility claim",
            "measurement_timestamp": None, "measurements": [], "units": None,
            "ground_context_effect_on_aircraft_state": False,
            "timing_note": "Decision recorded during Part 3 implementation after the scheduled cutoff; no on-time completion is claimed.",
        })
    live = {"execution_mode": "not_attempted", "failure": {"code": "live_check_not_requested", "message": "Run with --live to attempt configured service"}}
    if args.live:
        live = run_agent(mission, state, mode="live")
        save(output / "ai-live-check.json", {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
                                            "scope": "actual configured provider request; no action execution",
                                            "result": live})
    assert state.snapshot() == initial_snapshot
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in before.items())
    assert existing_runs == {p.name: p.read_bytes() for p in (ROOT / "saved-runs").glob("*.json")}
    live_verified = (live["execution_mode"] == "live_ai" and live.get("failure") is None
                     and len(live.get("response_events", [])) == 2 and live["validation"]["allowed"])
    complete = [f"S{i:03d}" for i in (21, 22, 23, 24, 25, 27, 28, 29, 30)]
    if live_verified:
        complete.extend(("S026", "S031"))
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(), "workspace": str(ROOT),
        "python": sys.version.split()[0], "behavior_tests": int(match[1]), "test_exit_code": tests.returncode,
        "local_implementation_checks": "passed", "part3_gate": "passed" if live_verified else "blocked_live_service",
        "completed_actions": sorted(complete), "completed_count": len(complete), "part3_total_actions": 11,
        "pending_actions": [] if live_verified else ["S026", "S031"],
        "live_ai_attempted": args.live, "live_ai_verified": live_verified,
        "live_ai_failure": live.get("failure"), "unit_test_provider_calls": "mocked; never counted as live AI",
        "toy_reserve_margins": [50, 0, -1], "toy_capture_allowed": [True, True, False],
        "fallback_mode": fallback["execution_mode"], "fallback_proposal": fallback["proposal"],
        "input_and_image_hashes_unchanged": True, "failed_or_proposed_actions_preserve_state": True,
        "new_saved_inspection_runs": 0, "live_vision": "not implemented; authored synthetic replay is explicit",
        "sensor_decision": json.loads(sensor_path.read_text(encoding="utf-8")),
        "next_step": "Proceed to Part 4" if live_verified else "Resolve the recorded live-service failure and rerun python -B scripts/verify_part3.py --live",
    }
    save(output / "verification.json", report)
    sources = [p for folder in ("stratus", "scripts", "tests", "evidence/inspection", "context")
               for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    (output / "checksums.sha256").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}\n"
        for path in sorted(sources)), encoding="utf-8")
    print(json.dumps({"tests": int(match[1]), "local_checks": "passed", "gate": report["part3_gate"],
                      "part3_verified": f"{len(complete)}/11", "live_ai_failure": live.get("failure")}, indent=2))
    return 0 if live_verified or not args.live else 4


if __name__ == "__main__":
    raise SystemExit(main())
