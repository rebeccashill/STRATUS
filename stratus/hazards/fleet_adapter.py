"""Adapter for the frozen Part 12 plain-record contract, without fleet imports.

Both coordinate frames are explicitly authored local metre grids. The identity
mapping below is a declared convention for this synthetic scenario only. It is
not a geographic reprojection or a claim that a physical node is at this site.
"""

from copy import deepcopy
from stratus.contracts.fleet_v1 import FRAME as FLEET_FRAME, PATH_VERSION, REGISTRY_VERSION, validate_path
from .core import CONTRACT, FRAME, HazardRegistry, assess_path, path_signature


def fleet_registry(registry):
    value = registry.snapshot() if isinstance(registry, HazardRegistry) else deepcopy(registry)
    # Replaying first rejects forged/tampered lifecycle records.
    value = HazardRegistry.restore(value).snapshot()
    return {"schema_version": REGISTRY_VERSION, "coordinate_frame": deepcopy(FLEET_FRAME),
            "revision": value["revision"], "hazards": [deepcopy(h) for h in value["hazards"].values()],
            "events": deepcopy(value["events"])}


def assess_fleet_path(proposed, registry):
    checked = registry.get("revision") if isinstance(registry, dict) else None
    failure = {"schema_version": "stratus-hazard-assessment-v1", "checked_revision": checked,
               "state": "review_required", "hazard_ids": [], "reason": "Invalid fleet path/registry"}
    try:
        validate_path(proposed)
        if not isinstance(registry, dict) or registry.get("schema_version") != REGISTRY_VERSION or registry.get("coordinate_frame") != FLEET_FRAME:
            raise ValueError("Unsupported fleet registry frame/schema")
        if not isinstance(registry.get("hazards"), list) or not isinstance(registry.get("events"), list):
            raise ValueError("Fleet registry requires hazard and event lists")
        records = {}
        for hazard in registry["hazards"]:
            if not isinstance(hazard, dict) or hazard.get("hazard_id") in records:
                raise ValueError("Fleet hazard records require unique identities")
            records[hazard["hazard_id"]] = deepcopy(hazard)
            # Only accept the explicitly declared synthetic-site alias.
            if hazard.get("coordinate_frame") not in (FRAME, FLEET_FRAME):
                raise ValueError("Unknown hazard coordinate frame")
            records[hazard["hazard_id"]]["coordinate_frame"] = deepcopy(FRAME)
        source = {"schema_version": CONTRACT, "coordinate_frame": deepcopy(FRAME),
                  "revision": registry["revision"], "hazards": records, "events": deepcopy(registry["events"])}
        # A nonempty registry must carry a replayable, internally consistent history.
        source = HazardRegistry.restore(source).snapshot()
        p = {"schema_version": CONTRACT, "coordinate_frame": deepcopy(FRAME),
             **{k: proposed[k] for k in ("drone_id", "task_id", "view_id", "model_version", "fleet_revision", "drone_revision", "task_revision", "hazard_revision")},
             "position": deepcopy(proposed["origin"]), "target": deepcopy(proposed["target"]),
             "return_point": deepcopy(proposed["return_point"]),
             "outbound": deepcopy(proposed["segments"]["outbound"]), "return": deepcopy(proposed["segments"]["protected_return"])}
        assessment = assess_path(p, source)
        return {"schema_version": "stratus-hazard-assessment-v1", "checked_revision": assessment["hazard_revision"],
                "state": assessment["state"], "hazard_ids": assessment["hazard_ids"],
                "reason": assessment["reason"], "intersections": assessment["intersections"],
                "path_signature": assessment.get("path_signature"),
                "coordinate_mapping": "Declared identity between authored local-metre fixture grids; not a real-world reprojection"}
    except (ValueError, KeyError, TypeError) as exc:
        failure["reason"] = str(exc)
        return failure


def fleet_path(core_path, scenario_id="part13-synthetic-local-grid"):
    """Executable frozen-contract example for the Part 12 owner and tests."""
    return {"schema_version": PATH_VERSION, "coordinate_frame": deepcopy(FLEET_FRAME),
            **{k: core_path[k] for k in ("drone_id", "task_id", "view_id", "model_version", "fleet_revision", "drone_revision", "task_revision", "hazard_revision")},
            "scenario_id": scenario_id, "origin": deepcopy(core_path["position"]), "current": deepcopy(core_path["position"]),
            "target": deepcopy(core_path["target"]), "return_point": deepcopy(core_path["return_point"]),
            "segments": {"outbound": deepcopy(core_path["outbound"]), "protected_return": deepcopy(core_path["return"])}}
