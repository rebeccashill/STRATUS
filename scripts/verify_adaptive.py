"""Verify Part 2 with simulated captures, saved feedback, shared context and a report."""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.computation import CostCalculator
from stratus.inspection.loader import load_mission
from stratus.inspection.report import save_report
from stratus.inspection.review import InspectionSession,ground_snapshot
from stratus.inspection.workflow import AdaptiveWorkflow


def save(folder,name,value):
    (folder/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def protected():
    files=[*(ROOT/'stratus/inspection/missions').rglob('*'),*(ROOT/'evidence').rglob('*'),
           *(ROOT/'saved-runs').glob('first-inspection*.json'),ROOT/'context/hardware-status.json',
           ROOT/'context/ground-record.schema.json',ROOT/'context/ground-measurements/observations-20261114.jsonl',
           *(ROOT/'context/ground-measurements').glob('both-*.csv'),*(ROOT/'context/ground-measurements').glob('pmsa-*.csv')]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}


def browser_evidence(folder):
    try:
        data=json.loads((folder/'browser-walkthrough.json').read_text(encoding='utf-8'))
        assert data['status']=='passed'
        for name,checksum in data['source_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==checksum
        assert data['explicit_capture_controls'] and data['feedback_replanning'] and data['report_download_verified']
        return data
    except (OSError,ValueError,KeyError,AssertionError):return None


def main():
    folder=ROOT/'docs/evidence/inspection-0.0.2/part2';folder.mkdir(parents=True,exist_ok=True)
    before=protected()
    tests=subprocess.run([sys.executable,'-B','-S','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,timeout=90)
    (folder/'tests.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    match=re.search(r'Ran (\d+) tests?',tests.stderr)
    if tests.returncode or not match:raise RuntimeError('Behavior tests failed; see part2/tests.txt')
    frontend=subprocess.run(['node','tests/frontend_races.test.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=10)
    (folder/'frontend-tests.txt').write_text(frontend.stdout+frontend.stderr,encoding='utf-8')
    if frontend.returncode:raise RuntimeError('Frontend regression failed')
    mission=load_mission();calc=CostCalculator('local');ground=ground_snapshot(mission)
    core=InspectionSession(mission);flow=AdaptiveWorkflow(core)
    first=flow.plan(ground,calc,asset='P05',view='overview')
    unclear=flow.execute(first['plan_id'],calc)
    assert unclear['assessment']['image_quality']=='unclear' and unclear['assessment']['finding']=='unknown'
    feedback=flow.feedback(unclear['assessment']['assessment_id'],'request_view',request_id='acceptance-follow-up',expected_review_revision=0,ground=ground)
    follow=flow.plan(ground,calc)
    assert (follow['proposal']['asset_id'],follow['proposal']['view_id'])==('P05','follow-up')
    assert follow['alternative'] and follow['alternative']['asset_id']!='P05'
    before_follow=core.state.snapshot();follow_result=flow.execute(follow['plan_id'],calc)
    assert follow_result['assessment']['image_quality']=='clear' and core.state.actions_remaining==1
    flow.feedback(follow_result['assessment']['assessment_id'],'resolve',request_id='acceptance-resolve',expected_review_revision=1,ground=ground)
    next_plan=flow.plan(ground,calc)
    unchanged=core.snapshot();preview=flow.preview(50,20,calc)
    assert core.snapshot()==unchanged and preview['selected'] is None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6]
    checkpoint=ROOT/'saved-runs'/('adaptive-acceptance-'+stamp+'.json');core.save(checkpoint)
    restored=AdaptiveWorkflow(InspectionSession.load(mission,checkpoint))
    assert restored.snapshot()==flow.snapshot()
    receipt=restored.execute(follow['plan_id'],calc)
    assert receipt['status']=='already_processed' and restored.session.state.snapshot()==core.state.snapshot()
    report=save_report(flow,next_plan['computation'],ROOT/'saved-runs/reports')
    linked=follow['ground_context_id']
    assert follow['context_tool']['optional_ground_sensor_context']==flow.data['contexts'][linked]==report['report']['ground_snapshots'][linked]
    assert follow_result['ground_context_id']==linked
    assert any(a['asset_id']=='P05' and a['view_id']=='overview' and a['effective_finding']=='unknown' for a in report['report']['assessments'])
    save(folder,'unclear-follow-up.json',{'first_proposal':first,'unclear_result':unclear,'operator_request':feedback,
         'follow_up_proposal':follow,'before_follow_up':before_follow,'follow_up_result':follow_result,'next_plan':next_plan})
    save(folder,'what-if.json',preview)
    save(folder,'context-linkage.json',{'snapshot_id':linked,'ai_context_tool':follow['context_tool']['optional_ground_sensor_context'],
         'executed_action_reference':follow_result['ground_context_id'],'report_reference':linked,'original_ground':flow.data['contexts'][linked]})
    # Independent feedback-only case from the original saved Friday run.
    old=InspectionSession.load(mission,ROOT/'saved-runs/first-inspection.json');review=AdaptiveWorkflow(old)
    hold=review.plan(ground,calc);old_state=old.state.snapshot()
    concern=next(a for a in old.snapshot()['assessments'] if a['asset_id']=='P03')
    accepted=review.feedback(concern['assessment_id'],'accept_concern',request_id='acceptance-human-review',expected_review_revision=0,ground=ground)
    replanned=review.plan(ground,calc)
    assert hold['proposal'] is None and replanned['proposal'] and old.state.snapshot()==old_state
    save(folder,'feedback-replanning.json',{'before':hold,'feedback':accepted,'after':replanned,'aircraft_before':old_state,'aircraft_after':old.state.snapshot()})
    assert protected()==before
    browser=browser_evidence(folder)
    result={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'python_tests':int(match.group(1)),'tests_passed':True,
       'frontend_regressions':sum(line.startswith('PASS:') for line in frontend.stdout.splitlines()),'software_checks':'passed','browser_walkthrough':'passed' if browser else 'pending',
       'part2_checklist':'13/13' if browser else 'software complete; browser gate pending',
       'checkpoint':checkpoint.relative_to(ROOT).as_posix(),'report_html':'saved-runs/reports/'+report['html'],
       'report_json':'saved-runs/reports/'+report['json'],'captures_in_acceptance':2,'remaining_capture_actions':1,
       'feedback_changes_work_without_aircraft_debit':True,'distinct_follow_up_executed':True,'shared_ground_snapshot_verified':True,
       'feedback_and_context_exact_on_reopen':True,'execution_retry_no_second_debit':True,'unknowns_remain_unknown':True,
       'what_if_state_unchanged':True,'frozen_inputs_and_friday_checkpoints_unchanged':True,
       'software_evidence_computation':'local_python','live_ai':'See startup-plan.json; injected tests are not live API evidence',
       'real_flight':False,'vision':'authored synthetic replay; human review pending','new_physical_sensor_success':False,'new_zip_created':False}
    save(folder,'verification.json',result);save(folder,'checksums.json',protected())
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
