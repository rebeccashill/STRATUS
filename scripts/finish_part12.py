"""Start Fleet Intelligence on the user's normal host; no tests run implicitly.

Checks bounded data-only local Wolfram batches for 2 and 50 drones, preserving
every attempt. Uses explicit local fallback when activation/access is unavailable.
Never uses Cloud/Alpha, polls hardware automatically, or executes real aircraft.
"""
import argparse
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stratus.inspection.dashboard import Dashboard,make_server
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import FleetCalculator
from stratus.inspection.fleet_service import FleetService
from fleet_benchmark import OUT,write,verify_freeze

def verify_wolfram(ground,local=False):
    results=[];calculators={}
    for size in (2,50):
        calc=FleetCalculator('local' if local else 'wolfram');core=FleetSession(size,11,ground,calculator=calc)
        batch,blocked=core.shortlist();before=core.outcome_digest();first=calc.compute(batch);cached=calc.compute(batch) if first['mode']=='wolfram_local' else None
        results.append({'fleet_size':size,'candidate_pairs':len(batch['pairs']),'calculation':first,'same_snapshot_cache':cached,
            'fleet_revision':core.data['fleet_revision'],'hazard_revision':core.data['hazards']['revision'],
            'state_transition_applied':core.outcome_digest()!=before,'status':'passed' if first['mode']=='wolfram_local' and first['execution_permitted'] and cached['mode']=='cached_wolfram_local' else 'live Wolfram unavailable/unrun or disagreement; inspect explicit result'})
        calculators[size]=calc
        print(str(size)+' drones / '+str(len(batch['pairs']))+' candidate pairs: '+first['mode']+' / '+str(round(first['latency_seconds'],3))+' seconds',flush=True)
    boundary_calc=FleetCalculator('local' if local else 'wolfram');b=copy.deepcopy(results[0]['calculation']['input']);base=b['pairs'][0];b['pairs']=[]
    for label,delta in [('below',-0.000001),('equal',0),('above',0.000001)]:
        row=copy.deepcopy(base);row.update(task_id='boundary:'+label,position={'x':0,'y':0},target={'x':6,'y':8},launch={'x':0,'y':0},battery=30+delta,rate=0.5,capture=5,reserve=15)
        b['pairs'].append(row)
    boundaries=boundary_calc.compute(b)
    # Conversion is normalized before the fixed Wolfram interface; preserve proof.
    km=copy.deepcopy(b)
    for row in km['pairs']:
        row['distance_unit']='km';row['rate']*=1000
        for point in ('position','target','launch'):
            for axis in ('x','y'):row[point][axis]/=1000
    converted=boundary_calc.compute(km) if boundaries['mode']=='wolfram_local' and boundaries['execution_permitted'] else {'mode':'unrun','reason':'No retry of an identical normalized batch after runtime failure'}
    status='passed' if all(r['status']=='passed' for r in results) and boundaries['mode']=='wolfram_local' and boundaries['execution_permitted'] and converted['mode']=='cached_wolfram_local' else 'not fully live verified; explicit results retained'
    record={'at_utc':datetime.now(timezone.utc).isoformat(),'status':status,'snapshots':results,'reserve_boundaries':boundaries,'kilometres_equivalent':converted,
        'local_kernel_calls':sum(c.calls for c in calculators.values())+boundary_calc.calls,'cloud_requests':0,'alpha_calls':0,
        'credits_consumed':'Unknown; no usage account queried','physical_sensor_or_camera_read':False,'real_flight':False}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');write(OUT/('wolfram-fleet-'+stamp+'.json'),record);write(OUT/'wolfram-fleet-latest.json',record)
    return record,calculators

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--local',action='store_true');parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    verify_freeze();ground=json.loads((OUT/'ground-context.json').read_text())
    print('Checking read-only fleet costs; no captures or hardware polls...',flush=True)
    proof,calculators=verify_wolfram(ground,args.local)
    checkpoint=ROOT/'saved-runs/ui11-browser-final.json'
    if not checkpoint.is_file():raise FileNotFoundError('The existing Part 11 saved run is required; choose a specific saved single-drone run before starting.')
    recorded=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part11/browser-recorded-export.json').read_text())
    app=Dashboard(checkpoint=checkpoint,recorded=recorded,computation='local')
    app._fleet=FleetService(app);app._fleet.mode='wolfram' if proof['status']=='passed' else 'local'
    calculator=calculators[2] if proof['status']=='passed' else FleetCalculator('local')
    app._fleet.core=FleetSession(2,11,ground,calculator=calculator)
    server=make_server(app,args.port)
    write(OUT/'browser-startup.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'url':f'http://127.0.0.1:{server.server_port}/fleet',
        'fleet_paused':True,'fleet_size':2,'captures':0,'single_checkpoint':checkpoint.name,'ground_snapshot_id':ground['snapshot_id'],
        'fleet_computation':app._fleet.mode,'hardware_automatically_polled':False,'wolfram_status':proof['status']})
    print(f'STRATUS Part 12 ready: http://127.0.0.1:{server.server_port}/fleet',flush=True)
    print('One ground context; simulated independent drones. Opened paused; Run or Step explicitly starts logical events.',flush=True)
    print('Local timing matrix and tests are separate commands; this launcher never runs them implicitly.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()
if __name__=='__main__':main()
