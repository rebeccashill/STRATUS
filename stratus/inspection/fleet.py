"""Independent fleet state, deterministic logical events and atomic guarded captures."""
import copy
import heapq
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from stratus.contracts.fleet_v1 import FRAME,PATH_VERSION,empty_registry,empty_assessment
from .actions import strict_json
from .computation import MODEL
from .fleet_costs import CONTRACT,FleetCalculator,canonical,digest,python_pair
from .fleet_scenario import RULES,SCENARIO,scenario,annotation,illustration
from .workflow import validate_context
from stratus.hazards.fleet_adapter import assess_fleet_path

FORMAT='stratus-fleet-run-v1'
LIMIT=32_000_000

def distance(a,b):return math.hypot(a['x']-b['x'],a['y']-b['y'])

def route_signature(scenario_id,model_version,drone_id,task_id,origin,target,launch,hazard_revision):
    return digest({'scenario_id':scenario_id,'model_version':model_version,'drone_id':drone_id,'task_id':task_id,
                   'origin':origin,'target':target,'return_point':launch,'hazard_revision':hazard_revision})

class FleetSession:
    def __init__(self,size=2,seed=11,ground=None,*,calculator=None,method='coordinator',assessor=None):
        if type(size) is not int or not 2<=size<=50:raise ValueError('Fleet size must be an integer from 2 to 50')
        if type(seed) is not int or not 0<=seed<=2147483647:raise ValueError('Seed must be a bounded nonnegative integer')
        if method not in ('coordinator','round-robin'):raise ValueError('Unknown allocation method')
        self.lock=threading.RLock();self.calculator=calculator or FleetCalculator();self.assessor=assessor or assess_fleet_path
        self.assets={a['asset_id']:a for a in scenario()['assets']}
        if ground is not None:validate_context(ground)
        self.data={'schema_version':FORMAT,'run_id':'fleet-'+uuid4().hex,'scenario_id':SCENARIO,'scenario_sha256':digest(scenario()),
            'seed':seed,'size':size,'method':method,'computation_mode':self.calculator.mode,'kernel_calls':self.calculator.calls,'model_version':MODEL,'rules':copy.deepcopy(RULES),'fleet_revision':0,'state_revision':0,
            'clock':0.0,'paused':True,'status':'paused','stop_reason':None,'queue':[],'sequence':0,'round':0,'round_robin_cursor':0,
            'drones':{},'tasks':{},'assignments':{},'evidence':{},'receipts':{},'journal':[],'allocations':[],'feedback':[],
            'ground':copy.deepcopy(ground),'ground_history':{ground['snapshot_id']:copy.deepcopy(ground)} if ground else {},
            'hazards':empty_registry(),'hazard_assessments':[],'explanations':[],'ai_requests':0,'prior_evidence':[]}
        for i in range(size):
            point={'x':round((i+0.5)*40/size,8),'y':0.0};did=f'D{i+1:03d}'
            self.data['drones'][did]={'drone_id':did,'position':dict(point),'launch':dict(point),'initial_battery':100.0,
                'battery':100.0,'reserve':15.0,'capture_cost':5.0,'rate':0.5,'actions_used':0,'capture_cap':3,
                'revision':0,'status':'idle','task_id':None,'reason':'Ready for an exclusive assignment','last_decision':None}
        for a in self.assets.values():self._new_task(a['asset_id'],'overview')
        self.assert_invariants()

    def _new_task(self,asset,view):
        tid=asset+':'+view
        if tid not in self.data['tasks']:
            self.data['tasks'][tid]={'task_id':tid,'asset_id':asset,'view_id':view,'priority':self.assets[asset]['priority'],
                'state':'pending','owner':None,'revision':0,'need':1 if view=='follow-up' else 0,'reason':'Awaiting allocation'}
        return self.data['tasks'][tid]

    def _path(self,drone,task,origin=None):
        origin=copy.deepcopy(origin if origin is not None else drone['position']);target=copy.deepcopy(self.assets[task['asset_id']]['position'])
        return {'schema_version':PATH_VERSION,'scenario_id':SCENARIO,'drone_id':drone['drone_id'],'task_id':task['task_id'],'view_id':task['view_id'],
            'fleet_revision':self.data['fleet_revision'],'drone_revision':drone['revision'],'task_revision':task['revision'],
            'hazard_revision':self.data['hazards']['revision'],'model_version':MODEL,'coordinate_frame':dict(FRAME),
            'origin':origin,'current':copy.deepcopy(drone['position']),'target':target,'return_point':copy.deepcopy(drone['launch']),
            'segments':{'outbound':[origin,target],'protected_return':[target,copy.deepcopy(drone['launch'])]}}

    def _assess(self,path):
        try:
            result=self.assessor(copy.deepcopy(path),copy.deepcopy(self.data['hazards']))
            if not isinstance(result,dict) or result.get('checked_revision')!=self.data['hazards']['revision'] or result.get('state') not in ('clear','blocked','review_required'):raise ValueError('Invalid hazard assessment')
            return result
        except (ValueError,KeyError,TypeError):return {'checked_revision':self.data['hazards']['revision'],'state':'review_required','hazard_ids':[],'reason':'Invalid/mismatched path assessment; no authorization'}

    def shortlist(self):
        rows=[];blocked=[]
        for drone in self.data['drones'].values():
            if drone['status'] not in ('idle','held') or drone['actions_used']>=drone['capture_cap'] or drone.get('hazard_review_required',False):continue
            available=[t for t in self.data['tasks'].values() if t['state']=='pending' and t['owner'] is None]
            near=sorted(available,key=lambda t:(distance(drone['position'],self.assets[t['asset_id']]['position']),t['task_id']))[:6]
            high=sorted(available,key=lambda t:(-t['priority'],-t['need'],t['task_id']))[:4]
            selected={t['task_id']:t for t in near+high}
            for task in selected.values():
                path=self._path(drone,task);assessment=self._assess(path)
                if assessment['state']!='clear':blocked.append({'drone_id':drone['drone_id'],'task_id':task['task_id'],'assessment':assessment});continue
                rows.append({'drone_id':drone['drone_id'],'task_id':task['task_id'],'asset_id':task['asset_id'],'view_id':task['view_id'],
                    'drone_revision':drone['revision'],'task_revision':task['revision'],'position':copy.deepcopy(drone['position']),
                    'target':copy.deepcopy(self.assets[task['asset_id']]['position']),'launch':copy.deepcopy(drone['launch']),
                    'battery':drone['battery'],'capture':drone['capture_cost'],'rate':drone['rate'],'reserve':drone['reserve'],
                    'remaining_actions':drone['capture_cap']-drone['actions_used'],'distance_unit':'m','energy_unit':'simulated_energy_unit'})
        assert len(rows)<=500
        return {'contract_version':CONTRACT,'model_version':MODEL,'scenario_id':SCENARIO,'fleet_revision':self.data['fleet_revision'],
                'hazard_revision':self.data['hazards']['revision'],'pairs':rows},blocked

    def preview(self):
        with self.lock:
            batch,blocked=self.shortlist()
            if not batch['pairs']:return {'candidate_pairs':0,'blocked':blocked,'calculation':None,'choices':[],'preview_only':True}
            calc=self.calculator.compute(batch)
            self.data['kernel_calls']=self.calculator.calls
            return {'candidate_pairs':len(batch['pairs']),'blocked':blocked,'calculation':calc,'choices':self._rank(calc),'preview_only':True}

    def _rank(self,calc):
        allowed=[c for c in calc['output']['options'] if c['feasible']] if calc['execution_permitted'] else []
        if self.data['method']=='round-robin':
            ids=list(self.data['drones']);cursor=self.data['round_robin_cursor']%len(ids)
            return sorted(allowed,key=lambda c:((ids.index(c['drone_id'])-cursor)%len(ids),c['task_id']))
        return sorted(allowed,key=lambda c:(self.data['drones'][c['drone_id']]['actions_used'],-self.data['tasks'][c['task_id']]['priority'],
                    -self.data['tasks'][c['task_id']]['need'],c['outbound']+c['capture'],c['drone_id'],c['task_id']))

    def _event(self,at,kind,did,assignment=None):
        self.data['sequence']+=1
        heapq.heappush(self.data['queue'],[round(at,9),self.data['sequence'],kind,did,assignment])

    def allocate(self):
        begin=time.perf_counter();self.data['fleet_revision']+=1;self.data['round']+=1
        batch,blocked=self.shortlist();calc=self.calculator.compute(batch) if batch['pairs'] else None
        self.data['kernel_calls']=self.calculator.calls
        ordered=self._rank(calc) if calc else [];chosen=[];used_drones=set();used_tasks=set();conflicts=[]
        for cost in ordered:
            if cost['drone_id'] in used_drones or cost['task_id'] in used_tasks:
                conflicts.append([cost['drone_id'],cost['task_id']]);continue
            used_drones.add(cost['drone_id']);used_tasks.add(cost['task_id']);chosen.append(cost)
        numeric={(p['drone_id'],p['task_id']):p for p in batch['pairs']}
        for cost in chosen:
            did,tid=cost['drone_id'],cost['task_id'];drone=self.data['drones'][did];task=self.data['tasks'][tid]
            task.update(state='assigned',owner=did,revision=task['revision']+1,reason='Exclusive reservation')
            aid=f"r{self.data['round']}:{did}:{tid}";origin=copy.deepcopy(drone['position'])
            assignment={'assignment_id':aid,'drone_id':did,'task_id':tid,'fleet_revision':self.data['fleet_revision'],
                'hazard_revision':self.data['hazards']['revision'],'drone_revision':drone['revision'],'task_revision':task['revision'],
                'phase':'assigned','origin':origin,'initial_battery':drone['battery'],'numeric':copy.deepcopy(numeric[did,tid]),
                'cost':copy.deepcopy(cost),'mode':calc['mode'],'execution_permitted':calc['execution_permitted']}
            assignment['route_signature']=route_signature(self.data['scenario_id'],MODEL,did,tid,origin,assignment['numeric']['target'],drone['launch'],assignment['hazard_revision'])
            self.data['assignments'][did]=assignment
            alternative=next((c for c in ordered if c['drone_id']==did and c['task_id']!=tid),None)
            drone.update(status='assigned',task_id=tid,reason='Bounded greedy priority/evidence/cost choice' if self.data['method']=='coordinator' else 'Round-robin feasible task choice',
                         last_decision={'selected':copy.deepcopy(cost),'alternative':copy.deepcopy(alternative),'mode':calc['mode'],'fleet_revision':self.data['fleet_revision'],'hazard_revision':assignment['hazard_revision']})
            self._event(self.data['clock'],'depart',did,aid)
        self.data['round_robin_cursor']+=1
        self.data['allocations'].append({'round':self.data['round'],'time':self.data['clock'],'fleet_revision':self.data['fleet_revision'],
            'shortlist':batch,'calculation':calc,'selected':copy.deepcopy(chosen),'ownership_conflicts_skipped':conflicts,'hazard_blocks':blocked,
            'wall_seconds':time.perf_counter()-begin})
        for d in self.data['drones'].values():
            if d['status'] in ('idle','held'):
                if not chosen or d['actions_used']>=d['capture_cap']:self._return(d)
                else:d['reason']='No exclusive feasible shortlisted pair this wave; retry after the wave'
        self.data['state_revision']+=1
        return chosen

    def _return(self,drone):
        if drone['status']=='unavailable':return
        if drone.get('hazard_review_required',False):
            drone.update(status='held',reason='Affected logical segment remains held for operator review; no stop point or return inferred');return
        cost=distance(drone['position'],drone['launch'])*drone['rate']
        if drone['battery']-cost<drone['reserve']-1e-9:
            drone.update(status='held',reason='Return reserve cannot be protected; retained for review');return
        if self._assess(self._return_path(drone))['state']!='clear':
            drone.update(status='held',reason='Reported-hazard module must authorize return; no automatic detour');return
        if cost<=1e-12:drone.update(status='complete',task_id=None,reason='At launch; no further capture selected')
        else:
            drone.update(status='returning',task_id=None,reason='Returning to launch with the protected reserve')
            self._event(self.data['clock']+distance(drone['position'],drone['launch'])/RULES['speed_m_per_sim_second'],'return',drone['drone_id'],{'hazard_revision':self.data['hazards']['revision']})

    def _return_path(self,drone):
        origin=copy.deepcopy(drone['position']);home=copy.deepcopy(drone['launch'])
        return {'schema_version':PATH_VERSION,'scenario_id':SCENARIO,'drone_id':drone['drone_id'],'task_id':'return:'+drone['drone_id'],'view_id':'return',
            'fleet_revision':self.data['fleet_revision'],'drone_revision':drone['revision'],'task_revision':0,
            'hazard_revision':self.data['hazards']['revision'],'model_version':MODEL,'coordinate_frame':dict(FRAME),
            'origin':origin,'current':origin,'target':home,'return_point':home,'segments':{'outbound':[origin,home],'protected_return':[home,home]}}

    def check_assignment(self,drone,assignment,phase):
        task=self.data['tasks'][assignment['task_id']]
        if assignment['fleet_revision']!=self.data['fleet_revision'] or assignment['hazard_revision']!=self.data['hazards']['revision']:return 'stale_fleet_or_hazard_revision'
        if drone['revision']!=assignment['drone_revision'] or task['revision']!=assignment['task_revision']:return 'stale_drone_or_task_revision'
        if task['owner']!=drone['drone_id'] or task['state']!='assigned' or drone['task_id']!=task['task_id']:return 'ownership_conflict'
        if drone['status']=='unavailable' or assignment['phase']!=phase:return 'invalid_lifecycle'
        if drone['status']!=phase:return 'invalid_lifecycle'
        row=assignment['numeric'];expected_target=self.assets[task['asset_id']]['position']
        if assignment.get('route_signature')!=route_signature(self.data['scenario_id'],MODEL,drone['drone_id'],task['task_id'],assignment['origin'],expected_target,drone['launch'],assignment['hazard_revision']):return 'route_signature_changed'
        if any(row[k]!=v for k,v in {'drone_id':drone['drone_id'],'task_id':task['task_id'],'asset_id':task['asset_id'],'view_id':task['view_id'],
                'position':assignment['origin'],'target':expected_target,'launch':drone['launch'],'capture':drone['capture_cost'],
                'rate':drone['rate'],'reserve':drone['reserve'],'battery':assignment['initial_battery'],
                'remaining_actions':drone['capture_cap']-drone['actions_used']}.items()):return 'numeric_identity_or_model_changed'
        if assignment['drone_revision']!=row['drone_revision']+{'assigned':0,'traveling':1,'inspecting':2}[phase] or assignment['task_revision']!=row['task_revision']+1:return 'numeric_revision_changed'
        if drone['actions_used']>=drone['capture_cap'] or not assignment['execution_permitted']:return 'actions_or_numerical_block'
        expected=python_pair(assignment['numeric'])
        if any(not math.isclose(assignment['cost'][k],expected[k],abs_tol=1e-8,rel_tol=1e-10) for k in ('outbound','capture','return_cost','reserve','margin')) or assignment['cost']['feasible']!=expected['feasible']:return 'numerical_disagreement'
        spent=assignment['cost']['outbound'] if phase=='inspecting' else 0
        if not math.isclose(drone['battery'],assignment['initial_battery']-spent,abs_tol=1e-8):return 'budget_revision_changed'
        required=assignment['cost']['capture']+assignment['cost']['return_cost']+drone['reserve']+(0 if phase=='inspecting' else assignment['cost']['outbound'])
        if drone['battery']<required:return 'return_reserve'
        assessment=self._assess(self._path(drone,task,assignment['origin']))
        if assessment['state']!='clear' or assessment['checked_revision']!=assignment['hazard_revision']:return 'reported_hazard_gate'
        return None

    def _log(self,kind,did,battery_debit=0,capture_debit=0,**fields):
        self.data['journal'].append({'sequence':len(self.data['journal'])+1,'sim_time':self.data['clock'],'kind':kind,'drone_id':did,
            'battery_debit':battery_debit,'capture_debit':capture_debit,**fields});self.data['state_revision']+=1

    def commit_capture(self,did,aid):
        with self.lock:
            key='capture:'+aid
            if key in self.data['receipts']:
                receipt=self.data['receipts'][key]
                if receipt['drone_id']!=did:return {'status':'rejected','reason':'receipt_drone_mismatch'}
                return dict(receipt,status='already_processed')
            drone=self.data['drones'].get(did);assignment=self.data['assignments'].get(did)
            if drone is None or assignment is None or assignment['assignment_id']!=aid:return {'status':'rejected','reason':'unknown_assignment'}
            error=self.check_assignment(drone,assignment,'inspecting')
            if error:return {'status':'rejected','reason':error}
            task=self.data['tasks'][assignment['task_id']];target=self.assets[task['asset_id']]['position']
            if drone['position']!=target:return {'status':'rejected','reason':'wrong_target_position'}
            try: image=illustration(self.data['seed'],task['asset_id'],task['view_id'],verify=True)
            except (OSError,ValueError):return {'status':'rejected','reason':'illustration_missing_or_invalid'}
            record={'evidence_id':f"{SCENARIO}:{self.data['seed']}:{task['task_id']}",'drone_id':did,'task_id':task['task_id'],
                'asset_id':task['asset_id'],'view_id':task['view_id'],'simulated_capture_time':self.data['clock'],
                'ground_snapshot_id':self.data['ground']['snapshot_id'] if self.data['ground'] else None,
                'flight_and_capture':'simulated','real_camera_capture':False,'illustration':image,**annotation(self.data['seed'],task['asset_id'],task['view_id'])}
            self.data['evidence'][task['task_id']]=record;task.update(state='completed',owner=None,revision=task['revision']+1,reason=record['image_quality']+' authored replay')
            debit=assignment['cost']['capture'];drone['battery']-=debit;drone['actions_used']+=1;drone['revision']+=1
            drone.update(status='idle',task_id=None,reason='Capture complete; pending next allocation wave')
            del self.data['assignments'][did]
            self._log('capture',did,debit,1,task_id=task['task_id'],assignment_id=aid,mode=assignment['mode'],ground_snapshot_id=record['ground_snapshot_id'])
            if record['image_quality']=='unclear':self._new_task(task['asset_id'],'follow-up')
            result={'status':'executed','drone_id':did,'task_id':task['task_id'],'evidence_id':record['evidence_id']}
            self.data['receipts'][key]=result
            return copy.deepcopy(result)

    def _release(self,did,reason):
        a=self.data['assignments'].pop(did,None);d=self.data['drones'][did]
        if a:
            t=self.data['tasks'][a['task_id']]
            if t['state']!='completed':t.update(state='unavailable' if reason=='illustration_missing_or_invalid' else 'pending',owner=None,revision=t['revision']+1,reason=reason)
        if d['status']!='unavailable':d.update(status='idle',task_id=None,reason=reason)

    def _advance_event(self,event):
        at,_,kind,did,aid=event;self.data['clock']=at;drone=self.data['drones'][did]
        if kind=='return':
            if drone['status']!='returning':return
            if not isinstance(aid,dict) or aid['hazard_revision']!=self.data['hazards']['revision'] or self._assess(self._return_path(drone))['state']!='clear':
                drone.update(status='held',reason='Return hazard revision changed; operator review required');return
            debit=distance(drone['position'],drone['launch'])*drone['rate']
            if drone['battery']-debit<drone['reserve']-1e-9:drone.update(status='held',reason='Return recheck blocked');return
            drone['battery']-=debit;drone['position']=copy.deepcopy(drone['launch']);drone['revision']+=1
            drone.update(status='complete',reason='Returned; reserve retained');self._log('return',did,debit);return
        a=self.data['assignments'].get(did)
        if a is None or a['assignment_id']!=aid:return
        if kind=='capture':
            result=self.commit_capture(did,aid)
            if result['status']=='rejected':self._release(did,result['reason'])
            return
        phase='assigned' if kind=='depart' else 'traveling';error=self.check_assignment(drone,a,phase)
        if error:self._release(did,error);return
        if kind=='depart':
            drone['revision']+=1;a.update(phase='traveling',drone_revision=drone['revision']);drone['status']='traveling'
            self._event(at+distance(a['origin'],a['numeric']['target'])/RULES['speed_m_per_sim_second'],'arrive',did,aid);self._log('depart',did,task_id=a['task_id'])
        else:
            debit=a['cost']['outbound'];drone['battery']-=debit;drone['position']=copy.deepcopy(a['numeric']['target']);drone['revision']+=1
            drone['status']='inspecting';a.update(phase='inspecting',drone_revision=drone['revision'])
            self._event(at+RULES['capture_sim_seconds'],'capture',did,aid);self._log('arrive',did,debit,task_id=a['task_id'])

    def advance(self,count=1):
        if type(count) is not int or not 1<=count<=1000:raise ValueError('Advance 1-1000 logical events')
        with self.lock:
            if self.data['status'] in ('complete','stopped'):return self.snapshot()
            for _ in range(count):
                from stratus.hazards.integration import review_due_reports
                review_due_reports(self)
                if not self.data['assignments'] and any(d['status'] in ('idle','held') and d['actions_used']<3 for d in self.data['drones'].values()):self.allocate()
                if not self.data['assignments']:
                    for d in self.data['drones'].values():
                        if d['status']=='idle':self._return(d)
                if not self.data['queue']:
                    self.data.update(status='complete',paused=True,stop_reason='No feasible shortlisted capture remains; completed returns or explicit holds retained. This is not a global infeasibility proof.');break
                event=heapq.heappop(self.data['queue'])
                if event[0]>RULES['horizon_sim_seconds']:
                    heapq.heappush(self.data['queue'],event);self.data.update(status='stopped',paused=True,stop_reason='Declared logical horizon reached');break
                self._advance_event(event);self.assert_invariants()
            return self.snapshot()

    def run_to_end(self):
        with self.lock:
            self.data.update(status='running',paused=False)
            for _ in range(20):
                self.advance(1000)
                if self.data['status'] in ('complete','stopped'):break
            else:raise RuntimeError('Bounded event cap exceeded')
            return self.snapshot()

    def invalidate(self,reason):
        self.data['fleet_revision']+=1
        if self.data['status']=='complete':self.data.update(status='paused',paused=True,stop_reason=None)
        for did in list(self.data['assignments']):self._release(did,reason)
        self.data['queue']=[e for e in self.data['queue'] if e[2]=='return'];heapq.heapify(self.data['queue']);self.data['state_revision']+=1

    def unavailable(self,did):
        with self.lock:
            if did not in self.data['drones']:raise ValueError('Unknown drone')
            drone=self.data['drones'][did];drone['status']='unavailable';self.invalidate('Reallocate after simulated unavailable drone')
            drone.update(status='unavailable',task_id=None,reason='Injected simulated unavailability; completed evidence/costs retained',revision=drone['revision']+1)
            self.data['queue']=[e for e in self.data['queue'] if e[3]!=did];heapq.heapify(self.data['queue'])
            self._log('injected_unavailable',did);self.data['feedback'].append({'kind':'injected_unavailable','drone_id':did,'time':self.data['clock']})

    def priority(self,asset,value):
        if asset not in self.assets or type(value) is not int or not 1<=value<=3:raise ValueError('Choose an asset and priority 1-3')
        with self.lock:
            self.invalidate('Operator priority changed; stale proposals invalidated')
            for t in self.data['tasks'].values():
                if t['asset_id']==asset:t.update(priority=value,revision=t['revision']+1)
            self.data['feedback'].append({'kind':'priority','asset_id':asset,'value':value,'time':self.data['clock']})

    def request_view(self,asset):
        with self.lock:
            if asset+':overview' not in self.data['evidence']:raise ValueError('A distinct follow-up requires a completed overview')
            if asset+':follow-up' in self.data['evidence']:raise ValueError('That distinct view is already completed')
            self.invalidate('Operator requested a distinct follow-up');self._new_task(asset,'follow-up')
            self.data['feedback'].append({'kind':'request_view','asset_id':asset,'time':self.data['clock']})

    def set_ground(self,context):
        validate_context(context)
        with self.lock:
            self.data['ground']=copy.deepcopy(context);self.data['ground_history'][context['snapshot_id']]=copy.deepcopy(context)

    def set_hazards(self,registry):
        from stratus.hazards.integration import publish_registry
        return publish_registry(self,registry)

    def assert_invariants(self):
        d=self.data
        from stratus.hazards.integration import restore_fleet_registry
        restore_fleet_registry(d['hazards'])
        if d['scenario_id']!=SCENARIO or d['scenario_sha256']!=digest(scenario()) or d['rules']!=RULES:raise ValueError('Scenario/model changed')
        if type(d['size']) is not int or not 2<=d['size']<=50 or len(d['drones'])!=d['size']:raise ValueError('Invalid fleet size')
        if set(d['drones'])!={f'D{i+1:03d}' for i in range(d['size'])}:raise ValueError('Drone identity changed')
        if type(d['clock']) not in (int,float) or not math.isfinite(d['clock']) or not 0<=d['clock']<=600:raise ValueError('Invalid logical clock')
        if type(d['paused']) is not bool or d['status'] not in ('paused','running','complete','stopped'):raise ValueError('Invalid fleet lifecycle')
        if d['computation_mode']!=self.calculator.mode or type(d['kernel_calls']) is not int or d['kernel_calls']<0 or d['kernel_calls']!=self.calculator.calls:raise ValueError('Saved computation mode/count changed')
        owners=[];captures=[j for j in d['journal'] if j['kind']=='capture']
        if len({j['task_id'] for j in captures})!=len(captures) or len(captures)!=len(d['evidence']):raise ValueError('Duplicate/missing completed view')
        if len(d['receipts'])!=len(captures):raise ValueError('Capture receipt count mismatch')
        for j in captures:
            receipt=d['receipts'].get('capture:'+j['assignment_id'])
            if not receipt or receipt['status']!='executed' or receipt['task_id']!=j['task_id'] or receipt['drone_id']!=j['drone_id']:raise ValueError('Capture receipt identity mismatch')
        for did,drone in d['drones'].items():
            if type(drone.get('hazard_review_required',False)) is not bool:raise ValueError('Invalid hazard review flag')
            if drone.get('hazard_review_required',False) and (drone['status'] not in ('held','unavailable') or did in d['assignments']):raise ValueError('Unreviewed logical segment cannot execute or own a new assignment')
            launch={'x':round((int(did[1:])-0.5)*40/d['size'],8),'y':0.0}
            if drone['launch']!=launch:raise ValueError('Independent launch identity changed')
            if drone['drone_id']!=did or type(drone['actions_used']) is not int or not 0<=drone['actions_used']<=3 or drone['capture_cap']!=3:raise ValueError('Capture cap/identity changed')
            if drone['initial_battery']!=100 or drone['reserve']!=15 or drone['capture_cost']!=5 or drone['rate']!=0.5:raise ValueError('Frozen drone model changed')
            debit=sum(j['battery_debit'] for j in d['journal'] if j['drone_id']==did)
            if not math.isfinite(drone['battery']) or not math.isclose(drone['battery'],100-debit,abs_tol=1e-8):raise ValueError('Budget ledger mismatch')
            if drone['actions_used']!=sum(j['capture_debit'] for j in d['journal'] if j['drone_id']==did):raise ValueError('Action ledger mismatch')
            if drone['battery']<drone['reserve']-1e-8:raise ValueError('Protected reserve violated')
            if any(type(drone['position'][k]) not in (int,float) or not math.isfinite(drone['position'][k]) for k in ('x','y')):raise ValueError('Invalid position')
            if drone['status'] not in ('idle','assigned','traveling','inspecting','returning','complete','held','unavailable'):raise ValueError('Invalid lifecycle')
            position=launch
            for entry in d['journal']:
                if entry['drone_id']==did:
                    if entry['kind']=='arrive':position=self.assets[d['tasks'][entry['task_id']]['asset_id']]['position']
                    elif entry['kind']=='return':position=launch
            if drone['position']!=position:raise ValueError('Position does not match completed logical movement')
        for tid,t in d['tasks'].items():
            if tid!=t['asset_id']+':'+t['view_id'] or t['asset_id'] not in self.assets or t['view_id'] not in ('overview','follow-up'):raise ValueError('Task identity mismatch')
            if t['state']=='assigned':
                owners.append(t['owner'])
                if t['owner'] not in d['assignments'] or d['assignments'][t['owner']]['task_id']!=tid:raise ValueError('Reservation missing')
            elif t['owner'] is not None:raise ValueError('Unassigned task owns a drone')
            if t['state']=='completed' and tid not in d['evidence']:raise ValueError('Completed without evidence')
        if len(owners)!=len(set(owners)) or len(owners)!=len(d['assignments']):raise ValueError('Conflicting ownership')
        for did,assignment in d['assignments'].items():
            error=self.check_assignment(d['drones'][did],assignment,assignment['phase'])
            if error:raise ValueError('Invalid saved assignment: '+error)
        for tid,e in d['evidence'].items():
            if e['task_id']!=tid or e['drone_id'] not in d['drones'] or e['asset_id']+':'+e['view_id']!=tid:raise ValueError('Evidence identity mismatch')
            if any(e[k]!=annotation(d['seed'],e['asset_id'],e['view_id'])[k] for k in annotation(d['seed'],e['asset_id'],e['view_id'])):raise ValueError('Replay evidence changed')
            if e['illustration']!=illustration(d['seed'],e['asset_id'],e['view_id']):raise ValueError('Illustration bytes/identity changed')
        for context in d['ground_history'].values():validate_context(context)
        if len(d['journal'])>5000 or len(d['queue'])>1000 or len(d['allocations'])>200:raise ValueError('Fleet history exceeds bounds')

    def metrics(self):
        d=self.data;usable={e['asset_id'] for e in d['evidence'].values() if e['image_quality']=='clear'}
        priorities={a:self.assets[a]['priority'] for a in self.assets}
        for f in d['feedback']:
            if f['kind']=='priority':priorities[f['asset_id']]=f['value']
        counts={status:sum(x['status']==status for x in d['drones'].values()) for status in ('idle','assigned','traveling','inspecting','returning','complete','held','unavailable')}
        return {'fleet_size':d['size'],'seed':d['seed'],'method':d['method'],'captures':len(d['evidence']),'unique_usable_assets':len(usable),
            'usable_priority':sum(priorities[a] for a in usable),'total_priority':sum(priorities.values()),'unresolved_assets':200-len(usable),
            'unclear_views':sum(e['image_quality']=='unclear' for e in d['evidence'].values()),'human_review_pending':len(d['evidence']),
            'total_energy_EU':sum(100-x['battery'] for x in d['drones'].values()),'total_battery_EU':sum(x['battery'] for x in d['drones'].values()),
            'remaining_captures':sum(3-x['actions_used'] for x in d['drones'].values()),'travel_metres':sum(j['battery_debit']/0.5 for j in d['journal'] if j['kind'] in ('arrive','return')),
            'drone_participation':sum(x['actions_used']>0 for x in d['drones'].values()),'rounds':d['round'],'candidate_pairs':sum(len(a['shortlist']['pairs']) for a in d['allocations']),
            'event_count':len(d['journal']),'logical_seconds':d['clock'],'allocation_wall_seconds':[a['wall_seconds'] for a in d['allocations']],
            'violations':0,'status_counts':counts,'stop_reason':d['stop_reason'],'local_kernel_calls':self.calculator.calls,'cloud_requests':0,'alpha_calls':0,'ai_requests':d['ai_requests']}

    def snapshot(self):
        result=copy.deepcopy(self.data);result['assets']=[dict(copy.deepcopy(a),priority=self.data['tasks'][a['asset_id']+':overview']['priority']) for a in self.assets.values()];result['metrics']=self.metrics()
        return result

    def outcome_digest(self):
        return digest({k:self.data[k] for k in ('drones','tasks','evidence','clock','journal','queue','feedback')})

    def save(self,path):
        with self.lock:
            self.assert_invariants();path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            payload=copy.deepcopy(self.data);envelope={'format':FORMAT,'sha256':digest(payload),'payload':payload};raw=canonical(envelope)
            if len(raw)>LIMIT:raise ValueError('Fleet checkpoint exceeds 32 MB')
            temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp');temp.write_bytes(raw);temp.replace(path)
            return {'checkpoint':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}

    @classmethod
    def load(cls,path,*,calculator=None,assessor=None):
        path=Path(path)
        if path.stat().st_size>LIMIT:raise ValueError('Fleet checkpoint too large')
        obj=strict_json(path.read_text(encoding='utf-8'),max_chars=LIMIT)
        if not isinstance(obj,dict) or set(obj)!={'format','payload','sha256'} or obj['format']!=FORMAT or digest(obj['payload'])!=obj['sha256']:raise ValueError('Fleet checksum/format mismatch')
        p=obj['payload'];p.setdefault('hazards',empty_registry());p.setdefault('hazard_assessments',[])
        # Version-zero legacy saves predate the explicit route digest. Their
        # checksum is verified above; all identity/budget checks still run.
        for did,a in p.get('assignments',{}).items():
            if 'route_signature' not in a and p['hazards']['revision']==0 and not p['hazards']['hazards']:
                a['route_signature']=route_signature(p['scenario_id'],p['model_version'],did,a['task_id'],a['origin'],a['numeric']['target'],p['drones'][did]['launch'],0)
        core=cls(p['size'],p['seed'],p['ground'],calculator=calculator or FleetCalculator(p['computation_mode']),method=p['method'],assessor=assessor)
        if core.calculator.mode!=p['computation_mode']:raise ValueError('Saved computation mode changed; choose a new run to change the model path')
        core.calculator.calls=p['kernel_calls']
        if set(p)!=set(core.data):raise ValueError('Unknown fleet checkpoint fields')
        core.data=p;core.data['paused']=True
        for e in p['evidence'].values():
            if e['illustration']!=illustration(p['seed'],e['asset_id'],e['view_id'],verify=True):raise ValueError('Saved illustration bytes changed')
        if core.data['status']=='running':core.data['status']='paused'
        core.assert_invariants();heapq.heapify(core.data['queue']);return core
