"""Load a validated local mission or request fixed synthetic capture evidence."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from .agent import run_agent
from .capture import simulated_capture
from .computation import CostCalculator, compute_mission_options
from .engine import evaluate, initial_state, list_candidates
from .loader import MissionValidationError, load_mission
from .review import InspectionSession
from .operator import operator_summary, render_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", type=Path, help="Alternative mission JSON; evidence paths remain project-relative")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--capture", nargs=2, metavar=("ASSET", "VIEW"), help="Read-only simulated capture evidence")
    operation.add_argument("--agent", choices=("fallback", "live", "auto"), help="Propose one action using the selected visible mode")
    operation.add_argument("--proposal", type=Path, help="Validate a local JSON action proposal")
    operation.add_argument("--candidates", action="store_true", help="List local candidate checks without changing state")
    operation.add_argument("--compute-options", action="store_true", help="Compute batched costs without changing state")
    operation.add_argument("--run-state", action="store_true", help="Show a fresh run, separate ground snapshot and pending review")
    operation.add_argument("--inspect", nargs=2, metavar=("ASSET", "VIEW"), help="Preview one inspection; add --execute to capture and update review in memory")
    parser.add_argument("--ground-context", choices=("recorded", "unavailable"), help="Fresh-run ground context; loaded runs retain their saved snapshot")
    parser.add_argument("--load", type=Path, help="Open a checkpoint without resetting budgets or refreshing measurements")
    parser.add_argument("--save", type=Path, help="Atomically save a checkpoint; existing files require loading first")
    parser.add_argument("--summary", action="store_true", help="Print a concise operator summary")
    parser.add_argument("--request-id", help="Stable ID for an execution retry; otherwise a new ID is generated")
    parser.add_argument("--expected-revision", type=int, help="Original state revision when retrying the same request")
    parser.add_argument("--computation", choices=("local", "wolfram"), default="local", help="Python costs (default) or verified local Wolfram with visible fallback")
    parser.add_argument("--execute", action="store_true", help="Explicitly execute one validated action in memory; no run is saved")
    parser.add_argument("--scenario", help="Require this scenario identity when requesting evidence")
    args = parser.parse_args()
    if args.execute and not (args.agent or args.proposal or args.inspect):
        parser.error("--execute requires --agent, --proposal or --inspect")
    if args.scenario and not args.capture:
        parser.error("--scenario requires --capture")
    if args.load and args.ground_context:
        parser.error("Loaded runs retain their exact ground snapshot; --ground-context is for fresh runs")
    if args.save and (args.capture or args.candidates or args.compute_options):
        parser.error("--save applies to run/proposal/inspection operations")
    if (args.request_id or args.expected_revision is not None) and not args.execute:
        parser.error("Retry fields require --execute")
    try:
        mission = load_mission(args.mission)
        doc = mission.document
        session = InspectionSession.load(mission, args.load) if args.load else InspectionSession(mission, ground_mode=args.ground_context or "recorded")
        if args.run_state:
            if args.save: session.save(args.save)
            print(render_summary(operator_summary(session)) if args.summary else json.dumps(session.snapshot(), indent=2, allow_nan=False))
            return 0
        if args.capture:
            response = simulated_capture(mission, *args.capture, scenario_id=args.scenario)
            print(json.dumps(response, indent=2, allow_nan=False))
            return 0 if response["status"] == "available" else 3
        if args.agent or args.proposal or args.inspect or args.candidates or args.compute_options:
            state = session.state
            before = state.snapshot()
            if args.compute_options:
                result = compute_mission_options(mission, state, CostCalculator(args.computation))
                result.update(state_before=before, state_after=state.snapshot(), real_flight=False)
                print(json.dumps(result, indent=2, allow_nan=False))
                return 0 if result["execution_permitted"] else 3
            if args.candidates:
                print(json.dumps({"execution_mode": "local_python_checks", "candidates": list_candidates(mission, state),
                                  "state": before, "state_transition_applied": False}, indent=2, allow_nan=False))
                return 0
            if args.inspect:
                asset_id, view_id = args.inspect
                proposal = {"action_type": "inspect" if view_id == "overview" else "follow_up", "asset_id": asset_id,
                            "view_id": view_id, "reason": "Operator requested inspection", "alternative": "Return or stop if infeasible"}
                decision = evaluate(mission, state, proposal)
                result = {"execution_mode": "operator_supplied_proposal", "validation": decision.to_dict(),
                          "proposal": proposal, "failure": None}
            elif args.agent:
                result = run_agent(mission, state, mode=args.agent)
            else:
                if args.proposal.stat().st_size > 32_000:
                    raise ValueError("Proposal file exceeds the 32 KiB limit")
                decision = evaluate(mission, state, args.proposal.read_text(encoding="utf-8-sig"))
                result = {"execution_mode": "operator_supplied_proposal", "validation": decision.to_dict(),
                          "proposal": decision.proposal.to_dict() if decision.proposal else None, "failure": None}
            code = 4 if result.get("failure") else 0 if result["validation"]["allowed"] else 3
            if result.get("proposal"):
                session.propose(result["proposal"])
            if args.execute and not result.get("failure"):
                result["run_before"] = session.snapshot()
                event = session.execute(result["proposal"], request_id=args.request_id or "operator-" + uuid4().hex,
                                        expected_revision=args.expected_revision if args.expected_revision is not None else state.revision,
                                        calculator=CostCalculator(args.computation))
                state = session.state
                result["execution"] = event
                result["run_after"] = session.snapshot()
                code = 0 if event["status"] == "executed" or (event["status"] == "already_processed" and event["original_status"] == "executed") else 3
            elif args.execute:
                result["execution"] = {"status": "not_executed", "state_transition_applied": False,
                                       "reason": "AI request failed; run --agent fallback --execute to explicitly continue locally"}
            result.update(state_before=before, state_after=state.snapshot(),
                          session_scope="checkpoint" if args.load or args.save else "ephemeral_in_memory_no_saved_run_or_resume", real_flight=False)
            result["operator_summary"] = operator_summary(session)
            if args.save: result["saved_checkpoint"] = session.save(args.save)
            print(render_summary(result["operator_summary"]) if args.summary else json.dumps(result, indent=2, allow_nan=False))
            return code
        if args.load or args.save or args.summary:
            if args.save: session.save(args.save)
            print(render_summary(operator_summary(session)))
            return 0
        state, energy = doc["initial_state"], doc["energy_model"]
        print("STRATUS 0.0.1 | inspection checks, optional AI and local Wolfram computation")
        print(f"Mission: {doc['mission_id']} | revision: {doc['revision']} | scenario: {doc['scenario_id']}")
        print(f"Mode: {doc['execution_mode']} | source: SYNTHETIC | live vision: pending")
        print(f"Layout: {len(doc['assets'])} reviewed panels | coordinates: {doc['coordinate_frame']['unit']}")
        print(f"Launch/return: {dict(doc['launch_point'])} | position: {dict(state['position'])}")
        print(f"Battery: {state['battery_available']} {energy['energy_unit']} | reserve: {energy['return_reserve']}")
        print(f"New capture actions: {state['actions_remaining']} remaining / {doc['action_rules']['max_new_capture_actions']} maximum")
        print(f"Prior records: {len(doc['prior_records'])} | new actions consumed by prior records: 0")
        print(f"Evidence: {len(mission.evidence_by_view)} PNG views validated, with separate authored replay annotations.")
        for prior in doc["prior_records"]:
            print(f"  {prior['record_id']} {prior['asset_id']}/{prior['view_id']} | {prior['image_quality_annotation']} | {prior['evidence_ref']}")
        print("No real flight or live vision inference. Human review is pending.")
        print("--agent fallback proposes locally; --execute explicitly applies one simulated transition in memory.")
        print("--agent live uses configured OpenAI credentials; failed calls preserve state and show fallback mode.")
        print("Live AI requires configured credentials. Ground measurements are separate context; see docs/HARDWARE_HANDOFF.md.")
        print("--compute-options --computation wolfram checks local Wolfram costs without changing state.")
        print("--run-state shows the fresh run and ground snapshot; --inspect P03 overview --execute adds a replay assessment and review entry.")
        print("--save saved-runs/first-inspection.json writes a checkpoint; --load that path --summary reopens it.")
        print("Live vision and the report/dashboard remain pending.")
    except (MissionValidationError, OSError, ValueError) as exc:
        parser.error(f"Cannot load mission: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
