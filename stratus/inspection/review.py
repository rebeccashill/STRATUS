"""S032-S036: one in-memory run, explicit replay review, and idempotent execution."""

import copy
import hashlib
import json
from datetime import datetime, timezone
import re
import threading
from uuid import uuid4

from .actions import ProposalError, parse_proposal, strict_json
from .computation import CostCalculator, execute_computed_action
from .engine import evaluate, initial_state, plain
from .loader import finite, freeze, local_path, read_json

GROUND_UNITS = {"temperature": "degC", "relative_humidity": "%RH", "pressure": "hPa",
                "pm1_0": "ug/m3", "pm2_5": "ug/m3", "pm10": "ug/m3"}


def utc_time(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    return value.astimezone(timezone.utc)


def _utc_string(value):
    if not isinstance(value, str):
        raise ValueError("Recorded acquisition time is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Recorded time must be explicitly UTC")
    return parsed


def ground_snapshot(mission, mode="recorded", *, now=None):
    """Read existing measurements only. Missing/invalid input never blocks the core run."""
    when = utc_time(now)
    if mode not in ("recorded", "unavailable"):
        raise ValueError("Ground mode must be recorded or unavailable")
    result = {"status": "unavailable", "mode": "unavailable", "context_role": "ground_context_only",
              "snapshot_at_utc": when.isoformat(), "node_id": None,
              "location": {"status": "unknown", "position": None, "coordinate_frame": None, "label": None},
              "observations": [], "source": None, "reason": "operator_selected_unavailable",
              "physical_acquisition_performed": False}
    if mode == "unavailable":
        return result
    try:
        registry_path = local_path(mission.project_root, "context/hardware-status.json", "Hardware registry")
        registry = read_json(registry_path, "Hardware registry")
        source = registry["normalized_source"]
        path = local_path(mission.project_root, source["path"], "Recorded ground observations")
        if path.stat().st_size > 2_000_000:
            raise ValueError("Recorded observations exceed 2 MB")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != source["sha256"]:
            raise ValueError("Recorded observation hash does not match hardware registry")
        rows = [strict_json(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
        if not rows or len(rows) != source["observations"] or len(rows) > 1000:
            raise ValueError("Recorded observation count is invalid")
        seen, latest = set(), {}
        sensors = {s["sensor_id"] for s in registry["sensors"]}
        for row in rows:
            if (row["observation_id"] in seen or row["node_id"] != registry["node_id"]
                    or row["sensor_id"] not in sensors or row["source_mode"] != "recorded_measured"
                    or row["acquisition_source"] != "physical_sensor" or row["context_role"] != "ground_context_only"
                    or row["unit"] != GROUND_UNITS.get(row["variable"]) or not finite(row["value"])
                    or row["location"] != registry["location"]):
                raise ValueError("Recorded observation failed identity/source/unit/location validation")
            acquired = _utc_string(row["acquired_at_utc"])
            if row["received_at_utc"] is not None:
                _utc_string(row["received_at_utc"])
            seen.add(row["observation_id"])
            key = (row["sensor_id"], row["variable"])
            if key not in latest or acquired > _utc_string(latest[key]["acquired_at_utc"]):
                latest[key] = row
        observations = [copy.deepcopy(latest[k]) for k in sorted(latest)]
        ages = [(when - _utc_string(r["acquired_at_utc"])).total_seconds() for r in observations]
        result.update(status="available", mode="recorded_measured", node_id=registry["node_id"],
                      location=copy.deepcopy(registry["location"]), observations=observations, reason=None,
                      source={"path": source["path"], "sha256": digest, "records_checked": len(rows),
                              "raw_source_verification": "not_rechecked_by_this_reader"},
                      age_seconds_at_snapshot={"youngest": min(ages), "oldest": max(ages)},
                      time_status="future_timestamp_present" if min(ages) < 0 else "recorded_original_times")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, AttributeError) as exc:
        result["reason"] = "recorded_ground_data_missing_or_invalid"
        result["technical_details"] = {"error_type": type(exc).__name__, "message": str(exc)}
    return result


def _flags(quality, finding):
    flags = ["human_review_pending"]
    if quality != "clear":
        flags.append("insufficient_image_detail")
    if finding.startswith("unknown"):
        flags.append("finding_unknown")
    if finding == "apparent_concern_review_required":
        flags.append("tentative_concern")
    return flags


def _prior_assessments(mission):
    records = []
    for prior in mission.document["prior_records"]:
        evidence = mission.evidence_by_view[prior["asset_id"], prior["view_id"]].record
        quality, finding = prior["image_quality_annotation"], prior["finding"]
        records.append({"assessment_id": prior["record_id"], "asset_id": prior["asset_id"],
            "view_id": prior["view_id"], "origin": "frozen_prior_record", "state_revision": 0,
            "assessment_mode": prior["assessment_mode"], "source_label": evidence["source_label"],
            "model": None, "live_model_output": False, "human_review_status": "pending",
            "image_quality": quality, "finding": finding, "flags": _flags(quality, finding),
            "evidence_ref": {"evidence_id": evidence["evidence_id"], "image_path": evidence["image_path"],
                             "sha256": evidence["sha256"]},
            "note": "Original prior finding retained; no new assessment or capture is implied."})
    return records


def _assess_capture(event, revision):
    """Only the simulator's returned capture supplies assessment labels; no new vision claim."""
    capture = event["evidence"]
    annotation = capture.get("annotation") or {}
    mode = capture.get("assessment_mode")
    usable = (capture.get("status") == "available" and mode == "authored_replay_annotation"
              and annotation.get("live_model_output") is False
              and annotation.get("human_review_status") == "pending")
    quality = capture["image_quality"] if usable else "unknown"
    finding = capture["finding"] if usable else "unknown"
    return {"assessment_id": event["event_id"], "asset_id": capture["asset_id"],
            "view_id": capture["view_id"], "origin": "executed_simulated_capture", "state_revision": revision,
            "assessment_mode": "authored_replay_annotation" if usable else "unavailable_no_assessment",
            "source_label": capture.get("source_label"), "model": None, "live_model_output": False,
            "human_review_status": "pending", "image_quality": quality, "finding": finding,
            "flags": _flags(quality, finding), "evidence_ref": copy.deepcopy(capture["evidence_ref"]),
            "assessed_at_utc": event["timestamp"],
            "note": annotation.get("note") if usable else "Assessment unavailable; finding remains unknown."}


class InspectionSession:
    """Serializes commits; save/reload retains state, ground snapshot and request receipts."""

    def __init__(self, mission, *, ground_mode="recorded", now=None):
        self._mission = mission
        self._state = initial_state(mission)
        self._run_id = "run-" + uuid4().hex
        self._created_at = utc_time(now).isoformat()
        self._ground = freeze(ground_snapshot(mission, ground_mode, now=now))
        self._assessments = _prior_assessments(mission)
        self._events, self._requests = [], {}
        self._audit = []
        self._store_path, self._store_hash = None, None
        self._lock = threading.RLock()

    @property
    def state(self):
        with self._lock:
            return self._state

    def snapshot(self):
        with self._lock:
            assets = []
            for asset in self._mission.document["assets"]:
                records = [r for r in self._assessments if r["asset_id"] == asset["asset_id"]]
                latest = records[-1] if records else None
                has_concern = any("tentative_concern" in r["flags"] for r in records)
                excluded = asset["eligibility"]["state"] != "eligible"
                if excluded:
                    coverage = "excluded_uninspected"
                elif not latest:
                    coverage = "uninspected"
                elif latest["image_quality"] != "clear":
                    coverage = "needs_distinct_follow_up"
                elif has_concern:
                    coverage = "captured_concern_review_required"
                elif "finding_unknown" in latest["flags"]:
                    coverage = "captured_finding_unknown"
                else:
                    coverage = "captured_pending_human_review"
                unresolved = [] if excluded else (["initial_capture_required"] if not latest else list(latest["flags"]))
                if has_concern and not excluded and "tentative_concern" not in unresolved:
                    unresolved.append("tentative_concern")
                assets.append({"asset_id": asset["asset_id"], "eligibility": asset["eligibility"]["state"],
                    "captured_views": [r["view_id"] for r in records], "coverage_status": coverage,
                    "latest_assessment_id": latest["assessment_id"] if latest else None,
                    "image_quality": latest["image_quality"] if latest else "unknown",
                    "finding": latest["finding"] if latest else "unknown", "unresolved": unresolved})
            return {"run_id": self._run_id, "mission_revision": self._mission.document["revision"],
                "created_at_utc": self._created_at, "execution_mode": "simulated", "real_flight": False,
                "session_scope": "in_memory_session_with_optional_checkpoint",
                "aircraft_state": self._state.snapshot(), "ground_context": plain(self._ground),
                "assets": assets,
                "uninspected_assets": [a["asset_id"] for a in assets if a["coverage_status"] == "uninspected"],
                "incomplete_assets": [a["asset_id"] for a in assets if a["unresolved"]],
                "assessments": copy.deepcopy(self._assessments),
                "review_queue": copy.deepcopy(self._assessments),
                "events": copy.deepcopy(self._events), "processed_request_count": len(self._requests),
                "human_review_status": "pending", "live_vision_status": "not_run"}

    def propose(self, value):
        """Record a read-only proposal or rejection for the checkpoint audit trail."""
        with self._lock:
            decision = evaluate(self._mission, self._state, value)
            self._audit.append({"timestamp": utc_time().isoformat(), "kind": "proposal",
                                "decision": decision.to_dict(), "state_transition_applied": False})
            return decision

    def save(self, path):
        from .persistence import save_session
        return save_session(self, path)

    @classmethod
    def load(cls, mission, path):
        from .persistence import load_session
        return load_session(mission, path)

    def execute(self, value, *, request_id, expected_revision, calculator=None):
        """Validate, compute, capture, assess and commit once, under a per-session lock."""
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request_id):
            raise ValueError("request_id must contain 1-128 letters, digits, dots, underscores or hyphens")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        try:
            proposal = parse_proposal(value)
        except ProposalError as exc:
            return {"status": "rejected", "code": "invalid_proposal", "message": str(exc),
                    "state_transition_applied": False}
        fingerprint = hashlib.sha256(json.dumps({"proposal": proposal.to_dict(), "expected_revision": expected_revision},
                                               sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._lock:
            def reject(code):
                return {"status": "rejected", "code": code, "request_id": request_id,
                        "state_transition_applied": False, "state_revision": self._state.revision}

            if request_id in self._requests:
                previous = self._requests[request_id]
                if previous["fingerprint"] != fingerprint:
                    return reject("idempotency_key_conflict")
                return {"status": "already_processed", "original_status": previous["event"]["status"],
                        "original_event_id": previous["event"]["event_id"], "request_id": request_id,
                        "state_transition_applied": False, "battery_debit": 0, "capture_action_debit": 0,
                        "assessment_added": False, "state_revision": self._state.revision}
            if expected_revision != self._state.revision:
                return reject("stale_state_revision")
            if len(self._requests) >= 1024:
                return reject("session_request_limit")
            updated, event = execute_computed_action(self._mission, self._state, proposal,
                                                     calculator or CostCalculator("local"))
            event.update(event_id=f"{self._run_id}:{request_id}", request_id=request_id, proposal=proposal.to_dict(),
                         expected_revision=expected_revision, assessment_added=False)
            assessments = list(self._assessments)
            if event["status"] == "executed" and proposal.action_type in ("inspect", "follow_up"):
                assessment = _assess_capture(event, updated.revision)
                assessments.append(assessment)
                event.update(assessment=copy.deepcopy(assessment), assessment_added=True)
            # All derived data is prepared before these in-memory references are committed.
            self._state, self._assessments = updated, assessments
            self._events.append(copy.deepcopy(event))
            self._requests[request_id] = {"fingerprint": fingerprint, "event": copy.deepcopy(event)}
            return copy.deepcopy(event)
