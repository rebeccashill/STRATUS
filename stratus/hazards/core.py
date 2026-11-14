"""Versioned, data-only reported hazards. No aircraft, sensor or cost mutations.

Lock order for a host: host state lock, then registry.lock. Registry updates
must release their lock before notifying a host. This makes report/commit
ordering atomic without creating a dependency on a particular fleet engine.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import threading
import time

CONTRACT = "fleet-hazard-v1"
FRAME = {"name": "site_local_cartesian", "unit": "m"}
EPS = 1e-9
MAX_EVENTS = 2000


def number(value, label, minimum=-1e6, maximum=1e6):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be finite and within {minimum}..{maximum}")
    return float(value)


def integer(value, label):
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return value


def text(value, label, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must contain 1..{maximum} characters")
    return value


def utc(value):
    text(value, "UTC timestamp", 80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Timestamp must be ISO 8601 with a UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must include a UTC offset of zero")
    return parsed.astimezone(timezone.utc).isoformat()


def point(value):
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError("Point requires exactly x and y")
    return {axis: number(value[axis], axis) for axis in ("x", "y")}


def rectangle(value):
    if not isinstance(value, dict) or set(value) != {"x_min", "y_min", "x_max", "y_max", "buffer_m"}:
        raise ValueError("Rectangle requires x_min, y_min, x_max, y_max, buffer_m")
    result = {k: number(value[k], k, 0 if k == "buffer_m" else -1e6,
                        10000 if k == "buffer_m" else 1e6) for k in value}
    if result["x_min"] >= result["x_max"] or result["y_min"] >= result["y_max"]:
        raise ValueError("Rectangle must have ordered bounds and positive area")
    return result


def intersects(start, end, rect):
    """Closed segment/closed buffered AABB intersection, including all touches."""
    a, b, r = point(start), point(end), rectangle(rect)
    lo, hi = 0.0, 1.0
    for axis in ("x", "y"):
        lower, upper = r[axis + "_min"] - r["buffer_m"], r[axis + "_max"] + r["buffer_m"]
        delta = b[axis] - a[axis]
        if abs(delta) <= EPS:
            if a[axis] < lower - EPS or a[axis] > upper + EPS:
                return False
        else:
            first, last = sorted(((lower - a[axis]) / delta, (upper - a[axis]) / delta))
            lo, hi = max(lo, first), min(hi, last)
            if lo > hi + EPS:
                return False
    return True


class HazardRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self._revision = 0
        self._hazards = {}
        self._events = []

    @property
    def revision(self):
        with self.lock:
            return self._revision

    def snapshot(self):
        with self.lock:
            return deepcopy({"schema_version": CONTRACT, "coordinate_frame": FRAME,
                             "revision": self._revision, "hazards": self._hazards,
                             "events": self._events})

    def apply(self, event):
        with self.lock:
            if not isinstance(event, dict):
                raise ValueError("Hazard event must be an object")
            required = {"schema_version", "event_id", "hazard_id", "expected_revision", "revision", "action",
                        "source", "observed_at_utc", "reported_at_utc", "effective_sim_time", "notes"}
            allowed = required | {"coordinate_frame", "rectangle", "review_after_sim_time", "source_reference"}
            if not required <= set(event) or set(event) - allowed:
                raise ValueError("Hazard event has missing or unsupported fields")
            e = deepcopy(event)
            if e["schema_version"] != CONTRACT:
                raise ValueError("Unsupported hazard contract")
            for key in ("event_id", "hazard_id"):
                text(e[key], key)
            integer(e["expected_revision"], "expected_revision")
            integer(e["revision"], "revision")
            if e["expected_revision"] != self._revision or e["revision"] != self._revision + 1:
                raise ValueError("Stale/out-of-order hazard revision")
            if any(x["event_id"] == e["event_id"] for x in self._events):
                raise ValueError("Duplicate hazard event")
            if len(self._events) >= MAX_EVENTS:
                raise ValueError("Hazard event history is full; start a new simulation")
            if e["source"] not in ("operator_report", "synthetic_event"):
                raise ValueError("Use operator_report or synthetic_event; automatic detection is not implemented")
            e["observed_at_utc"], e["reported_at_utc"] = utc(e["observed_at_utc"]), utc(e["reported_at_utc"])
            if datetime.fromisoformat(e["observed_at_utc"]) > datetime.fromisoformat(e["reported_at_utc"]):
                raise ValueError("Observation cannot be later than its report")
            e["effective_sim_time"] = number(e["effective_sim_time"], "effective_sim_time", 0, 1e9)
            if self._events and e["effective_sim_time"] < self._events[-1]["effective_sim_time"]:
                raise ValueError("Simulation events must not move backward in time")
            text(e["notes"], "notes", 1000)
            if "source_reference" in e:
                text(e["source_reference"], "source_reference", 1000)
            previous = self._hazards.get(e["hazard_id"])
            if e["action"] not in ("report", "amend", "clear", "review"):
                raise ValueError("Use report, amend, review or clear")
            if (e["action"] == "report") == (previous is not None):
                raise ValueError("Report creates a new ID; amend/clear/review require an existing ID")
            if e["action"] in ("report", "amend"):
                if e.get("coordinate_frame") != FRAME:
                    raise ValueError("Reported area must use the site-local metre frame")
                e["rectangle"] = rectangle(e.get("rectangle"))
            elif "rectangle" in e or "coordinate_frame" in e:
                raise ValueError("Clear/review cannot silently replace geometry")
            if "review_after_sim_time" in e:
                e["review_after_sim_time"] = number(e["review_after_sim_time"], "review_after_sim_time", e["effective_sim_time"], 1e9)
            hazard = deepcopy(previous) if previous else {}
            hazard.update({k: deepcopy(v) for k, v in e.items() if k not in ("action", "expected_revision")})
            hazard["state"] = {"report": "active", "amend": "active", "clear": "cleared", "review": "review_required"}[e["action"]]
            self._hazards[e["hazard_id"]] = hazard
            self._revision = e["revision"]
            self._events.append(e)
            return self.snapshot()

    def expire(self, sim_time):
        """Logical-time expiry never clears a restriction or polls physical sensors."""
        number(sim_time, "sim_time", 0, 1e9)
        with self.lock:
            for h in list(self._hazards.values()):
                if h["state"] == "active" and h.get("review_after_sim_time", math.inf) <= sim_time:
                    stamp = datetime.now(timezone.utc).isoformat()
                    self.apply({"schema_version": CONTRACT, "event_id": f"expiry-{h['hazard_id']}-{self._revision + 1}",
                                "hazard_id": h["hazard_id"], "expected_revision": self._revision,
                                "revision": self._revision + 1, "action": "review", "source": h["source"],
                                "observed_at_utc": h["observed_at_utc"], "reported_at_utc": stamp,
                                "effective_sim_time": sim_time, "notes": "Report expired; restriction retained until explicit operator clearance"})
            return self.snapshot()

    @classmethod
    def restore(cls, value):
        if not isinstance(value, dict) or set(value) != {"schema_version", "coordinate_frame", "revision", "hazards", "events"}:
            raise ValueError("Malformed saved hazard registry")
        if value["schema_version"] != CONTRACT or value["coordinate_frame"] != FRAME:
            raise ValueError("Unsupported saved hazard contract/frame")
        if not isinstance(value["events"], list) or len(value["events"]) > MAX_EVENTS:
            raise ValueError("Invalid hazard history")
        registry = cls()
        for event in value["events"]:
            registry.apply(event)
        if registry.snapshot() != value:
            raise ValueError("Saved registry and replayed event history disagree")
        return registry


def normalize_path(value):
    if not isinstance(value, dict) or value.get("schema_version") != CONTRACT or value.get("coordinate_frame") != FRAME:
        raise ValueError("Path requires the hazard v1 contract and site-local metre frame")
    result = deepcopy(value)
    for key in ("drone_id", "task_id", "view_id", "model_version"):
        text(value.get(key), key)
    for key in ("fleet_revision", "drone_revision", "task_revision", "hazard_revision"):
        integer(value.get(key), key)
    for key in ("position", "target", "return_point"):
        result[key] = point(value.get(key))
    for key, start, end in (("outbound", "position", "target"), ("return", "target", "return_point")):
        segment = value.get(key)
        if not isinstance(segment, list) or len(segment) != 2:
            raise ValueError(f"{key} requires two explicit endpoints")
        result[key] = [point(p) for p in segment]
        if result[key] != [result[start], result[end]]:
            raise ValueError(f"{key} endpoints disagree with the proposed position/target/return")
    return result


def path_signature(value):
    normalized = normalize_path(value)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def assess_path(path, registry):
    """Pure conservative assessment; invalid paths/registries never become clear."""
    value = registry.snapshot() if isinstance(registry, HazardRegistry) else deepcopy(registry)
    result = {"schema_version": CONTRACT, "drone_id": path.get("drone_id") if isinstance(path, dict) else None,
              "hazard_revision": value.get("revision") if isinstance(value, dict) else None,
              "state": "review_required", "hazard_ids": [], "intersections": [], "reason": "Invalid path or registry"}
    try:
        p = normalize_path(path)
        if not isinstance(value, dict) or value.get("schema_version") != CONTRACT or value.get("coordinate_frame") != FRAME:
            raise ValueError("Invalid hazard snapshot/frame")
        integer(value.get("revision"), "hazard revision")
        if not isinstance(value.get("hazards"), dict):
            raise ValueError("Invalid hazard dictionary")
        if p["hazard_revision"] != value["revision"]:
            result["reason"] = "Stale hazard revision; reassess before execution"
            return result
        result["path_signature"] = path_signature(p)
        for identifier, hazard in value["hazards"].items():
            text(identifier, "hazard_id")
            if hazard.get("coordinate_frame") != FRAME or hazard.get("state") not in ("active", "review_required", "cleared"):
                raise ValueError("Invalid hazard geometry/state")
            rect = rectangle(hazard.get("rectangle"))
            if hazard["state"] == "cleared":
                continue
            for leg in ("outbound", "return"):
                if intersects(*p[leg], rect):
                    result["intersections"].append({"hazard_id": identifier, "leg": leg, "hazard_state": hazard["state"]})
        result["hazard_ids"] = sorted({x["hazard_id"] for x in result["intersections"]})
        result["state"] = "blocked" if result["intersections"] else "clear"
        result["reason"] = ("Reported exclusion intersects " + ", ".join(sorted({x["leg"] for x in result["intersections"]})) if result["intersections"] else "Both proposed segments clear of currently reported 2D exclusions")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result["state"], result["reason"] = "review_required", str(exc)
    return result


def assess_fleet(paths, registry):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 50:
        raise ValueError("Assess 1..50 explicit drone path snapshots")
    ids = [p.get("drone_id") if isinstance(p, dict) else None for p in paths]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) for i in ids):
        raise ValueError("Every assessed drone requires a unique ID")
    snapshot = registry.snapshot() if isinstance(registry, HazardRegistry) else deepcopy(registry)
    started = time.perf_counter()
    assessments = [assess_path(p, snapshot) for p in paths]
    return {"schema_version": CONTRACT, "hazard_revision": snapshot.get("revision"),
            "assessed_count": len(assessments), "affected_count": sum(x["state"] != "clear" for x in assessments),
            "assessments": assessments, "duration_seconds": time.perf_counter() - started,
            "acknowledgement_mode": "simulator state assessment; no real radio acknowledgement"}
