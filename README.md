# STRATUS

Drone fleet inspection planning with reported-hazard updates and real ground sensing.

STRATUS helps a solar-site operator choose inspections and follow-up views while
respecting each simulated drone's battery, return reserve and capture allowance.
A newly reported obstruction changes the fleet's shared plan and invalidates
stale actions before they can execute. Built as fresh standalone work for
HackPrinceton.

## What it demonstrates

- One single-drone inspection workflow and a fleet of 2–50 independent drones.
- Exclusive inspection assignments, feedback, per-drone resource checks and recovery.
- Operator-reported or synthetic 2D exclusions checked against outbound and return segments.
- Atomic stale-plan rejection, eligible reassignment and explicit in-progress review holds.
- Actual local Wolfram calculations independently validated by Python, with labeled local fallback.
- Optional OpenAI proposals and explanations; Python controls validation and execution.
- A separate BME280/PMSA003I ground panel with Live, Recorded, Synthetic and Unavailable modes.
- Save/reopen and portable HTML/JSON reports retaining evidence and original ground times.

Aircraft movement, battery and capture are simulated. Images are self-authored
illustrations with annotated replay. The physical ground station does not detect
cranes, measure fleet-wide weather, diagnose panel faults or establish flight safety.

## Run locally

Python 3.10–3.12 is supported. The recorded/local demo needs no API key or hardware.
From PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -B scripts\finish_part12.py --port 8774 --local
```

Keep the terminal open, then visit:

- http://127.0.0.1:8774/fleet — start with two paused drones; explicitly Run or Step.
- http://127.0.0.1:8774/ — choose Fresh mission and Load mission for the inspection story.
- http://127.0.0.1:8774/hazards — prepare an assignment, report the example crane,
  try the stale action, and replan eligible work while fleet playback is paused.

All three pages use the same local server. The fleet and hazard desks share the
same fleet state. New simulation requires explicit confirmation when progress exists.

For actual local Wolfram plus Python validation, install/activate Wolfram on the
same computer and omit `--local`. Runtime failures remain labeled. Cloud and Alpha
are not required. OpenAI is optional; configure the variables documented in
[.env.example](.env.example) through your environment and keep keys out of Git.
The launcher above uses local planning by default.

For physical sensing, follow the exact kit, optional dependency versions and
unplug-before-rewiring guidance in [HARDWARE_HANDOFF.md](docs/HARDWARE_HANDOFF.md).
One laptop ground node is separate from simulated aircraft. Recorded mode works
without the USB kit. Do not expose this development HTTP server to the public internet.

For a short judging walkthrough, use [the demo guide](docs/FLEET_DEMO.md).
It covers the fleet, shared hazard updates, recorded ground readings and reports.

## Verified results

The frozen product source passed 276 Python tests plus the frontend checks.
The final browser walkthrough verified inspection, feedback, numerical what-if,
portable report download and recovery, including two/50-drone stale-plan rejection.

- Nominal 50-drone seed-11 run: 150 captures, all 50 participating, 129 usable assets.
- Reported-hazard seed-11 run: 50 assessed, 20 affected at the report, 83 captures,
  66 usable assets and 134 unresolved assets after eligible work completed.
- Matched active-hazard save/reopen retained exact state and resumed outcomes.

These are authored simulation results, not field performance or proven collision
prevention. The bounded coordinator is not globally optimal; baseline ties and
regressions are retained in [the comparison evidence](docs/FLEET_GUIDE.md).

## Verification and project structure

```powershell
.\.venv\Scripts\python.exe -B scripts\offline_checks.py
node --test tests/frontend_hazards.test.cjs tests/frontend_fleet.test.cjs tests/frontend_fleet_map.test.cjs tests/frontend_clarity.test.cjs tests/frontend_races.test.cjs
```

Tests inject service failures and numerical providers unless actual runtime proof
is explicitly labeled. HTTP tests prefer an actual localhost socket. If the host
denies the connection, they exercise the unchanged app handlers with serialized
HTTP requests and parsed responses in process. The Python report records which
transport ran; in-process checks do not establish OS socket connectivity.

- `stratus/inspection/`: operator workflow, fleet engine, dashboard, numerical adapter.
- `stratus/hazards/`: registry, geometry, lifecycle and real fleet integration.
- `stratus/contracts/`: versioned shared fleet formats.
- `context/` and `evidence/`: authored scenarios and recorded sensing/image provenance.
- `tests/`: Python and frontend regression checks.
- `docs/evidence/`: retained measurements and verification outputs.
- `saved-runs/`: starter checkpoints; new runs and streamed samples remain local.

Read [the verified demonstration and limits](docs/FINAL_FREEZE.md),
[operator guide](docs/OPERATOR_GUIDE.md), [fleet guide](docs/FLEET_GUIDE.md),
[planner comparisons](docs/COMPARISON_GUIDE.md),
[Wolfram setup](docs/WOLFRAM_HANDOFF.md) and
[fleet/hazard contracts](docs/FLEET_CONTRACT.md).
The [documentation index](docs/CHECKPOINT.md) maps these guides to retained evidence.

The motivating crane scenario is incident-inspired; the authored grid is not a
reconstruction of Amazon's flight paths. The source is the
[NTSB preliminary report WPR26LA001](https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/201774/pdf).
