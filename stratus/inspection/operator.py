"""Concise operator view; diagnostic details remain separate from the message."""

from .agent import fallback_proposal
from .review import _utc_string, utc_time


def operator_summary(session, *, now=None):
    workflow=None
    if any(a.get("kind")=="adaptive_workflow_v1" for a in session._audit):
        from .workflow import AdaptiveWorkflow
        workflow=AdaptiveWorkflow(session)
    run = workflow.snapshot() if workflow else session.snapshot()
    state = run["aircraft_state"]; ground = run["ground_context"]
    when = utc_time(now)
    changed = "Fresh run: two prior records retained; no new capture executed."
    if run["events"]:
        event = run["events"][-1]
        if event["status"] == "executed":
            p = event["proposal"]
            changed = (f"Captured {p['asset_id']}/{p['view_id']}; used {event['battery_debit']:.2f} simulated energy units."
                       if p["asset_id"] else f"Simulation {state['status']}.")
        else:
            changed = "No action executed. " + event.get("decision", {}).get("message", "The request requires review.")
    concerns = sorted({r["asset_id"] for r in run["review_queue"] if "tentative_concern" in r["flags"] and r.get("operator_review_status","pending")=="pending"})
    if state["status"] != "active":
        next_action = {"type": "hold", "label": "Review the completed simulation", "reason": "The run has returned or stopped."}
    elif concerns:
        next_action = {"type": "hold", "label": "Review the tentative concern on " + ", ".join(concerns),
                       "reason": "The replay flag awaits human review; it is not a confirmed defect."}
    else:
        p = fallback_proposal(session._mission, session.state)
        if workflow:
            from .computation import CostCalculator, compute_mission_options
            from .actions import Proposal
            _,allowed=workflow.selection(compute_mission_options(session._mission,session.state,CostCalculator("local")))
            if allowed:
                c=allowed[0];p=Proposal("inspect" if c["view_id"]=="overview" else "follow_up",c["asset_id"],c["view_id"],"Feedback-aware priority/uncertainty/cost rule; explicit execution required","Return or hold if the work becomes infeasible")
            else:p=Proposal("stop",None,None,"No eligible capture remains after operator feedback; hold for review","Return only if deterministic reserve checks allow")
        next_action = {"type": p.action_type,
                       "label": f"Capture {p.asset_id}/{p.view_id}" if p.asset_id else p.action_type.capitalize() + " the simulation",
                       "reason": p.reason, "proposal": p.to_dict()}
    observations = ground["observations"]
    ages = [(when - _utc_string(r["acquired_at_utc"])).total_seconds() for r in observations]
    context = {"availability": "Recorded" if ground["mode"] == "recorded_measured" else "Unavailable",
               "source": ground["mode"], "location": ground["location"],
               "oldest_age_seconds": max(ages) if ages else None,
               "acquired_at_utc": sorted({r["acquired_at_utc"] for r in observations}),
               "measurements": [{k: r[k] for k in ("sensor_id", "variable", "value", "unit", "acquired_at_utc", "quality")}
                                for r in observations]}
    computation = next((e["computation"]["mode"] for e in reversed(run["events"]) if "computation" in e), "not_run")
    return {"run_id": run["run_id"], "rendered_at_utc": when.isoformat(), "what_changed": changed,
            "computation_mode": computation,
            "battery_available": state["battery_available"], "actions_remaining": state["actions_remaining"],
            "next_action": next_action, "ground": context, "pending_review_count": len(run["review_queue"]),
            "assessment_mode": "authored_replay_annotation; human review pending",
            "technical_details": {"ground": ground.get("technical_details"), "ground_reason": ground.get("reason")}}


def render_summary(summary):
    ground = summary["ground"]
    age = ground["oldest_age_seconds"]
    age_text = "" if age is None else (f"; oldest reading {age/60:.1f} minutes old" if age >= 0 else "; timestamp is in the future")
    measurements = "; ".join(f"{r['variable']} {r['value']:.2f} {r['unit']}" for r in ground["measurements"])
    modes = {"not_run": "not run", "local_python": "local Python", "local_python_fallback": "local Python fallback",
             "wolfram_local": "local Wolfram", "cached_wolfram_local": "cached local Wolfram",
             "wolfram_disagreement": "disagreement; execution blocked"}
    return "\n".join([summary["what_changed"],
        f"Battery: {summary['battery_available']:.2f} simulated units | Capture actions remaining: {summary['actions_remaining']}",
        "Computation: " + modes.get(summary["computation_mode"], "unknown"),
        "Next: " + summary["next_action"]["label"] + ". " + summary["next_action"]["reason"],
        "Ground conditions: " + ground["availability"] + age_text + (". " + measurements if measurements else "."),
        "Image assessment: annotated replay; human review pending.",
        "Ground readings remain unreviewed; location/calibration metadata is retained with the saved observations." if measurements else "No ground measurements available."])
