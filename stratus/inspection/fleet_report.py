"""Portable fleet evidence, resource limits and allocation details."""
import base64
from datetime import datetime,timezone
from html import escape
import json
from pathlib import Path

def save_fleet_report(core,root):
    root=Path(root);state=core.snapshot();m=state['metrics'];h=lambda v:escape(str(v),quote=True)
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>STRATUS fleet report</title>',
      '<style>:root{color-scheme:dark}body{background:#000;color:#f4f4f7;font:15px/1.6 "IBM Plex Sans","Segoe UI",sans-serif;max-width:1200px;margin:35px auto;padding:0 22px}h1{font-size:34px;line-height:1.15}h2,a{color:#ffb21a}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border-bottom:1px solid #3d3f47;padding:9px;text-align:left}th{background:#09090b}.scroll{overflow:auto}.note{border:1px solid #3d3f47;border-left:3px solid #ffb21a;padding:15px;background:#09090b}code,pre{font-family:"IBM Plex Mono",Consolas,monospace;font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}img{width:100%;max-width:400px}small{color:#c4c4cc}summary{cursor:pointer}section{margin:25px 0}</style>',
      '<h1>STRATUS Fleet Intelligence</h1><p class="note">Independent simulated aircraft, modeled battery and replay image evidence. One ground station is separate context. Exclusive task allocation does not establish collision avoidance, real flight or a panel diagnosis.</p>',
      f'<p>{m["fleet_size"]} drones / seed {m["seed"]} / {h(m["method"])} / {h(state["status"])} / {m["logical_seconds"]:.3f} simulated seconds.</p>',
      f'<h2>Outcome</h2><p>{m["captures"]} simulated captures; {m["drone_participation"]}/{m["fleet_size"]} drones participated. {m["unique_usable_assets"]}/200 unique usable assets, weighted priority {m["usable_priority"]}/{m["total_priority"]}. {m["unresolved_assets"]} assets still need usable evidence; {m["human_review_pending"]} replay assessments await human review.</p>',
      f'<p>Total modeled energy {m["total_energy_EU"]:.3f} EU, travel including return {m["travel_metres"]:.3f} m. Each drone starts with 100 EU, retains 15 EU reserve and has at most three new captures. More drones bring more total resources; coverage growth is not proof of algorithm superiority. {h(m["stop_reason"])}</p>',
      '<h2>Every independent drone</h2><div class="scroll"><table><tr><th>Drone</th><th>Status</th><th>Position (m)</th><th>Battery EU</th><th>Reserve EU</th><th>Captures / cap</th><th>Current task</th><th>Reason</th></tr>']
    for d in state['drones'].values():parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [d['drone_id'],d['status'],f"({d['position']['x']:.2f}, {d['position']['y']:.2f})",f"{d['battery']:.3f}",d['reserve'],f"{d['actions_used']}/3",d['task_id'] or '-',d['reason']])+'</tr>')
    parts.append('</table></div><h2>Evidence and unresolved work</h2><p>Coordinates/tasks are unique. The illustrative P04/P05 images below are reused across the seeded 200-asset synthetic workload; they are not independent site photographs. An unclear overview remains unknown even after a clear distinct follow-up.</p>')
    for asset,label in [('P05','Representative unclear overview'),('P04','Representative clear illustration')]:
        p=root/'evidence/inspection/images'/(asset+'-overview.png')
        parts.append('<figure><img alt="'+label+'; reused synthetic illustration" src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'"><figcaption>'+label+'; no real defect diagnosis.</figcaption></figure>')
    parts.append('<details><summary>Every captured asset/view and its ground reference</summary><div class="scroll"><table><tr><th>Task</th><th>Drone</th><th>Quality / finding</th><th>Simulated capture time</th><th>Ground snapshot</th></tr>')
    for e in state['evidence'].values():parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [e['task_id'],e['drone_id'],e['image_quality']+' / '+e['finding'],e['simulated_capture_time'],e['ground_snapshot_id']])+'</tr>')
    parts.append('</table></div></details><h2>One shared ground station</h2>')
    g=state['ground']
    if g:
        parts.append(f'<p>Frozen {h(g["source_label"])} context / node {h(g["node_id"])} / {h(g["location"].get("label") or "Location not supplied")}. Original times below; no new sample is acquired by opening this report. Not 50 airborne sensors, wind or flight clearance.</p><table><tr><th>Quantity</th><th>Value / unit</th><th>Original acquisition UTC</th></tr>')
        for o in g['observations']:parts.append(f'<tr><td>{h(o["sensor_model"])} / {h(o["variable"])}</td><td>{h(o["value"])} {h(o["unit"])}</td><td>{h(o["acquired_at_utc"])}</td></tr>')
        parts.append('</table><p>Unreviewed observations; calibration and uncertainty unverified. Ground loss/refresh never changes aircraft budgets or diagnoses panel defects.</p>')
    else:parts.append('<p>Unavailable ground context. No inferred measurements.</p>')
    parts.append('<h2>Reported temporary obstructions</h2><p>Registry revision '+h(state['hazards']['revision'])+'. Operator reports and synthetic events are separate from environmental measurements. Expired reports remain restricted until explicit clearance.</p>')
    if state['hazards']['hazards']:
        parts.append('<table><tr><th>Reported area</th><th>State / source</th><th>Local rectangle and buffer (m)</th><th>Observed / reported UTC</th><th>Reason</th></tr>')
        for zone in state['hazards']['hazards']:
            parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [zone['hazard_id'],zone['state']+' / '+zone['source'],json.dumps(zone['rectangle']),zone['observed_at_utc']+' / '+zone['reported_at_utc'],zone['notes']])+'</tr>')
        parts.append('</table>')
    else:parts.append('<p>No reported areas are loaded. An empty registry is not proof the real environment is obstacle-free.</p>')
    if state['hazard_assessments']:
        impact=state['hazard_assessments'][-1]
        parts.append('<p>'+h(impact['assessed_count'])+' fleet records assessed; '+h(impact['affected_count'])+' affected at revision '+h(impact['hazard_revision'])+'. In-progress logical segments held for review: '+h(impact['review_required_drone_ids'])+'.</p><details><summary>Per-drone paths, revisions and reasons</summary><pre>'+h(json.dumps(impact,indent=2))+'</pre></details>')
    parts.append('<h2>Costs, allocation and model limits</h2><p>The bounded greedy shortlist uses six nearby and four high-priority tasks per drone, at most 500 pairs. Stable ties and an allocation wave barrier are declared before measuring. Python rechecks ownership, revisions, cap, budget, numerical agreement and the reported-hazard gate at commit. Event positions are last completed logical waypoints; no continuous flight physics or validated separation is modeled.</p>')
    modes=sorted({a['calculation']['mode'] for a in state['allocations'] if a['calculation']})
    parts.append(f'<p>Observed calculation modes: {h(modes)}. Local kernel counter for this calculator instance: {m["local_kernel_calls"]}; cloud/Alpha requests 0/0. Account credit consumption unknown; not inferred from local counters. AI requests: {m["ai_requests"]}. AI explanations never execute aircraft actions.</p>')
    parts.append('<details><summary>Allocation reasons, alternatives, revisions and numerical evidence</summary>')
    for a in state['allocations']:
        parts.append(f'<h3>Round {a["round"]}: {len(a["selected"])} distinct assignments from {len(a["shortlist"]["pairs"])} pairs</h3><p>Calculation: {h(a["calculation"]["mode"] if a["calculation"] else "no candidates")}; allocation wall time {a["wall_seconds"]:.6f}s; ownership conflicts skipped {len(a["ownership_conflicts_skipped"])}.</p><pre>'+h(json.dumps(a['selected'],indent=2))+'</pre>')
    parts.append('</details><p>No real autopilot, aircraft communications, 3D physics, multi-site environmental inference or solver-optimality claim. Reported 2D areas gate simulated proposals; they do not establish automatic crane detection, real trajectory separation or accident prevention.</p></html>')
    folder=root/'saved-runs/reports';folder.mkdir(parents=True,exist_ok=True)
    stem='fleet-'+state['run_id'][6:14]+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (folder/(stem+'.html')).write_text(''.join(parts),encoding='utf-8');(folder/(stem+'.json')).write_text(json.dumps(state,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return {'html':stem+'.html','json':stem+'.json','view':'/api/report/view?name='+stem+'.html','download':'/api/report/download?name='+stem+'.html'}
