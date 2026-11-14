"""Newly authored 200-asset synthetic workload; illustrations are disclosed reuse."""
import hashlib
from pathlib import Path
from functools import lru_cache
from .png import validate_png
from .computation import MODEL
from stratus.contracts.fleet_v1 import FRAME

SCENARIO='stratus-solar-200-v1'
SEEDS=(11,23,47)
RULES={'battery_EU':100,'reserve_EU':15,'capture_EU':5,'travel_EU_per_m':0.5,
       'capture_cap':3,'speed_m_per_sim_second':2,'capture_sim_seconds':2,'horizon_sim_seconds':600,
       'shortlist_nearest':6,'shortlist_priority':4,'max_pairs':500,
       'coordinator':'Bounded greedy: fewest captures first, descending priority/evidence need, travel+capture, drone/task IDs',
       'baseline':'Cyclic drone order; first feasible task ID within the identical shortlist',
       'tie_policy':'Stable drone ID and task ID; logical event time then insertion sequence',
       'allocation_boundary':'Wave barrier after all assigned travel/captures; returning drones may finish independently',
       'limits':'Simulated independent aircraft; unique task ownership is not trajectory separation or flight control'}

def scenario():
    return {'schema_version':'stratus-fleet-scenario-v1','scenario_id':SCENARIO,'generator_version':'1',
        'coordinate_frame':dict(FRAME),'model_version':MODEL,'rules':dict(RULES),
        'assets':[{'asset_id':f'A{i+1:03d}','position':{'x':2+2*(i%20),'y':2+2*(i//20)},
                   'priority':1+(i*7)%3,'views':['overview','follow-up']} for i in range(200)],
        'evidence_disclosure':'200 unique synthetic asset coordinates; representative P04/P05 overview/follow-up illustrations are reused. These are not 200 independent photographs.'}

def annotation(seed,asset,view):
    unclear=view=='overview' and int(hashlib.sha256(f'{seed}:{asset}:overview'.encode()).hexdigest()[:8],16)%7==0
    return {'image_quality':'unclear' if unclear else 'clear','finding':'unknown' if unclear else 'no_apparent_concern_in_authored_replay',
            'source_mode':'reused_procedural_synthetic_illustration','assessment_mode':'seeded_authored_replay_not_live_vision',
            'human_review_status':'pending','illustration_asset':'P05' if unclear else 'P04','illustration_view':view}

@lru_cache(maxsize=4)
def _checked_image(relative,modified,size):
    path=Path(__file__).resolve().parents[2]/relative
    raw,width,height=validate_png(path)
    return {'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'width':width,'height':height,'source':'reused authored synthetic illustration'}

@lru_cache(maxsize=4)
def _descriptor(relative):
    stat=(Path(__file__).resolve().parents[2]/relative).stat()
    return _checked_image(relative,stat.st_mtime_ns,stat.st_size)

def illustration(seed,asset,view,verify=False):
    label=annotation(seed,asset,view)
    relative='evidence/inspection/images/'+label['illustration_asset']+'-'+view+'.png'
    if verify:
        stat=(Path(__file__).resolve().parents[2]/relative).stat()
        return dict(_checked_image(relative,stat.st_mtime_ns,stat.st_size))
    return dict(_descriptor(relative))
