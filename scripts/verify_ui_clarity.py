"""Verify Part 11 UI behavior and preserve the existing frozen mission/evidence inputs."""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.finish_part11 import FOLDER,SOURCES,write
from stratus.inspection.comparison import load_frozen
from stratus.inspection.comparison_checks import sensor_parity


def main():
    FOLDER.mkdir(parents=True,exist_ok=True)
    protected=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part6/checksums.json').read_text())
    tests=subprocess.run([sys.executable,'-B','-S','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (FOLDER/'tests.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    match=re.search(r'Ran (\d+) tests',tests.stderr)
    if tests.returncode or not match:raise RuntimeError('Behavior tests failed; see part11/tests.txt')
    messages=[]
    for name in ['frontend_races.test.cjs','frontend_clarity.test.cjs']:
        check=subprocess.run(['node','tests/'+name],cwd=ROOT,capture_output=True,text=True,timeout=15)
        messages.append(check.stdout+check.stderr)
        if check.returncode:raise RuntimeError(name+' failed')
    text='\n'.join(messages);(FOLDER/'frontend-tests.txt').write_text(text,encoding='utf-8')
    for name,value in protected.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,name+' changed'
    load_frozen(ROOT,ROOT/'docs/evidence/inspection-0.0.2/part8')
    write('sensor-parity.json',sensor_parity(ROOT,ROOT/'docs/evidence/inspection-0.0.2/part8'))
    write('before-after.json',{'source':'Read existing dashboard HTML/CSS/JS before editing; final browser notes are separate',
        'changes':[
            {'before':'Map, viewer and technical next-decision card had equal prominence','after':'Next-step recommendation and costs come first, with mission budgets above'},
            {'before':'Small labels such as Plan next / Execute simulated capture / Margin','after':'Review next action / Run simulated inspection / Energy after reserve, with explanations'},
            {'before':'No compact workflow or concrete no-actions instruction','after':'Five-step progress, execution gate and save/review/Fresh mission continuation'},
            {'before':'Ground source mode mostly a badge; sensor times in technical JSON','after':'Readable source meanings, sensor status/age, original UTC times, unknown location and missing-value help'},
            {'before':'Calculation mode could only be selected at launch','after':'Explicit Wolfram + Python check versus Local Python choice; read-only recalculation, honest cache/fallback/disagreement'},
            {'before':'Export report immediately downloaded; separate report styling','after':'Visible Open/Download report links, confirmed save messages and matching Aevaryn black/amber report styling'}]})
    source_names=SOURCES+['scripts/finish_part11.py','scripts/verify_ui_clarity.py','tests/test_ui_clarity.py','tests/frontend_clarity.test.cjs']
    verification={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'python_tests':int(match.group(1)),
        'frontend_checks':len(re.findall(r'^PASS:',text,re.M)),'tests_passed':True,
        'protected_mission_images_earlier_checkpoints_unchanged':True,'part8_frozen_inputs_unchanged':True,
        'sensor_raw_normalized_presentation_report_parity':'passed using earlier actual sample; no new hardware read',
        'calculation_selection':'same-origin, typed, replans without aircraft debit; injected Wolfram/fallback/cache/disagreement checks pass',
        'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_names},
        'browser_walkthrough':'pending normal-host final UI check','actual_wolfram':'see wolfram-boundaries.json / fresh-start.json; no injected result is live evidence',
        'part11_checklist':'software checks passed; browser gate pending','part9_status':'pending; no code freeze claimed'}
    write('verification.json',verification)
    print(json.dumps({k:verification[k] for k in ['python_tests','frontend_checks','tests_passed','part11_checklist']},indent=2))


if __name__=='__main__':main()
