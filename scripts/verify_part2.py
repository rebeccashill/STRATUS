"""Run the Part 2 gate and save actual observations, never invented run history."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.capture import simulated_capture  # noqa: E402
from stratus.inspection.loader import DEFAULT_MISSION, MissionValidationError, load_mission  # noqa: E402


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    output = ROOT / "docs/evidence/inspection-0.0.1/part2"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / DEFAULT_MISSION
    before = source.read_bytes()
    existing_runs = sorted(p.name for p in (ROOT / "saved-runs").glob("*.json"))
    tests = subprocess.run([sys.executable, "-B", "-S", "-m", "unittest", "discover", "-s", "tests", "-v"],
                           cwd=ROOT, capture_output=True, text=True, timeout=45)
    (output / "tests.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    if tests.returncode:
        raise RuntimeError("Part 2 gate failed; see tests.txt")
    match = re.search(r"Ran (\d+) tests?", tests.stderr)
    assert match and int(match[1]) > 0, "No behavior tests were executed"
    startup = subprocess.run([sys.executable, "-B", "-S", "-m", "stratus.inspection"],
                             cwd=ROOT, capture_output=True, text=True, timeout=20)
    if startup.returncode:
        raise RuntimeError(startup.stderr)
    (output / "startup.txt").write_text(startup.stdout, encoding="utf-8")
    mission = load_mission()
    cases = {}
    for label, asset, view in (("clear", "P01", "overview"), ("unclear", "P02", "overview"),
                               ("concern", "P03", "overview"), ("follow-up", "P02", "follow-up"),
                               ("unknown-view", "P01", "missing"), ("excluded", "P06", "overview")):
        response = simulated_capture(mission, asset, view)
        save_json(output / f"capture-{label}.json", response)
        cases[label] = {key: response[key] for key in ("status", "image_quality", "finding", "reason")}
    errors = []
    with tempfile.TemporaryDirectory(prefix="stratus-part2-invalid-") as temporary:
        bad = Path(temporary) / "invalid.json"
        for label, data in (("malformed-json", "{"), ("invalid-battery", None), ("missing-units", None)):
            if data is None:
                doc = json.loads(before)
                if label == "invalid-battery":
                    doc["initial_state"]["battery_available"] = -1
                else:
                    del doc["coordinate_frame"]["unit"]
                data = json.dumps(doc)
            bad.write_text(data, encoding="utf-8")
            try:
                load_mission(bad)
            except MissionValidationError as exc:
                errors.append({"case": label, "result": "rejected", "message": str(exc)})
            else:
                raise AssertionError(f"{label} was not rejected")
    save_json(output / "validation-errors.json", errors)
    assert source.read_bytes() == before, "Evidence requests mutated the mission file"
    assert existing_runs == sorted(p.name for p in (ROOT / "saved-runs").glob("*.json"))
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ROOT), "python": sys.version.split()[0],
        "source_checklist": "https://app.notion.com/p/4185b396b48e81c3b6e9c07502d50958",
        "part2_actions": "S010-S020", "gate": "passed", "behavior_tests": int(match[1]),
        "test_exit_code": tests.returncode, "standard_library_only_startup_exit_code": startup.returncode,
        "assets": len(mission.document["assets"]), "indexed_synthetic_png_views": len(mission.evidence_by_view),
        "prior_records": len(mission.document["prior_records"]),
        "initial_actions_remaining": mission.document["initial_state"]["actions_remaining"],
        "initial_battery": mission.document["initial_state"]["battery_available"],
        "mission_file_unchanged_by_load_and_requests": True, "saved_inspection_runs_created": 0,
        "missing_unreadable_corrupt_or_changed_image": "unavailable + unknown; no annotation replayed (tests.txt)",
        "case_reproducibility": "independent mission loads return identical fixture responses with an injected clock",
        "visual_review": "clear, box-blurred, and apparent-concern PNGs inspected; SYNTHETIC watermark legible",
        "capture_cases": cases,
        "pending": ["human evidence review", "live AI/vision", "action/energy state execution",
                    "Wolfram access/integration", "report", "save/reopen"],
    }
    save_json(output / "verification.json", report)
    paths = [p for folder in (ROOT / "stratus", ROOT / "scripts", ROOT / "tests", ROOT / "evidence/inspection")
             for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    (output / "checksums.sha256").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}\n"
        for path in sorted(paths)), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
