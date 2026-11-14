"""Deterministic toy energy checks and atomic in-memory simulated execution."""

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from .actions import Proposal, ProposalError, parse_proposal
from .capture import simulated_capture
from .loader import Mission, check_image, finite, freeze


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


@dataclass(frozen=True)
class RunState:
    mission_id: str
    scenario_id: str
    position: tuple[float, float]
    battery_available: float
    actions_used: int
    actions_remaining: int
    completed_views: frozenset[tuple[str, str]]
    history: tuple[Mapping[str, Any], ...]
    revision: int = 0
    status: str = "active"

    def snapshot(self):
        return {
            "mission_id": self.mission_id, "scenario_id": self.scenario_id,
            "position": {"x": self.position[0], "y": self.position[1]},
            "battery_available": self.battery_available, "actions_used": self.actions_used,
            "actions_remaining": self.actions_remaining,
            "completed_views": [{"asset_id": a, "view_id": v} for a, v in sorted(self.completed_views)],
            "history": plain(self.history), "revision": self.revision, "status": self.status,
        }


def initial_state(mission: Mission) -> RunState:
    doc, initial = mission.document, mission.document["initial_state"]
    return RunState(
        doc["mission_id"], doc["scenario_id"], (initial["position"]["x"], initial["position"]["y"]),
        initial["battery_available"], initial["actions_used"], initial["actions_remaining"],
        frozenset((r["asset_id"], r["view_id"]) for r in doc["prior_records"]),
        tuple(doc["prior_records"]),
    )


def state_error(mission: Mission, state: RunState) -> str | None:
    doc = mission.document
    if state.mission_id != doc["mission_id"] or state.scenario_id != doc["scenario_id"]:
        return "state_identity_mismatch"
    if not finite(state.battery_available) or not 0 <= state.battery_available <= doc["energy_model"]["initial_battery_capacity"]:
        return "invalid_state_battery"
    if len(state.position) != 2 or not all(finite(x) for x in state.position):
        return "invalid_state_position"
    if any(type(n) is not int or n < 0 for n in (state.actions_used, state.actions_remaining, state.revision)):
        return "invalid_state_action_count"
    if state.actions_used + state.actions_remaining != doc["action_rules"]["max_new_capture_actions"]:
        return "invalid_state_action_budget"
    if state.status not in ("active", "returned", "stopped"):
        return "invalid_state_status"
    if not state.completed_views.issubset(mission.evidence_by_view):
        return "invalid_state_completed_views"
    return None


def protected_margin(available, outbound, capture, return_cost, reserve) -> float:
    values = (available, outbound, capture, return_cost, reserve)
    if not all(finite(x) and x >= 0 for x in values):
        raise ValueError("Energy values must be finite, nonnegative numbers")
    try:
        margin = math.fsum((available, -outbound, -capture, -return_cost, -reserve))
    except OverflowError as exc:
        raise ValueError("Energy calculation exceeds representable limits") from exc
    if not math.isfinite(margin):
        raise ValueError("Energy margin is not finite")
    return margin


@dataclass(frozen=True)
class Costs:
    outbound: float
    capture: float
    return_cost: float
    reserve: float
    margin: float
    model_version: str
    distance_unit: str = "m"
    energy_unit: str = "simulated_energy_unit"
    calculator_mode: str = "local_python_euclidean"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    message: str
    state_revision: int
    proposal: Proposal | None = None
    costs: Costs | None = None

    def to_dict(self):
        return asdict(self)


def evaluate(mission: Mission, state: RunState, value: Any) -> Decision:
    """A proposal, explanation, or rejection never mutates state or coverage."""
    proposal = None

    def reject(code, message, costs=None):
        return Decision(False, code, message, state.revision, proposal, costs)

    try:
        proposal = parse_proposal(value)
    except ProposalError as exc:
        return reject("invalid_proposal", str(exc))
    error = state_error(mission, state)
    if error:
        return reject(error, "Current simulated state is invalid; no action executed")
    if state.status != "active":
        return reject("mission_closed", "The simulated run has already returned or stopped")
    energy = mission.document["energy_model"]
    if energy["model_version"] != "toy-euclidean-energy-v1":
        return reject("unsupported_energy_model", "Only toy-euclidean-energy-v1 is implemented")
    if proposal.action_type == "stop":
        return Decision(True, "allowed", "Stop the simulation; no landing or flight claim", state.revision, proposal)
    launch = mission.document["launch_point"]
    home = (launch["x"], launch["y"])
    outbound = capture = return_cost = 0.0
    if proposal.action_type == "return":
        return_cost = math.dist(state.position, home) * energy["travel_energy_per_m"]
    else:
        asset = next((a for a in mission.document["assets"] if a["asset_id"] == proposal.asset_id), None)
        if asset is None:
            return reject("unknown_asset", "Requested asset ID is not in the mission")
        if proposal.view_id not in asset["planned_view_ids"]:
            return reject("unknown_view", "Requested view ID is not planned for this asset")
        if asset["eligibility"]["state"] != "eligible":
            return reject("asset_excluded", "Operator excluded this panel/point")
        key = (proposal.asset_id, proposal.view_id)
        if key in state.completed_views:
            return reject("duplicate_view", "This asset/view already has a prior or executed record")
        if state.actions_remaining <= 0:
            return reject("actions_exhausted", "No new capture actions remain")
        if proposal.action_type == "inspect" and proposal.view_id != "overview":
            return reject("follow_up_action_required", "A distinct follow-up must use the follow_up action type")
        if proposal.action_type == "follow_up":
            if proposal.view_id == "overview":
                return reject("distinct_follow_up_required", "Follow-up requires a distinct view ID")
            if not any(a == proposal.asset_id for a, _ in state.completed_views):
                return reject("prior_view_required", "Inspect an initial view before requesting follow-up")
        evidence = mission.evidence_by_view[key]
        try:
            check_image(evidence, mission.project_root)
        except (OSError, ValueError):
            return reject("evidence_unavailable", "Image is missing, unreadable, corrupt, or changed; finding remains unknown")
        target = (asset["position"]["x"], asset["position"]["y"])
        outbound = math.dist(state.position, target) * energy["travel_energy_per_m"]
        capture = energy["capture_energy_per_action"]
        return_cost = math.dist(target, home) * energy["travel_energy_per_m"]
    try:
        margin = protected_margin(state.battery_available, outbound, capture, return_cost, energy["return_reserve"])
    except ValueError as exc:
        return reject("invalid_energy_calculation", str(exc))
    costs = Costs(outbound, capture, return_cost, energy["return_reserve"], margin, energy["model_version"])
    if margin < 0:
        return reject("return_reserve_violation", "Available battery cannot protect travel, capture, return, and reserve", costs)
    return Decision(True, "allowed", "Local constraints passed; no state change until explicit execution", state.revision, proposal, costs)


def execute_action(mission: Mission, state: RunState, value: Any) -> tuple[RunState, dict]:
    """Revalidate against current state; commit exactly one immutable transition."""
    decision = evaluate(mission, state, value)
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "execution_mode": "simulated",
             "real_flight": False, "decision": decision.to_dict(), "status": "rejected",
             "state_transition_applied": False}
    if not decision.allowed:
        return state, event
    proposal, costs = decision.proposal, decision.costs
    if proposal.action_type in ("inspect", "follow_up"):
        response = simulated_capture(mission, proposal.asset_id, proposal.view_id,
                                     scenario_id=state.scenario_id)
        if response["status"] != "available":
            event.update(code="evidence_unavailable_before_commit", evidence=response)
            return state, event
        asset = next(a for a in mission.document["assets"] if a["asset_id"] == proposal.asset_id)
        record = freeze({"record_id": f"simulated-{state.revision + 1:03d}",
                         "asset_id": proposal.asset_id, "view_id": proposal.view_id,
                         "evidence": response, "consumes_new_action": True})
        updated = replace(
            state, position=(asset["position"]["x"], asset["position"]["y"]),
            battery_available=math.fsum((state.battery_available, -costs.outbound, -costs.capture)),
            actions_used=state.actions_used + 1, actions_remaining=state.actions_remaining - 1,
            completed_views=state.completed_views | {(proposal.asset_id, proposal.view_id)},
            history=state.history + (record,), revision=state.revision + 1,
        )
        event.update(evidence=response, battery_debit=costs.outbound + costs.capture, capture_action_debit=1)
    elif proposal.action_type == "return":
        launch = mission.document["launch_point"]
        updated = replace(state, position=(launch["x"], launch["y"]),
                          battery_available=state.battery_available - costs.return_cost,
                          revision=state.revision + 1, status="returned")
        event.update(battery_debit=costs.return_cost, capture_action_debit=0)
    else:
        updated = replace(state, revision=state.revision + 1, status="stopped")
        event.update(battery_debit=0, capture_action_debit=0)
    event.update(status="executed", state_transition_applied=True,
                 state_before_revision=state.revision, state_after_revision=updated.revision)
    return updated, event


def list_candidates(mission: Mission, state: RunState) -> list[dict]:
    candidates = []
    for asset in mission.document["assets"]:
        for view in asset["planned_view_ids"]:
            proposal = Proposal("inspect" if view == "overview" else "follow_up", asset["asset_id"], view,
                                "Candidate for operator/agent review", "Return or stop if infeasible")
            candidates.append({"priority": asset["priority"], **evaluate(mission, state, proposal).to_dict()})
    return candidates
