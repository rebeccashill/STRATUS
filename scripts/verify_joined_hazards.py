"""Save bounded Part 13 real-engine traces, separate from Part 12's benchmark.

Two and 50 drones, seed 11, one frozen ground snapshot. No sockets, hardware,
cloud, AI, or full regression suite. --wolfram adds four read-only local batches.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.hazards.integration import LiveFleetHazards
from stratus.hazards.fleet_adapter import assess_fleet_path
from stratus.inspection.fleet import FleetSession
from stratus.inspection.fleet_costs import FleetCalculator, digest
from stratus.inspection.fleet_report import save_fleet_report

OUT = ROOT / 'docs/evidence/inspection-0.0.2/part13/joined'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def resources(core):
    return {i: {k: deepcopy(d[k]) for k in ('position', 'battery', 'actions_used')} for i, d in core.data['drones'].items()}


def host(size, ground, calculator=None):
    service = SimpleNamespace(lock=threading.RLock(), core=FleetSession(size, 11, ground, calculator=calculator or FleetCalculator('local')))
    return service.core, LiveFleetHazards(service)


def initial_digest(core):
    return digest({k: core.data[k] for k in ('scenario_id', 'model_version', 'seed', 'size', 'ground', 'drones', 'tasks', 'hazards')})


def run_case(size, ground, reported):
    core, controller = host(size, ground)
    same_initial = initial_digest(core)
    core.allocate()
    proposals = deepcopy(core.data['assignments'])
    before = resources(core)
    impact, rejections, replacements = None, [], []
    after_rejections = before
    if reported:
        impact = controller.report(controller.event())
        assert resources(core) == before
        for did, a in proposals.items():
            result = core.commit_capture(did, a['assignment_id'])
            assert result['status'] == 'rejected'
            rejections.append(dict(drone_id=did, **result))
        assert resources(core) == before
        after_rejections = resources(core)
        core.allocate()
        for did, a in core.data['assignments'].items():
            path = core._path(core.data['drones'][did], core.data['tasks'][a['task_id']], a['origin'])
            assessment = assess_fleet_path(path, core.data['hazards'])
            assert assessment['state'] == 'clear'
            replacements.append({'drone_id': did, 'old_task_id': proposals.get(did, {}).get('task_id'),
                                 'assignment': deepcopy(a), 'path': path, 'assessment': assessment})
    core.advance(5)
    core.data.update(paused=True, status='paused')
    active = deepcopy(core.data)
    stem = f'fleet-{size}-' + ('reported' if reported else 'no-report')
    active_file = OUT / (stem + '-active.json')
    core.save(active_file)
    loaded = FleetSession.load(active_file)
    assert loaded.data == active
    core.run_to_end()
    loaded.run_to_end()
    assert loaded.outcome_digest() == core.outcome_digest()
    duplicate = None
    if core.data['receipts']:
        key, receipt = next(iter(core.data['receipts'].items()))
        before_duplicate = deepcopy(core.data)
        duplicate = core.commit_capture(receipt['drone_id'], key[len('capture:'):])
        assert duplicate['status'] == 'already_processed' and core.data == before_duplicate
    core.save(OUT / (stem + '-final.json'))
    report = save_fleet_report(core, ROOT)
    for kind in ('html', 'json'):
        shutil.copyfile(ROOT / 'saved-runs/reports' / report[kind], OUT / (stem + '.' + kind))
    metrics = core.metrics()
    record = {'mode': 'actual_part12_fleet_integration', 'fleet_size': size, 'seed': 11,
              'reported': reported, 'initial_state_sha256': same_initial, 'ground': ground,
              'prepared_assignments': proposals, 'impact': impact, 'stale_rejections': rejections,
              'report_and_rejections_resources_unchanged': after_rejections == before,
              'resources_after_report_and_rejections': after_rejections,
              'resources_before_report': before, 'replacements': replacements,
              'exact_active_save_reopen': True, 'resumed_outcome_exact': True,
              'duplicate_capture': duplicate, 'metrics': metrics,
              'calculation_modes': sorted({a['calculation']['mode'] for a in core.data['allocations'] if a['calculation']}),
              'affected_drone_ids': [a['drone_id'] for a in impact['assessments'] if a['state'] != 'clear'] if impact else [],
              'reassigned_task_count': sum(r['old_task_id'] != r['assignment']['task_id'] for r in replacements),
              'held_drone_ids': [i for i,d in core.data['drones'].items() if d['status'] == 'held'],
              'unaffected_participating_drone_ids': [i for i,d in core.data['drones'].items() if d['actions_used'] and (not impact or next(a['state'] for a in impact['assessments'] if a['drone_id']==i)=='clear')],
              'limitations': 'Authored 2D exclusion; no real collision outcome, obstacle detection, radio acknowledgement, or detour planning.'}
    write(OUT / (stem + '-trace.json'), record)
    return record


def resources_from_data(data):
    return {i: {k: deepcopy(d[k]) for k in ('position', 'battery', 'actions_used')} for i,d in data['drones'].items()}


def numerical(size, ground):
    calc = FleetCalculator('wolfram')
    core, controller = host(size, ground, calc)
    before_resources = resources(core)
    before = core.preview()
    controller.report(controller.event())
    after = core.preview()
    assert resources(core) == before_resources
    first, second = before['calculation'], after['calculation']
    assert first['cache_key'] != second['cache_key']
    repeated = calc.compute(after['calculation']['input']) if second['mode'] == 'wolfram_local' else None
    record = {'fleet_size': size, 'before_report': before, 'after_report': after,
              'same_post_report_snapshot': repeated, 'resources_unchanged': True,
              'calls': calc.calls, 'cloud_requests': 0, 'alpha_calls': 0,
              'status': 'passed' if all(c['mode']=='wolfram_local' and c['execution_permitted'] for c in (first,second)) and repeated['mode']=='cached_wolfram_local' else 'actual local runtime unavailable/disagreement; explicit results retained'}
    write(OUT / f'wolfram-{size}.json', record)
    return record


def in_progress(ground):
    core, controller = host(2, ground)
    core.advance(1)
    before = resources(core)
    impact = controller.report(controller.event())
    assert resources(core) == before and impact['review_required_drone_ids']
    core.run_to_end()
    for did in impact['review_required_drone_ids']:
        assert core.data['drones'][did]['hazard_review_required'] and core.data['drones'][did]['status']=='held'
        assert resources(core)[did] == before[did]
    write(OUT / 'in-progress-hold.json', {'impact':impact, 'before':before, 'after':resources(core), 'metrics':core.metrics()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wolfram', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ground = json.loads((ROOT / 'docs/evidence/inspection-0.0.2/part12/ground-context.json').read_text())
    runs = []
    for size in (2,50):
        pair = [run_case(size, ground, reported) for reported in (False,True)]
        assert pair[0]['initial_state_sha256'] == pair[1]['initial_state_sha256']
        runs.extend(pair)
        print(f'{size} drones: matched initial state, report/reject/reallocate/save/reopen passed', flush=True)
    in_progress(ground)
    live = [numerical(size, ground) for size in (2,50)] if args.wolfram else []
    paths = ['stratus/contracts/fleet_v1.py','stratus/hazards/core.py','stratus/hazards/fleet_adapter.py','stratus/hazards/integration.py',
             'stratus/inspection/fleet.py','stratus/inspection/fleet_costs.py','stratus/inspection/fleet_service.py',
             'stratus/inspection/fleet_report.py','stratus/inspection/dashboard.py','stratus/inspection/web/hazards.js',
             'stratus/inspection/web/hazards.css','stratus/inspection/web/fleet.js','stratus/inspection/web/fleet.html',
             'stratus/inspection/wolfram/fleet_costs.wls','tests/test_joined_hazards.py','scripts/verify_joined_hazards.py']
    summary = {'created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed',
               'implementation':'actual Part 12 FleetSession and LiveFleetHazards, not the fixture host',
               'runs':[{k:r[k] for k in ('fleet_size','reported','initial_state_sha256','exact_active_save_reopen','resumed_outcome_exact','affected_drone_ids','reassigned_task_count','held_drone_ids','metrics','calculation_modes')} for r in runs],
               'live_numerical_status':[{'fleet_size':r['fleet_size'],'status':r['status'],'calls':r['calls']} for r in live],
               'cloud_requests':0,'alpha_calls':0,'source_checksums':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
               'limits':['This command does not run Part 12 scaling/baselines or the full regression suite.',
                         'Browser verification is recorded separately.','No physical station was polled; the original ground snapshot was reused.']}
    write(OUT / 'verification.json', summary)
    print(json.dumps({'status':summary['status'],'live_numerical':summary['live_numerical_status']}),flush=True)


if __name__ == '__main__':
    main()
