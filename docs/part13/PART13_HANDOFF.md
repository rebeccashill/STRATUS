# STRATUS Part 13: reported fleet hazards

Part 13 is integrated with the actual Part 12 fleet engine. The independent
fixture module remains available for isolated development; the joined results
below use FleetSession and FleetService, not that fixture host.

## Implemented behavior

The existing fleet store owns one versioned reported-area registry, all aircraft
resources, task reservations, event order, receipts and ground provenance.
LiveFleetHazards projects that store into /hazards; /fleet uses the same run.
There is no second live mission store. Both pages link to each other.

A report validates before publication, assesses every drone's complete outbound
and protected-return segments, then invalidates old authorizations under the
fleet lock. Assignment revisions and a path digest are checked alongside current
ownership, numerical permission, capture cap and return reserve at commit.
Reporting and stale rejection do not spend simulated energy or captures.
Eligible work is reallocated through the existing coordinator and cost adapter.

An affected segment already in progress is held at its last completed logical
waypoint for operator review. Completed movement and costs are retained. There
is no inferred stop point or automatic detour/return through the reported area.
Report expiry becomes review-required at the next logical event boundary and
retains the restriction. Explicit operator clearance adds a new revision.
In-progress review holds remain held even after clearance; this version does
not provide an operational recovery/resume command for those aircraft.

Save/open and HTML/JSON reports retain the registry, sources, timestamps, impact,
assignments, original ground reference and exact per-drone budgets. Legacy
no-hazard saves acquire an explicit empty registry without refilling resources.

## Verification

The combined checkpoint is docs/evidence/inspection-0.0.2/part13/joined.

* 18 real-engine/service integration checks passed.
* 47 independent geometry, lifecycle, contract and controller checks passed.
* 15 selected existing no-hazard fleet, cost-adapter and single-drone checks passed.
* 13 Node test entries passed across the four frontend files; final hazard JS
  syntax check passed after minor wording and decimal-input improvements.
* Four actual local Wolfram fleet batches passed independent Python validation:
  2 and 50 drones before/after a report, with changed cache keys and the current
  hazard revision. Identical post-report input reused the checked cache. These
  are read-only numerical checks; matched end-to-end traces use labeled local
  Python costs. Cloud/Alpha requests: 0/0; account credit usage remains unknown.

Matched seed-11 runs use identical initial aircraft/tasks and one frozen ground
snapshot. Each starts with 100 EU and at most three captures per aircraft.

| Fleet | Report | Affected at report | Captures | Usable assets | Unresolved assets | Modeled energy EU |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | No | 0 | 6 | 5 | 195 | 47.000 |
| 2 | Yes | 2 | 6 | 5 | 195 | 43.877 |
| 50 | No | 0 | 150 | 129 | 71 | 1367.020 |
| 50 | Yes | 20 | 83 | 66 | 134 | 711.673 |

The report invalidated all old allocation-wave proposals, including unaffected
ones whose fleet revision changed. Both sizes rejected all old prepared
assignments without debit. All new selections passed both segment checks.
The first replanned wave changed two task assignments at size 2 and six at size
50; unchanged eligible task IDs are still revalidated. Unaffected drones did
continue working. The restricted 50-drone workload leaves more unresolved work;
no improvement in coverage or proven collision prevention is inferred.

Active-hazard save/reopen matched the complete paused payload at both sizes,
and resumed outcomes matched uninterrupted runs. Duplicate capture receipts
remained suppressed. A separate in-progress trace demonstrates a persistent
review hold without movement/refund. All allocation and impact durations are
stored with the outputs; the initial 50-record impact took about 0.056 seconds
in this run, not a hardware-independent performance guarantee.

## Browser evidence and remaining release limits

The running http://127.0.0.1:8774/hazards page displayed actual two- and 50-drone
states, all 50 rows, source/revision labels, impact counts and the shared fleet
link. Saving the live 50-drone run succeeded. A stale UI command was rejected
without replacing concurrent progress. browser-live-50.jpg records a later
operator report with 15 affected records and 150 prior captures; it is a different
report placement from the fixed seeded comparison above.

The full prepare/report/reject/replan/open browser click-through was not run
while the live fleet was being changed concurrently. Its actual application
controller sequence passed the focused service tests. Keep this distinction
visible during Part 9's final end-to-end walkthrough. No test reset was applied
over the concurrently changing browser run.

Part 12's full scaling/baseline benchmark and full regression suite remain
separate and pending. They were not rerun here after their earlier automatic
approval rejection involving unknown Visual Studio telemetry. The earlier
242-test attempt (232 pass, ten socket-permission errors) is historical evidence,
not a current all-pass claim. This checkpoint is handed to Part 9 with these
limits; Part 13 completion does not complete Part 12 or the release gate.

## Reproduce focused evidence

From the standalone STRATUS folder:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_joined_hazards.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_hazard*.py' -v
node --test tests/frontend_hazards.test.cjs tests/frontend_fleet.test.cjs tests/frontend_clarity.test.cjs tests/frontend_races.test.cjs
.\.venv\Scripts\python.exe -B scripts/verify_joined_hazards.py --wolfram
```

The last command authors new report files and evidence traces. It does not run
the blocked scaling benchmark, full suite, physical sensors, live AI, Cloud or
Alpha. Without --wolfram it executes local traces and leaves live checks unrun.

## Demonstrated claim

An external operator report or authored synthetic event consistently changes
simulated fleet authorization. The BME280/PMSA003I ground station does not detect
a crane. No real flight, radio acknowledgement, validated 3D separation, accident
prevention or Amazon endorsement is established. The motivating incident source
is the NTSB preliminary report WPR26LA001; the authored grid and paths are not a
reconstruction of that flight:
https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/201774/pdf
