"""Part 6 acceptance: bounded captures, injected failures, exact offline recovery."""

import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.actions import Proposal
from stratus.inspection.agent import ServiceError, fallback_proposal, run_agent
from stratus.inspection.computation import CostCalculator, ComputationUnavailable, mission_input, python_costs
from stratus.inspection.dashboard import Dashboard
from stratus.inspection.ground import GroundFeed, HardwareReader, present_snapshot
from stratus.inspection.loader import load_mission
from stratus.inspection.report import build_report, save_report
from stratus.inspection.review import InspectionSession, ground_snapshot
from stratus.inspection.workflow import AdaptiveWorkflow

SOURCES = ['stratus/inspection/'+p for p in ('dashboard.py','ground.py','workflow.py','review.py','persistence.py','computation.py','report.py','engine.py','agent.py','web/app.js','web/index.html','web/style.css')]
FOLDER = ROOT/'docs/evidence/inspection-0.0.2/part6'


def save(name, value):
    (FOLDER/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def protected():
    files = [*(ROOT/'evidence').rglob('*'), *(ROOT/'stratus/inspection/missions').rglob('*'),
             *(ROOT/'saved-runs').glob('first-inspection*.json'), ROOT/'context/hardware-status.json',
             ROOT/'context/ground-measurements/observations-20261114.jsonl',
             *(ROOT/'context/ground-measurements').glob('both-*.csv'), *(ROOT/'context/ground-measurements').glob('pmsa-*.csv')]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in files if p.is_file()}


def choice(asset='P04', view='overview'):
    return Proposal('inspect' if view=='overview' else 'follow_up', asset, view,
                    'Part 6 explicit acceptance action', 'Hold or return if any check fails').to_dict()


def isolated(root, mission):
    for name in ('evidence','context'):
        shutil.copytree(mission.project_root/name, root/name, ignore=shutil.ignore_patterns('live','examples'))
    target=root/'stratus/inspection/missions'; target.mkdir(parents=True)
    shutil.copy2(mission.mission_path, target/mission.mission_path.name)
    (root/'saved-runs').mkdir()
    return load_mission(project_root=root)


def failure_examples(mission, ground):
    result={'evidence_kind':'injected integration failures, not live service outages or physical acquisition'}
    core=InspectionSession(mission); flow=AdaptiveWorkflow(core); before=core.snapshot()
    class Interrupted:
        provider='injected_test'; model='no_live_call'; response_events=[]
        def propose(self, tools): raise ServiceError('timeout','Injected AI interruption; explicit local fallback')
    interrupted=flow.plan(ground, CostCalculator('local'), mode='live', client=Interrupted())
    assert interrupted['execution_mode']=='deterministic_rule_based' and interrupted['agent']['failure']['code']=='timeout'
    assert core.snapshot()==before
    result['ai_interruption']={'plan':interrupted,'aircraft_unchanged':True,'live_call_performed':False}
    with patch('stratus.inspection.engine.simulated_capture',return_value={'status':'unavailable','finding':'unknown'}):
        vision=core.execute(choice(),request_id='interrupted-capture',expected_revision=0)
    assert vision['status']=='rejected' and not vision['assessment_added'] and core.state.actions_used==0
    result['capture_interruption']={'event':vision,'assessment_mode':'no live vision implementation invoked','budget_unchanged':True}
    numeric=[]
    for code in ('timeout','quota_exceeded','access_denied','invalid_response'):
        def fail(_data, code=code): raise ComputationUnavailable(code,'Injected '+code)
        calc=CostCalculator(runner=fail); reference=core.state.snapshot()
        plan=flow.plan(ground,calc)
        assert plan['computation']['mode']=='local_python_fallback'
        assert plan['computation']['output']==python_costs(plan['computation']['normalized_input'])
        assert calc.local_kernel_calls==1 and core.state.snapshot()==reference
        numeric.append({'injected_failure':code,'computation':plan['computation'],'aircraft_unchanged':True,'retries':0})
    result['numerical_failures']=numeric
    def mismatch(data):
        value=dict(python_costs(data),wolfram_version='INJECTED_TEST',system_id='test')
        value['options'][0]['capture']+=2
        return value
    rejected=core.execute(choice(),request_id='numerical-disagreement',expected_revision=0,calculator=CostCalculator(runner=mismatch))
    assert rejected['code']=='numerical_disagreement' and core.state.actions_used==0
    result['numerical_disagreement']={'event':rejected,'budget_unchanged':True}
    low=InspectionSession(mission); low._state=replace(low.state,battery_available=20)
    state=low.state.snapshot(); rejected=low.execute(choice('P03'),request_id='reserve',expected_revision=0)
    assert rejected['decision']['code']=='return_reserve_violation' and low.state.snapshot()==state
    low._state=replace(low.state,battery_available=15)
    no_action=AdaptiveWorkflow(low).plan(ground,CostCalculator('local'))
    assert no_action['proposal'] is None
    result['reserve_and_no_feasible']={'injected_low_battery':20,'rejection':rejected,'no_feasible_plan':no_action,
                                     'agent':fallback_proposal(mission,low.state).to_dict(),'aircraft_unchanged':True}
    save('service-failures.json',result)


def cache_examples(mission):
    calls=[]
    def runner(data):
        calls.append(copy.deepcopy(data))
        return dict(python_costs(data),wolfram_version='INJECTED_TEST',system_id='test')
    calc=CostCalculator(runner=runner); data=mission_input(mission,InspectionSession(mission).state)
    first=calc.compute(data); same=calc.compute(copy.deepcopy(data))
    assert same['mode']=='cached_wolfram_local' and len(calls)==1
    rows=[]
    for field in ('position','battery_available','return_reserve','mission_revision','state_revision'):
        changed=copy.deepcopy(data)
        if field=='position': changed[field]['x']+=1
        elif field=='mission_revision': changed[field]+='-new'
        elif field=='battery_available': changed[field]-=10
        else: changed[field]+=1
        count=len(calls); value=calc.compute(changed)
        assert len(calls)==count+1 and value['cache_key']!=first['cache_key']
        rows.append({'changed':field,'cache_key':value['cache_key'],'mode':value['mode'],'recomputed':True})
    stale=CostCalculator(runner=lambda _data:first['output'])
    changed=copy.deepcopy(data);changed['battery_available']=20
    blocked=stale.compute(changed)
    assert blocked['mode']=='wolfram_disagreement' and not blocked['execution_permitted']
    invalid=copy.deepcopy(data);invalid['model_version']='unsupported-new-model'
    try: calc.compute(invalid)
    except ValueError as exc:model_error=str(exc)
    else:raise AssertionError('Unsupported model reused a cached result')
    save('numerical-cache.json',{'evidence_kind':'injected numerical runner, no live Wolfram call',
         'exact_input_cache':same,'changed_inputs':rows,'unsupported_model_rejected':model_error,'stale_reply_blocked':blocked})


def evidence_examples(mission):
    rows=[]
    for failure in ('missing','corrupt'):
        with tempfile.TemporaryDirectory(prefix='stratus-evidence-failure-') as directory:
            root=Path(directory); local=isolated(root,mission); core=InspectionSession(local);flow=AdaptiveWorkflow(core)
            calc=CostCalculator('local');p=flow.plan(ground_snapshot(local),calc,asset='P02',view='follow-up')
            flow.execute(p['plan_id'],calc);path=root/'saved-runs/before-failure.json';core.save(path)
            image=local.evidence_by_view['P02','follow-up'].image_path; original=image.read_bytes()
            if failure=='missing':image.unlink()
            else:image.write_bytes(b'INJECTED CORRUPT PNG')
            before=core.state.snapshot()
            from stratus.inspection.capture import simulated_capture
            viewer=simulated_capture(local,'P02','follow-up');report=build_report(flow,p['computation'])
            assessment=next(a for a in report['assessments'] if a['asset_id']=='P02' and a['view_id']=='follow-up')
            assert viewer['finding']=='unknown' and assessment['effective_finding']=='unknown' and not assessment['evidence_available']
            try:InspectionSession.load(local,path)
            except (ValueError,OSError) as exc:restore_error=str(exc)
            else:raise AssertionError('Corrupt evidence silently restored')
            image.write_bytes(original);restored=InspectionSession.load(local,path)
            assert restored.state.snapshot()==before
            rows.append({'injected_case':failure,'viewer':viewer,'report_effective_quality':assessment['effective_quality'],
                         'report_effective_finding':assessment['effective_finding'],'load_error':restore_error,
                         'after_restoring_original_bytes':'same checkpoint and budget restore exactly','budget_unchanged':True})
    save('evidence-failures.json',{'evidence_kind':'isolated temporary copy; original project images unchanged','cases':rows})


def hardware_examples(mission):
    with tempfile.TemporaryDirectory(prefix='stratus-hardware-mock-') as directory:
        local=replace(mission,project_root=Path(directory));reader=HardwareReader(local,monotonic=lambda:100)
        good=SimpleNamespace(temperature=22.5,relative_humidity=41.0,pressure=1005.7)
        bad=type('DisconnectedBME',(),{'temperature':property(lambda _self:(_ for _ in ()).throw(OSError('Injected USB loss')))})()
        pm=SimpleNamespace(read=lambda:{'pm10 env':1,'pm25 env':2,'pm100 env':3})
        failed=SimpleNamespace(read=lambda:(_ for _ in ()).throw(OSError('Injected sensor disconnect')))
        snapshots=[]
        for label,bme,pmsa in (('one_sensor_lost',good,failed),('both_lost',bad,failed),('both_recovered',good,pm)):
            reader.i2c=SimpleNamespace(deinit=lambda:None);reader.devices={'BME280':bme,'PMSA003I':pmsa}
            reader.addresses=[0x12,0x77];reader.pmsa_started=0
            data=present_snapshot(reader.sample());snapshots.append({'case':label,'statuses':{s['sensor_model']:s['status'] for s in data['sensors']},
                'observation_count':len(data['observations']),'values':{r['variable']:r['value'] for r in data['observations']}})
        reader.close()
        assert [x['observation_count'] for x in snapshots]==[3,0,6]
        assert snapshots[0]['statuses']=={'BME280':'fresh','PMSA003I':'unavailable'}
        save('hardware-integration-mocks.json',{'evidence_kind':'injected hardware integration mocks only',
             'physical_acquisition_evidence':False,'cases':snapshots,'no_fabricated_zeros':True,
             'actual_physical_evidence':'physical-recovery.json'})


def main():
    FOLDER.mkdir(parents=True,exist_ok=True); before=protected();mission=load_mission();ground=ground_snapshot(mission)
    tests=subprocess.run([sys.executable,'-B','-S','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,timeout=100)
    (FOLDER/'tests.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    match=re.search(r'Ran (\d+) tests?',tests.stderr)
    if tests.returncode or not match:raise RuntimeError('Behavior tests failed; see part6/tests.txt')
    frontend=subprocess.run(['node','tests/frontend_races.test.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=10)
    (FOLDER/'frontend-tests.txt').write_text(frontend.stdout+frontend.stderr,encoding='utf-8')
    if frontend.returncode:raise RuntimeError('Frontend tests failed')
    failure_examples(mission,ground);cache_examples(mission);evidence_examples(mission);hardware_examples(mission)
    core=InspectionSession(mission);flow=AdaptiveWorkflow(core);calc=CostCalculator('local')
    events=[]
    first=flow.plan(ground,calc,asset='P05',view='overview');events.append(flow.execute(first['plan_id'],calc))
    flow.feedback(events[-1]['assessment']['assessment_id'],'request_view',request_id='part6-follow-up',expected_review_revision=0,ground=ground)
    second=flow.plan(ground,calc);events.append(flow.execute(second['plan_id'],calc))
    assert second['proposal']['view_id']=='follow-up'
    flow.feedback(events[-1]['assessment']['assessment_id'],'resolve',request_id='part6-resolve',expected_review_revision=1,ground=ground)
    third=flow.plan(ground,calc,asset='P02',view='follow-up')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6]
    partial=ROOT/'saved-runs'/('part6-partial-'+stamp+'.json');core.save(partial)
    reopened=AdaptiveWorkflow(InspectionSession.load(mission,partial));assert reopened.snapshot()==flow.snapshot()
    readback=subprocess.run([sys.executable,'-B','-S','-m','stratus.inspection','--load',str(partial),'--summary'],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert readback.returncode==0,readback.stderr
    (FOLDER/'offline-fresh-process.txt').write_text(readback.stdout+readback.stderr,encoding='utf-8')
    events.append(flow.execute(third['plan_id'],calc));prior=core.state.snapshot();findings=core.snapshot()['assessments']
    fourth=core.execute(choice(),request_id='fourth-capture',expected_revision=core.state.revision)
    assert fourth['decision']['code']=='actions_exhausted' and core.state.snapshot()==prior and core.snapshot()['assessments']==findings
    duplicate=flow.execute(third['plan_id'],calc);assert duplicate['status']=='already_processed' and core.state.snapshot()==prior
    hold=flow.plan(ground,calc);assert hold['proposal'] is None
    returning=core.execute(Proposal('return',None,None,'No capture actions remain; explicitly return','Hold for review').to_dict(),request_id='part6-return',expected_revision=core.state.revision)
    assert returning['status']=='executed' and returning['capture_action_debit']==0 and core.state.status=='returned'
    flow._sync();final=ROOT/'saved-runs'/('part6-final-'+stamp+'.json');core.save(final)
    restored=AdaptiveWorkflow(InspectionSession.load(mission,final));assert restored.snapshot()==flow.snapshot()
    report=save_report(flow,hold['computation'],ROOT/'saved-runs/reports')
    captures=[a for a in report['report']['actions'] if a['status']=='executed' and a.get('capture_action_debit')==1]
    assert len(captures)==3 and len(core.state.history)==5 and core.state.actions_remaining==0
    assert report['report']['aircraft_state']==core.state.snapshot()
    save('bounded-run.json',{'capture_events':events,'fourth_capture':fourth,'duplicate_result':duplicate,
         'hold_plan':hold,'return_event':returning,'final_state':core.state.snapshot(),'prior_records':2,'new_capture_actions':3})
    assert protected()==before
    hashes={p:sha(ROOT/p) for p in SOURCES};physical=None;browser=None
    try:physical=json.loads((FOLDER/'physical-recovery.json').read_text())
    except (OSError,ValueError):pass
    try:
        browser=json.loads((FOLDER/'browser-walkthrough.json').read_text())
        assert browser['status']=='passed' and browser['source_sha256']==hashes
    except (OSError,ValueError,KeyError,AssertionError):browser=None
    physical_pass=bool(physical and physical['actual_unplug_observed'] and physical['recorded_recovery_verified'])
    result={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'python_tests':int(match.group(1)),
        'frontend_regressions':sum(s.startswith('PASS:') for s in frontend.stdout.splitlines()),'software_checks':'passed',
        'part6_checklist':'18/18' if browser and physical_pass else 'software passed; browser/physical evidence pending',
        'physical_unplug':'passed' if physical_pass else 'pending','browser':'passed' if browser else 'pending',
        'partial_checkpoint':partial.relative_to(ROOT).as_posix(),'final_checkpoint':final.relative_to(ROOT).as_posix(),
        'report_html':'saved-runs/reports/'+report['html'],'report_json':'saved-runs/reports/'+report['json'],
        'captures':3,'original_prior_records':2,'fourth_blocked':True,'duplicate_no_second_debit':True,
        'explicit_return_executed':True,'fresh_process_offline_restore':True,'protected_inputs_unchanged':True,
        'source_sha256':hashes,'injected_examples_are_not_live_service_or_physical_success':True}
    save('checksums.json',before);save('verification.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
