"""Run Part 8's frozen nine-run comparison and independent software checks."""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.comparison import load_frozen, run_matrix
from stratus.inspection.comparison_checks import boundary_checks, injected_numerical_checks, sensor_parity
from stratus.inspection.comparison_report import save_report

FOLDER=ROOT/'docs/evidence/inspection-0.0.2/part8'
SOURCES=['stratus/inspection/'+n for n in ['comparison.py','comparison_checks.py','comparison_report.py','computation.py','engine.py','workflow.py','ground.py','wolfram/inspection_costs.wls']]


def write(name,value):
    (FOLDER/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    spec,_,context,receipt=load_frozen(ROOT,FOLDER)
    protected=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part6/checksums.json').read_text())
    tests=subprocess.run([sys.executable,'-B','-S','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    (FOLDER/'tests.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests',tests.stderr)
    if tests.returncode or not count:raise RuntimeError('Tests failed; see part8/tests.txt')
    frontend=subprocess.run(['node','tests/frontend_races.test.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=10)
    (FOLDER/'frontend-tests.txt').write_text(frontend.stdout+frontend.stderr,encoding='utf-8')
    if frontend.returncode:raise RuntimeError('Frontend tests failed')
    write('numerical-local.json',boundary_checks(ROOT,FOLDER))
    write('numerical-injected.json',injected_numerical_checks(ROOT,FOLDER))
    write('sensor-parity.json',sensor_parity(ROOT,FOLDER))
    results=run_matrix(ROOT,FOLDER);saved=save_report(ROOT,FOLDER,results)
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in protected.items())
    assert all(r['metrics']['violations']==0 for r in results)
    load_frozen(ROOT,FOLDER)
    verification={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'python_tests':int(count.group(1)),
        'frontend_regressions':sum(s.startswith('PASS:') for s in frontend.stdout.splitlines()),'tests_passed':True,
        'method_case_runs':len(results),'all_nine_runs_saved':True,'shared_start_per_case':True,
        'shared_ground_snapshot_id':context['snapshot_id'],'source_mode':'Recorded','new_hardware_reads':0,
        'spec_sha256':receipt['spec_sha256'],'inputs_frozen_before_scores':True,'weights_unchanged':True,
        'all_violations':sum(r['metrics']['violations'] for r in results),'accuracy_claim':None,
        'numerical_local':'passed','numerical_injected':'passed, not live Wolfram evidence',
        'numerical_live':'see numerical-live.json; not required to fabricate a successful live check',
        'sensor_physical_sample_parity':'passed','report_html':saved['html'],'report_json':saved['json'],
        'protected_mission_images_friday_checkpoints_unchanged':True,
        'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
        'part8_checklist':'software complete; numerical live/browser handoff pending'}
    write('verification.json',verification)
    print(json.dumps({'tests':verification['python_tests'],'frontend':verification['frontend_regressions'],
        'runs':len(results),'report':saved['html'],'results':saved['report']['results'],'ties_and_weaknesses':saved['report']['exceptions_and_ties']},indent=2))


if __name__=='__main__':main()
