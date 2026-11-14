"""Verify the standalone Part 1 startup and save actual setup observations."""

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    evidence = project / "docs/evidence/inspection-0.0.1/part1"
    evidence.mkdir(parents=True, exist_ok=True)
    mission_path = project / "stratus/inspection/missions/solar-array-001.json"
    before = mission_path.read_bytes()
    mission = json.loads(before)
    assets = mission["assets"]
    assert len(assets) == len({a["asset_id"] for a in assets}) == 6
    assert mission["coordinate_frame"]["unit"] == "m"
    assert all(a["eligibility"]["reviewed"] for a in assets)
    assert sum(a["eligibility"]["state"] == "excluded" for a in assets) == 1
    assert all(a["priority"] in (1, 2, 3) for a in assets)
    assert all(math.isfinite(a["position"][axis]) for a in assets for axis in ("x", "y"))
    records = mission["prior_records"]
    assert len(records) == 2 and all(not r["consumes_new_action"] for r in records)
    assert all(r["asset_id"] in {a["asset_id"] for a in assets} for r in records)
    assert all(
        r["evidence_ref"] is None and r["evidence_status"] == "pending_part_2" for r in records
    )
    assert mission["initial_state"]["actions_remaining"] == 3
    assert mission["initial_state"]["actions_used"] == 0
    assert mission["energy_model"]["return_reserve"] == 15
    assert mission["initial_state"]["battery_available"] == 100

    run = subprocess.run(
        [sys.executable, "-B", "-S", "-m", "stratus.inspection"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0, run.stderr
    assert "Evidence: pending Part 2" in run.stdout
    assert "3 remaining / 3 maximum" in run.stdout
    assert mission_path.read_bytes() == before
    assert not list((project / "saved-runs").glob("*.json"))
    (evidence / "startup.txt").write_text(run.stdout, encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="stratus-part1-check-") as temporary:
        scratch = Path(temporary)
        bad_path = scratch / "invalid.json"
        bad_path.write_text("{", encoding="utf-8")
        results = []
        for path in (bad_path, scratch / "missing.json"):
            result = subprocess.run(
                [sys.executable, "-B", "-m", "stratus.inspection", "--mission", str(path)],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert result.returncode == 2
            assert "Cannot preview mission skeleton" in result.stderr
            assert "Traceback" not in result.stderr
            results.append(result.returncode)

        # Check ignore rules in a new throwaway repository; no prior project is required.
        subprocess.run(["git", "init", "--quiet", str(scratch)], check=True, timeout=20)
        (scratch / ".gitignore").write_bytes((project / ".gitignore").read_bytes())
        (scratch / "saved-runs").mkdir()
        (scratch / "saved-runs/.gitignore").write_bytes(
            (project / "saved-runs/.gitignore").read_bytes()
        )
        ignored = [".env", ".env.local", ".venv/pyvenv.cfg", "saved-runs/private-run.json"]
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", *ignored, ".env.example"],
            cwd=scratch,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0 and set(result.stdout.splitlines()) == set(ignored)

    assert "STRATUS_AI_API_KEY=replace_with_your_own_key" in (project / ".env.example").read_text()
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace_checked": str(project),
        "intended_workspace": "C:\\Users\\shill\\OneDrive\\Desktop\\STRATUS",
        "migration_status": "destination_write_denied; standalone copy staged",
        "python": sys.version.split()[0],
        "standard_library_only_launch_verified": True,
        "startup_exit_code": run.returncode,
        "mission_sanity_checks": "6 reviewed unique panels, metres, 2 historical placeholders, 3 new actions, explicit energy and reserve",
        "mission_unchanged_after_launch": True,
        "saved_inspection_runs_created": 0,
        "malformed_json_and_missing_file_exit_codes": results,
        "fresh_credential_and_output_ignore_rules": "passed",
        "prior_project_code_or_environment_required": False,
        "full_mission_validation_and_evidence_capture": "pending Part 2",
    }
    (evidence / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    paths = [
        p
        for p in project.rglob("*")
        if p.is_file()
        and ".venv" not in p.parts
        and "__pycache__" not in p.parts
        and p.name != "checksums.sha256"
    ]
    (evidence / "checksums.sha256").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(project).as_posix()}\n"
            for p in sorted(paths)
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
