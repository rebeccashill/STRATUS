"""Verify the local Wolfram adapter and save actual input/output separately from injected tests."""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.computation import (CONTRACT, MODEL, CostCalculator, LocalWolfram,
    compute_mission_options, mission_input)
from stratus.inspection.engine import initial_state
from stratus.inspection.loader import load_mission


def save(folder, name, data):
    (folder / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def protected_files():
    paths = [* (ROOT / "stratus/inspection/missions").rglob("*.json"),
             * (ROOT / "evidence").rglob("*"), * (ROOT / "context").rglob("*"),
             * (ROOT / "saved-runs").rglob("*")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def main():
    output = ROOT / "docs/evidence/inspection-0.0.1/wolfram"
    output.mkdir(parents=True, exist_ok=True)
    before = protected_files()
    tests = subprocess.run([sys.executable, "-B", "-S", "-m", "unittest", "discover", "-s", "tests", "-v"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
    (output / "tests.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests?", tests.stderr)
    if tests.returncode or not match: raise RuntimeError("Tests failed; see tests.txt")
    runtime = LocalWolfram()
    calculator = CostCalculator(runner=runtime)
    mission = load_mission(); state = initial_state(mission); snapshot = state.snapshot()
    result = compute_mission_options(mission, state, calculator)
    save(output, "mission-computation.json", result)
    if result["mode"] != "wolfram_local": raise RuntimeError(f"Actual Wolfram call did not pass: {result['failure'] or result['disagreements']}")
    save(output, "typed-input.json", result["normalized_input"])
    save(output, "typed-output.json", result["wolfram_output"])
    cached = calculator.compute(mission_input(mission, state))
    assert cached["mode"] == "cached_wolfram_local" and calculator.local_kernel_calls == 1
    toy = dict(contract_version=CONTRACT, model_version=MODEL, mission_id="arithmetic-fixture",
        mission_revision="fixture-1", state_revision=0, position=dict(point_id="current", x=20, y=0),
        launch=dict(point_id="launch", x=0, y=0), distance_unit="m", energy_unit="simulated_energy_unit",
        battery_available=100, capture_cost=5, travel_energy_per_distance=0.5, return_reserve=15,
        remaining_actions=3, candidates=[dict(asset_id="P03", view_id="overview", x=40, y=0)])
    cases = []
    for available, expected in ((100, 50), (50, 0), (49, -1)):
        data = copy.deepcopy(toy); data["battery_available"] = available
        measured = calculator.compute(data)
        assert measured["mode"] == "wolfram_local"
        assert measured["output"]["options"][0]["margin"] == expected
        assert measured["output"]["options"][0]["feasible"] == (expected >= 0)
        cases.append(measured)
    exhausted = copy.deepcopy(toy); exhausted["remaining_actions"] = 0
    exhausted_result = calculator.compute(exhausted)
    assert exhausted_result["mode"] == "wolfram_local"
    assert not exhausted_result["output"]["options"][0]["feasible"]
    km = copy.deepcopy(toy); km.update(distance_unit="km", travel_energy_per_distance=500)
    for point in (km["position"], km["launch"], *km["candidates"]): point["x"] /= 1000; point["y"] /= 1000
    equivalent = calculator.compute(km)
    assert equivalent["mode"] == "cached_wolfram_local" and equivalent["cache_key"] == cases[0]["cache_key"]
    save(output, "arithmetic-parity.json", dict(scope="Actual local Wolfram and independent Python; authored toy geometry", cases=cases, exhausted=exhausted_result, kilometre_equivalent=equivalent))
    assert state.snapshot() == snapshot and protected_files() == before
    # Read-only runtime probe; never logs account identity or authenticates to the cloud.
    command = [runtime.executable, "-local"] + ([runtime.kernel] if runtime.kernel else [])
    probe = subprocess.run(command + ["-timeout", "15", "-format", "RawJSON", "-code",
        '<|"version"->$Version,"system_id"->$SystemID,"cloud_connected"->TrueQ[$CloudConnected]|>'],
        capture_output=True, text=True, timeout=25, stdin=subprocess.DEVNULL)
    if probe.returncode: raise RuntimeError("Runtime metadata probe failed")
    metadata = json.loads(probe.stdout)
    resources = dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(), integration_mode="wolfram_local",
        runtime=metadata, cloud_deployed=False, alpha_api_access="unverified",
        resource_pools=[dict(pool="Cloud Credits", balance=175000, verification="user_confirmed", expiry="unknown"),
                        dict(pool="Service Credits", balance=500, verification="user_confirmed", expiry="unknown"),
                        dict(pool="Wolfram Alpha API calls", allocation=6200, verification="previously_reported; current balance not reconfirmed", expiry="unknown")],
        usage_scope="This verification only; no programmatic balance read or account-wide usage inference",
        cloud_requests=0, alpha_calls=0, cloud_or_service_credits_consumed="not inferred from request counts",
        service_backed_ai_entitlement="not assumed", local_runtime_blocker=None)
    save(output, "resource-access.json", resources)
    summary = dict(verified_at_utc=datetime.now(timezone.utc).isoformat(), tests=int(match.group(1)),
        tests_passed=True, actual_local_wolfram_parity="passed", wolfram_section="7/7",
        model_version=MODEL, version=metadata["version"], candidate_batch_size=len(result["output"]["options"]),
        boundary_margins=[50, 0, -1], exhausted_actions_rejected=True, equivalent_units="passed",
        cache_reuse="passed", local_cost_kernel_calls=calculator.local_kernel_calls, metadata_kernel_calls=1,
        cloud_requests=0, alpha_calls=0, max_attempts_per_computation=1, retries=0,
        subprocess_timeout_seconds=runtime.timeout, script_computation_timeout_seconds=5,
        failure_tests="Injected timeout/quota/access/invalid responses and numerical mismatch; not live cloud evidence",
        computation_state_unchanged=True, mission_evidence_ground_data_and_saved_runs_unchanged=True,
        real_flight=False, state_transitions_in_tests="ephemeral only; no new saved inspection run")
    save(output, "verification.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
