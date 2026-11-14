"""Verify S037-S042 and leave one resumable, explicitly simulated checkpoint."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.loader import load_mission
from stratus.inspection.operator import operator_summary, render_summary
from stratus.inspection.review import InspectionSession


def save(folder, name, data):
    (folder / name).write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def protected():
    paths = [*(ROOT / "stratus/inspection/missions").rglob("*"), *(ROOT / "context").rglob("*"), *(ROOT / "evidence").rglob("*")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def main():
    folder = ROOT / "docs/evidence/inspection-0.0.1/persistence"; folder.mkdir(parents=True, exist_ok=True)
    before = protected()
    existing = {p: p.read_bytes() for p in (ROOT / "saved-runs").glob("*.json")}
    tests = subprocess.run([sys.executable,"-B","-S","-m","unittest","discover","-s","tests","-v"],
                           cwd=ROOT,capture_output=True,text=True,timeout=90)
    (folder / "tests.txt").write_text(tests.stdout+tests.stderr,encoding="utf-8")
    match = re.search(r"Ran (\d+) tests?",tests.stderr)
    if tests.returncode or not match: raise RuntimeError("Tests failed; see persistence/tests.txt")
    mission = load_mission(); run = InspectionSession(mission)
    def proposal(asset):
        return dict(action_type="inspect",asset_id=asset,view_id="overview",reason="Checkpoint acceptance run",alternative="Return or stop")
    run.propose(proposal("P06")); run.propose(proposal("P03"))
    rejected = run.execute(proposal("P06"),request_id="excluded",expected_revision=0)
    event = run.execute(proposal("P03"),request_id="first-inspection",expected_revision=0)
    path = ROOT / "saved-runs/first-inspection.json"
    if path.exists():
        path = path.with_name("first-inspection-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:6]+".json")
    saved = run.save(path); restored = InspectionSession.load(mission,path)
    assert restored.snapshot() == run.snapshot()
    original = restored.snapshot()
    receipt = restored.execute(proposal("P03"),request_id="first-inspection",expected_revision=0)
    assert receipt["status"] == "already_processed" and restored.snapshot() == original
    summary = operator_summary(restored)
    (folder / "operator-summary.txt").write_text(render_summary(summary)+"\n",encoding="utf-8")
    save(folder,"operator-summary.json",summary)
    save(folder,"save-reload.json",dict(checkpoint=str(path.relative_to(ROOT)),saved=saved,before=run.snapshot(),
         after=restored.snapshot(),rejected=rejected,executed=event,retry_receipt=receipt))
    assert protected() == before and all(p.read_bytes() == raw for p,raw in existing.items())
    checkpoint = dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(),original_stop_target_utc="2026-11-14T05:00:00+00:00",
        original_stop_target_met=False, timing_note="Checkpoint completed at its actual time in response to Rebecca's request to continue; original midnight stop was missed, not backdated.",
        planned_resume_local="2026-11-14T09:00:00-05:00",timezone="America/New_York",saved_run=str(path.relative_to(ROOT)),
        normal_launch=r".\.venv\Scripts\python.exe -B -m stratus.inspection",
        reopen=r".\.venv\Scripts\python.exe -B -m stratus.inspection --load "+str(path.relative_to(ROOT))+" --summary",
        fallback_modes=dict(computation="local_python",assessment="authored_replay_annotation",ground=original["ground_context"]["mode"]),
        blockers=[dict(component="Wolfram",status="latest Windows attempts timed out; earlier successful parity retained",next_step="Run scripts/verify_wolfram.py in normal PowerShell before selecting Wolfram mode; keep Python fallback until a new actual call passes"),
                  dict(component="Live ground backend",status="independent/shared-bus acquisition verified; backend polling/UI pending",next_step="Implement H009/H010 using the shared record contract and original node location"),
                  dict(component="Location/calibration/uncertainty",status="unknown; saved labels retained",next_step="Supply real node location and verified calibration metadata when available"),
                  dict(component="Vision/human review",status="annotated replay; human review pending",next_step="Implement the explicit vision/review path in 0.0.2; keep unknowns/tentative flags"),
                  dict(component="Live AI planning",status="previously verified in normal PowerShell; not called by this gate",next_step="Use the configured optional live mode when needed; deterministic planning remains available")],
        physical_acquisition_performed=False,cloud_requests=0,alpha_calls=0,live_ai_requests=0,new_zip_created=False)
    save(folder,"checkpoint.json",checkpoint)
    verification = dict(verified_at_utc=checkpoint["recorded_at_utc"],tests=int(match.group(1)),tests_passed=True,
        persistence_section="6/6 deliverables",completion_gate="passed",saved_run=str(path.relative_to(ROOT)),
        checkpoint_sha256=saved["sha256"],battery_after=restored.state.battery_available,actions_remaining=restored.state.actions_remaining,
        same_run_identity=True,exact_state_and_ground_snapshot_retained=True,retry_after_reopen="no second debit/finding",
        atomic_write_failure_and_stale_writer_tests="passed",mission_evidence_and_ground_files_unchanged=True,
        preexisting_saved_runs_unchanged=True,computation="local_python",assessment="authored_replay_annotation",
        live_vision="not run",physical_acquisition="not performed",original_midnight_stop_met=False,platform=sys.platform)
    save(folder,"verification.json",verification)
    print(json.dumps(verification,indent=2))


if __name__ == "__main__": main()
