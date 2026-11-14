# Fleet and reported-hazard v1 handoff

Part 12 owns the fleet state, allocator, guarded capture path, shared dashboard
integration, persistence, reports and fixed numeric adapter. Part 13 owns its
independent hazard module and reported-area UI. Both are authored in this
standalone project.

stratus/contracts/fleet_v1.py defines plain JSON path and registry records.
The frame is solar-site-local-v1 in metres; no real-world ground location is
inferred. Paths carry scenario/drone/task/view IDs, model version, fleet/drone/
task/hazard revisions, origin/current/target/return coordinates and outbound/
protected-return segments. Return events also recheck their hazard revision.

A pure assessor accepts copies of (path, registry) and returns checked_revision,
state (clear, blocked, review_required), hazard IDs and reason. It cannot mutate
fleet state. Admission and atomic commit both check the current assessment,
alongside exclusive ownership and independent numerical/budget checks.

The standalone empty_assessment shim authorizes only a matching empty version-zero
registry. The joined engine now uses Part 13's assess_fleet_path adapter and
versioned, replay-validated registry history. Malformed/forged history is rejected;
updates invalidate outstanding proposals while retaining completed costs and
evidence. See docs/part13 for that workstream's own acceptance evidence.

The separate numeric envelope is stratus-fleet-costs-v1. It has contract, model,
scenario, fleet/hazard revisions and 1-500 typed pair rows. Geometry is checked by
the pure gate; undeclared fields are never added to the older single-drone cost
schema. A bounded local kernel batch serves a round. Python checks every returned
ID, revision, finite cost, reserve margin and sign after unit normalization.
Missing/malformed/disagreeing rows block execution. Availability failures have
an explicitly labeled local fallback without unbounded retries.
