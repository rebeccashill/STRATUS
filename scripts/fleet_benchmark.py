"""Frozen 15-case fleet matrix plus six same-size round-robin controls.

Every case is a fresh local Python process; no live service is called. Performance
numbers include invariant checks. No post-result ranking adjustment is allowed.
"""
import argparse
import csv
import ctypes
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import digest
from stratus.inspection.fleet_scenario import RULES,SEEDS,scenario,illustration
from stratus.inspection.workflow import freeze_context
from offline_checks import audit
OUT=ROOT/'docs/evidence/inspection-0.0.2/part12'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def freeze():
    if (OUT/'freeze-receipt.json').exists():return
    raw=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part11/browser-recorded-export.json').read_text())
    ground=freeze_context(raw)
    protocol={'version':'fleet-matrix-v1','sizes':[2,5,10,25,50],'seeds':list(SEEDS),'scenario':scenario()['scenario_id'],
        'rules':RULES,'matrix_mode':'local_python','baseline_sizes':[2,50],'baseline':'round-robin','common_ground_sha256':digest(ground),
        'fifty_gate':'Each of all 50 independent drones must complete at least one new capture; no prior completed evidence',
        'bounds':'600 simulated seconds; three captures and 100 EU per drone; 15 EU protected reserve; at most 500 candidate pairs per round',
        'measurement':'Fresh process per case. Raw allocation durations, total run wall time including guards, process peak working set, deterministic event count and outcome hash.',
        'interpretation':'Local software scaling is separate from live Wolfram/service latency. More drones add resources. Retain every comparison including regressions and ties.',
        'registration_note':'Rules, sizes and seeds were authored before initial 2/50 smoke tests. This receipt freezes unchanged rules before the complete matrix; it is not a pre-smoke registration.',
        'no_post_result_tuning':True}
    write(ROOT/'context/fleet/solar-200-v1.json',scenario());write(OUT/'ground-context.json',ground);write(OUT/'protocol.json',protocol)
    write(OUT/'shared-contract-examples.json',{'path':FleetSession(2,11,ground)._path(FleetSession(2).data['drones']['D001'],FleetSession(2).data['tasks']['A001:overview']),
        'registry':FleetSession(2).data['hazards'],'owner':'Part 12 owns fleet/gate; Part 13 supplies a pure assessor and reported hazard geometry; no Part 13 implementation claimed.'})
    files=['context/fleet/solar-200-v1.json','docs/evidence/inspection-0.0.2/part12/ground-context.json','docs/evidence/inspection-0.0.2/part12/protocol.json',
           'stratus/inspection/fleet_scenario.py','stratus/contracts/fleet_v1.py','stratus/inspection/fleet_costs.py','stratus/inspection/wolfram/fleet_costs.wls']
    write(OUT/'freeze-receipt.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files},
        'illustrations':[illustration(11,'A001',v,verify=True) for v in ('overview','follow-up')],
        'prior_implementation_smoke':True,'full_matrix_started':False})

def verify_freeze():
    receipt=json.loads((OUT/'freeze-receipt.json').read_text())
    for name,sha in receipt['sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:raise ValueError('Frozen input changed: '+name)

def peak_memory():
    if sys.platform=='win32':
        class Counters(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        p=Counters();p.cb=ctypes.sizeof(p)
        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=ctypes.c_void_p
        psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(p),p.cb):raise ctypes.WinError()
        return p.PeakWorkingSetSize,'Windows PeakWorkingSetSize; whole case process'
    import resource
    n=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return n*(1 if sys.platform=='darwin' else 1024),'resource.ru_maxrss; whole case process'

def case(size,seed,method):
    verify_freeze();ground=json.loads((OUT/'ground-context.json').read_text());start=time.perf_counter()
    core=FleetSession(size,seed,ground,method=method);core.run_to_end();core.assert_invariants();wall=time.perf_counter()-start
    if size==50 and core.metrics()['drone_participation']!=50:raise ValueError('Not all 50 drones completed an action')
    memory,source=peak_memory();name=f'{method}-{size:02d}-{seed}'
    saved=core.save(OUT/'runs'/(name+'.json'))
    result={**core.metrics(),'case_id':name,'total_wall_seconds':wall,'peak_process_memory_bytes':memory,'memory_method':source,
        'max_pairs_in_round':max(len(a['shortlist']['pairs']) for a in core.data['allocations']),
        'outcome_sha256':core.outcome_digest(),'ground_snapshot_id':ground['snapshot_id'],'ground_sha256':digest(ground),
        'scenario_sha256':digest(scenario()),'checkpoint':saved,'new_completed_actions_by_drone':{k:d['actions_used'] for k,d in core.data['drones'].items()},
        'minimum_battery_EU':min(d['battery'] for d in core.data['drones'].values()),'versions':{'python':sys.version,'platform':platform.platform(),'processor':platform.processor()},
        'service_mode':'local_python_only; not a live latency measurement','invariant_status':'passed'}
    write(OUT/'metrics'/(name+'.json'),result);print(name+': '+str(result['captures'])+' captures / '+str(result['drone_participation'])+' drones / '+str(round(wall,3))+' seconds',flush=True)

def matrix():
    freeze();verify_freeze()
    definitions=[(n,s,'coordinator') for n in (2,5,10,25,50) for s in SEEDS]+[(n,s,'round-robin') for n in (2,50) for s in SEEDS]
    for n,s,m in definitions:
        subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--case',str(n),str(s),m],check=True,cwd=ROOT,timeout=120)
    rows=[json.loads((OUT/'metrics'/f'{m}-{n:02d}-{s}.json').read_text()) for n,s,m in definitions]
    comparisons=[]
    for n in (2,50):
        for s in SEEDS:
            a=next(r for r in rows if r['fleet_size']==n and r['seed']==s and r['method']=='coordinator');b=next(r for r in rows if r['fleet_size']==n and r['seed']==s and r['method']=='round-robin')
            comparisons.append({'size':n,'seed':s,'coordinator_usable':a['unique_usable_assets'],'baseline_usable':b['unique_usable_assets'],
                'usable_delta':a['unique_usable_assets']-b['unique_usable_assets'],'priority_delta':a['usable_priority']-b['usable_priority'],'energy_delta_EU':a['total_energy_EU']-b['total_energy_EU']})
    summary={'status':'passed','matrix_cases':15,'baseline_cases':6,'protocol':json.loads((OUT/'protocol.json').read_text()),'runs':rows,'same_size_comparisons':comparisons,
        'all_50_gate':all(r['drone_participation']==50 for r in rows if r['fleet_size']==50),'violations':sum(r['violations'] for r in rows),
        'interpretation':'These are deterministic local toy-model runs. More drones add total battery/capture resources. Unique-task ownership is not collision avoidance; seeded illustrations are not real site imagery.'}
    write(OUT/'matrix-summary.json',summary)
    fields=['case_id','fleet_size','seed','method','captures','unique_usable_assets','usable_priority','unresolved_assets','drone_participation','total_energy_EU','logical_seconds','total_wall_seconds','peak_process_memory_bytes','candidate_pairs','max_pairs_in_round','event_count','violations']
    with (OUT/'matrix.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print('Matrix complete: 15 coordinator + 6 baseline runs; all 50-drone participation gates passed.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--freeze-only',action='store_true');parser.add_argument('--case',nargs=3);args=parser.parse_args()
    sys.addaudithook(audit)
    if args.freeze_only:freeze();verify_freeze();print('Unchanged matrix inputs frozen.')
    elif args.case:case(int(args.case[0]),int(args.case[1]),args.case[2])
    else:matrix()
