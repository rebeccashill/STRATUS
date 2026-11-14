"""Numerical and sensor parity evidence, kept separate from planner quality."""

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import time

from .actions import Proposal
from .comparison import load_frozen
from .computation import (ABS_TOLERANCE, REL_TOLERANCE, CONTRACT, MODEL, CostCalculator,
    ComputationUnavailable, LocalWolfram, normalize_input, python_costs)
from .ground import present_snapshot, validate_observation
from .loader import load_mission
from .review import InspectionSession


def boundary_input(row):
    return {'contract_version':CONTRACT,'model_version':MODEL,'mission_id':'part8-boundary',
        'mission_revision':'predeclared-v1','state_revision':0,'position':{'point_id':'current','x':0,'y':0},
        'launch':{'point_id':'launch','x':0,'y':0},'distance_unit':'m','energy_unit':'simulated_energy_unit',
        'battery_available':row['battery'],'capture_cost':5,'travel_energy_per_distance':0.5,'return_reserve':15,
        'remaining_actions':row.get('remaining_actions',3),'candidates':[{'asset_id':'boundary','view_id':'overview','x':6,'y':8}]}


def boundary_checks(root,folder,*,live=False):
    spec,_,_,_=load_frozen(root,folder)
    calc=CostCalculator('wolfram' if live else 'local',runner=LocalWolfram(timeout=25) if live else None)
    records=[];blocked=False
    for case in spec['numeric_boundaries']['cases']:
        data=boundary_input(case)
        if blocked:
            records.append({'name':case['name'],'status':'live_not_run','reason':'Stopped after first unavailable live runtime; no repeated activation/timeout attempts','expected':case,'input':data});continue
        start=time.perf_counter();result=calc.compute(data);latency=time.perf_counter()-start
        expected=result['python_output']['options'][0]
        assert math.isclose(expected['margin'],case['expected_margin'],abs_tol=ABS_TOLERANCE,rel_tol=REL_TOLERANCE)
        assert expected['feasible']==case['expected_feasible']
        actual=result['wolfram_output']['options'][0] if result['wolfram_output'] else None
        status=('passed' if result['mode'] in ('wolfram_local','cached_wolfram_local') else 'live_unavailable') if live else 'local_passed'
        if live and status!='passed':blocked=True
        records.append({'name':case['name'],'status':status,'expected':case,'python':expected,'wolfram':actual,
            'latency_seconds':latency,'computation':result})
    metres=boundary_input(spec['numeric_boundaries']['cases'][1]);kilometres=copy.deepcopy(metres)
    kilometres.update(distance_unit='km',travel_energy_per_distance=500)
    kilometres['candidates'][0].update(x=0.006,y=0.008)
    assert normalize_input(metres)==normalize_input(kilometres)
    unit={'status':'local_passed','metre_input':metres,'kilometre_input':kilometres,
          'identical_normalized_input':True,'identical_python_output':python_costs(metres)==python_costs(kilometres)}
    if live and not blocked:
        start=time.perf_counter();unit_result=calc.compute(kilometres)
        unit.update(status='passed' if unit_result['mode']=='cached_wolfram_local' else 'failed',
                    computation=unit_result,latency_seconds=time.perf_counter()-start)
    elif live:unit['live_status']='not_run_after_runtime_failure'
    return {'evidence_kind':'actual local Wolfram runtime calls' if live else 'local Python boundary/unit checks',
        'status':'passed' if not blocked else 'live unavailable; explicit local fallback and unrun rows retained',
        'boundaries':records,'unit_conversion':unit,
        'request_counts':{'local_kernel_calls':calc.local_kernel_calls,'cloud_requests':0,'alpha_calls':0},
        'account_credit_consumption':'Unknown; no account usage data retrieved. Not inferred from request counts.',
        'limits':'Arithmetic parity of the declared toy model only; not aircraft endurance or inspection accuracy.'}


def injected_numerical_checks(root,folder):
    spec,_,_,_=load_frozen(root,folder);data=boundary_input(spec['numeric_boundaries']['cases'][1]);calls=[]
    def reply(value):
        calls.append(value)
        return dict(python_costs(value),wolfram_version='INJECTED_TEST',system_id='test')
    calc=CostCalculator(runner=reply);first=calc.compute(data);same=calc.compute(copy.deepcopy(data))
    assert same['mode']=='cached_wolfram_local' and len(calls)==1
    changes=[]
    for field in ('position','battery_available','return_reserve','mission_revision'):
        changed=copy.deepcopy(data)
        if field=='position':changed[field]['x']=1
        elif field=='mission_revision':changed[field]+='-changed'
        else:changed[field]+=1
        count=len(calls);result=calc.compute(changed)
        assert len(calls)==count+1 and result['cache_key']!=first['cache_key']
        changes.append({'changed':field,'recomputed':True,'cache_key':result['cache_key']})
    stale=CostCalculator(runner=lambda _data:first['output']);changed=copy.deepcopy(data);changed['battery_available']=100
    stale_result=stale.compute(changed);assert not stale_result['execution_permitted']
    failures=[]
    for code in ('timeout','quota_exceeded','access_denied','invalid_response'):
        def fail(_data,code=code):raise ComputationUnavailable(code,'Injected '+code)
        result=CostCalculator(runner=fail).compute(data)
        assert result['mode']=='local_python_fallback' and result['output']==python_costs(data)
        failures.append({'failure':code,'result':result,'retries':0,'state_transition_applied':False})
    mission=load_mission(Path(root)/spec['cases'][0]['mission_path'],project_root=Path(root))
    core=InspectionSession(mission);before=core.state.snapshot()
    def mismatch(value):
        result=dict(python_costs(value),wolfram_version='INJECTED_TEST',system_id='test')
        result['options'][0]['capture']+=2;return result
    event=core.execute(Proposal('inspect','P03','overview','Injected disagreement check','Hold').to_dict(),
        request_id='comparison-numerical-mismatch',expected_revision=0,calculator=CostCalculator(runner=mismatch))
    assert event['code']=='numerical_disagreement' and core.state.snapshot()==before
    return {'evidence_kind':'injected adapter tests; these are not live Wolfram calls',
        'exact_cache':same,'changed_inputs':changes,'stale_reply':stale_result,
        'failure_fallbacks':failures,'material_mismatch':event,'mission_state_unchanged':True}


def sensor_parity(root,folder):
    _,raw,context,_=load_frozen(root,folder);ui=present_snapshot(raw)
    assert ui['source_label']==context['source_label']=='Recorded'
    normalized={r['observation_id']:r for r in raw['observations']}
    reported={r['observation_id']:r for r in context['observations']}
    assert normalized==reported and ui['observations']==context['observations']
    rows=[]
    for observation in raw['observations']:
        validate_observation(observation);provenance=observation['provenance']
        path=(Path(root)/provenance['source_file']).resolve()
        if not path.is_relative_to(Path(root).resolve()/'context/ground-measurements'):raise ValueError('Raw ground source escapes measurement area')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==provenance['source_sha256']
        with path.open(newline='',encoding='utf-8') as stream:original=list(csv.DictReader(stream))[provenance['source_row']-2]
        assert original['variable']==observation['variable'] and original['sensor_model']==observation['sensor_model']
        assert float(original['value'])==observation['value'] and original['unit']==observation['unit']
        assert original['acquired_at_utc']==observation['acquired_at_utc'] and original['received_at_utc']==observation['received_at_utc']
        rows.append({'observation_id':observation['observation_id'],'variable':observation['variable'],'unit':observation['unit'],
            'value':observation['value'],'raw_csv':provenance['source_file'],'sha256':provenance['source_sha256'],
            'raw_normalized_ui_report_equal':True})
    return {'status':'passed','physical_sample_parity':'passed using earlier actual hotplug recovery sample',
        'frozen_snapshot_id':context['snapshot_id'],'source_mode':'Recorded','rows':rows,
        'ui_sensor_states':[{k:s[k] for k in ('sensor_model','status','age_seconds')} for s in ui['sensors']],
        'location':context['location'],'new_hardware_read_performed':False,
        'software_failure_evidence':'full test suite: GroundTests and USBReconnectTests; physical disconnect evidence in hotplug/physical-recovery.json',
        'limits':'Software/source parity only; no sensor calibration, accuracy or defect-detection claim.'}
