"""Bounded JSON checkpoints with atomic writes and deterministic restoration checks."""

import copy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading

from .actions import parse_proposal, strict_json
from .computation import _check_reply, mission_input, python_costs
from .engine import evaluate, initial_state, plain
from .loader import check_image, finite, freeze
from .review import GROUND_UNITS, InspectionSession, _assess_capture, _prior_assessments, _utc_string, utc_time

FORMAT = "stratus-run-1"
LIMIT = 8_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError("Cannot restore run: " + message)


def mission_digest(mission):
    return digest({"mission": plain(mission.document),
        "evidence": [plain(item.record) for _, item in sorted(mission.evidence_by_view.items())],
        "annotations": [plain(item) for _, item in sorted(mission.annotations_by_id.items())]})


def _read(path):
    require(path.stat().st_size <= LIMIT, "checkpoint exceeds 8 MB")
    raw = path.read_bytes()
    obj = strict_json(raw.decode("utf-8-sig"), max_chars=LIMIT)
    require(isinstance(obj, dict) and set(obj) == {"format", "payload", "sha256"}, "invalid envelope")
    require(obj["format"] == FORMAT and digest(obj["payload"]) == obj["sha256"], "format or checksum mismatch")
    return obj["payload"], hashlib.sha256(raw).hexdigest()


def _ground(data):
    require(isinstance(data, dict) and data["context_role"] == "ground_context_only", "invalid ground context")
    _utc_string(data["snapshot_at_utc"])
    require(data["physical_acquisition_performed"] is False, "checkpoint cannot claim a new physical acquisition")
    require(data["mode"] in ("recorded_measured", "unavailable"), "unsupported saved ground mode")
    require(isinstance(data["observations"], list) and len(data["observations"]) <= 128, "invalid saved ground batch")
    if data["mode"] == "unavailable":
        require(data["status"] == "unavailable" and not data["observations"], "unavailable context contains measurements")
    else:
        require(data["status"] == "available" and data["observations"], "recorded context lacks measurements")
        seen = set()
        for row in data["observations"]:
            require(row["observation_id"] not in seen and row["source_mode"] == "recorded_measured"
                and row["context_role"] == "ground_context_only" and row["node_id"] == data["node_id"]
                and row["location"] == data["location"] and finite(row["value"])
                and row["unit"] == GROUND_UNITS.get(row["variable"]), "invalid saved observation")
            seen.add(row["observation_id"]); _utc_string(row["acquired_at_utc"])
            if row["received_at_utc"] is not None: _utc_string(row["received_at_utc"])


def _restore(mission, payload):
    require(set(payload) == {"mission_sha256", "saved_at_utc", "run", "requests", "proposal_audit"}, "invalid payload fields")
    require(payload["mission_sha256"] == mission_digest(mission), "mission/revision/evidence changed")
    _utc_string(payload["saved_at_utc"])
    run = payload["run"]
    require(re.fullmatch(r"run-[a-f0-9]{32}", run["run_id"]) is not None, "invalid run ID")
    require(run["mission_revision"] == mission.document["revision"] and run["real_flight"] is False, "invalid run identity/mode")
    _utc_string(run["created_at_utc"]); _ground(run["ground_context"])
    require(isinstance(run["events"], list) and len(run["events"]) <= 1024, "invalid event log")
    state, assessments, receipts = initial_state(mission), _prior_assessments(mission), {}
    for event in run["events"]:
        proposal = parse_proposal(event["proposal"])
        request_id = event["request_id"]
        require(isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request_id)
                and request_id not in receipts, "invalid/duplicate request ID")
        require(type(event["expected_revision"]) is int and event["expected_revision"] == state.revision,
                "event revision is inconsistent")
        require(event["event_id"] == run["run_id"] + ":" + request_id, "event identity mismatch")
        decision = evaluate(mission, state, proposal)
        require(event["status"] in ("executed", "rejected"), "invalid event status")
        if event["status"] == "executed":
            require(decision.allowed and event["state_transition_applied"] is True, "executed action violates current rules")
            require(event["decision"] == decision.to_dict(), "saved action costs/decision changed")
            _utc_string(event["timestamp"])
            costs = decision.costs
            if proposal.action_type in ("inspect", "follow_up"):
                capture = event["evidence"]; evidence = mission.evidence_by_view[proposal.asset_id, proposal.view_id]
                check_image(evidence, mission.project_root)
                require(capture["status"] == "available" and capture["asset_id"] == proposal.asset_id
                    and capture["view_id"] == proposal.view_id and capture["scenario_id"] == state.scenario_id
                    and capture["mission_id"] == state.mission_id and capture["real_flight"] is False,
                    "capture identity/status mismatch")
                require(capture["evidence_ref"]["evidence_id"] == evidence.record["evidence_id"]
                    and capture["evidence_ref"]["sha256"] == evidence.record["sha256"]
                    and capture["evidence_ref"]["image_path"] == evidence.record["image_path"], "capture evidence changed")
                if capture["assessment_mode"] == "authored_replay_annotation":
                    annotation = plain(mission.annotations_by_id[evidence.record["evidence_id"]])
                    require(capture["annotation"] == annotation and capture["image_quality"] == annotation["image_quality"]
                        and capture["finding"] == annotation["finding"], "replay annotation changed")
                require(event["battery_debit"] == costs.outbound + costs.capture
                    and event["capture_action_debit"] == 1, "capture debit mismatch")
                calculation = event["computation"]
                require(calculation["model_version"] == costs.model_version and calculation["execution_permitted"] is True,
                        "executed action lacks valid computation provenance")
                require(calculation["mode"] in ("local_python", "local_python_fallback", "wolfram_local", "cached_wolfram_local"),
                        "unsupported executed computation mode")
                expected_input = mission_input(mission, state)
                expected_output = python_costs(expected_input)
                require(canonical(calculation["normalized_input"]) == canonical(expected_input)
                    and canonical(calculation["python_output"]) == canonical(expected_output), "computation input/reference changed")
                if calculation["mode"] in ("wolfram_local", "cached_wolfram_local"):
                    require(not _check_reply(calculation["output"], expected_output)
                        and calculation["wolfram_output"] == calculation["output"], "saved Wolfram costs disagree")
                else:
                    require(canonical(calculation["output"]) == canonical(expected_output), "saved Python costs disagree")
                record = freeze(dict(record_id=f"simulated-{state.revision+1:03d}", asset_id=proposal.asset_id,
                    view_id=proposal.view_id, evidence=capture, consumes_new_action=True))
                target = next(a["position"] for a in mission.document["assets"] if a["asset_id"] == proposal.asset_id)
                state = replace(state, position=(target["x"], target["y"]),
                    battery_available=math.fsum((state.battery_available, -costs.outbound, -costs.capture)),
                    actions_used=state.actions_used+1, actions_remaining=state.actions_remaining-1,
                    completed_views=state.completed_views | {(proposal.asset_id, proposal.view_id)},
                    history=state.history+(record,), revision=state.revision+1)
                assessment = _assess_capture(event, state.revision)
                require(event["assessment"] == assessment and event["assessment_added"] is True, "assessment changed")
                assessments.append(assessment)
            else:
                debit = costs.return_cost if costs else 0
                require(event["battery_debit"] == debit and event["capture_action_debit"] == 0
                    and event["assessment_added"] is False, "terminal action debit/assessment mismatch")
                home = mission.document["launch_point"]
                state = replace(state, battery_available=state.battery_available-debit,
                    position=(home["x"], home["y"]) if proposal.action_type == "return" else state.position,
                    status="returned" if proposal.action_type == "return" else "stopped", revision=state.revision+1)
        else:
            require(event["state_transition_applied"] is False and event["assessment_added"] is False, "rejected action changed state")
            require(not decision.allowed or event.get("code") in ("numerical_disagreement", "evidence_unavailable_before_commit"),
                    "unexplained saved rejection")
        fingerprint = hashlib.sha256(json.dumps({"proposal": proposal.to_dict(), "expected_revision": event["expected_revision"]},
                                   sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipts[request_id] = {"fingerprint": fingerprint, "event": event}
    require(canonical(state.snapshot()) == canonical(run["aircraft_state"]), "budget/position/history does not match actions")
    require(assessments == run["assessments"] == run["review_queue"], "review queue does not match captured evidence")
    require(receipts == payload["requests"] and len(receipts) == run["processed_request_count"], "request receipts changed")
    require(isinstance(payload["proposal_audit"], list) and len(payload["proposal_audit"]) <= 4096, "invalid proposal audit")
    # Bypass __init__: restoring never reads sensors, loads a new ground sample, or captures an image.
    restored = InspectionSession.__new__(InspectionSession)
    restored._mission, restored._state, restored._lock = mission, state, threading.RLock()
    restored._run_id, restored._created_at = run["run_id"], run["created_at_utc"]
    restored._ground, restored._assessments = freeze(run["ground_context"]), copy.deepcopy(assessments)
    restored._events, restored._requests = copy.deepcopy(run["events"]), copy.deepcopy(receipts)
    restored._audit = copy.deepcopy(payload["proposal_audit"])
    restored._store_path, restored._store_hash = None, None
    require(canonical(restored.snapshot()) == canonical(run), "derived run fields changed")
    return restored


def load_session(mission, path):
    path = Path(path).resolve()
    try:
        payload, file_hash = _read(path)
        session = _restore(mission, payload)
    except (KeyError, TypeError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError("Cannot restore run: malformed checkpoint") from exc
    session._store_path, session._store_hash = str(path), file_hash
    return session


def save_session(session, path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".json": raise ValueError("Save checkpoints as .json files")
    if path == session._mission.mission_path.resolve(): raise ValueError("Cannot overwrite the frozen mission")
    root = session._mission.project_root
    for folder in (root / "stratus", root / "evidence", root / "context"):
        if path.is_relative_to(folder.resolve()): raise ValueError("Save runs separately from source, mission, evidence and ground context")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("Another checkpoint writer holds this file lock") from exc
    os.close(fd)
    temp = None
    try:
        with session._lock:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            expected = session._store_hash if session._store_path == str(path) else None
            if current != expected: raise ValueError("Checkpoint changed or already exists; reload it or choose a new filename")
            payload = dict(mission_sha256=mission_digest(session._mission), saved_at_utc=utc_time().isoformat(),
                run=session.snapshot(), requests=copy.deepcopy(session._requests), proposal_audit=copy.deepcopy(session._audit))
            _restore(session._mission, payload)
            raw = json.dumps(dict(format=FORMAT, payload=payload, sha256=digest(payload)), indent=2, allow_nan=False).encode("utf-8") + b"\n"
            if len(raw) > LIMIT: raise ValueError("Checkpoint exceeds 8 MB")
            with tempfile.NamedTemporaryFile(prefix=".stratus-", suffix=".tmp", dir=path.parent, delete=False) as file:
                temp = Path(file.name); file.write(raw); file.flush(); os.fsync(file.fileno())
            os.replace(temp, path); temp = None
            session._store_path, session._store_hash = str(path), hashlib.sha256(raw).hexdigest()
            return {"path": str(path), "sha256": session._store_hash, "saved_at_utc": payload["saved_at_utc"],
                    "run_id": session._run_id, "state_revision": session.state.revision}
    finally:
        if temp is not None: temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
