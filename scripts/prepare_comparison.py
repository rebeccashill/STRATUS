"""Freeze Part 8 cases, policies and recorded context before computing scores."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prepare_part2_evidence import image
from stratus.inspection.loader import load_mission
from stratus.inspection.workflow import freeze_context

FOLDER=ROOT/'docs/evidence/inspection-0.0.2/part8'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def prepare(root=ROOT,folder=FOLDER):
    root=Path(root).resolve();folder=Path(folder).resolve()
    receipt=folder/'freeze-receipt.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        for name,checksum in saved['input_sha256'].items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=checksum:
                raise ValueError('Frozen comparison input changed: '+name)
        return saved
    base=load_mission(project_root=root)
    document=json.loads(base.mission_path.read_text())
    folder.mkdir(parents=True,exist_ok=True)
    files=[];images={}
    for a in document['assets']:
        for view in a['planned_view_ids']:
            variants=['clear']+(['blur'] if (a['asset_id'],view)==('P02','overview') else ['glare'] if (a['asset_id'],view)==('P03','overview') else [])
            for condition in variants:
                path=folder/'fixtures'/f"{a['asset_id']}-{view}-{condition}.png"
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(image(a['asset_id'],view,condition));files.append(path)
                images[a['asset_id'],view,condition]=path
    source=root/'context/ground-measurements/hotplug-recovered.json'
    raw=json.loads(source.read_text(encoding='utf-8'))
    if raw['mode']!='recorded_measured' or len(raw['observations'])!=6:
        raise ValueError('Use the existing exported physical recorded sample')
    raw['source_label']='Recorded'  # Correct obsolete display metadata; preserve all observations.
    frozen=freeze_context(raw)
    for name,value in [('ground-input.json',raw),('ground-context.json',frozen)]:
        path=folder/name;write(path,value);files.append(path)
    cases=[]
    for name,battery in [('clear',100),('unclear',100),('low-battery',20)]:
        doc=copy.deepcopy(document);scenario='comparison-part8-'+name
        doc.update(scenario_id=scenario,revision='comparison-v1-'+name)
        doc['initial_state']['battery_available']=battery
        entries=[];annotations=[]
        for asset in doc['assets']:
            for view in asset['planned_view_ids']:
                condition=('blur' if (asset['asset_id'],view)==('P02','overview') else
                           'glare' if (asset['asset_id'],view)==('P03','overview') else 'clear') if name=='unclear' else 'clear'
                path=images[asset['asset_id'],view,condition]
                evidence_id=f"{scenario}:{asset['asset_id']}:{view}"
                entries.append({'evidence_id':evidence_id,'scenario_id':scenario,'asset_id':asset['asset_id'],
                    'view_id':view,'image_path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'source_label':'synthetic','source_mode':'procedural_synthetic',
                    'source_note':'New Part 8 procedural illustration using this standalone STRATUS authoring routine.',
                    'rights_note':'Self-authored synthetic benchmark fixture; not a photograph or diagnostic evidence.',
                    'generator':'scripts/prepare_comparison.py:v1'})
                unclear=condition!='clear'
                annotations.append({'evidence_id':evidence_id,'scenario_id':scenario,
                    'assessment_mode':'authored_replay_annotation','annotation_author':'Scripted synthetic benchmark preparation; human review pending',
                    'human_review_status':'pending','live_model_output':False,'image_quality':'unclear' if unclear else 'clear',
                    'finding':'unknown' if unclear else 'no_apparent_concern_in_synthetic_drawing',
                    'note':'Authored blur/occlusion; hidden detail remains unknown.' if unclear else 'Authored visible grid; no real inspection accuracy claim.'})
        for prior in doc['prior_records']:
            evidence_id=f"{scenario}:{prior['asset_id']}:{prior['view_id']}"
            annotation=next(a for a in annotations if a['evidence_id']==evidence_id)
            prior.update(evidence_ref=evidence_id,image_quality_annotation=annotation['image_quality'],finding=annotation['finding'])
        casefolder=folder/'cases'/name
        manifest=casefolder/'manifest.json';annotation_path=casefolder/'annotations.json';mission=casefolder/'mission.json'
        doc['evidence_manifest']=manifest.relative_to(root).as_posix()
        write(annotation_path,{'schema_version':'1','scenario_id':scenario,'annotations':annotations})
        write(manifest,{'schema_version':'1','scenario_id':scenario,'annotations_path':annotation_path.relative_to(root).as_posix(),
                        'fixture_policy':'One immutable response per scenario/asset/view for all planners','entries':entries})
        write(mission,doc);files.extend([annotation_path,manifest,mission]);load_mission(mission,project_root=root)
        cases.append({'case_id':name,'mission_path':mission.relative_to(root).as_posix(),'battery':battery,
            'description':{'clear':'All authored images clear; two clear prior records',
                           'unclear':'P02 prior overview blurred; P03 new overview occluded; distinct follow-ups clear',
                           'low-battery':'Clear imagery but 20 energy units cannot cover any new capture plus protected return/reserve'}[name]})
    spec={'version':'stratus-comparison-v1','preflight_revision':2,
        'preflight_correction':'Obsolete exported Live display label corrected to Recorded before any score; observations and policy unchanged.',
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'cases':cases,'methods':['fixed-order','nearest-feasible','adaptive'],
        'fixed_order':['P01','P02','P03','P04','P05','P06'],
        'fixed_order_rule':'Cyclic asset route; advance cursor after every capture. A new follow-up waits for the next route pass.',
        'nearest_rule':'Minimum outbound distance among identical eligible views; ties by asset ID then view ID.',
        'adaptive_rule':'Current AdaptiveWorkflow ranking: requested view, descending operator priority, observed unclear follow-up, outbound plus capture cost, asset/view ID.',
        'adaptive_weights':{'priority_values':{a['asset_id']:a['priority'] for a in document['assets']},
                            'ranking':'lexicographic; no fitted weights; unchanged after freeze'},
        'common_review_policy':'Scripted benchmark reviewer resolves only clear no-apparent-concern task rows, including priors; unclear tasks stay open. It is not real human review, diagnosis or training.',
        'common_guards':'Same compute_mission_options, AdaptiveWorkflow candidate eligibility, explicit execution engine, evidence identity, exclusions, three-capture cap, return reserve.',
        'follow_up_policy':'Distinct declared uncaptured view and earlier view required; every follow-up uses one capture action.',
        'ground_source':'context/ground-measurements/hotplug-recovered.json','ground_snapshot_id':frozen['snapshot_id'],
        'ground_rule':'Same exact frozen snapshot for all nine runs; no live polling or influence on energy/exclusions/findings.',
        'metric':'Usable priority coverage: sum each eligible asset priority once if at least one available clear image exists, divided by total eligible priority. Include common priors and report the new gain separately.',
        'review_metric':'Open scripted operator tasks and unresolved assets; authored human-review metadata remains pending.',
        'random_seed':None,'stochastic_inputs':False,'live_llm_used':False,'planner_computation_mode':'local_python',
        'cache_policy':'Fresh local calculator per method/case; numerical service/cache measurements reported separately.',
        'numeric_boundaries':{'point_m':[6,8],'rate':0.5,'capture':5,'reserve':15,
            'cases':[{'name':'below','battery':29.999999,'expected_margin':-0.000001,'expected_feasible':False},
                     {'name':'equal','battery':30,'expected_margin':0,'expected_feasible':True},
                     {'name':'above','battery':30.000001,'expected_margin':0.000001,'expected_feasible':True},
                     {'name':'exhausted','battery':31,'remaining_actions':0,'expected_margin':1,'expected_feasible':False}],
            'unit_case':'Equivalent metres/kilometres must normalize to identical inputs/results/cache keys',
            'failure_cases':['stale cache','timeout','quota/access denial','malformed response','material disagreement'],
            'tolerance':{'absolute':1e-8,'relative':1e-10,'feasibility_sign':'strict; no tolerance relaxation'}},
        'claims':'Three authored cases only; no image accuracy, sensor calibration, real flight or universal planner-superiority claim.'}
    specpath=folder/'comparison-spec.json';write(specpath,spec);files.append(specpath)
    saved={'frozen_at_utc':spec['frozen_at_utc'],'input_sha256':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
           'spec_sha256':hashlib.sha256(specpath.read_bytes()).hexdigest(),'note':'Written before any planner comparison score was calculated.'}
    write(receipt,saved);return saved


if __name__=='__main__':
    r=prepare();print(json.dumps({'frozen_at_utc':r['frozen_at_utc'],'inputs':len(r['input_sha256']),'spec_sha256':r['spec_sha256']},indent=2))
