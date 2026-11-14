"""Save controlled fleet failure examples. All failures here are injected tests."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import FleetCalculator,python_batch
from stratus.inspection.fleet_scenario import annotation
from stratus.inspection.fleet_service import FleetService
from stratus.inspection.computation import ComputationUnavailable
from stratus.inspection.agent import ServiceError
from stratus.inspection.ground import unavailable
from stratus.inspection.workflow import freeze_context
from stratus.inspection.loader import load_mission
from offline_checks import audit
from fleet_benchmark import OUT,write

def accounts(core):return {k:{n:copy.deepcopy(d[n]) for n in ('battery','actions_used','position')} for k,d in core.data['drones'].items()}
def main():
    sys.addaudithook(audit);folder=OUT/'failures';ground=json.loads((OUT/'ground-context.json').read_text());cases=[]
    f=FleetSession(2,11,ground)
    for _ in range(50):
        f.advance()
        if f.data['drones']['D001']['actions_used']==1 and f.data['assignments'].get('D001',{}).get('phase')=='inspecting':break
    else:raise AssertionError('Unavailable fixture did not reach its declared boundary')
    before=accounts(f);completed=copy.deepcopy(f.data['evidence']);f.unavailable('D001');after=accounts(f)
    assert before==after and completed==f.data['evidence'];f.run_to_end();assert f.data['drones']['D002']['actions_used']==3
    saved=f.save(folder/'injected-unavailable.json');cases.append({'case':'one drone unavailable','injected':True,'before':before,'after_injection':after,'completed_evidence_preserved':True,'healthy_drone_actions':3,'saved':saved})
    f=FleetSession(2,11,ground);f.advance();did=next(iter(f.data['assignments']));a=f.data['assignments'][did];task=f.data['tasks'][a['task_id']];owner=task['owner'];before=accounts(f)
    task['owner']='D999';rejection=f.check_assignment(f.data['drones'][did],a,a['phase']);task['owner']=owner
    assert rejection=='ownership_conflict' and accounts(f)==before;cases.append({'case':'simultaneous task contention','injected':True,'rejection':rejection,'accounts_unchanged':True,'exclusive_tasks':[x['task_id'] for x in f.data['assignments'].values()]})
    f=FleetSession(2,11,ground);asset=next(a for a in f.assets if annotation(11,a,'overview')['image_quality']=='unclear')
    for t in f.data['tasks'].values():
        if t['asset_id']!=asset:t['state']='blocked'
    f.run_to_end();assert f.data['evidence'][asset+':overview']['finding']=='unknown' and f.data['evidence'][asset+':follow-up']['image_quality']=='clear'
    assert f.metrics()['unique_usable_assets']==1;cases.append({'case':'unclear authored replay followed by distinct view','injected':True,'saved':f.save(folder/'injected-follow-up.json'),'metrics':f.metrics()})
    batch=FleetSession(2,11,ground).shortlist()[0]
    for kind in ('timeout','malformed','mismatch','missing'):
        def runner(value):
            if kind=='timeout':raise ComputationUnavailable('timeout','Injected test only')
            result=dict(python_batch(value),wolfram_version='INJECTED TEST; NOT LIVE',system_id='test')
            if kind=='malformed':return {'invalid':True}
            if kind=='mismatch':result['options'][0]['margin']+=2
            if kind=='missing':result['options'].pop()
            return result
        calc=FleetCalculator('wolfram',runner);result=calc.compute(batch)
        assert calc.calls==1 and result['execution_permitted']==(kind=='timeout')
        write(folder/('injected-wolfram-'+kind+'.json'),{'injected':True,'actual_external_requests':0,'result':result})
        cases.append({'case':'Wolfram '+kind,'injected':True,'attempts':1,'actual_external_requests':0,'mode':result['mode'],'execution_permitted':result['execution_permitted']})
    raw=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part11/browser-recorded-export.json').read_text())
    app=SimpleNamespace(mission=load_mission(),computation_preference='local',ground=SimpleNamespace(snapshot=lambda:copy.deepcopy(raw)))
    service=FleetService(app);before=service.core.outcome_digest()
    class Outage:
        model='INJECTED TEST; NOT LIVE'
        def request(self,payload):raise ServiceError('timeout','Injected only')
    reply=service.explain(True,Outage());assert reply['mode']=='local_rule_fallback' and service.core.outcome_digest()==before
    cases.append({'case':'AI outage','injected':True,'actual_external_requests':0,'result':reply,'aircraft_unchanged':True})
    f=FleetSession(2,11,ground);f.advance(6);before=accounts(f);old=copy.deepcopy(f.data['ground']);f.set_ground(freeze_context(unavailable(load_mission())))
    assert accounts(f)==before and f.data['ground_history'][old['snapshot_id']]==old
    f.run_to_end();assert f.metrics()['captures']==6;cases.append({'case':'ground loss','injected':True,'old_ground_retained':True,'aircraft_unchanged_at_loss':True,'healthy_drone_actions':6,'saved':f.save(folder/'injected-ground-loss.json')})
    write(OUT/'failure-examples.json',{'status':'passed','scope':'controlled injected failures and authored replay, not physical disconnects or actual provider failures','cases':cases,'actual_external_requests':0})
    print(json.dumps({'status':'passed','saved_cases':len(cases),'actual_external_requests':0}))
if __name__=='__main__':main()
