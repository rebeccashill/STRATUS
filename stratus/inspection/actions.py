"""Typed proposal contract. Loaded text and model output are data, never code."""

import json
from dataclasses import asdict, dataclass
from typing import Any

ACTION_TYPES = ("inspect", "follow_up", "return", "stop")
FIELDS = {"action_type", "asset_id", "view_id", "reason", "alternative"}
ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
        "asset_id": {"type": ["string", "null"]},
        "view_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
        "alternative": {"type": "string"},
    },
    "required": sorted(FIELDS),
}


class ProposalError(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProposalError("Duplicate proposal field")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ProposalError("Non-finite JSON is not allowed")


def strict_json(raw: str, *, max_chars: int = 32_000) -> Any:
    if not isinstance(raw, str) or len(raw) > max_chars:
        raise ProposalError("Tool arguments must be bounded JSON text")
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ProposalError("Malformed tool-argument JSON") from exc


@dataclass(frozen=True)
class Proposal:
    action_type: str
    asset_id: str | None
    view_id: str | None
    reason: str
    alternative: str

    def to_dict(self):
        return asdict(self)


def parse_proposal(value: Any) -> Proposal:
    if isinstance(value, Proposal):
        value = value.to_dict()
    elif isinstance(value, str):
        value = strict_json(value)
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ProposalError("Proposal requires exactly action_type, asset_id, view_id, reason, alternative")
    if not isinstance(value["action_type"], str) or value["action_type"] not in ACTION_TYPES:
        raise ProposalError("Unknown action type; allowed: inspect, follow_up, return, stop")
    for key in ("reason", "alternative"):
        if not isinstance(value[key], str) or not 1 <= len(value[key].strip()) <= 1600:
            raise ProposalError(f"{key} must contain 1-1600 characters")
    for key in ("asset_id", "view_id"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not 1 <= len(item.strip()) <= 128):
            raise ProposalError(f"{key} must be a bounded ID or null")
    capture = value["action_type"] in ("inspect", "follow_up")
    if capture and (value["asset_id"] is None or value["view_id"] is None):
        raise ProposalError("Inspection actions require an asset and view")
    if not capture and (value["asset_id"] is not None or value["view_id"] is not None):
        raise ProposalError("Return/stop must use null asset_id and view_id")
    return Proposal(**value)
