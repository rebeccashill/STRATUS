"""Save S032-S036 observations; no saved-run/resume or live-vision claim."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.computation import CostCalculator
from stratus.inspection.loader import load_mission
from stratus.inspection.review import InspectionSession


def save(folder, name, value):
    (folder / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def protected_files():
    paths = [*(ROOT / "stratus/inspection/missions").rglob("*"), *(ROOT / "evidence").rglob("*"),
             *(ROOT / "context").rglob("*"), *(ROOT / "saved-runs").rglob("*")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def proposal(asset, view="overview"):
    return dict(action_type="inspect" if view == "overview" else "follow_up", asset_id=asset,
                view_id=view, reason="State/review verification", alternative="Return or stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wolfram", action="store_true", help="Require one actual local Wolfram computation during execution")
    args = parser.parse_args()
    folder = ROOT / "docs/evidence/inspection-0.0.1/state-review"
    folder.mkdir(parents=True, exist_ok=True)
    before = protected_files()
    tests = subprocess.run([sys.executable, "-B", "-S", "-m", "unittest", "discover", "-s", "tests", "-v"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
    (folder / "tests.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests?", tests.stderr)
    if tests.returncode or not match: raise RuntimeError("Tests failed; see state-review/tests.txt")
    mission = load_mission(); run = InspectionSession(mission)
    initial = run.snapshot(); save(folder, "initial-run.json", initial)
    assert initial["aircraft_state"]["battery_available"] == 100
    assert initial["aircraft_state"]["actions_remaining"] == 3
    assert len(initial["aircraft_state"]["history"]) == 2
    calculator = CostCalculator("wolfram" if args.wolfram else "local")
    first = run.execute(proposal("P03"), request_id="first-inspection", expected_revision=0, calculator=calculator)
    after = run.snapshot()
    save(folder, "first-inspection.json", dict(before=initial, event=first, after=after))
    assert first["status"] == "executed" and after["aircraft_state"]["actions_remaining"] == 2
    assert len(after["review_queue"]) == 3 and first["assessment"]["finding"] == "apparent_concern_review_required"
    assert after["ground_context"] == initial["ground_context"]
    if args.wolfram and first["computation"]["mode"] != "wolfram_local":
        raise RuntimeError("Actual Wolfram execution not achieved; inspect first-inspection.json for the fallback/blocker")
    replay = run.execute(proposal("P03"), request_id="first-inspection", expected_revision=0, calculator=calculator)
    assert run.snapshot() == after and replay["status"] == "already_processed"
    duplicate = run.execute(proposal("P03"), request_id="different-request-same-view", expected_revision=1, calculator=calculator)
    assert duplicate["status"] == "rejected" and run.state.snapshot() == after["aircraft_state"]
    assert len(run.snapshot()["review_queue"]) == 3
    stale = run.execute(proposal("P04"), request_id="stale", expected_revision=0, calculator=calculator)
    conflict = run.execute(proposal("P04"), request_id="first-inspection", expected_revision=0, calculator=calculator)
    save(folder, "idempotence.json", dict(same_request=replay, different_request_same_view=duplicate,
         stale_request=stale, conflicting_request=conflict, aircraft_state_after=run.state.snapshot(),
         assessment_count=len(run.snapshot()["assessments"]), computation_calls=calculator.local_kernel_calls))
    cases = []
    for asset, view in (("P04", "overview"), ("P05", "overview"), ("P02", "follow-up"), ("P06", "overview")):
        example = InspectionSession(mission)
        event = example.execute(proposal(asset, view), request_id="case", expected_revision=0)
        cases.append(dict(asset_id=asset, view_id=view, event=event, after=example.snapshot()))
    save(folder, "replay-review-cases.json", cases)
    assert protected_files() == before
    summary = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(), tests=int(match.group(1)),
        tests_passed=True, state_review_section="5/5", platform=sys.platform,
        initial_battery=100, initial_capture_actions=3, prior_records=2,
        executed_asset_view="P03/overview", battery_after=run.state.battery_available,
        remaining_actions=2, new_assessments=1, assessment_mode="authored_replay_annotation",
        human_review="pending", live_vision="not_run", computation_mode=first["computation"]["mode"],
        model_version=first["computation"]["model_version"], local_kernel_calls=calculator.local_kernel_calls,
        cloud_requests=0, alpha_calls=0, live_ai_requests=0,
        same_request_replay="no additional computation, capture, debit, finding or event",
        concurrent_retries="8 requests; exactly 1 execution in behavior test",
        stale_request=stale["code"], conflicting_request=conflict["code"],
        ground_mode=initial["ground_context"]["mode"], ground_snapshot_unchanged=True,
        ground_location=initial["ground_context"]["location"], protected_files_unchanged=True,
        persistence="not implemented by this section; verification snapshots are not resumable runs",
        idempotency_scope="within one in-memory InspectionSession; no cross-process persistence claim", real_flight=False)
    save(folder, "verification.json", summary)
    source_paths = [ROOT / p for p in ("stratus/inspection/review.py", "stratus/inspection/__main__.py",
                                      "tests/test_review.py", "scripts/verify_state_review.py")]
    save(folder, "checksums.json", {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in source_paths + sorted(folder.glob("*.json")) + [folder / "tests.txt"]
                                   if p.name != "checksums.json"})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
