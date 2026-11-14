"""Self-contained inspection report: evidence, operator feedback and separate ground context."""

import base64
import copy
from html import escape
import json
from pathlib import Path

from .loader import check_image
from .review import utc_time


def build_report(workflow,calculation):
    run=workflow.snapshot();mission=workflow.session._mission
    assessments=[]
    for original in run["assessments"]:
        a=copy.deepcopy(original);e=mission.evidence_by_view.get((a["asset_id"],a["view_id"]))
        try:
            if e is None:raise ValueError("No mapped evidence")
            check_image(e,mission.project_root)
            a["image_data_url"]="data:image/png;base64,"+base64.b64encode(e.image_path.read_bytes()).decode()
            a["evidence_available"]=True
        except (OSError,ValueError):a.update(evidence_available=False,image_data_url=None)
        a["effective_quality"]=a["image_quality"] if a["evidence_available"] else "unknown"
        a["effective_finding"]=(a["finding"] if a["evidence_available"] and a["image_quality"]=="clear" else "unknown")
        a["interpretation"]="Authored synthetic replay; human review required. Operator resolution changes task status only."
        assessments.append(a)
    return {"report_version":"stratus-inspection-report-1","generated_at_utc":utc_time().isoformat(),
            "mission_id":mission.document["mission_id"],"mission_revision":mission.document["revision"],"run_id":run["run_id"],
            "execution_mode":"simulated_aircraft_and_capture","assessment_mode":"authored_replay_annotation_not_live_vision",
            "aircraft_state":run["aircraft_state"],"assets":run["assets"],"assessments":assessments,
            "feedback":run["feedback"],"actions":run["events"],"plans":run["plan_history"],"what_if":run["what_if_history"],
            "ground_snapshots":run["ground_snapshots"],"computation":copy.deepcopy(calculation),
            "unresolved_work":[a for a in run["assets"] if a["unresolved"]],
            "human_follow_up":[a for a in assessments if a["operator_review_status"]!="resolved" or a["effective_finding"].startswith("unknown")],
            "limitations":["No real flight, thermal/electrical fault diagnosis, sensor calibration or inspection accuracy validation",
                           "Unknown or unclear evidence is not a no-defect result",
                           "Ground context cannot change aircraft costs/actions or establish a visual diagnosis",
                           "Developer accounts and driver errors belong to technical evidence, not mission energy"]}


def render_html(report):
    h=lambda v:escape(str(v if v is not None else "unknown"),quote=True)
    labels={"temperature":"Temperature","relative_humidity":"Relative humidity","pressure":"Pressure","pm1_0":"Environmental PM1.0","pm2_5":"Environmental PM2.5","pm10":"Environmental PM10"}
    units={"degC":"°C","%RH":"%RH","hPa":"hPa","ug/m3":"µg/m³"}
    state=report["aircraft_state"]
    review_labels={'accept_concern':'Accepted for human review','resolve':'Task resolved; image finding unchanged','request_view':'Requested another view'}
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>STRATUS inspection report</title><style>:root{color-scheme:dark}body{font:15px/1.65 "IBM Plex Sans","Segoe UI",Arial,Helvetica,sans-serif;color:#f4f4f7;background:#000;max-width:1150px;margin:36px auto;padding:0 22px}h1{font-size:32px;line-height:1.15}h2{color:#ffb21a;margin-top:35px;font-size:22px}h3{font-size:17px}table{border-collapse:collapse;width:100%;margin:15px 0;font-size:13px}td,th{border-bottom:1px solid #3d3f47;text-align:left;padding:10px;vertical-align:top}th{background:#09090b;font:11px/1.5 "IBM Plex Mono",Consolas,monospace;color:#c4c4cc}.note{background:#09090b;border:1px solid #3d3f47;border-left:3px solid #ffb21a;padding:16px;border-radius:4px}.evidence{border-top:1px solid #3d3f47;padding:20px 0;break-inside:avoid}img{max-width:480px;width:100%;border:1px solid #3d3f47}code{overflow-wrap:anywhere;font-family:"IBM Plex Mono",Consolas,monospace;font-size:12px}small{color:#c4c4cc}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.report-table{overflow-x:auto}summary{cursor:pointer;color:#c4c4cc}a{color:#ffb21a}@media(max-width:600px){body{padding:0 16px}h1{font-size:27px}table{font-size:12px}}@media print{body{margin:0;color:#111;background:white}h2{color:#805600}th{background:#eee;color:#111}.note{background:#fff;color:#111}details{display:block}}</style>',
           '<h1>STRATUS inspection report</h1>',f'<p>{h(report["mission_id"])} · {h(report["mission_revision"])} · <code>{h(report["run_id"])}</code><br>Generated {h(report["generated_at_utc"])}</p>',
           '<p class="note">Simulated aircraft, capture and battery. Images are self-authored synthetic illustrations; assessments are annotated replay. Concern flags remain tentative. Ground measurements have independent source/time/location labels.</p>',
           f'<h2>Mission resources</h2><p>Battery <b>{state["battery_available"]:.2f} simulated units</b> · {state["actions_remaining"]} capture action(s) left · position ({state["position"]["x"]:.2f}, {state["position"]["y"]:.2f}) m · aircraft revision {state["revision"]}.</p>',
           '<h2>Asset evidence and review</h2>']
    for a in report["assessments"]:
        finding="Unknown — insufficient or unreviewed evidence" if a["effective_finding"].startswith("unknown") else "Tentative concern — human review required" if a["effective_finding"]=="apparent_concern_review_required" else "No apparent concern in authored replay; not a diagnosis"
        parts.extend([f'<section class="evidence"><h3>{h(a["asset_id"])} / {h(a["view_id"])}</h3>',
                      f'<p>Quality: <b>{h(a["effective_quality"])}</b> · {h(finding)}<br>Operator task status: {h(a["operator_review_status"].replace("_"," "))}</p>'])
        parts.append(f'<img alt="{h(a["asset_id"])} {h(a["view_id"])} synthetic illustration" src="{a["image_data_url"]}">' if a["image_data_url"] else '<p>Evidence unavailable; finding remains unknown.</p>')
        parts.append(f'<p><small>Evidence {h((a.get("evidence_ref") or {}).get("evidence_id"))}<br>SHA256 <code>{h((a.get("evidence_ref") or {}).get("sha256"))}</code><br>{h(a["note"])}</small></p></section>')
    parts.append('<h2>Operator feedback</h2><table><tr><th>Time (UTC)</th><th>Evidence</th><th>Task action</th><th>Ground reference</th></tr>')
    for f in report["feedback"]:parts.append(f'<tr><td>{h(f["timestamp"])}</td><td>{h(f["asset_id"])}/{h(f["view_id"])}</td><td>{h(review_labels[f["action"]])}; no aircraft debit</td><td><code>{h(f["ground_context_id"])}</code></td></tr>')
    parts.append('</table><h2>Next actions and cost calculation</h2><p>Wolfram results are independently checked by Python. Cached Wolfram reuses an exact-input result. Local Python and Python fallback are labeled separately. Numerical agreement does not validate real aircraft endurance.</p>')
    for p in report["plans"]:
        c=p["computation"];heading=('Proposed '+p['proposal']['asset_id']+'/'+p['proposal']['view_id']) if p['proposal'] else 'Hold for review';parts.append(f'<h3>{h(heading)} · {h(p["plan_id"])}</h3><p>{h(p["reason"])}<br>Aircraft revision {p["state_revision"]}; review revision {p["review_revision"]}; {h(c["model_version"])} / {h(c["mode"])}<br>Ground <code>{h(p["ground_context_id"])}</code></p>')
        parts.append('<table><tr><th>Candidate</th><th>Priority</th><th>Travel to view</th><th>Take image</th><th>Return to launch</th><th>Protected reserve</th><th>Energy after reserve</th></tr>')
        for candidate in (p["selected"],p["alternative"]):
            if candidate:parts.append('<tr>'+''.join('<td>'+h(v)+'</td>' for v in [candidate['asset_id']+'/'+candidate['view_id'],candidate['priority'],*[f'{candidate[k]:.3f}' for k in ('outbound','capture','return_cost','reserve','margin')]])+'</tr>')
        parts.append('</table><p>Distances in m; costs in simulated energy units. Disagreements: '+h(c['disagreements'])+'</p>')
    parts.append('<h2>Actions and rejections</h2><table><tr><th>Evidence/action</th><th>Result</th><th>Resource change</th><th>Context</th></tr>')
    for e in report['actions']:
        p=e['proposal'];parts.append(f'<tr><td>{h(p["asset_id"] or p["action_type"])}/{h(p["view_id"])}</td><td>{h(e["status"])} · {h(e.get("decision",{}).get("message",e.get("code")))}</td><td>Energy {h(e.get("battery_debit",0))}; capture actions {h(e.get("capture_action_debit",0))}</td><td><code>{h(e.get("ground_context_id","Historical action; no newer context attached"))}</code></td></tr>')
    parts.append('</table><h2>Ground conditions — frozen decision context</h2>')
    groups={}
    for context in report['ground_snapshots'].values():
        key=json.dumps([context['source_mode'],context['node_id'],context['location'],context['observations']],sort_keys=True)
        groups.setdefault(key,[]).append(context)
    for contexts in groups.values():
        context=contexts[0];location=context['location']
        location_text=location.get('label') or ('Location not supplied' if location['status']=='unknown' else str(location.get('position'))+' '+str(location.get('coordinate_frame')))
        parts.append(f'<h3>{h(context["source_label"])} ground measurements</h3><p>Node {h(context["node_id"])} · {h(location_text)}. Identical readings are shown once; every decision reference is retained below.</p>')
        parts.append('<table><tr><th>Sensor</th><th>Quantity</th><th>Value / unit</th><th>Acquired / received (UTC)</th></tr>')
        for row in context['observations']:
            parts.append(f'<tr><td>{h(row["sensor_model"])}</td><td>{h(labels[row["variable"]])}</td><td>{float(row["value"]):.2f} {h(units[row["unit"]])} · {h(row["quality"]["status"])}</td><td>{h(row["acquired_at_utc"])}<br>{h(row["received_at_utc"])}</td></tr>')
        parts.append('</table><p>Calibration and uncertainty remain unknown when unverified. Live describes the original acquisition, not a new measurement when reopening this report.</p><details><summary>Decision snapshot references and original CSV sources</summary>')
        for c in contexts:
            statuses=', '.join(x['sensor_model']+': '+x['status'] for x in c['sensors'])
            parts.append(f'<p><code>{h(c["snapshot_id"])}</code><br>Frozen at {h(c["as_of_utc"])} · {h(statuses)}</p>')
        sources=sorted({(r['sensor_id'],r['provenance']['source_file'],r['provenance']['source_sha256']) for r in context['observations']})
        for sensor,source,checksum in sources:
            parts.append(f'<p>{h(sensor)} · CSV <code>{h(source)}</code><br>SHA256 <code>{h(checksum)}</code></p>')
        parts.append('</details>')
    parts.append('<h2>What-if — read-only comparisons</h2>')
    for p in report['what_if']:
        parts.append(f'<p><code>{h(p["preview_id"])}</code> · aircraft revision {p["state_revision"]}, review revision {p["review_revision"]}, mission {h(p["mission_revision"])}<br>Reserve {p["reserve"]}, capture cost {p["capture_cost"]} simulated units · {h(p["mode"])} / {h(p["model_version"])}<br>{h(p["explanation"])} Removed feasible candidates: {h(p["removed_candidates"])}. No capture or setting change was applied.</p>')
    parts.append('<h2>Unresolved work and human follow-up</h2><ul>')
    for a in report['unresolved_work']:parts.append(f'<li>{h(a["asset_id"])}: {h(a["coverage_status"])}; {h(a["unresolved"])}</li>')
    parts.append('</ul><h2>Limits</h2><ul>'+''.join('<li>'+h(x)+'</li>' for x in report['limitations'])+'</ul></html>')
    return ''.join(parts).replace('<table', '<div class="report-table"><table').replace('</table>', '</table></div>')


def save_report(workflow,calculation,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    result=build_report(workflow,calculation)
    stem="inspection-"+result['run_id'][4:12]+"-"+utc_time().strftime('%Y%m%dT%H%M%S%fZ')
    html=folder/(stem+'.html');data=folder/(stem+'.json')
    html.write_text(render_html(result),encoding='utf-8')
    data.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return {'html':html.name,'json':data.name,'report':result}
