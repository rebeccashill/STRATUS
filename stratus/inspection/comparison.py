"""Predeclared, deterministic three-method comparison using the live workflow guards."""

import copy
import hashlib
import json
import math
from pathlib import Path
import time

from .actions import Proposal
from .computation import CostCalculator, compute_mission_options
from .engine import plain
from .loader import check_image, freeze, load_mission
from .review import InspectionSession, _utc_string
from .workflow import AdaptiveWorkflow, validate_context


def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def load_frozen(root,folder):
    root,folder=Path(root),Path(folder)
    receipt=json.loads((folder/'freeze-receipt.json').read_text())
    for name,expected in receipt['input_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen comparison input changed: '+name)
    spec=json.loads((folder/'comparison-spec.json').read_text())
    ground=json.loads((folder/'ground-input.json').read_text())
    context=validate_context(json.loads((folder/'ground-context.json').read_text()))
    if spec['ground_snapshot_id']!=context['snapshot_id']:raise ValueError('Frozen context reference changed')
    return spec,ground,context,receipt


class ComparisonWorkflow(AdaptiveWorkflow):
    """Freeze decision context once for a benchmark; execution checks are inherited."""
    def __init__(self,session,context):
        self.fixed=copy.deepcopy(validate_context(context));super().__init__(session)

    def context(self,ground):
        if (ground['mode']!=self.fixed['source_mode'] or ground['observations']!=self.fixed['observations']
            or ground['location']!=self.fixed['location']):raise ValueError('Comparison ground input drifted')
        self.data['contexts'][self.fixed['snapshot_id']]=copy.deepcopy(self.fixed)
        return copy.deepcopy(self.fixed)


def review_clear(flow,ground):
    """Identical scripted task policy; raw annotations/human-review labels stay unchanged."""
    for assessment in flow.snapshot()['assessments']:
        if (assessment['image_quality']=='clear' and assessment['finding']=='no_apparent_concern_in_synthetic_drawing'
            and assessment['operator_review_status']!='resolved'):
            flow.feedback(assessment['assessment_id'],'resolve',request_id='scripted-review-'+str(flow.review_revision),
                expected_review_revision=flow.review_revision,ground=ground)


def rank(method,allowed,order,cursor):
    if method=='adaptive':return list(allowed),cursor
    if method=='nearest-feasible':
        return sorted(allowed,key=lambda c:(c['outbound'],c['asset_id'],c['view_id'])),cursor
    if method!='fixed-order':raise ValueError('Unknown comparison method')
    position={asset:i for i,asset in enumerate(order)}
    rows=sorted(allowed,key=lambda c:((position[c['asset_id']]-cursor)%len(order),c['view_id']!='overview',c['view_id']))
    return rows,((position[rows[0]['asset_id']]+1)%len(order) if rows else cursor)


def usable_assets(mission,assessments):
    eligible={a['asset_id'] for a in mission.document['assets'] if a['eligibility']['state']=='eligible'}
    result=set()
    for a in assessments:
        if a['asset_id'] not in eligible or a['image_quality']!='clear':continue
        evidence=mission.evidence_by_view.get((a['asset_id'],a['view_id']))
        try:check_image(evidence,mission.project_root)
        except (OSError,ValueError,AttributeError):continue
        result.add(a['asset_id'])
    return result


def run_method(root,folder,case_id,method,*,calculator=None):
    spec,ground,context,receipt=load_frozen(root,folder)
    case=next(c for c in spec['cases'] if c['case_id']==case_id)
    if method not in spec['methods']:raise ValueError('Method was not predeclared')
    mission=load_mission(Path(root)/case['mission_path'],project_root=Path(root))
    core=InspectionSession(mission,now=_utc_string(spec['frozen_at_utc']))
    # Controlled benchmark input reset, not an aircraft execution or a hardware read.
    core._ground=freeze(ground)
    flow=ComparisonWorkflow(core,context);calc=calculator or CostCalculator('local')
    start=core.state.snapshot();initial_assessments=core.snapshot()['assessments']
    initial_usable=usable_assets(mission,initial_assessments)
    fingerprint=digest({'mission':plain(mission.document),'state':start,'ground':context,
        'evidence':[plain(e.record) for e in mission.evidence_by_view.values()],
        'annotations':[plain(a) for a in mission.annotations_by_id.values()]})
    review_clear(flow,ground)
    steps=[];cursor=0;started=time.perf_counter()
    for index in range(mission.document['action_rules']['max_new_capture_actions']):
        compute_started=time.perf_counter();computation=compute_mission_options(mission,core.state,calc)
        _,allowed=flow.selection(computation)
        choices,cursor=rank(method,allowed,spec['fixed_order'],cursor)
        if not choices:
            steps.append({'decision':'hold','state_revision':core.state.revision,
                'reason':'No eligible capture: see current shared identity/exclusion/action/reserve checks',
                'computation':computation,'blocking_checks':computation['action_checks'],
                'ground_snapshot_id':context['snapshot_id']});break
        selected=choices[0]
        plan=flow.plan(ground,calc,**({} if method=='adaptive' else {'asset':selected['asset_id'],'view':selected['view_id']}))
        if plan['selected'] is None:
            steps.append({'decision':'hold','reason':plan['reason'],'plan':plan});break
        if (plan['selected']['asset_id'],plan['selected']['view_id'])!=(selected['asset_id'],selected['view_id']):
            raise AssertionError('Selected proposal differs from the declared method')
        before=core.state.snapshot();event=flow.execute(plan['plan_id'],calc)
        steps.append({'decision':'capture','method':method,'state_before':before,'selected':selected,
            'alternative':choices[1] if len(choices)>1 else None,'selection_reason':spec[{'fixed-order':'fixed_order_rule','nearest-feasible':'nearest_rule','adaptive':'adaptive_rule'}[method]],
            'plan':plan,'event':event,'state_after':core.state.snapshot(),
            'step_wall_seconds':time.perf_counter()-compute_started,'ground_snapshot_id':context['snapshot_id']})
        if event['status']!='executed':break
        review_clear(flow,ground)
    stop_plan=flow.plan(ground,calc)
    returning=core.execute(Proposal('return',None,None,'Predeclared end-of-comparison return','Hold if return is not feasible').to_dict(),
        request_id='comparison-return',expected_revision=core.state.revision,calculator=calc)
    flow._sync();run=flow.snapshot();state=core.state.snapshot();usable=usable_assets(mission,run['assessments'])
    priorities={a['asset_id']:a['priority'] for a in mission.document['assets'] if a['eligibility']['state']=='eligible'}
    initial_priority=sum(priorities[a] for a in initial_usable);priority=sum(priorities[a] for a in usable)
    captures=[s['event'] for s in steps if s['decision']=='capture' and s['event']['status']=='executed']
    all_actions=run['events'];energy=sum(e.get('battery_debit',0) for e in all_actions if e['status']=='executed')
    capture_energy=sum(e['decision']['costs']['capture'] for e in captures)
    travel_energy=energy-capture_energy
    violations=[e for e in captures if not e['decision']['allowed'] or e['decision']['costs']['margin']<0]
    if state['actions_used']>mission.document['action_rules']['max_new_capture_actions']:violations.append('capture_cap')
    if len({(e['proposal']['asset_id'],e['proposal']['view_id']) for e in captures})!=len(captures):violations.append('duplicate_view')
    metrics={'usable_assets':sorted(usable),'usable_priority':priority,'eligible_priority':sum(priorities.values()),
        'usable_priority_fraction':priority/sum(priorities.values()),'initial_usable_priority':initial_priority,
        'new_usable_priority_gain':priority-initial_priority,'captures':len(captures),
        'distinct_new_assets':len({e['proposal']['asset_id'] for e in captures}),
        'capture_energy':capture_energy,'travel_energy_including_return':travel_energy,
        'travel_metres_including_return':travel_energy/mission.document['energy_model']['travel_energy_per_m'],
        'total_energy_including_return':energy,'battery_final':state['battery_available'],
        'open_scripted_review_tasks':len(run['review_queue']),
        'unresolved_assets':[a['asset_id'] for a in run['assets'] if a['unresolved']],
        'violations':len(violations),'final_status':state['status']}
    return {'case_id':case_id,'method':method,'status':'completed','spec_sha256':receipt['spec_sha256'],
        'start_fingerprint':fingerprint,'initial_state':start,'initial_assessments':initial_assessments,
        'ground_snapshot_id':context['snapshot_id'],'ground_context':context,'steps':steps,'stop_plan':stop_plan,
        'return_event':returning,'final_state':state,'review_feedback':run['feedback'],'assessments':run['assessments'],
        'metrics':metrics,'method_wall_seconds':time.perf_counter()-started,
        'computation_mode':'local_python' if calc.mode=='local' else 'see per-step computation',
        'request_counts':{'local_kernel_calls':calc.local_kernel_calls,'cloud_requests':0,'alpha_calls':0,'llm_requests':0},
        'assessment_mode':'authored synthetic replay; no live vision','review_mode':'scripted benchmark task handling, not actual human review',
        'image_accuracy_claim':None,'source_mode':'Recorded','sensor_mode_not_a_planner_score':True}


def run_matrix(root,folder):
    spec,_,context,_=load_frozen(root,folder);results=[]
    for case in spec['cases']:
        for method in spec['methods']:
            result=run_method(root,folder,case['case_id'],method)
            path=Path(folder)/'runs'/f"{case['case_id']}--{method}.json";path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8');results.append(result)
        assert len({r['start_fingerprint'] for r in results if r['case_id']==case['case_id']})==1
    assert len(results)==9 and {r['ground_snapshot_id'] for r in results}=={context['snapshot_id']}
    return results
