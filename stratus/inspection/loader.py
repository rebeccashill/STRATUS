"""Validate and freeze local mission inputs and traceable evidence references."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from .png import validate_png

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MISSION = "stratus/inspection/missions/solar-array-001.json"


class MissionValidationError(ValueError):
    """A local input cannot be used by the prototype."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MissionValidationError(message)


def mapping(value: Any, label: str) -> dict:
    require(isinstance(value, dict), f"{label}: expected an object")
    return value


def sequence(value: Any, label: str) -> list:
    require(isinstance(value, list), f"{label}: expected a list")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty text")
    return value


def finite(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def number(value: Any, label: str, *, positive: bool = False) -> float:
    require(type(value) in (int, float), f"{label}: expected a finite number, not a boolean")
    require(finite(value), f"{label}: must be finite and representable")
    require(value > 0 if positive else value >= 0,
            f"{label}: must be {'positive' if positive else 'nonnegative'}")
    return value


def integer(value: Any, label: str) -> int:
    require(type(value) is int and value >= 0, f"{label}: expected a nonnegative integer")
    return value


def point(value: Any, label: str) -> None:
    obj = mapping(value, label)
    for axis in ("x", "y"):
        value = obj.get(axis)
        require(finite(value),
                f"{label}.{axis}: expected a finite coordinate")


def local_path(root: Path, value: Any, label: str) -> Path:
    relative = text(value, label)
    pure = PurePosixPath(relative)
    require(not pure.is_absolute() and ".." not in pure.parts
            and "\\" not in relative and ":" not in relative,
            f"{label}: use a project-relative path without parent traversal")
    path = (root / relative).resolve()
    require(path.is_relative_to(root), f"{label}: path escapes the STRATUS folder")
    return path


def _unique_keys(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, f"JSON contains duplicate field {key!r}")
        value[key] = item
    return value


def _invalid_constant(value):
    raise MissionValidationError(f"JSON contains non-finite numeric value {value}")


def read_json(path: Path, label: str) -> dict:
    try:
        require(path.stat().st_size <= 2 * 1024 * 1024, f"{label}: JSON exceeds 2 MiB")
        return mapping(json.loads(path.read_text(encoding="utf-8-sig"),
                                  object_pairs_hook=_unique_keys,
                                  parse_constant=_invalid_constant), label)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MissionValidationError(f"{label}: cannot read valid JSON at {path.name}: {exc}") from exc


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Evidence:
    record: Mapping[str, Any]
    image_path: Path


@dataclass(frozen=True)
class Mission:
    document: Mapping[str, Any]
    project_root: Path
    mission_path: Path
    evidence_by_view: Mapping[tuple[str, str], Evidence]
    annotations_by_id: Mapping[str, Mapping[str, Any]]


def check_image(evidence: Evidence, root: Path) -> tuple[int, int]:
    """Check again at request time: files may change after mission load."""
    path = local_path(root, evidence.record["image_path"], "image_path")
    data, width, height = validate_png(path)
    if hashlib.sha256(data).hexdigest() != evidence.record["sha256"]:
        raise ValueError("image SHA-256 does not match the declared fixture")
    return width, height


def load_mission(path: Path | None = None, *, project_root: Path = PROJECT_ROOT) -> Mission:
    root = project_root.resolve()
    path = Path(path).resolve() if path is not None else root / DEFAULT_MISSION
    doc = read_json(path, "mission")
    require(doc.get("schema_version") == "0.0.1", "mission.schema_version: expected 0.0.1")
    for name in ("mission_id", "scenario_id", "revision", "operator_role", "decision"):
        text(doc.get(name), f"mission.{name}")
    require(doc.get("execution_mode") == "synthetic_evidence_replay",
            "mission.execution_mode: this adapter requires synthetic_evidence_replay")
    scenario = doc["scenario_id"]
    frame = mapping(doc.get("coordinate_frame"), "coordinate_frame")
    require(frame.get("unit") == "m", "coordinate_frame.unit: required and must be m (metres)")
    point(doc.get("launch_point"), "launch_point (also the return point)")
    state = mapping(doc.get("initial_state"), "initial_state")
    point(state.get("position"), "initial_state.position")
    energy = mapping(doc.get("energy_model"), "energy_model")
    text(energy.get("model_version"), "energy_model.model_version")
    require(energy.get("distance_unit") == frame["unit"], "energy_model.distance_unit: must match coordinates")
    require(energy.get("energy_unit") == "simulated_energy_unit", "energy_model.energy_unit: expected simulated_energy_unit")
    capacity = number(energy.get("initial_battery_capacity"), "energy_model.initial_battery_capacity", positive=True)
    available = number(state.get("battery_available"), "initial_state.battery_available")
    require(available <= capacity, "initial_state.battery_available: exceeds battery capacity")
    for key in ("travel_energy_per_m", "capture_energy_per_action", "return_reserve"):
        number(energy.get(key), f"energy_model.{key}")
    require(energy["return_reserve"] <= capacity, "energy_model.return_reserve: exceeds battery capacity")
    rules = mapping(doc.get("action_rules"), "action_rules")
    maximum = integer(rules.get("max_new_capture_actions"), "action_rules.max_new_capture_actions")
    used = integer(state.get("actions_used"), "initial_state.actions_used")
    remaining = integer(state.get("actions_remaining"), "initial_state.actions_remaining")
    require(used + remaining == maximum, "initial_state: used + remaining actions must equal the action cap")
    for key, expected in {
        "new_inspection_action_cost": 1, "follow_up_view_action_cost": 1,
        "prior_records_consume_new_actions": False, "duplicate_asset_view_allowed": False,
        "follow_up_requires_distinct_view_id": True, "return_or_stop_capture_action_cost": 0,
        "proposal_and_review_action_cost": 0,
    }.items():
        require(type(rules.get(key)) is type(expected) and rules[key] == expected,
                f"action_rules.{key}: expected {expected!r}")
    assets = sequence(doc.get("assets"), "assets")
    require(bool(assets), "assets: at least one panel is required")
    assets_by_id, expected_views = {}, set()
    for asset in assets:
        asset = mapping(asset, "asset")
        asset_id = text(asset.get("asset_id"), "asset.asset_id")
        require(asset_id not in assets_by_id, f"duplicate asset ID: {asset_id}")
        assets_by_id[asset_id] = asset
        point(asset.get("position"), f"asset {asset_id}.position")
        require(type(asset.get("priority")) is int and asset["priority"] in (1, 2, 3),
                f"asset {asset_id}.priority: expected 1, 2, or 3")
        eligibility = mapping(asset.get("eligibility"), f"asset {asset_id}.eligibility")
        require(eligibility.get("reviewed") is True and eligibility.get("state") in ("eligible", "excluded"),
                f"asset {asset_id}.eligibility: must be reviewed and eligible/excluded")
        text(eligibility.get("reason"), f"asset {asset_id}.eligibility.reason")
        views = sequence(asset.get("planned_view_ids"), f"asset {asset_id}.planned_view_ids")
        require(bool(views), f"asset {asset_id}: planned views are required")
        for view in views:
            text(view, f"asset {asset_id}.view_id")
            require((asset_id, view) not in expected_views, f"asset {asset_id}: duplicate view ID {view}")
            expected_views.add((asset_id, view))

    manifest = read_json(local_path(root, doc.get("evidence_manifest"), "evidence_manifest"), "manifest")
    require(manifest.get("schema_version") == "1" and manifest.get("scenario_id") == scenario,
            "manifest: schema or scenario does not match the mission")
    by_view, by_id, image_paths = {}, {}, set()
    for entry in sequence(manifest.get("entries"), "manifest.entries"):
        entry = mapping(entry, "manifest entry")
        evidence_id = text(entry.get("evidence_id"), "evidence_id")
        asset_id = text(entry.get("asset_id"), f"{evidence_id}.asset_id")
        view = text(entry.get("view_id"), f"{evidence_id}.view_id")
        require(asset_id in assets_by_id, f"{evidence_id}: unknown asset ID {asset_id}")
        require((asset_id, view) in expected_views, f"{evidence_id}: unknown view ID {view}")
        require(entry.get("scenario_id") == scenario, f"{evidence_id}: scenario mismatch")
        require(evidence_id not in by_id, f"duplicate evidence ID: {evidence_id}")
        require((asset_id, view) not in by_view, f"duplicate asset/view evidence: {asset_id}/{view}")
        require(entry.get("source_label") == "synthetic", f"{evidence_id}: an explicit synthetic source label is required")
        for field in ("source_mode", "source_note", "rights_note", "generator"):
            text(entry.get(field), f"{evidence_id}.{field}")
        require(isinstance(entry.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])),
                f"{evidence_id}: expected a SHA-256 digest")
        image_path = local_path(root, entry.get("image_path"), f"{evidence_id}.image_path")
        require(image_path not in image_paths, f"{evidence_id}: distinct views require distinct image paths")
        image_paths.add(image_path)
        evidence = Evidence(freeze(entry), image_path)
        try:
            check_image(evidence, root)
        except (OSError, ValueError) as exc:
            raise MissionValidationError(f"{asset_id}/{view}: missing, unreadable, or changed evidence: {exc}") from exc
        by_view[(asset_id, view)], by_id[evidence_id] = evidence, evidence
    require(set(by_view) == expected_views, "manifest: missing evidence for planned asset/view pairs")

    annotations = read_json(local_path(root, manifest.get("annotations_path"), "annotations_path"), "annotations")
    require(annotations.get("schema_version") == "1" and annotations.get("scenario_id") == scenario,
            "annotations: schema or scenario does not match the mission")
    annotations_by_id = {}
    for annotation in sequence(annotations.get("annotations"), "annotations.annotations"):
        annotation = mapping(annotation, "annotation")
        evidence_id = text(annotation.get("evidence_id"), "annotation.evidence_id")
        require(evidence_id in by_id, f"annotation: unknown evidence ID {evidence_id}")
        require(evidence_id not in annotations_by_id, f"duplicate annotation ID: {evidence_id}")
        require(annotation.get("scenario_id") == scenario, f"annotation {evidence_id}: scenario mismatch")
        require(annotation.get("assessment_mode") == "authored_replay_annotation"
                and annotation.get("live_model_output") is False,
                f"annotation {evidence_id}: must be an authored replay, never live inference")
        require(annotation.get("human_review_status") == "pending", f"annotation {evidence_id}: human review must remain pending")
        text(annotation.get("annotation_author"), f"annotation {evidence_id}.annotation_author")
        text(annotation.get("note"), f"annotation {evidence_id}.note")
        require(annotation.get("image_quality") in ("clear", "unclear"), f"annotation {evidence_id}: invalid image quality")
        require(annotation.get("finding") in ("unknown", "apparent_concern_review_required", "no_apparent_concern_in_synthetic_drawing"),
                f"annotation {evidence_id}: invalid finding")
        require(annotation["image_quality"] != "unclear" or annotation["finding"] == "unknown",
                f"annotation {evidence_id}: unclear evidence must retain an unknown finding")
        annotations_by_id[evidence_id] = freeze(annotation)
    require(set(annotations_by_id) == set(by_id), "annotations: every evidence ID needs a separate annotation")
    prior_ids, prior_views = set(), set()
    for prior in sequence(doc.get("prior_records"), "prior_records"):
        prior = mapping(prior, "prior record")
        record_id = text(prior.get("record_id"), "prior.record_id")
        require(record_id not in prior_ids, f"duplicate prior record ID: {record_id}")
        prior_ids.add(record_id)
        asset = text(prior.get("asset_id"), f"{record_id}.asset_id")
        view = text(prior.get("view_id"), f"{record_id}.view_id")
        require((asset, view) in by_view, f"{record_id}: unknown prior asset/view {asset}/{view}")
        require((asset, view) not in prior_views, f"duplicate prior asset/view: {asset}/{view}")
        prior_views.add((asset, view))
        evidence = by_view[(asset, view)]
        ref = prior.get("evidence_ref")
        require(ref == evidence.record["evidence_id"], f"{record_id}: evidence reference does not match its asset/view")
        require(prior.get("consumes_new_action") is False, f"{record_id}: prior records cannot consume new actions")
        require(prior.get("source_class") == evidence.record["source_label"]
                and prior.get("assessment_mode") == "authored_replay_annotation",
                f"{record_id}: prior provenance does not match its evidence")
        require(prior.get("image_quality_annotation") == annotations_by_id[ref]["image_quality"],
                f"{record_id}: prior quality conflicts with its replay annotation")
        require(prior.get("evidence_status") == "available_synthetic", f"{record_id}: expected available_synthetic")
    require(doc.get("optional_sensor_context_ref") is None,
            "optional sensor context remains separate and pending in this case")
    return Mission(freeze(doc), root, path, MappingProxyType(by_view), MappingProxyType(annotations_by_id))
