# STRATUS verified demonstration and limits

This records the Part 9 release walkthrough and its frozen inputs. Later UI
clarity changes and final hardware checks are recorded separately under
`docs/evidence/inspection-0.0.3/`. The historical hashes below identify the
original checkpoint; they do not identify every later presentation change.
Use [the demo guide](FLEET_DEMO.md) to reproduce the current judging workflow.

Source identity: `sha256:a2188440b1fe8068410054e5b78f82462a8f8f30f3d6197f38251f6a4141468f`. The complete path/hash list, exact mission and
checkpoint IDs, model/configuration, Python and package versions are in
`docs/evidence/inspection-0.0.2/part9/FINAL_FREEZE.json`.
Freeze recorded at `2026-11-14T22:34:30.345444+00:00`.

## Verified operator workflow

The actual browser on port 8774 completed a fresh recorded mission: select
P05 overview, inspect costs, explicitly capture, keep the unclear finding
unknown, request a distinct follow-up, explicitly capture it and resolve only
that follow-up task. Battery changed from 100 to 80.857864 to 75.857864 EU;
one capture remained. Feedback, sensor refresh and a 50-EU reserve / 20-EU
capture what-if spent no aircraft resources. Actual local Wolfram validated
the recalculated costs and the infeasible what-if, separately from local Python
and cache labels.

The portable report matched 75.86 EU / one action, the two P05 views and their
different review states. All four embedded images loaded. Downloaded HTML was
byte-identical to the saved report. Save/reopen preserved budgets, position,
review history and original ground references. The earlier user mission was
restored to ui11-browser-final.json (65.86 EU / zero actions).

Both the two- and 50-drone hazard flows were exercised through the browser:
prepare a real assignment, publish the crane report, reject the prepared stale
action without debit, reallocate current eligible work, and save/reopen the
active hazard state exactly. The two-drone valid attempt advanced one globally
ordered event. The 50-drone update assessed every record and affected 20 paths;
24 exclusive eligible assignments were prepared after the update. The recovered
50-drone run completed 83 captures, 66 usable assets and 134 unresolved assets,
matching the fixed seeded trace. This restriction reduces eligible work; no
coverage improvement or real collision-prevention outcome is claimed. The
previous 150-capture user fleet was restored with every displayed drone row
and its original hazard revision intact.

## Hardware and fallback freeze

The supplied kit consists of SparkFun BME280 15440 (one), Qwiic 17259 100mm
cables (two), Adafruit MCP2221A bridge 4471 (one), PMSA003I 4632 (one), and
Adafruit USB cable 6324 (one purchased). The actually working USB cable was a
replacement whose product identity was not recorded. Approved hookup:
USB -> MCP2221A -> Qwiic -> BME280 -> Qwiic -> PMSA003I. Unplug USB before
rewiring. Actual working addresses are 0x77 and 0x12. No extra computer or
microcontroller is required. Current installed dependencies are retained in
FINAL_FREEZE.json, alongside the earlier context/hardware-packages.txt record.

A new actual six-channel export is saved as final-live-export.json. Each value,
unit and raw CSV hash passed parity checks. The two sensors were fresh in the
browser. Ground location, calibration, uncertainty and physical serials remain
unknown. PM zeros are retained as observed, unreviewed values.

The browser also showed Recorded, Synthetic example and Unavailable modes.
Original recorded times remained unchanged; unavailable values stayed dashes.
Mission battery and captures were unchanged across all three modes. One shared
Ground conditions panel explains the units, source, age and limits. Technical
bus/driver information stays expandable. An offline/hosted view uses exported
Recorded data; it does not access the laptop's USB.

## Frozen launch and demo modes

From the existing standalone STRATUS folder in normal PowerShell:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part12.py --port 8774
```

Open http://127.0.0.1:8774/fleet for a newly paused two-drone fleet. The same
server provides the single-drone desk at `/` and shared hazard desk at `/hazards`.
For the single-drone story, choose Fresh mission and Load mission. Use explicit
Run/Step controls; opening a page never authorizes a capture.

For a device/API-independent local calculation backup, append `--local` to the
launcher. It uses saved Recorded ground data without polling hardware. Live
sensors and AI proposals are optional. Keep the existing running app or stop
its own terminal with Ctrl+C before reusing the port; do not start competing
servers or duplicate a mission store.

Cloud Credits: **175,000 available**. Service Credits: **500 available**.
Alpha API calls: **6,200 available**, based on the original allowance and the
user's confirmation that all resources remain available. The supplied screenshot
shows Cloud and Service balances. STRATUS's recorded Cloud/Alpha requests are
0/0; local kernel calls remain separate. No transaction ledger was read, so no
complete historical usage/charge claim is inferred. Optional Alpha explanations
are explicitly skipped in this version.

## Acceptance map

| Item | Evidence |
| --- | --- |
| H018 | Exact kit/hookup/addresses above, installed versions, final-live-export.json and final-live-parity.json |
| H019 | Actual browser units/source/time labels and all fallback modes; one ground panel with expandable details |
| S097 | Fresh mission through feedback, replan, actual what-if, report/download and exact reopen |
| S098 | Map/viewer/report review states and resources agree; frozen ground source/units/times retained |
| S099 | Synthetic aircraft/images, annotated replay, optional AI, actual/cached/local costs and independent ground sources labeled |
| S100 | Local Python/no-key workflow and Recorded/Synthetic/Unavailable sources keep the mission usable |
| S101 | Tentative review findings and explicit no-diagnosis/flight/safety limits remain visible |
| S102 | Next action, reason, selected/alternative costs, reserve, budget preview and unresolved work visible |
| S103 | Scope frozen; Alpha, new sites/sensors, maps, advanced routing and real flight deferred |
| W017 | wolfram-resource-review.json records user-confirmed balances separately from local request counters |
| W018 | Optional Alpha explanations skipped |
| W019 | Current actual Wolfram costs/what-if plus retained typed/boundary/unit/cache/failure evidence |
| S104 | FINAL_FREEZE.json identifies 51 application/config files and immutable evidence inputs; no new per-part ZIP |
| S105 | All required observations saved; original mission/fleet restored; Part 10 handoff ready |

All 276 Python tests and frontend checks passed in Part 12; all source hashes
still match that tested version. They were not needlessly repeated during
this no-code-change freeze. The browser walkthrough records 20 checks. Existing
failure, numerical disagreement, USB recovery and geometry/lifecycle tests are
retained. The PowerShell startup telemetry issue is resolved for test shells.

Desktop UI is verified. Narrow-screen layout remains unverified. The model is
an authored 2D grid with logical waypoints, toy energy and replay images, not
real flight physics, 3D separation, a thermal/electrical diagnosis or calibrated
air-quality certification. In-progress hazard holds need human review and do
not have an automatic resume command. Preserve Part 12's baseline ties and
regressions when presenting performance.
