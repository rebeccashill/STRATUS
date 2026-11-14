"""Read-only fixture adapter; state execution/accounting is later checklist work."""

from datetime import datetime, timezone
from typing import Any

from .loader import Mission, check_image


def simulated_capture(mission: Mission, asset_id: str, view_id: str, *,
                      scenario_id: str | None = None,
                      requested_at: datetime | None = None) -> dict[str, Any]:
    """Return fixed evidence or an explicit unknown, without debiting mission state.

    Timestamp is response creation time, not a claimed flight/camera timestamp.
    All planners select the same manifest entry for a given scenario/asset/view.
    """
    when = requested_at or datetime.now(timezone.utc)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("requested_at must include a timezone")
    scenario = mission.document["scenario_id"]
    result = {
        "mission_id": mission.document["mission_id"], "scenario_id": scenario,
        "asset_id": asset_id, "view_id": view_id,
        "timestamp": when.astimezone(timezone.utc).isoformat(),
        "timestamp_kind": "response_created_at_not_camera_capture",
        "capture_mode": "simulated_local_fixture", "real_flight": False,
        "state_transition_applied": False, "source_label": None, "source_mode": None,
        "assessment_mode": "unavailable_no_assessment", "status": "unavailable",
        "image_quality": "unknown", "finding": "unknown", "evidence_ref": None,
        "annotation": None, "reason": None,
    }
    if scenario_id is not None and scenario_id != scenario:
        result["reason"] = "scenario_mismatch"
        return result
    asset = next((a for a in mission.document["assets"] if a["asset_id"] == asset_id), None)
    if asset is None:
        result["reason"] = "unknown_asset_id"
        return result
    if asset["eligibility"]["state"] == "excluded":
        result["reason"] = "asset_excluded_by_operator"
        return result
    evidence = mission.evidence_by_view.get((asset_id, view_id))
    if evidence is None:
        result["reason"] = "unknown_view_id"
        return result
    try:
        width, height = check_image(evidence, mission.project_root)
    except (OSError, ValueError) as exc:
        result["reason"] = f"evidence_unavailable: {exc}"
        return result
    record = evidence.record
    annotation = dict(mission.annotations_by_id[record["evidence_id"]])
    result.update(
        status="available", reason="fixed_synthetic_fixture_no_aircraft_state_change",
        evidence_ref={"evidence_id": record["evidence_id"], "image_path": record["image_path"],
                      "sha256": record["sha256"], "width": width, "height": height,
                      "source_note": record["source_note"], "rights_note": record["rights_note"]},
        source_label=record["source_label"], source_mode=record["source_mode"],
        assessment_mode=annotation["assessment_mode"], image_quality=annotation["image_quality"],
        finding=annotation["finding"], annotation=annotation,
    )
    return result
