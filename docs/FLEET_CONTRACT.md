# Fleet and reported-hazard contracts

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
evidence. Integration evidence is retained under
`docs/evidence/inspection-0.0.2/part13/joined/`.

The separate numeric envelope is stratus-fleet-costs-v1. It has contract, model,
scenario, fleet/hazard revisions and 1-500 typed pair rows. Geometry is checked by
the pure gate; undeclared fields are never added to the older single-drone cost
schema. A bounded local kernel batch serves a round. Python checks every returned
ID, revision, finite cost, reserve margin and sign after unit normalization.
Missing/malformed/disagreeing rows block execution. Availability failures have
an explicitly labeled local fallback without unbounded retries.

## Shared fleet integration

The shared formats remain stratus/contracts/fleet_v1.py. The pure adapter in
stratus/hazards/fleet_adapter.py consumes those records without importing the
executor. Its identity mapping between solar-site-local-v1 and the internal
site_local_cartesian frame is limited to this newly authored synthetic metre
grid. It does not translate geographic coordinates or the ground-node location.
Unknown frames and malformed/replayed registries fail closed.

### Joined entry points

* FleetSession defaults to assess_fleet_path for shortlist, return and commit.
* LiveFleetHazards references FleetService.core dynamically after New/Open.
* publish_registry holds the fleet lock, verifies a monotonic history extension
  at the current logical time, assesses every path, invalidates stale proposals,
  retains resources and records all checked revisions and impact duration.
* In-progress affected aircraft receive hazard_review_required and remain held.
  No automatic detour, stop coordinate or recovery-resume command is supplied.
* review_due_reports retains expired restrictions and publishes review-required
  revisions at the next logical boundary before further queued work.
* Assignments carry fleet/drone/task/hazard revisions and a route_signature.
  The one existing FleetCalculator binds full normalized position/target/launch,
  state/model inputs, hazard revision and fixed script checksum into its cache.
  A Part 13 adapter never appends unvalidated fields to Wolfram's typed payload.
* FleetSession save/load validates the registry's replayed history, budgets and
  assignments; FleetService's existing save/report/open commands are reused.
* dashboard.py mounts /hazards, static component assets and /api/hazards actions.
  Mutations use existing origin/body guards plus current run_id/state_revision.
  Stale writes refresh the view without automatically retrying a mutation.
* The map on /fleet displays reported buffered rectangles. /hazards is a view
  over the same authoritative fleet, not an independently reset fixture store.

The older HazardBridge + FixtureFleetHost contract remains an isolated test
interface, labeled fixture_host_not_part12_fleet_integration. Its evidence stays
separate from the real-engine results under part13/joined. No unfinished or
unverified fixture output is substituted for a live integration claim.

### Integration evidence

Joined engine, service and browser observations are retained under
`docs/evidence/inspection-0.0.2/part13/joined/`; standalone fixture-harness
results are identified separately. `scripts/verify_joined_hazards.py` exercises
two bounded fleet sizes through the actual engine. The scaling matrix and
release walkthrough remain separate evidence sets.
