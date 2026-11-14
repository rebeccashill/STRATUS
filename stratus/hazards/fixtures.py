"""Newly authored crane scenario; no Amazon flight-path reconstruction."""

from copy import deepcopy
from .core import CONTRACT, FRAME

STAMP = "2026-11-14T20:00:00+00:00"


def crane_event(revision=0, *, action="report", effective=1, hazard_id="crane-001", rect=None,
                source="synthetic_event", notes="Authored crane report after the initial simulated inspection"):
    event = {"schema_version": CONTRACT, "event_id": f"{hazard_id}-{revision + 1}-{action}",
             "hazard_id": hazard_id, "expected_revision": revision, "revision": revision + 1,
             "action": action, "source": source, "observed_at_utc": STAMP, "reported_at_utc": STAMP,
             "effective_sim_time": effective, "notes": notes}
    if action in ("report", "amend"):
        event.update(coordinate_frame=deepcopy(FRAME), rectangle=rect or {
            "x_min": 20, "y_min": -5, "x_max": 30, "y_max": 5, "buffer_m": 1},
            review_after_sim_time=effective + 30)
    return event


def path(drone_id="D001", task_id="T001", *, index=0, hazard_revision=0, fleet_revision=0,
         drone_revision=0, task_revision=0, position=None, target=None, home=None):
    y = index * 5 if index < 2 else 30 + index * 3
    start = position or {"x": 0, "y": y}
    dest = target or {"x": 50 if index < 2 else 15, "y": y}
    end = home or deepcopy(start)
    return {"schema_version": CONTRACT, "coordinate_frame": deepcopy(FRAME),
            "drone_id": drone_id, "task_id": task_id, "view_id": "overview",
            "model_version": "toy-euclidean-energy-v1", "fleet_revision": fleet_revision,
            "drone_revision": drone_revision, "task_revision": task_revision, "hazard_revision": hazard_revision,
            "position": deepcopy(start), "target": deepcopy(dest), "return_point": deepcopy(end),
            "outbound": [deepcopy(start), deepcopy(dest)], "return": [deepcopy(dest), deepcopy(end)]}


def fleet_paths(size=2, revision=0):
    if type(size) is not int or not 2 <= size <= 50:
        raise ValueError("Fixture fleet size must be 2..50")
    return [path(f"D{i + 1:03d}", f"T{i + 1:03d}", index=i, hazard_revision=revision) for i in range(size)]


def return_only(revision=0):
    return path("D001", "RETURN-BLOCKED", hazard_revision=revision,
                position={"x": 40, "y": 20}, target={"x": 40, "y": 0}, home={"x": 0, "y": 0})

