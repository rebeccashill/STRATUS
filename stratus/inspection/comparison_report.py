"""Portable comparison report with explicit weak results and separate numerical evidence."""

import base64
import csv
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

from .comparison import load_frozen


def save_report(root,folder,results):
    root,folder=Path(root),Path(folder);spec,_,context,receipt=load_frozen(root,folder)
    local=json.loads((folder/'numerical-local.json').read_text())
    live=json.loads((folder/'numerical-live.json').read_text()) if (folder/'numerical-live.json').exists() else {
        'status':'not run','evidence_kind':'No Part 8 live Wolfram boundary call yet',
        'request_counts':{'local_kernel_calls':0,'cloud_requests':0,'alpha_calls':0},
        'account_credit_consumption':'Unknown; account usage was not retrieved.','boundaries':[]}
    parity=json.loads((folder/'sensor-parity.json').read_text())
    summary=[{'case':r['case_id'],'method':r['method'],**r['metrics'],
              'method_wall_seconds':r['method_wall_seconds'],'ground_snapshot_id':r['ground_snapshot_id']} for r in results]
    notes=[]
    for case in spec['cases']:
        rows=[r for r in results if r['case_id']==case['case_id']];best=max(r['metrics']['usable_priority'] for r in rows)
        winners=[r['method'] for r in rows if r['metrics']['usable_priority']==best]
        adaptive=next(r for r in rows if r['method']=='adaptive');nearest=next(r for r in rows if r['method']=='nearest-feasible')
        notes.append({'case':case['case_id'],'coverage_leaders_or_ties':winners,'best_usable_priority':best,
            'adaptive_energy':adaptive['metrics']['total_energy_including_return'],
            'nearest_energy':nearest['metrics']['total_energy_including_return'],
            'adaptive_uses_more_energy_than_nearest':adaptive['metrics']['total_energy_including_return']>nearest['metrics']['total_energy_including_return']+1e-8})
    example=next((s for r in results if r['case_id']=='unclear' and r['method']=='adaptive' for s in r['steps']
                  if s['decision']=='capture' and s['selected']['asset_id']=='P03' and s['selected']['view_id']=='follow-up'),None)
    report={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'spec':spec,'freeze_receipt':receipt,
        'results':summary,'exceptions_and_ties':notes,'illustrative_decision':example,
        'numerical_local':local,'numerical_live':live,'sensor_parity':parity,'ground_context':context,
        'image_assessment_accuracy':None,'all_runs_saved':len(results)==9,
        'limits':['Three authored cases, deterministic adaptive rule, no live LLM or vision evaluation',
                  'Scripted review task handling is not actual human review or defect validation',
                  'Ground sensor availability/calibration are not planner-performance gains',
                  'No universal superiority, real flight or aircraft endurance claim']}
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'comparison-results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (folder/'comparison-results.csv').open('w',newline='',encoding='utf-8') as stream:
        fields=['case','method','usable_priority','eligible_priority','new_usable_priority_gain','captures','distinct_new_assets',
                'total_energy_including_return','travel_metres_including_return','open_scripted_review_tasks','violations','final_status']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(summary)
    h=lambda value:escape(str(value),quote=True)
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>STRATUS — Fair planner comparison</title><style>:root{color-scheme:dark}body{background:#000;color:#f4f4f7;font:15px/1.6 "IBM Plex Sans","Segoe UI",Arial,Helvetica,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px}h1{font-size:34px;line-height:1.15}h2{color:#ffb21a;margin-top:36px}h3{font-size:17px}small,.muted{color:#a5a6b0}a{color:#ffb21a}.eyebrow,th,code{font-family:"IBM Plex Mono","Cascadia Mono",Consolas,"Liberation Mono",monospace}.eyebrow{font-size:11px;color:#ffb21a;letter-spacing:1.5px}.note{padding:16px;background:#09090b;border:1px solid #3d3f47;border-left:3px solid #ffb21a;border-radius:4px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:10px 9px;text-align:left;vertical-align:top;border-bottom:1px solid #3d3f47}th{font-size:10px;color:#c4c4cc;background:#09090b}td.num{font-variant-numeric:tabular-nums;white-space:nowrap}code{font-size:11px;overflow-wrap:anywhere}.images{display:flex;gap:20px;flex-wrap:wrap}.images figure{margin:0;max-width:460px;flex:1;min-width:260px}img{width:100%;border:1px solid #3d3f47}figcaption{font-size:12px;color:#c4c4cc}.box{border:1px solid #3d3f47;padding:16px;margin:16px 0}pre{white-space:pre-wrap;font-size:11px}@media print{body{background:white;color:black}h2{color:#805600}th,td{border-color:#888}}</style>',
        '<div class="eyebrow">STRATUS / PART 8 / FROZEN COMPARISON</div><h1>What changes when the next view adapts?</h1>',
        '<p class="note">Nine runs. Three authored cases. One cost model, one action cap, one fixed Recorded ground snapshot. Adaptive means the deterministic rule used by STRATUS, with the same scripted review policy for every method. This is not an evaluation of live AI image accuracy.</p>',
        f'<p><small>Inputs frozen {h(spec["frozen_at_utc"])} · report generated {h(report["generated_at_utc"])}<br>Spec SHA256 <code>{h(receipt["spec_sha256"])}</code></small></p>',
        '<h2>All nine results</h2><p>Usable priority counts each eligible asset once when any available image is clear. Common priors are included; gain shows only improvement above those priors. Denominator is 11 priority units. A follow-up uses an action and cannot double-count an asset.</p>',
        '<div class="scroll"><table><tr><th>Case</th><th>Method</th><th>Usable priority</th><th>New gain</th><th>Captures</th><th>Distinct captured assets</th><th>Total energy incl. return</th><th>Travel incl. return</th><th>Open scripted tasks</th><th>Violations</th></tr>']
    for r in summary:
        parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [r['case'],r['method'],f"{r['usable_priority']}/{r['eligible_priority']}",
            r['new_usable_priority_gain'],r['captures'],r['distinct_new_assets'],f"{r['total_energy_including_return']:.3f} EU",
            f"{r['travel_metres_including_return']:.3f} m",r['open_scripted_review_tasks'],r['violations']])+'</tr>')
    parts.append('</table></div><p>EU are invented simulated energy units. All methods explicitly return to launch; return energy is debited once and the reserve remains protected. Violations are checked by the same engine for every method.</p><h2>Ties, weak results and tradeoffs</h2>')
    for note in notes:
        text=f"{note['case']}: usable-priority leaders/ties are {', '.join(note['coverage_leaders_or_ties'])} at {note['best_usable_priority']}/11."
        if note['adaptive_uses_more_energy_than_nearest']:
            text+=f" Adaptive uses more modeled energy than nearest-feasible ({note['adaptive_energy']:.3f} vs {note['nearest_energy']:.3f} EU); that weaker result is retained."
        if note['case']=='low-battery':text+=' All methods execute zero new captures and gain zero usable priority; remaining actions cannot compensate for insufficient energy.'
        parts.append('<p>'+h(text)+'</p>')
    parts.append('<p class="note">These results do not establish universal superiority. Clear-case coverage can tie while routes differ in travel. An uncertainty-reducing follow-up can improve weighted coverage while visiting fewer distinct assets. Old unclear images remain unknown and their review tasks can remain open.</p><h2>What was fixed before measuring?</h2><ul>')
    for key in ('fixed_order_rule','nearest_rule','adaptive_rule','common_review_policy','common_guards','follow_up_policy','ground_rule','cache_policy'):
        parts.append('<li>'+h(spec[key])+'</li>')
    parts.append('</ul><p>No random seed is needed: all choices are deterministic. No weights were tuned after the freeze. Excluded P06 stays excluded. Method wall times are logged for traceability, not treated as stable speed benchmarks.</p>')
    if example:
        parts.append('<h2>One illustrative decision</h2><p>After receiving the unclear P03 overview, the adaptive method compares a distinct P03 follow-up with another eligible asset at the same revision. The following costs are the actual saved step, not a universal claim.</p><table><tr><th>Option</th><th>Priority</th><th>Outbound</th><th>Capture</th><th>Return</th><th>Reserve</th><th>Margin</th></tr>')
        for candidate in (example['selected'],example['alternative']):
            if candidate:parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [candidate['asset_id']+'/'+candidate['view_id'],candidate['priority'],*[f'{candidate[k]:.3f}' for k in ('outbound','capture','return_cost','reserve','margin')]])+'</tr>')
        parts.append('</table><p>One additional action yielded clear follow-up evidence, so P03 became usable for coverage. The original overview remained unknown. Scripted task resolution does not imply actual human review.</p><div class="images">')
        case=next(c for c in spec['cases'] if c['case_id']=='unclear')
        from .loader import load_mission
        mission=load_mission(root/case['mission_path'],project_root=root)
        for view,label in [('overview','Original overview: authored occlusion, finding unknown'),('follow-up','Distinct follow-up: clear authored illustration, no real defect diagnosis')]:
            evidence=mission.evidence_by_view['P03',view];encoded=base64.b64encode(evidence.image_path.read_bytes()).decode()
            parts.append(f'<figure><img alt="P03 {h(view)} synthetic fixture" src="data:image/png;base64,{encoded}"><figcaption>{h(label)}<br>SHA256 <code>{h(evidence.record["sha256"])}</code></figcaption></figure>')
        parts.append('</div>')
    parts.append('<h2>Numerical verification — separate from planner scores</h2><p>All nine planner runs use the same local Python adapter with a fresh calculator per run. No Wolfram cache, LLM provider or live sensor timing can benefit one planner. The following independent checks verify the declared arithmetic.</p>')
    parts.append(f'<p>Local boundaries/units: <b>{h(local["status"])}</b>. Live Wolfram: <b>{h(live["status"])}</b>.</p><table><tr><th>Boundary</th><th>Expected feasible</th><th>Python margin</th><th>Wolfram margin</th><th>Live status</th><th>Latency</th></tr>')
    live_rows={r['name']:r for r in live.get('boundaries',[])}
    for row in local['boundaries']:
        actual=live_rows.get(row['name'],{});value=actual.get('wolfram')
        parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [row['name'],row['expected']['expected_feasible'],f"{row['python']['margin']:.9f}",
             f"{value['margin']:.9f}" if value else 'unrun/unavailable',actual.get('status','unrun'),f"{actual['latency_seconds']:.3f} s" if 'latency_seconds' in actual else '—'])+'</tr>')
    parts.append('</table><p>Absolute tolerance 1e-8 and relative tolerance 1e-10; feasibility sign is strict. Metre/kilometre normalization is explicit. Exhaustion, stale cache, timeout/quota/access failures, malformed response and material disagreement have separate labeled injection evidence; mismatch blocks capture.</p>')
    parts.append('<p>Actual numerical request counts: '+h(live['request_counts'])+'. '+h(live['account_credit_consumption'])+' Arithmetic parity is not aircraft endurance or inspection accuracy validation.</p>')
    parts.append(f'<h2>Ground input and sensor checks</h2><p><code>{h(context["snapshot_id"])}</code><br>Recorded · node {h(context["node_id"])} · location not supplied · original measurement times retained. Freshness is frozen at {h(context["as_of_utc"])}. Ground values never change aircraft costs, exclusions or image findings.</p><table><tr><th>Sensor/variable</th><th>Value / unit</th><th>Acquired UTC</th><th>Source</th></tr>')
    for row in context['observations']:
        parts.append(f'<tr><td>{h(row["sensor_model"])} / {h(row["variable"])}</td><td>{h(row["value"])} {h(row["unit"])}</td><td>{h(row["acquired_at_utc"])}</td><td><code>{h(row["provenance"]["source_file"])}</code></td></tr>')
    parts.append('</table><p>All six actual raw CSV rows match normalized data, the shared presentation function and report context by ID, value, unit and acquisition/receipt times. Ground and USB tests cover invalid/non-finite values, labels, units, missing drivers/device, partial availability, stale time, duplicates, reconnect and offline replay. Physical recovery is documented separately; this comparison performs no new hardware read and makes no calibration claim.</p><h2>Evidence and limits</h2>')
    parts.append('<p>Complete per-run JSON, the CSV summary, frozen input hashes, numerical inputs/outputs, sensor parity and test logs are in <code>docs/evidence/inspection-0.0.2/part8/</code>. No image-flag accuracy is reported: there is no independent human ground-truth set. Three authored cases cannot establish real-world effectiveness.</p></html>')
    reports=root/'saved-runs/reports';reports.mkdir(parents=True,exist_ok=True)
    path=reports/'comparison-part8.html';path.write_text(''.join(parts),encoding='utf-8')
    (reports/'comparison-part8.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return {'html':path.relative_to(root).as_posix(),'json':'saved-runs/reports/comparison-part8.json','report':report}
