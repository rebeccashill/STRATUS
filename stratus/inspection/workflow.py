"""Feedback, frozen ground references and explicit adaptive proposals; no hidden capture."""

import copy
from dataclasses import replace
import hashlib
import json
import re
from uuid import uuid4

from .actions import Proposal
from .agent import BoundedTools, run_agent
from .computation import compute_mission_options, normalize_input, python_costs, _check_reply
from .engine import plain
from .ground import present_snapshot, MODE_LABELS
from .loader import freeze
from .review import _utc_string, utc_time

KIND="adaptive_workflow_v1"
FEEDBACK={"accept_concern","resolve","request_view"}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def freeze_context(snapshot):
    shown=present_snapshot(snapshot)
    data={"context_role":"ground_context_only","source_mode":shown["mode"],"source_label":shown["source_label"],
          "as_of_utc":shown["presented_at_utc"],"node_id":shown.get("node_id"),"location":shown["location"],
          "observations":shown["observations"],"sensors":[{k:s[k] for k in ("sensor_model","sensor_id","status","age_seconds","channels")} for s in shown["sensors"]],
          "source":shown.get("source"),"frozen_for_decision":True,
          "limitations":["Ground node context only; not simulated aircraft position","Location/calibration/uncertainty may be unknown",
                         "Not wind, flight clearance, airborne conditions or panel diagnosis","Freshness is evaluated at snapshot time; replay retains original measurement times"]}
    data["snapshot_id"]="ground-"+digest(data)
    return data


def validate_context(context):
    data=copy.deepcopy(context);identifier=data.pop("snapshot_id")
    if identifier!="ground-"+digest(data) or data["context_role"]!="ground_context_only" or not data["frozen_for_decision"]:
        raise ValueError("Ground snapshot identity/role mismatch")
    _utc_string(data["as_of_utc"])
    if data["source_label"]!=MODE_LABELS.get(data["source_mode"]) or data["node_id"] not in (None,"ground-node-001"):
        raise ValueError("Ground source/node label mismatch")
    if any(s["status"] not in ("fresh","stale","invalid","unavailable","warming_up") for s in data["sensors"]):raise ValueError("Invalid per-sensor status")
    raw={"mode":data["source_mode"],"observations":data["observations"],"location":data["location"],"context_role":"ground_context_only",
         "sensor_states":{s["sensor_model"]:{"status":s["status"],"technical_error":None} for s in data["sensors"]}}
    checked=present_snapshot(raw,now=_utc_string(data["as_of_utc"]))
    if len(data["sensors"])!=2 or {s["sensor_id"] for s in data["sensors"]}!={s["sensor_id"] for s in checked["sensors"]}:raise ValueError("Ground sensor set changed")
    if checked["observations"]!=data["observations"]:raise ValueError("Saved ground observations are invalid")
    for sensor in data["sensors"]:
        match=next((s for s in checked["sensors"] if s["sensor_id"]==sensor["sensor_id"]),None)
        if match is None or sensor["channels"]!=match["channels"]:raise ValueError("Ground channel presentation changed")
    return context


class AdaptiveWorkflow:
    """Structured workflow state is saved in the existing validated checkpoint audit."""
    def __init__(self,session):
        self.session=session
        if any(not isinstance(a,dict) for a in session._audit):raise ValueError("Malformed checkpoint audit")
        saved=[a for a in session._audit if a.get("kind")==KIND]
        if len(saved)>1:raise ValueError("Duplicate workflow state")
        self.data=copy.deepcopy(saved[0]["data"]) if saved else {"feedback":[],"contexts":{},"plans":[],"previews":[]}
        try:self._validate()
        except (KeyError,TypeError,AttributeError,StopIteration,OverflowError) as exc:raise ValueError("Malformed saved workflow state") from exc

    @property
    def review_revision(self):return len(self.data["feedback"])

    def saved_ground(self):
        """Display the last frozen decision context, preserving its immutable registry entry."""
        if not self.data["contexts"]:
            return self.session.snapshot()["ground_context"]
        context = max(self.data["contexts"].values(), key=lambda c: c["as_of_utc"])
        return {"mode": context["source_mode"], "context_role": "ground_context_only",
                "status": "available" if context["observations"] else "unavailable",
                "snapshot_at_utc": context["as_of_utc"], "node_id": context["node_id"],
                "location": copy.deepcopy(context["location"]), "observations": copy.deepcopy(context["observations"]),
                "source": copy.deepcopy(context["source"]), "physical_acquisition_performed": False,
                "restored_snapshot_id": context["snapshot_id"],
                "sensor_states": {s["sensor_model"]: {"status": s["status"], "technical_error": None}
                                  for s in context["sensors"]}}

    def _sync(self):
        self.session._audit=[a for a in self.session._audit if a.get("kind")!=KIND]
        self.session._audit.append({"kind":KIND,"data":copy.deepcopy(self.data)})

    def _validate(self):
        if set(self.data)!={"feedback","contexts","plans","previews"}:raise ValueError("Invalid saved workflow fields")
        if any(not isinstance(self.data[k],list) or len(self.data[k])>256 for k in ("feedback","plans","previews")) or len(self.data["contexts"])>512:
            raise ValueError("Workflow history exceeds its bound")
        assessments={r["assessment_id"]:r for r in self.session.snapshot()["assessments"]}
        for key,context in self.data["contexts"].items():
            if key!=context["snapshot_id"]:raise ValueError("Ground registry key mismatch")
            validate_context(context)
        ids=set()
        for i,row in enumerate(self.data["feedback"]):
            if (row["action"] not in FEEDBACK or row["assessment_id"] not in assessments or row["review_revision"]!=i+1
                or row["request_id"] in ids or row["ground_context_id"] not in self.data["contexts"]):raise ValueError("Invalid saved operator feedback")
            ids.add(row["request_id"]);_utc_string(row["timestamp"])
            a=assessments[row["assessment_id"]]
            if (row["asset_id"],row["view_id"])!=(a["asset_id"],a["view_id"]):raise ValueError("Feedback evidence mismatch")
            if row["action"]=="accept_concern" and "tentative_concern" not in a["flags"]:raise ValueError("Feedback invents a concern")
            if row["action"]=="request_view" and (row["requested_view"]==a["view_id"] or (a["asset_id"],row["requested_view"]) not in self.session._mission.evidence_by_view):raise ValueError("Feedback view is not distinct/mapped")
        for row in self.data["plans"]:
            if row["ground_context_id"] not in self.data["contexts"] or row["review_revision"]>self.review_revision:raise ValueError("Plan context/review reference missing")
            calc=row["computation"];expected=python_costs(normalize_input(calc["normalized_input"]))
            if calc["mode"] in ("wolfram_local","cached_wolfram_local"):
                if _check_reply(calc["output"],expected):raise ValueError("Saved plan numerical disagreement")
            elif calc["output"]!=expected:raise ValueError("Saved plan Python costs changed")
            context=self.data["contexts"][row["ground_context_id"]]
            tool=row["context_tool"]["optional_ground_sensor_context"]
            if tool!=context:raise ValueError("AI and log ground snapshots differ")
        for preview in self.data["previews"]:
            for name in ("baseline_computation","changed_computation"):
                calc=preview[name];expected=python_costs(normalize_input(calc["normalized_input"]))
                if calc["mode"] in ("wolfram_local","cached_wolfram_local"):
                    if _check_reply(calc["output"],expected):raise ValueError("Saved preview disagreement")
                elif calc["output"]!=expected:raise ValueError("Saved preview costs changed")
        for event in self.session.snapshot()["events"]:
            if "workflow_plan_id" in event:
                plan=next((p for p in self.data["plans"] if p["plan_id"]==event["workflow_plan_id"]),None)
                if plan is None or plan["ground_context_id"]!=event["ground_context_id"]:raise ValueError("Action context reference missing")

    def context(self,ground):
        result=freeze_context(ground)
        if result["snapshot_id"] not in self.data["contexts"] and len(self.data["contexts"])>=512:raise ValueError("Ground context history full")
        self.data["contexts"][result["snapshot_id"]]=result
        return result

    def status(self,assessment_id):
        rows=[f for f in self.data["feedback"] if f["assessment_id"]==assessment_id]
        return rows[-1]["action"] if rows else "pending"

    def snapshot(self):
        run=self.session.snapshot();queue=[]
        for a in run["assessments"]:
            status=self.status(a["assessment_id"])
            a["operator_review_status"]={"resolve":"resolved","accept_concern":"accepted_for_human_review","request_view":"another_view_requested"}.get(status,"pending")
            a["can_request_view"]=any(asset==a["asset_id"] and view!=a["view_id"] and (asset,view) not in self.session.state.completed_views for asset,view in self.session._mission.evidence_by_view)
            if status=="request_view" and not a["can_request_view"]:a["operator_review_status"]="follow_up_captured_review_pending"
            queue.append(a)
        run["review_queue"]=[a for a in queue if a["operator_review_status"]!="resolved"]
        run["assessments"]=queue
        for asset in run["assets"]:
            rows=[a for a in queue if a["asset_id"]==asset["asset_id"]]
            asset["operator_review_status"]=rows[-1]["operator_review_status"] if rows else "not_inspected"
            if rows and all(a["operator_review_status"]=="resolved" for a in rows):
                asset["unresolved"]=[f for f in asset["unresolved"] if f not in ("human_review_pending","tentative_concern")]
                asset["coverage_status"]="review_resolved_finding_still_unknown" if rows[-1]["image_quality"]!="clear" or rows[-1]["finding"].startswith("unknown") else "captured_review_resolved"
        run.update(review_revision=self.review_revision,feedback=copy.deepcopy(self.data["feedback"]),
                   plan_history=copy.deepcopy(self.data["plans"]),what_if_history=copy.deepcopy(self.data["previews"]),
                   ground_snapshots=copy.deepcopy(self.data["contexts"]))
        return run

    def candidates(self,calculation,mission=None):
        mission=mission or self.session._mission;run=self.snapshot()
        latest={a["asset_id"]:a for a in run["assets"]}
        last={f["asset_id"]:f for f in self.data["feedback"]}
        requested={key:f["requested_view"] for key,f in last.items() if f["action"]=="request_view"}
        delegated={key for key,f in last.items() if f["action"]=="accept_concern"}
        checks={(c["asset_id"],c["view_id"]):c for c in calculation["action_checks"]}
        priorities={a["asset_id"]:a["priority"] for a in mission.document["assets"]}
        result=[]
        for c in calculation["output"]["options"]:
            item=dict(c,priority=priorities[c["asset_id"]],execution_allowed=checks[c["asset_id"],c["view_id"]]["execution_allowed"],reason_code=checks[c["asset_id"],c["view_id"]]["code"])
            asset=latest[c["asset_id"]]
            if c["asset_id"] in delegated or asset["coverage_status"]=="captured_review_resolved":
                item.update(execution_allowed=False,reason_code="operator_review_handled")
            item["operator_requested"]=requested.get(c["asset_id"])==c["view_id"]
            item["unclear_follow_up"]=asset["image_quality"]!="clear" and c["view_id"]=="follow-up"
            result.append(item)
        return result

    def selection(self,calculation,mission=None):
        items=self.candidates(calculation,mission)
        allowed=sorted([c for c in items if c["execution_allowed"]],key=lambda c:(-int(c["operator_requested"]),-c["priority"],-int(c["unclear_follow_up"]),c["outbound"]+c["capture"],c["asset_id"],c["view_id"]))
        return items,allowed

    def pending_hold(self):
        return [a for a in self.session.snapshot()["assessments"] if "tentative_concern" in a["flags"] and self.status(a["assessment_id"])=="pending"]

    def feedback(self,assessment_id,action,*,request_id,expected_review_revision,ground):
        if action not in FEEDBACK or not isinstance(request_id,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",request_id):raise ValueError("Invalid review action/request ID")
        previous=next((f for f in self.data["feedback"] if f["request_id"]==request_id),None)
        if previous:
            if (previous["assessment_id"],previous["action"])!=(assessment_id,action):raise ValueError("Feedback idempotency conflict")
            return dict(previous,status="already_processed")
        if type(expected_review_revision) is not int or expected_review_revision!=self.review_revision:raise ValueError("Review changed; reload before submitting feedback")
        a=next((a for a in self.session.snapshot()["assessments"] if a["assessment_id"]==assessment_id),None)
        if a is None:raise ValueError("Review evidence not found")
        if action=="accept_concern" and "tentative_concern" not in a["flags"]:raise ValueError("This evidence has no tentative concern to accept")
        target=None
        if action=="request_view":
            target=next((v for asset,v in self.session._mission.evidence_by_view if asset==a["asset_id"] and v!=a["view_id"] and (asset,v) not in self.session.state.completed_views),None)
            if target is None:raise ValueError("No distinct uncaptured view is declared; retain human follow-up")
        context=self.context(ground)
        result={"request_id":request_id,"assessment_id":assessment_id,"asset_id":a["asset_id"],"view_id":a["view_id"],
                "action":action,"requested_view":target,"timestamp":utc_time().isoformat(),"review_revision":self.review_revision+1,
                "ground_context_id":context["snapshot_id"],"aircraft_state_changed":False,"interpretation":"Operator task status only; not retraining, diagnosis or proof of environmental causation"}
        if len(self.data["feedback"])>=256:raise ValueError("Feedback history full")
        self.data["feedback"].append(result);self._sync();return copy.deepcopy(result)

    def plan(self,ground,calculator,*,asset=None,view=None,mode="fallback",client=None):
        if (asset is None)!=(view is None) or mode not in ("fallback","live"):raise ValueError("Invalid plan selection/mode")
        if asset is not None and mode=="live":raise ValueError("Choose an operator-selected view or a live AI proposal separately")
        if len(self.data["plans"])>=256:raise ValueError("Plan history full")
        calc=compute_mission_options(self.session._mission,self.session.state,calculator)
        items,allowed=self.selection(calc)
        if asset is not None and not any((c["asset_id"],c["view_id"])==(asset,view) for c in allowed):
            raise ValueError("Selected view fails identity, duplicate, exclusion, review or budget checks")
        context=self.context(ground)
        review={"review_revision":self.review_revision,"feedback":copy.deepcopy(self.data["feedback"]),
                "pending_concern_hold":[a["asset_id"] for a in self.pending_hold()],"workflow_candidate_checks":items}
        tool=BoundedTools(self.session._mission,self.session.state,ground_context=context,review_context=review).call("get_mission_context","{}")
        agent=None;agent_hold=False;chosen=allowed[0] if allowed else None
        if mode=="live":
            agent=run_agent(self.session._mission,self.session.state,mode="live",client=client,ground_context=context,review_context=review)
            if agent["execution_mode"]=="live_ai":
                p=agent["proposal"];choice=next((c for c in allowed if (c["asset_id"],c["view_id"])==(p["asset_id"],p["view_id"])),None)
                if choice:chosen=choice
                elif p["action_type"] in ("return","stop"):
                    agent_hold=True;chosen=None
                else:agent.update(execution_mode="deterministic_rule_based",failure={"code":"workflow_policy_rejected","message":"AI proposal not eligible after review checks; local proposal shown for explicit operator choice"})
        if asset is not None:
            chosen=next((c for c in allowed if (c["asset_id"],c["view_id"])==(asset,view)),None)
            if chosen is None:raise ValueError("Selected view fails identity, duplicate, exclusion, review or budget checks")
        hold=self.pending_hold()
        reason=("Review the tentative concern before another capture: "+", ".join(sorted({a["asset_id"] for a in hold})) if hold else
                "AI proposed return/stop for operator review; no capture executes" if agent_hold else
                "No eligible capture remains under the current budget/actions; return or hold for human review" if chosen is None else
                "Operator selected this view; its modeled cost fits the remaining battery, action and reserve limits" if asset is not None else
                "Operator requested a distinct follow-up to clarify the earlier unclear image; its cost fits the remaining budget" if chosen["operator_requested"] and chosen["unclear_follow_up"] else
                "Operator requested a distinct view for additional evidence; its cost fits the remaining budget" if chosen["operator_requested"] else
                "A distinct follow-up reduces observed image uncertainty within the priority and resource limits" if chosen["unclear_follow_up"] else
                "Highest eligible operator priority, then observed uncertainty and modeled capture/travel cost")
        selected=None if hold else chosen
        proposal=None if selected is None else Proposal("inspect" if selected["view_id"]=="overview" else "follow_up",selected["asset_id"],selected["view_id"],reason,"Inspect another eligible asset, or return/hold if constraints fail").to_dict()
        previous=self.data["plans"][-1]["plan_id"] if self.data["plans"] else None
        result={"plan_id":"plan-"+uuid4().hex,"timestamp":utc_time().isoformat(),"previous_plan_id":previous,
                "state_revision":self.session.state.revision,"review_revision":self.review_revision,"mission_revision":self.session._mission.document["revision"],
                "ground_context_id":context["snapshot_id"],"context_tool":tool,"selected":selected,
                "alternative":next((c for c in allowed if c is not chosen),None),"proposal":proposal,"reason":reason,
                "decision":"capture_proposal" if proposal else "hold","computation":calc,"agent":agent,
                "execution_mode":agent["execution_mode"] if agent else "deterministic_rule_based","state_transition_applied":False}
        result["selection_source"]="operator_selected_view" if asset is not None else result["execution_mode"]
        self.data["plans"].append(result);self._sync();return copy.deepcopy(result)

    def execute(self,plan_id,calculator):
        plan=next((p for p in self.data["plans"] if p["plan_id"]==plan_id),None)
        if plan is None:raise ValueError("Plan not found; propose before executing")
        key="execute-"+plan_id
        if key not in self.session._requests and (plan["state_revision"]!=self.session.state.revision or plan["review_revision"]!=self.review_revision):raise ValueError("Stale plan; recompute after state or feedback changed")
        if plan["proposal"] is None:raise ValueError("This plan is a hold; no capture may execute")
        event=self.session.execute(plan["proposal"],request_id=key,expected_revision=plan["state_revision"],calculator=calculator)
        if event["status"] in ("executed","rejected"):
            event.update(workflow_plan_id=plan_id,ground_context_id=plan["ground_context_id"],review_revision=plan["review_revision"])
            self.session._events[-1]=copy.deepcopy(event)
            self.session._requests[key]["event"]=copy.deepcopy(event)
        self._sync();return event

    def preview(self,reserve,capture,calculator):
        if type(reserve) not in (int,float) or type(capture) not in (int,float) or not 0<=reserve<=50 or not 0<=capture<=20:raise ValueError("Preview bounds: reserve 0-50 and capture 0-20")
        doc=plain(self.session._mission.document);doc["energy_model"].update(return_reserve=reserve,capture_energy_per_action=capture)
        altered=replace(self.session._mission,document=freeze(doc))
        base=compute_mission_options(self.session._mission,self.session.state,calculator);changed=compute_mission_options(altered,self.session.state,calculator)
        _,original=self.selection(base);items,updated=self.selection(changed,altered)
        active=self.data["plans"][-1] if self.data["plans"] else None
        if active and active["state_revision"]==self.session.state.revision and active["review_revision"]==self.review_revision and active["selected"]:
            preferred=(active["selected"]["asset_id"],active["selected"]["view_id"])
            for rows in (original,updated):rows.sort(key=lambda c:(c["asset_id"],c["view_id"])!=preferred)
        left={(c["asset_id"],c["view_id"]) for c in original};right={(c["asset_id"],c["view_id"]) for c in updated}
        def key(rows):return (rows[0]["asset_id"],rows[0]["view_id"]) if rows else None
        result={"preview_id":"preview-"+uuid4().hex,"timestamp":utc_time().isoformat(),"state_revision":self.session.state.revision,
                "review_revision":self.review_revision,"mission_revision":doc["revision"],"model_version":changed["model_version"],
                "base_plan_id":self.data["plans"][-1]["plan_id"] if self.data["plans"] else None,
                "baseline_computation":base,"changed_computation":changed,"candidates":items,
                "baseline_selected":original[0] if original else None,"selected":updated[0] if updated else None,
                "alternative":updated[1] if len(updated)>1 else None,"mode":changed["mode"],"reserve":reserve,"capture_cost":capture,
                "removed_candidates":[list(k) for k in sorted(left-right)],"added_candidates":[list(k) for k in sorted(right-left)],
                "recommendation_changed":key(original)!=key(updated),"preview_only":True,"state_transition_applied":False,
                "explanation":"No capture fits the preview budget; return/hold for review." if not updated else "The feasible inspection choice changes." if key(original)!=key(updated) else "The same inspection remains feasible under the preview budget."}
        if len(self.data["previews"])>=256:raise ValueError("Preview history full")
        self.data["previews"].append(result);self._sync();return copy.deepcopy(result)
