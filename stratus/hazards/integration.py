"""Part 13's join to the real Part 12 fleet store and guarded event engine.

The fleet's existing hazard registry, assessments, assignments and ledger are
authoritative. This controller does not keep a second mission state store.
"""

from copy import deepcopy
from datetime import datetime, timezone
import heapq
import time

from stratus.contracts.fleet_v1 import FRAME as FLEET_FRAME, REGISTRY_VERSION
from .core import CONTRACT, FRAME, HazardRegistry, number, text
from .fleet_adapter import assess_fleet_path, fleet_registry
from .fixtures import crane_event


def restore_fleet_registry(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "coordinate_frame", "revision", "hazards", "events"}:
        raise ValueError("Unsupported fleet hazard registry fields")
    if value["schema_version"] != REGISTRY_VERSION or value["coordinate_frame"] != FLEET_FRAME:
        raise ValueError("Unsupported fleet hazard frame/schema")
    if not isinstance(value["hazards"], list):
        raise ValueError("Fleet hazard records must be a list")
    records = {}
    for h in value["hazards"]:
        if not isinstance(h, dict) or h.get("hazard_id") in records:
            raise ValueError("Duplicate or malformed reported hazard")
        records[h["hazard_id"]] = deepcopy(h)
    registry = HazardRegistry.restore({"schema_version": CONTRACT, "coordinate_frame": deepcopy(FRAME),
                                      "revision": value["revision"], "hazards": records, "events": deepcopy(value["events"])})
    if fleet_registry(registry) != value:
        raise ValueError("Fleet registry disagrees with its event history")
    return registry


def fleet_paths(core, revision=None):
    """Assess every drone, including idle, returning and completed records."""
    result = []
    for did, drone in core.data["drones"].items():
        assignment = core.data["assignments"].get(did)
        p = core._path(drone, core.data["tasks"][assignment["task_id"]], assignment["origin"]) if assignment else core._return_path(drone)
        if revision is not None:
            p["hazard_revision"] = revision
        result.append(p)
    return result


def publish_registry(core, value):
    """Called under the real fleet lock; reports invalidate stale authorization.

    Completed logical waypoints and costs are retained. An affected in-progress
    segment is held for review; a position is never invented inside that segment.
    """
    with core.lock:
        registry = restore_fleet_registry(value)
        old = core.data["hazards"]
        if registry.revision <= old["revision"]:
            raise ValueError("A newer hazard revision is required")
        if value["events"][:len(old["events"])] != old["events"]:
            raise ValueError("Hazard history cannot be replaced by a different branch")
        if value["events"][-1]["effective_sim_time"] != core.data["clock"]:
            raise ValueError("Publish the report at the current logical event boundary")
        started = time.perf_counter()
        paths = fleet_paths(core, registry.revision)
        assessments = [dict(assess_fleet_path(p, value), drone_id=p["drone_id"], task_id=p["task_id"],
                            path=deepcopy(p)) for p in paths]
        affected = {a["drone_id"] for a in assessments if a["state"] != "clear"}
        in_progress = {did for did in affected if core.data["drones"][did]["status"] in ("traveling", "inspecting", "returning")}
        before = {i: (deepcopy(d["position"]), d["battery"], d["actions_used"]) for i, d in core.data["drones"].items()}
        core.data["hazards"] = deepcopy(value)
        core.invalidate("Reported exclusion changed; stale plans invalidated at a logical boundary")
        for a in assessments:
            drone = core.data["drones"][a["drone_id"]]
            drone["hazard_checked_revision"] = registry.revision
            if a["drone_id"] in in_progress or drone.get("hazard_review_required", False):
                drone.update(status="held", task_id=None, hazard_review_required=True,
                             reason="Affected in-progress logical segment: operator review required; no new stop position inferred")
            elif a["state"] != "clear" and drone["status"] not in ("complete", "unavailable"):
                drone.update(status="idle", reason="Previous proposed path blocked; allocation will seek another eligible task")
        queue = []
        for event in core.data["queue"]:
            if event[3] in affected:
                continue
            # Unaffected returns retain their timing after a fresh geometry check.
            if event[2] == "return":
                event = deepcopy(event)
                event[4]["hazard_revision"] = registry.revision
            queue.append(event)
        core.data["queue"] = queue
        heapq.heapify(core.data["queue"])
        impact = {"schema_version": CONTRACT, "hazard_revision": registry.revision,
                  "at_sim_time": core.data["clock"], "assessed_count": len(assessments),
                  "affected_count": len(affected), "review_required_drone_ids": sorted(in_progress),
                  "assessments": assessments, "duration_seconds": time.perf_counter() - started,
                  "acknowledgement_mode": "Actual fleet simulator assessments; no real radio acknowledgement"}
        core.data["hazard_assessments"].append(impact)
        core._log("hazard_update", None, revision=registry.revision, affected_drones=sorted(affected))
        after = {i: (deepcopy(d["position"]), d["battery"], d["actions_used"]) for i, d in core.data["drones"].items()}
        if before != after:
            raise RuntimeError("Reported hazard mutated completed aircraft resources")
        core.assert_invariants()
        return deepcopy(impact)


def review_due_reports(core):
    """At the next logical boundary, expiry retains the same restricted area."""
    if not core.data['hazards']['hazards']:
        return None
    registry = restore_fleet_registry(core.data['hazards'])
    registry.expire(core.data['clock'])
    if registry.revision != core.data['hazards']['revision']:
        return publish_registry(core, fleet_registry(registry))
    return None


class LiveFleetHazards:
    """A view/controller over FleetService.core, including after New/Open."""
    mode = "actual_part12_fleet_integration"

    def __init__(self, service):
        self.service = service
        self.prepared = {}

    @property
    def core(self):
        return self.service.core

    def report(self, event):
        with self.service.lock, self.core.lock:
            candidate = restore_fleet_registry(self.core.data["hazards"])
            candidate.apply(event)
            return publish_registry(self.core, fleet_registry(candidate))

    def event(self, action="report", *, rectangle=None, notes="Authored reported crane; not an automatically detected obstacle", source="synthetic_event"):
        d = self.core.data
        event = crane_event(d["hazards"]["revision"], action=action, effective=d["clock"], source=source,
                            rect=rectangle or {"x_min": 10.8, "y_min": 0.8, "x_max": 30.2, "y_max": 1.2, "buffer_m": 0.1}, notes=notes)
        if source == "operator_report":
            stamp = datetime.now(timezone.utc).isoformat()
            event["observed_at_utc"] = event["reported_at_utc"] = stamp
        return event

    def snapshot(self):
        with self.service.lock, self.core.lock:
            d = self.core.data
            registry = restore_fleet_registry(d["hazards"])
            paths = []
            for p in fleet_paths(self.core):
                paths.append({"schema_version": CONTRACT, "coordinate_frame": deepcopy(FRAME),
                              **{k: deepcopy(p[k]) for k in ("drone_id", "task_id", "view_id", "model_version", "fleet_revision", "drone_revision", "task_revision", "hazard_revision", "target", "return_point")},
                              "position": deepcopy(p["current"]), "original_origin": deepcopy(p["origin"]),
                              "outbound": deepcopy(p["segments"]["outbound"]), "return": deepcopy(p["segments"]["protected_return"])})
            drones = {i: dict(deepcopy(drone), actions_remaining=drone["capture_cap"] - drone["actions_used"],
                              checked_hazard_revision=drone.get("hazard_checked_revision")) for i, drone in d["drones"].items()}
            return {"schema_version": CONTRACT, "mode": self.mode, "simulated": True,
                    "run_id": d["run_id"], "state_revision": d["state_revision"], "size": d["size"],
                    "sim_time": d["clock"], "fleet_revision": d["fleet_revision"], "drones": drones,
                    "current_paths": paths, "proposals": {i:deepcopy(p) for i,p in self.prepared.items() if p['run_id']==d['run_id']},
                    "ground": deepcopy(d["ground"]),
                    "hazards": {"registry": registry.snapshot(), "latest_impact": deepcopy(d["hazard_assessments"][-1]) if d["hazard_assessments"] else None}}

    def prepare(self, did):
        with self.service.lock, self.core.lock:
            if did not in self.core.data["drones"]:
                raise ValueError("Unknown drone")
            if not self.core.data["assignments"]:
                self.core.allocate()
            a = self.core.data["assignments"].get(did)
            if a is None:
                self.prepared.pop(did, None)
                return "No eligible assignment for this drone. Review the hold reason on the fleet desk."
            p = self.core._path(self.core.data["drones"][did], self.core.data["tasks"][a["task_id"]], a["origin"])
            self.prepared[did] = {"run_id": self.core.data["run_id"], "assignment_id": a["assignment_id"], "path": p,
                                  "hazard": {"assessment": assess_fleet_path(p, self.core.data["hazards"])},
                                  "numerical": {"mode": a["mode"], "output": {"options": [deepcopy(a["cost"])]}}}
            return "Assignment prepared using the real fleet coordinator; no movement or capture executed."

    def try_prepared(self, did):
        with self.service.lock, self.core.lock:
            proposal = self.prepared.get(did)
            assignment = self.core.data["assignments"].get(did)
            if not proposal or proposal["run_id"] != self.core.data["run_id"] or not assignment or assignment["assignment_id"] != proposal["assignment_id"]:
                return {"status": "rejected", "reason": "Prepared assignment is missing/stale; no movement or debit"}
            p = self.core._path(self.core.data["drones"][did], self.core.data["tasks"][assignment["task_id"]], assignment["origin"])
            if p != proposal["path"] or self.core.check_assignment(self.core.data["drones"][did], assignment, assignment["phase"]):
                return {"status": "rejected", "reason": "Prepared path/revision is stale or blocked; no movement or debit"}
            self.core.advance(1)
            return {"status": "executed", "reason": "Advanced one globally ordered fleet event through the current guarded engine. Continue on Fleet desk for full playback."}

    def dispatch(self, name, data):
        with self.service.lock, self.core.lock:
            if name != "state":
                if data.get("run_id") != self.core.data["run_id"] or data.get("state_revision") != self.core.data["state_revision"]:
                    raise ValueError("Fleet changed; refresh the hazard desk before applying this command")
                data = {k: v for k, v in data.items() if k not in ("run_id", "state_revision")}
            message, saved = "Current live fleet store loaded; no aircraft action executed.", None
            if name == "state":
                pass
            elif name == "reset" and set(data) == {"size", "confirm_reset"}:
                token = self.core.data
                self.service.command({"action": "new", "run_id": token["run_id"], "state_revision": token["state_revision"],
                                      "size": data["size"], "seed": token["seed"], "mode": self.service.mode,
                                      "confirm_reset": data["confirm_reset"]})
                self.prepared.clear()
                message = "New paused fleet started. Existing saved runs remain available."
            elif name == "prepare" and set(data) == {"drone_id"}:
                message = self.prepare(data["drone_id"])
            elif name == "execute" and set(data) == {"drone_id"}:
                result = self.try_prepared(data["drone_id"])
                message = result["status"].upper() + ": " + result["reason"]
            elif name in ("report-example", "operator-report", "clear"):
                if name == "operator-report":
                    from .core import rectangle as validate_rectangle
                    validate_rectangle(data.get("rectangle"))
                exists = any(h["hazard_id"] == "crane-001" for h in self.core.data["hazards"]["hazards"])
                action = "clear" if name == "clear" else ("amend" if exists else "report")
                event = self.event(action, rectangle=data.get("rectangle"), notes=data.get("notes", "Authored crane report after earlier simulated planning"),
                                   source="synthetic_event" if name == "report-example" else "operator_report")
                impact = self.report(event)
                message = f"Revision {impact['hazard_revision']}: all {impact['assessed_count']} actual fleet records assessed; {impact['affected_count']} affected. Prior proposals invalidated."
            elif name == "replan" and not data:
                if self.core.data["assignments"]:
                    raise ValueError("A current allocation wave is still active; finish or report a change before replanning")
                selected = self.core.allocate()
                message = f"Real coordinator prepared {len(selected)} current exclusive assignments; affected in-progress drones remain held for review. No capture executed."
            elif name in ("save", "report") and not data:
                token = self.core.data
                result = self.service.command({"action": name, "run_id": token["run_id"], "state_revision": token["state_revision"]})
                saved = result["saved"]["checkpoint"]
                message = "Saved real fleet " + ("run and hazard report: " if name == "report" else "run: ") + saved
            elif name == "reopen" and set(data) == {"name"}:
                token = self.core.data
                self.service.command({"action": "open", "run_id": token["run_id"], "state_revision": token["state_revision"], "checkpoint": data["name"]})
                self.prepared.clear()
                saved, message = data["name"], "Real fleet reopened paused with exact reported areas, budgets and original ground context."
            else:
                raise ValueError("Unsupported hazard command")
            return {"state": self.snapshot(), "message": message, "saved_name": saved}
