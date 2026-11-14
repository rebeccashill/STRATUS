# STRATUS Fleet Intelligence

Part 12 is complete: 32/32 checklist actions, with independent 2-50-drone
simulation, exclusive tasks, guarded costs, recovery, save/reopen and reports.

## Open or start

The verified app is running at http://127.0.0.1:8774/fleet. Keep its normal
PowerShell window open. To start it again from STRATUS:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part12.py --port 8774
```

Startup attempts bounded data-only local Wolfram batches for two and 50 drones
and reserve boundaries. It never executes a capture or polls hardware implicitly.
Recorded context is the safe startup default. Select Live explicitly and use
"Use current station snapshot" to attach it. Use one live USB reader at a time;
the older port-8769 desk was switched to Recorded during verification.

Each aircraft starts with 100 simulated energy units, a 15 EU protected reserve
and three captures. Positions are last completed logical waypoints. One ground
node retains original UTC times, actual/unknown location, units and quality.
Neither the station nor reused illustrations establish airborne conditions,
flight clearance, calibrated accuracy or panel diagnoses.

## What was verified

- All 276 Python tests and all three frontend regression files passed.
- All 15 coordinator cases and six same-size round-robin cases are saved.
- Every nominal 50-drone run completed 150 new captures, with all 50 participating
  and zero invariant violations.
- Actual Wolfram 15.0.1 checked 18 candidate pairs for two drones and 456 for 50;
  the boundary batch and exact normalized-input/unit cache also passed. The proof
  uses three local kernel calls, zero Cloud/Alpha calls. Account credit usage is
  unknown and is not inferred from request counters.
- The browser preview spent no resources. A fresh page reopened 50 rows at
  78 captures, 4464.60 EU and 12.41289163 logical seconds with exact row equality;
  resumed accounting/evidence matched the completed run.
- The browser finished 150 captures and 129 unique usable assets, leaving 71
  unresolved. All 50 independent records and D050 selection were inspected.
- A labeled replay fork made D002 unavailable at 84.97 EU with one capture left.
  No expense was refunded. The other 49 finished; total captures were 149.
- The two-drone recovery run retained D001's spent energy and let D002 finish
  three captures. Operator priority and distinct follow-up requests were exercised.
- The final report embedded its images, included all 50 records, and its download
  matched the saved HTML byte-for-byte. Actual BME280/PMSA003I live context was
  attached without changing aircraft costs or captures.
- One actual AI explanation mixed up used and remaining battery. The UI now sets
  numeric AI restatements aside and shows verified totals. AI never executes.
- The desktop browser passed with no uncaught errors after the final reload.
  A requested narrow viewport did not take effect; narrow-browser verification
  is not claimed.

See FLEET_DEMO.md for the short operator script and recorded outcomes.

## Allocation and recovery

Each round selects six nearby and four high-priority eligible views per drone,
at most ten distinct pairs per drone and 500 total. The greedy order is fewest
captures, descending priority/evidence need, travel plus capture cost, then stable
drone/task IDs. Waves wait for assigned travel/captures; returns may finish
independently. This is a bounded heuristic, not a global optimum.

One task has one owner. Python atomically rechecks IDs, revisions, ownership,
numeric agreement, cap, battery, protected return and the reported-hazard gate.
Duplicate receipts do not charge twice. Priority changes or injected unavailability
invalidate unfinished proposals while preserving completed costs and evidence.
An unclear overview remains unknown when a distinct follow-up is added.

Run explicitly starts playback; Pause retains progress; Step advances one event.
Speed changes waiting time, not the seeded outcome. New simulation confirms
replacement of active unsaved progress and preserves saved runs. Save selects the
checkpoint just written; Open pauses it and restores mode, events and resources.

## Measured local software scaling

Three seeds (11, 23, 47) share the same authored 200-asset field, costs, horizon,
per-drone limits and frozen Recorded station snapshot. Timings include guards
and were measured while other validation work was running. They are host
observations, not flight performance or live-service latency.

| Drones | Captures per run | Unique usable assets | Total wall seconds | Peak process memory, maximum MiB |
| --- | --- | --- | --- | --- |
| 2 | 6 | 5-6 | 0.12-0.14 | 25.3 |
| 5 | 15 | 11-13 | 0.28-0.44 | 25.7 |
| 10 | 30 | 22-26 | 0.81-1.01 | 26.6 |
| 25 | 75 | 62-64 | 3.69-5.44 | 30.8 |
| 50 | 150 | 125-136 | 10.59-14.36 | 39.6 |

More drones add battery and capture allowance. The same-size baseline results
retain ties and regressions: at 50 drones/seed 11 the coordinator covered 129
assets and round-robin covered 130. Seeds 23/47 tied coverage at 125/136.
The coordinator used less modeled energy in the six compared runs and gave
different priority coverage; this does not establish general superiority.

## Evidence, checks and limits

The scenario is context/fleet/solar-200-v1.json. Its generator, rules, seeds,
ground snapshot and freeze receipt are under docs/evidence/inspection-0.0.2/part12.
Rules were authored before smoke tests; the unchanged full-matrix receipt was
written after those smoke tests. It is not a pre-smoke registration claim.

verification.json reconciles the 21 complete run/checkpoint records, raw timing
and Windows process-peak-memory samples, nine injected failures, actual Wolfram
proof, browser evidence, live ground context and deterministic paused resume.
matrix.csv and matrix-summary.json retain raw results and all baseline differences.
browser-walkthrough.json records actual UI observations and corrected issues.
The earlier partial-* files are historical checkpoints, superseded by verification.json.

```powershell
. .\scripts\use_private_test_shell.ps1
.\.venv\Scripts\python.exe -B scripts\verify_part12.py
```

The helper suppresses only the testing PowerShell process's optional Application
Insights startup sender. The queued event was ConsoleHostStartup; only its field
names were inspected. It changes no persistent system setting or security logging.
See telemetry-resolution.json. Full test runs use scripts/offline_checks.py and
deny external Python connections; actual provider checks are separate.

Representative P04/P05 illustrations are reused across 200 unique coordinates;
they are not 200 independent photographs. Authored replay awaits human review.
No real autopilot, radio acknowledgement, 3D flight, validated collision separation
or multi-site weather inference is modeled. Part 13 supplies the joined reported
hazard gate; its own acceptance is recorded separately. Part 9 final integration
and code freeze, and Part 10 packaging, remain separate.
