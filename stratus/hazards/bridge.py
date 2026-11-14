"""Host-neutral admission/commit and serialization hooks for Part 12.

A host supplies its real state lock, current snapshots, execution and replan
callbacks. Hazard code never owns or copies the fleet's authoritative store.
"""

from copy import deepcopy
from .core import CONTRACT, HazardRegistry, assess_fleet, assess_path, normalize_path, path_signature


class HazardBridge:
    def __init__(self, host, registry=None):
        self.host = host
        self.registry = registry if registry is not None else HazardRegistry()
        self.latest_impact = None

    def assess(self, path):
        return assess_path(path, self.registry)

    def envelope(self, path):
        """Keep these outer fields out of the strict Wolfram numeric payload."""
        assessment = self.assess(path)
        return {"schema_version": CONTRACT, "hazard_revision": assessment["hazard_revision"],
                "path_signature": assessment.get("path_signature"), "assessment": assessment}

    def report(self, event):
        with self.host.lock:
            with self.registry.lock:
                candidate = HazardRegistry.restore(self.registry.snapshot())
                candidate.apply(event)
                paths = self.host.path_snapshots(candidate.revision)
                impact = assess_fleet(paths, candidate)
                # Validate the event and host snapshots before publishing it.
                self.registry.apply(event)
                # The host owns reservations/lifecycle and chooses safe alternatives.
                self.host.on_hazard_update(deepcopy(impact))
                self.latest_impact = deepcopy(impact)
                return deepcopy(impact)

    def commit(self, proposed_path, numerical, *, request_id):
        """Atomic host->registry lock ordering closes report/proposal races.

        Numerical work must be done before calling this method. The host
        callback remains responsible for ownership, identity, evidence,
        numerical parity, budgets and its idempotent receipt transaction.
        """
        with self.host.lock:
            with self.registry.lock:
                receipt = self.host.existing_receipt(request_id)
                if receipt is not None:
                    return deepcopy(receipt)
                try:
                    proposed = normalize_path(proposed_path)
                    current = self.host.current_path(proposed["drone_id"], proposed["task_id"], self.registry.revision)
                    if path_signature(proposed) != path_signature(current):
                        return self._reject("stale_proposal", "Drone/task/fleet/hazard revision or path changed")
                    assessment = assess_path(current, self.registry)
                    if assessment["state"] != "clear":
                        return self._reject("reported_hazard", assessment["reason"], assessment)
                    if not isinstance(numerical, dict) or numerical.get("execution_permitted") is not True:
                        return self._reject("numerical_disagreement", "Numerical validation did not authorize execution", assessment)
                    return self.host.commit_validated(current, numerical, request_id, deepcopy(assessment))
                except (ValueError, KeyError, TypeError) as exc:
                    return self._reject("invalid_or_stale_proposal", str(exc))

    @staticmethod
    def _reject(code, reason, assessment=None):
        return {"status": "rejected", "code": code, "reason": reason,
                "state_transition_applied": False, "capture_action_debit": 0, "battery_debit": 0,
                "hazard_assessment": assessment}

    def export(self):
        with self.host.lock:
            return {"schema_version": CONTRACT, "registry": self.registry.snapshot(),
                    "latest_impact": deepcopy(self.latest_impact)}

    def restore(self, value=None):
        # Old runs without an extension load an explicit empty registry.
        candidate = HazardRegistry.restore(value["registry"]) if value is not None else HazardRegistry()
        if value is not None and value.get("schema_version") != CONTRACT:
            raise ValueError("Unsupported hazard extension")
        impact = deepcopy(value.get("latest_impact")) if value else None
        if impact is not None:
            if impact.get("hazard_revision") != candidate.revision:
                raise ValueError("Saved assessment has the wrong registry revision")
            for item in impact.get("assessments", []):
                if item.get("hazard_revision") != candidate.revision:
                    raise ValueError("Saved per-drone assessment is stale")
        with self.host.lock:
            self.registry, self.latest_impact = candidate, impact

