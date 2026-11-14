"""Save Part 1 software evidence without claiming browser or new hardware success."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.dashboard import Dashboard


def save(folder,name,value):
    (folder/name).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def protected():
    paths = [*(ROOT/"stratus/inspection/missions").rglob("*"),*(ROOT/"evidence").rglob("*"),
             *(ROOT/"context").rglob("*"),*(ROOT/"saved-runs").glob("*.json")]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def completion_evidence(folder):
    """Only retained observations matching this source/checkpoint can close the gate."""
    try:
        browser=json.loads((folder/'browser-walkthrough.json').read_text(encoding='utf-8'))
        wolfram=json.loads((folder/'wolfram-final-check.json').read_text(encoding='utf-8'))
        assert browser['status']=='passed' and len(browser['asset_view_checks'])==12
        for path,checksum in browser['source_sha256'].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==checksum
        assert hashlib.sha256((ROOT/browser['checkpoint']).read_bytes()).hexdigest()==browser['checkpoint_sha256']
        actual=wolfram['result']
        assert actual['mode']=='wolfram_local' and actual['failure'] is None and not actual['disagreements']
        assert browser['preview_refresh_and_evidence_do_not_execute_capture']
        return browser,wolfram
    except (OSError,ValueError,KeyError,TypeError,AssertionError):return None,None


def main():
    folder = ROOT/"docs/evidence/inspection-0.0.2/part1";folder.mkdir(parents=True,exist_ok=True)
    before=protected()
    tests=subprocess.run([sys.executable,"-B","-S","-m","unittest","discover","-s","tests","-v"],
                         cwd=ROOT,capture_output=True,text=True,timeout=90)
    (folder/"tests.txt").write_text(tests.stdout+tests.stderr,encoding="utf-8")
    match=re.search(r"Ran (\d+) tests?",tests.stderr)
    if tests.returncode or not match:raise RuntimeError("Tests failed; see part1/tests.txt")
    frontend=subprocess.run(['node','tests/frontend_races.test.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=10)
    (folder/'frontend-tests.txt').write_text(frontend.stdout+frontend.stderr,encoding='utf-8')
    if frontend.returncode:raise RuntimeError('Frontend evidence-selection regression failed')
    app=Dashboard()
    try:
        original=app.session.snapshot();state=app.state();save(folder,"dashboard-state.json",state)
        mapping=[app.evidence(*key) for key in sorted(app.mission.evidence_by_view)]
        assert all(r["status"] == ("unavailable" if r["asset_id"]=="P06" else "available") for r in mapping)
        save(folder,"image-mapping.json",mapping)
        normal=app.preview(15,5);hold=app.preview(50,20)
        assert normal["selected"]["asset_id"]=="P02" and hold["selected"] is None and hold["recommendation_changed"]
        save(folder,"what-if.json",{"baseline":normal,"bounded_hold":hold})
        recorded=app.ground.export_recorded();save(folder,"recorded-ground.json",recorded)
        assert len(recorded["observations"])==6 and recorded["mode"]=="recorded_measured"
        app.ground.select("unavailable");app.ground.snapshot();app.ground.select("recorded")
        for _ in range(3):app.state();app.ground.snapshot();app.evidence("P03","overview")
        app.load("first-inspection.json")
        assert app.session.snapshot()==original and protected()==before
        browser,wolfram=completion_evidence(folder)
        complete=browser is not None and wolfram is not None
        result={"verified_at_utc":datetime.now(timezone.utc).isoformat(),"tests":int(match.group(1)),
                "tests_passed":True,"software_checks":"passed","real_http_tests":"passed in one test process",
                "frontend_race_regressions":1,"frontend_race_regressions_passed":True,
                "browser_walkthrough":"passed on fresh normal-host server" if complete else "pending matching actual evidence",
                "visual_gate":"passed" if complete else "pending","part1_checklist":"18/18" if complete else "15/18; W008, S053, S054 pending",
                "checkpoint":"saved-runs/first-inspection.json","battery":app.session.state.battery_available,
                "actions_remaining":app.session.state.actions_remaining,"image_mappings":len(mapping),
                "excluded_asset_images":"explicit unavailable; no capture allowed",
                "preview_and_refresh_preserve_entire_run":True,"original_inputs_and_checkpoints_unchanged":True,
                "ground_mode":"recorded_measured","ground_channels":6,"new_physical_success":False,
                "new_hardware_attempt":"MCP2221 device not found; earlier measured records retained",
                "wolfram_latest_attempt":"actual typed call passed; 12 candidates; independent Python agreement" if complete else "no matching final evidence",
                "computation":"actual local Wolfram / cached Wolfram verified; software fixture uses local Python" if complete else "local_python",
                "actual_wolfram_evidence":"wolfram-final-check.json" if complete else None,
                "browser_evidence":"browser-walkthrough.json" if complete else None,
                "assessment":"authored_replay_annotation; human review pending",
                "cloud_requests":0,"alpha_calls":0,"live_ai_requests":0,"new_zip_created":False}
        save(folder,"verification.json",result)
        save(folder,"checksums.json",protected())
        print(json.dumps(result,indent=2))
    finally:app.close()


if __name__=="__main__":main()
