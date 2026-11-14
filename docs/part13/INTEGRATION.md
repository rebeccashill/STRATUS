# Part 13 live fleet integration

The shared formats remain stratus/contracts/fleet_v1.py. The pure adapter in
stratus/hazards/fleet_adapter.py consumes those records without importing the
executor. Its identity mapping between solar-site-local-v1 and the internal
site_local_cartesian frame is limited to this newly authored synthetic metre
grid. It does not translate geographic coordinates or the ground-node location.
Unknown frames and malformed/replayed registries fail closed.

## Joined entry points

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

## Scope and evidence

Read PART13_HANDOFF.md for counts, seeded comparisons, browser observations,
actual numerical batches and release limits. Scripts/verify_joined_hazards.py
runs only two bounded sizes through the actual engine. It does not replace the
Part 12 scaling matrix or Part 9's release walkthrough. One integration owner
made the shared engine/dashboard/service/report edits; the single-drone engine
and its mission data remain independent.
