"""One bounded fleet batch through the existing local runtime; Python owns authorization."""
import copy
import hashlib
import json
import math
from pathlib import Path
import time
from .computation import MODEL,ABS_TOLERANCE,REL_TOLERANCE,ComputationUnavailable,LocalWolfram
from .engine import protected_margin

CONTRACT='stratus-fleet-costs-v1'
SCRIPT=Path(__file__).resolve().parent/'wolfram/fleet_costs.wls'

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()

def normalize(value):
    fields={'contract_version','model_version','scenario_id','fleet_revision','hazard_revision','pairs'}
    if not isinstance(value,dict) or set(value)!=fields or value['contract_version']!=CONTRACT or value['model_version']!=MODEL:raise ValueError('Unsupported fleet numeric contract')
    if not isinstance(value['scenario_id'],str) or not value['scenario_id']:raise ValueError('Missing scenario ID')
    for name in ('fleet_revision','hazard_revision'):
        if type(value[name]) is not int or not 0<=value[name]<=100000:raise ValueError('Invalid fleet revision')
    rows=value['pairs']
    if not isinstance(rows,list) or not 1<=len(rows)<=500:raise ValueError('Fleet batch requires 1-500 pairs')
    expected={'drone_id','task_id','asset_id','view_id','drone_revision','task_revision','position','target','launch','battery','capture','rate','reserve','remaining_actions','distance_unit','energy_unit'}
    result=copy.deepcopy(value);keys=set()
    for row in result['pairs']:
        if not isinstance(row,dict) or set(row)!=expected:raise ValueError('Unexpected fleet pair fields')
        for name in ('drone_id','task_id','asset_id','view_id'):
            if not isinstance(row[name],str) or not 0<len(row[name])<=160:raise ValueError('Invalid pair identity')
        key=(row['drone_id'],row['task_id'])
        if key in keys:raise ValueError('Duplicate pair')
        keys.add(key)
        for name in ('drone_revision','task_revision','remaining_actions'):
            if type(row[name]) is not int or not 0<=row[name]<=100000:raise ValueError('Invalid pair revision/action count')
        if row['energy_unit']!='simulated_energy_unit' or row['distance_unit'] not in ('m','km'):raise ValueError('Unsupported fleet units')
        factor=1000 if row['distance_unit']=='km' else 1
        for name in ('position','target','launch'):
            if not isinstance(row[name],dict) or set(row[name])!={'x','y'}:raise ValueError('Invalid pair point')
            for axis in ('x','y'):
                n=row[name][axis]
                if type(n) not in (int,float) or not math.isfinite(n) or abs(n)>1e6:raise ValueError('Invalid coordinate')
                row[name][axis]=float(n)*factor
        for name in ('battery','capture','rate','reserve'):
            n=row[name]
            if type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1e9:raise ValueError('Invalid fleet budget')
            row[name]=float(n)
        row['rate']/=factor;row['distance_unit']='m'
    result['pairs'].sort(key=lambda p:(p['drone_id'],p['task_id']))
    return result

def python_pair(row):
    dist=lambda a,b:math.hypot(a['x']-b['x'],a['y']-b['y'])
    out=dist(row['position'],row['target'])*row['rate'];ret=dist(row['target'],row['launch'])*row['rate']
    margin=protected_margin(row['battery'],out,row['capture'],ret,row['reserve'])
    return {**{k:row[k] for k in ('drone_id','task_id','asset_id','view_id','drone_revision','task_revision')},
            'outbound':out,'capture':row['capture'],'return_cost':ret,'reserve':row['reserve'],'margin':margin,
            'feasible':margin>=0 and row['remaining_actions']>0}

def python_batch(value):
    n=normalize(value)
    return {**{k:n[k] for k in ('contract_version','model_version','scenario_id','fleet_revision','hazard_revision')},'options':[python_pair(p) for p in n['pairs']]}

def validate_reply(reply,expected):
    if not isinstance(reply,dict) or set(reply)!=set(expected)|{'wolfram_version','system_id'}:raise ValueError('Malformed fleet response')
    for key in set(expected)-{'options'}:
        if type(reply[key]) is not type(expected[key]) or reply[key]!=expected[key]:raise ValueError('Fleet response identity/revision mismatch')
    if not all(isinstance(reply[k],str) and 0<len(reply[k])<=200 for k in ('wolfram_version','system_id')):raise ValueError('Invalid runtime metadata')
    if not isinstance(reply['options'],list) or len(reply['options'])!=len(expected['options']):raise ValueError('Missing fleet result rows')
    received={}
    for row in reply['options']:
        if not isinstance(row,dict) or set(row)!=set(expected['options'][0]):raise ValueError('Malformed result row')
        key=(row['drone_id'],row['task_id'])
        if key in received:raise ValueError('Duplicate result identity')
        received[key]=row
    differences=[]
    for ref in expected['options']:
        row=received.pop((ref['drone_id'],ref['task_id']),None)
        if row is None:raise ValueError('Unknown/missing drone/task ID')
        for key in ('asset_id','view_id','drone_revision','task_revision','feasible'):
            if type(row[key]) is not type(ref[key]) or row[key]!=ref[key]:differences.append([ref['drone_id'],ref['task_id'],key])
        for key in ('outbound','capture','return_cost','reserve','margin'):
            if type(row[key]) not in (int,float) or not math.isfinite(row[key]):raise ValueError('Nonfinite result')
            if not math.isclose(row[key],ref[key],abs_tol=ABS_TOLERANCE,rel_tol=REL_TOLERANCE):differences.append([ref['drone_id'],ref['task_id'],key])
        if (row['margin']>=0)!=(ref['margin']>=0):differences.append([ref['drone_id'],ref['task_id'],'margin_sign'])
    if received:raise ValueError('Unknown result IDs')
    return differences

class FleetCalculator:
    def __init__(self,mode='local',runner=None):
        if mode not in ('local','wolfram'):raise ValueError('Choose local or wolfram')
        self.mode=mode;self.runner=runner or LocalWolfram(script=SCRIPT);self.cache={};self.calls=0
    def compute(self,value):
        n=normalize(value);expected=python_batch(n);key=digest({'input':n,'script':hashlib.sha256(SCRIPT.read_bytes()).hexdigest()})
        result={'mode':'local_python','input':n,'python_output':expected,'output':expected,'wolfram_output':None,'execution_permitted':True,
                'cache_key':key,'failure':None,'differences':[],'latency_seconds':0,'request_counts':{'local_kernel_calls':self.calls,'cloud_requests':0,'alpha_calls':0}}
        if self.mode=='local':return result
        if key in self.cache:
            result.update(mode='cached_wolfram_local',output=copy.deepcopy(self.cache[key]),wolfram_output=copy.deepcopy(self.cache[key]));return result
        self.calls+=1;result['request_counts']['local_kernel_calls']=self.calls;begin=time.perf_counter()
        try:
            reply=self.runner(copy.deepcopy(n));differences=validate_reply(reply,expected)
            result.update(wolfram_output=reply,differences=differences,mode='wolfram_disagreement' if differences else 'wolfram_local',execution_permitted=not differences)
            if not differences:
                result['output']=reply
                if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=copy.deepcopy(reply)
        except (ComputationUnavailable,TimeoutError,OSError) as exc:
            code=getattr(exc,'code','unavailable');invalid=code=='invalid_response'
            result.update(mode='wolfram_disagreement' if invalid else 'local_python_fallback',execution_permitted=not invalid,failure={'code':code,'message':'Bounded fleet runtime failed; no retry. Python fallback only for availability failures.'})
        except (ValueError,KeyError,TypeError,OverflowError):
            result.update(mode='wolfram_disagreement',execution_permitted=False,failure={'code':'invalid_response','message':'Malformed/missing/mismatched fleet results cannot authorize an action'})
        result['latency_seconds']=time.perf_counter()-begin
        return result
