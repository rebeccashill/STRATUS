"""Explicit fixture host for contract tests and preview, not the Part 12 engine."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import threading

from .bridge import HazardBridge
from .core import CONTRACT, assess_path, integer, normalize_path, number, path_signature, text
from .fixtures import crane_event, fleet_paths, path
from stratus.inspection.computation import CostCalculator, normalize_input, python_costs, _check_reply


class FixtureFleetHost:
    mode = "fixture_host_not_part12_fleet_integration"

    def __init__(self, size=2, *, calculator=None):
        self.lock = threading.RLock()
        self.paths = {p["drone_id"]: p for p in fleet_paths(size)}
        self.drones = {i: {"battery": 100.0, "actions_used": 0, "actions_remaining": 3,
                           "revision": 0, "status": "assigned", "task_id": p["task_id"],
                           "position": deepcopy(p["position"]), "in_progress": False} for i, p in self.paths.items()}
        self.fleet_revision = 0
        self.sim_time = 0.0
        self.receipts = {}
        self.completed_tasks = []
        self.proposals = {}
        self.notices = []
        self.ground = {"source_label": "Unavailable", "observed_at_utc": None, "location": "location not supplied",
                       "note": "No physical measurements are acquired by the hazard fixture host"}
        self.calculator = calculator if calculator is not None else CostCalculator("local")
        self.bridge = HazardBridge(self)

    def path_snapshots(self, hazard_revision):
        return [self.current_path(i, d["task_id"], hazard_revision) for i, d in self.drones.items()]

    def current_path(self, drone_id, task_id, hazard_revision):
        d = self.drones[drone_id]
        if d["task_id"] != task_id:
            raise ValueError("Task ownership changed")
        p = deepcopy(self.paths[drone_id])
        p.update(fleet_revision=self.fleet_revision, drone_revision=d["revision"], hazard_revision=hazard_revision,
                 position=deepcopy(d["position"]))
        p["outbound"] = [deepcopy(p["position"]), deepcopy(p["target"])]
        return normalize_path(p)

    def on_hazard_update(self, impact):
        self.fleet_revision += 1
        for assessment in impact["assessments"]:
            d = self.drones[assessment["drone_id"]]
            if d["status"] == "complete":
                continue
            d["status"] = "review_required" if d["in_progress"] else ("held" if assessment["state"] != "clear" else "assigned")
            d["checked_hazard_revision"] = impact["hazard_revision"]
        self.notices.append({"time": self.sim_time, "kind": "hazard_update", "impact": deepcopy(impact)})

    def existing_receipt(self, request_id):
        text(request_id, "request_id")
        return self.receipts.get(request_id)

    def cost_input(self, p):
        d = self.drones[p["drone_id"]]
        return normalize_input({"contract_version": "inspection-costs-v1", "model_version": p["model_version"],
                                "mission_id": "part13-authored-fixture", "mission_revision": "part13-v1",
                                "state_revision": p["drone_revision"],
                                "position": {"point_id": "current", **p["position"]},
                                "launch": {"point_id": "return", **p["return_point"]},
                                "distance_unit": "m", "energy_unit": "simulated_energy_unit",
                                "battery_available": d["battery"], "capture_cost": 5,
                                "travel_energy_per_distance": 0.5, "return_reserve": 15,
                                "remaining_actions": d["actions_remaining"],
                                "candidates": [{"asset_id": p["task_id"], "view_id": p["view_id"], **p["target"]}]})

    def prepare(self, drone_id):
        with self.lock:
            d = self.drones[drone_id]
            p = self.current_path(drone_id, d["task_id"], self.bridge.registry.revision)
            data = self.cost_input(p)
        # No network/kernel work while holding the host or registry lock.
        numerical = self.calculator.compute(data)
        proposal = {"path": p, "numerical": numerical, "hazard": self.bridge.envelope(p),
                    "mode": self.mode, "prepared_at_utc": datetime.now(timezone.utc).isoformat()}
        with self.lock:
            self.proposals[drone_id] = deepcopy(proposal)
        return proposal

    def commit_validated(self, p, numerical, request_id, assessment):
        d = self.drones[p["drone_id"]]
        if d["status"] in ("complete", "review_required") or d["in_progress"]:
            return HazardBridge._reject("lifecycle_block", "Fixture host requires review or a new task")
        if p["task_id"] in self.completed_tasks or d["actions_remaining"] <= 0:
            return HazardBridge._reject("completed_or_exhausted", "Task completed or capture allowance exhausted")
        expected = python_costs(self.cost_input(p))
        if numerical.get("normalized_input") != self.cost_input(p):
            return HazardBridge._reject("stale_numerical_input", "Numerical input does not match current drone/task state")
        output = numerical.get("output", {})
        # Local output deliberately has no Wolfram runtime metadata. Actual
        # Wolfram output uses the existing strict/tolerant typed validator.
        differences = _check_reply(output, expected) if "wolfram_version" in output else ([] if output == expected else ["local cost mismatch"])
        if differences or not output.get("options", [{}])[0].get("feasible"):
            return HazardBridge._reject("numerical_disagreement", "Independent cost/feasibility validation failed")
        o = output["options"][0]
        debit = o["outbound"] + o["capture"]
        d["battery"] -= debit
        d["actions_used"] += 1
        d["actions_remaining"] -= 1
        d["revision"] += 1
        d["position"] = deepcopy(p["target"])
        d["status"] = "complete"
        self.completed_tasks.append(p["task_id"])
        self.fleet_revision += 1
        self.sim_time += 1
        receipt = {"status": "executed", "mode": self.mode, "request_id": request_id,
                   "drone_id": p["drone_id"], "task_id": p["task_id"], "hazard_assessment": assessment,
                   "path_signature": path_signature(p), "battery_debit": debit, "capture_action_debit": 1,
                   "state_transition_applied": True, "numerical_mode": numerical["mode"], "sim_time": self.sim_time,
                   "evidence": "Synthetic contract-fixture capture; no camera or Part 12 flight engine executed"}
        self.receipts[request_id] = deepcopy(receipt)
        return receipt

    def execute(self, drone_id, request_id):
        with self.lock:
            proposal = deepcopy(self.proposals.get(drone_id))
        if proposal is None:
            return HazardBridge._reject("proposal_required", "Prepare a fixture proposal first")
        return self.bridge.commit(proposal["path"], proposal["numerical"], request_id=request_id)

    def report(self, event=None):
        with self.lock:
            event = event if event is not None else crane_event(self.bridge.registry.revision, effective=max(1, self.sim_time))
            if event.get("effective_sim_time", -1) < self.sim_time:
                raise ValueError("Hazard event is behind the host's current simulation time")
            impact = self.bridge.report(event)
            self.sim_time = max(self.sim_time, event["effective_sim_time"])
            return impact

    def replan(self):
        with self.lock:
            changes = []
            # Existing proposals deliberately remain available to test stale rejection.
            for i, d in self.drones.items():
                if d["status"] != "held":
                    continue
                old = self.current_path(i, d["task_id"], self.bridge.registry.revision)
                target = {"x": 10, "y": d["position"]["y"] + 10}
                candidate = path(i, "ALT-" + i, position=d["position"], target=target,
                                 home=old["return_point"], hazard_revision=self.bridge.registry.revision,
                                 fleet_revision=self.fleet_revision, drone_revision=d["revision"], task_revision=1)
                assessment = assess_path(candidate, self.bridge.registry)
                numeric = python_costs(self.cost_input(candidate))["options"][0]
                if assessment["state"] != "clear" or not numeric["feasible"]:
                    continue
                if any(other["task_id"] == candidate["task_id"] for name, other in self.drones.items() if name != i):
                    continue
                changes.append({"drone_id": i, "from_task": d["task_id"], "to_task": candidate["task_id"],
                                "reason": "Original work held; distinct fixture task passes both segment and budget checks"})
                self.paths[i] = candidate
                d["task_id"], d["status"] = candidate["task_id"], "assigned"
                d["revision"] += 1
            if changes:
                self.fleet_revision += 1
            return changes

    def snapshot(self):
        with self.lock:
            paths = self.path_snapshots(self.bridge.registry.revision)
            return deepcopy({"schema_version": CONTRACT, "mode": self.mode, "simulated": True,
                             "size": len(self.drones), "fleet_revision": self.fleet_revision,
                             "sim_time": self.sim_time, "drones": self.drones, "paths": self.paths,
                             "current_paths": paths, "receipts": self.receipts, "proposals": self.proposals,
                             "completed_tasks": self.completed_tasks, "notices": self.notices,
                             "ground": self.ground, "hazards": self.bridge.export()})

    @classmethod
    def restore(cls, saved, *, calculator=None):
        if not isinstance(saved, dict) or saved.get("mode") != cls.mode or saved.get("schema_version") != CONTRACT:
            raise ValueError("This loader accepts hazard fixture-host saves only")
        host = cls(saved["size"], calculator=calculator)
        ids = set(host.drones)
        if set(saved["drones"]) != ids or set(saved["paths"]) != ids:
            raise ValueError("Saved drone/path identities disagree")
        for i, d in saved["drones"].items():
            number(d["battery"], "battery", 0, 100)
            integer(d["revision"], "drone revision")
            if type(d["actions_used"]) is not int or type(d["actions_remaining"]) is not int or not 0 <= d["actions_used"] <= 3 or d["actions_used"] + d["actions_remaining"] != 3:
                raise ValueError("Saved action accounting is invalid")
            normalize_path(saved["paths"][i])
            receipts = [r for r in saved["receipts"].values() if r["drone_id"] == i]
            if len(receipts) != d["actions_used"] or not math.isclose(100 - sum(r["battery_debit"] for r in receipts), d["battery"], abs_tol=1e-8):
                raise ValueError("Saved receipts and budgets disagree")
        completed = [r["task_id"] for r in saved["receipts"].values()]
        if len(set(completed)) != len(completed) or sorted(completed) != sorted(saved["completed_tasks"]):
            raise ValueError("Saved completed task identities disagree")
        integer(saved["fleet_revision"], "fleet revision")
        number(saved["sim_time"], "sim_time", 0, 1e9)
        with host.lock:
            for key in ("drones", "paths", "receipts", "proposals", "completed_tasks", "notices", "ground", "fleet_revision", "sim_time"):
                setattr(host, key, deepcopy(saved[key]))
            host.bridge.restore(saved.get("hazards"))
            if host.path_snapshots(host.bridge.registry.revision) != saved["current_paths"]:
                raise ValueError("Saved current path snapshots disagree with state")
        return host

    def fingerprint(self):
        data = self.snapshot()
        # Performance measurements and operation descriptions are not aircraft resources.
        relevant = {k: data[k] for k in ("drones", "completed_tasks", "receipts", "ground")}
        return hashlib.sha256(json.dumps(relevant, sort_keys=True, allow_nan=False).encode()).hexdigest()
