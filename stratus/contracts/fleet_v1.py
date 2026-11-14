"""Frozen v1 fleet/hazard boundary: JSON records, no fleet-class imports."""
import math

FRAME={'name':'solar-site-local-v1','unit':'m'}
PATH_VERSION='stratus-fleet-path-v1'
REGISTRY_VERSION='stratus-hazards-v1'

def empty_registry():
    return {'schema_version':REGISTRY_VERSION,'revision':0,'coordinate_frame':dict(FRAME),'hazards':[],'events':[]}

def point(value):
    if not isinstance(value,dict) or set(value)!={'x','y'}:raise ValueError('Expected a local x/y point')
    if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) or abs(value[k])>1e6 for k in ('x','y')):raise ValueError('Invalid local coordinates')
    return value

def validate_path(value):
    if value.get('schema_version')!=PATH_VERSION or value.get('coordinate_frame')!=FRAME:raise ValueError('Unsupported path frame/schema')
    for key in ('drone_id','task_id','view_id','scenario_id','model_version'):
        if not isinstance(value.get(key),str) or not 0<len(value[key])<=160:raise ValueError('Invalid path identity')
    for key in ('fleet_revision','drone_revision','task_revision','hazard_revision'):
        if type(value.get(key)) is not int or value[key]<0:raise ValueError('Invalid path revision')
    for key in ('origin','current','target','return_point'):point(value[key])
    expected={'outbound':[value['origin'],value['target']],'protected_return':[value['target'],value['return_point']]}
    if value.get('segments')!=expected:raise ValueError('Path segments do not match declared points')
    return value

def empty_assessment(path,registry):
    """Fail closed until Part 13 supplies geometry for a nonempty registry."""
    try:
        validate_path(path)
        if registry.get('schema_version')!=REGISTRY_VERSION or registry.get('coordinate_frame')!=FRAME:raise ValueError('Registry frame/schema mismatch')
        if path['hazard_revision']!=registry['revision']:raise ValueError('Stale hazard revision')
        if type(registry['revision']) is not int or registry['revision']<0:raise ValueError('Invalid registry revision')
        if registry.get('hazards') or registry.get('revision')!=0:raise ValueError('Nonempty/revised registry requires the Part 13 assessor')
    except (ValueError,KeyError,TypeError) as exc:
        return {'schema_version':'stratus-hazard-assessment-v1','checked_revision':registry.get('revision'),
                'state':'review_required','hazard_ids':[],'reason':str(exc)}
    return {'schema_version':'stratus-hazard-assessment-v1','checked_revision':0,'state':'clear',
            'hazard_ids':[],'reason':'Empty reported-hazard registry; no real collision-clearance claim'}
