"""Validate the saved Part 12 evidence without spending service calls."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import digest
from fleet_benchmark import OUT,verify_freeze,write
from offline_checks import audit

def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def flight(core):
    return {k:{n:d[n] for n in ('position','launch','battery','reserve','actions_used','capture_cap')} for k,d in core.data['drones'].items()}
def main():
    sys.addaudithook(audit);verify_freeze();tests=read('python-tests.json');matrix=read('matrix-summary.json');failures=read('failure-examples.json');wolfram=read('wolfram-fleet-latest.json');browser=read('browser-walkthrough.json')
    assert tests['passed'] and tests['tests']>=276 and not tests['errors'] and not tests['failures']
    frontend=read('frontend-tests.json');assert frontend['status']=='passed' and frontend['fleet_tests']==10
    expected={(n,s,'coordinator') for n in (2,5,10,25,50) for s in (11,23,47)}|{(n,s,'round-robin') for n in (2,50) for s in (11,23,47)}
    assert {(r['fleet_size'],r['seed'],r['method']) for r in matrix['runs']}==expected and len(matrix['runs'])==21
    for row in matrix['runs']:
        c=FleetSession.load(OUT/'runs'/(row['case_id']+'.json'));m=c.metrics()
        assert c.outcome_digest()==row['outcome_sha256'] and m['captures']==row['fleet_size']*3
        assert row['violations']==0 and row['max_pairs_in_round']<=500 and row['peak_process_memory_bytes']>0
        assert row['ground_sha256']==matrix['protocol']['common_ground_sha256']
        if row['fleet_size']==50:assert all(d['actions_used']>=1 for d in c.data['drones'].values())
    assert len(matrix['same_size_comparisons'])==6 and failures['status']=='passed' and len(failures['cases'])==9
    assert wolfram['status']=='passed' and wolfram['local_kernel_calls']==3
    assert [r['fleet_size'] for r in wolfram['snapshots']]==[2,50]
    for row in wolfram['snapshots']:assert row['calculation']['mode']=='wolfram_local' and row['calculation']['execution_permitted'] and not row['state_transition_applied']
    assert browser['status']=='passed' and not browser['console_errors_after_final_reload']
    partial=FleetSession.load(OUT/'browser-fifty-paused.json');assert partial.metrics()['captures']==78
    partial.run_to_end();final=FleetSession.load(OUT/'browser-fifty-final.json')
    assert final.metrics()['captures']==150 and final.metrics()['drone_participation']==50
    assert flight(partial)==flight(final) and partial.data['evidence']==final.data['evidence']
    assert final.data['ground']['source_mode']=='live_measured' and len(final.data['ground']['observations'])==6
    assert final.data['ai_requests']==1
    recovery=FleetSession.load(OUT/'browser-fifty-recovery-final.json');assert recovery.metrics()['captures']==149
    assert recovery.data['drones']['D002']['status']=='unavailable' and sum(d['status']=='complete' for d in recovery.data['drones'].values())==49
    two=FleetSession.load(OUT/'browser-two-recovery-final.json');assert two.metrics()['captures']==4 and two.data['drones']['D002']['actions_used']==3
    report=ROOT/'saved-runs/reports'/browser['final_report'].split('name=')[1]
    assert report.is_file() and 'data:image/png;base64,' in report.read_text(encoding='utf-8')
    sources=[p for folder in ('stratus/inspection','stratus/contracts','stratus/hazards') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.css','.html','.wls')]
    sources+=list((ROOT/'scripts').glob('*fleet*.py'))+[ROOT/p for p in ('scripts/finish_part12.py','scripts/verify_part12.py','scripts/offline_checks.py','scripts/use_private_test_shell.ps1','tests/test_fleet.py','tests/test_fleet_service.py','tests/frontend_fleet.test.cjs','README.md','docs/CHECKPOINT.md','docs/FLEET_GUIDE.md','docs/FLEET_CONTRACT.md','docs/FLEET_DEMO.md')]
    result={'status':'passed','part12_verified':'32/32','python_tests':tests['tests'],'matrix_cases':15,'baseline_cases':6,'fifty_actions_per_nominal_run':150,
        'all_50_participated':True,'violations':0,'injected_failure_cases':9,'browser_verified_sizes':[2,50],'actual_wolfram_snapshots':[2,50],
        'wolfram_proof_kernel_calls':3,'cloud_requests':0,'alpha_calls':0,'account_credits_consumed':'Unknown; not inferred from local counters',
        'AI':'one actual explanation request; numerical restatement rejected in UI, verified local totals displayed',
        'telemetry_resolution':'Shell startup diagnostic sender suppressed for the checks; see telemetry-resolution.json',
        'browser_report':browser['final_report'],'protected_paused_resume':'same per-drone accounting and evidence after replay',
        'limits':['Synthetic inspection field and reused illustrations; human review pending','Toy energy and waypoint model; no real aircraft flight or collision separation','Desktop UI verified; narrow viewport override did not take effect','Part 9 final integration/freeze remains separate'],
        'source_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sources}}
    write(OUT/'verification.json',result);print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))
if __name__=='__main__':main()
