# STRATUS 0.0.1: operator brief and frozen minimum

Source: [Notion Friday checklist, Part 1 (S001-S009)](https://app.notion.com/p/4185b396b48e81c3b6e9c07502d50958).
This implements a standalone solar-inspection foundation created in this
session. The mission values below are authored prototype
assumptions, not observations of a real solar site or aircraft.

## Operator and decision

A solar-site maintenance operator has incomplete image coverage of one small
array and limited remaining battery. Choose the next useful panel inspection
or follow-up view while protecting return energy and a three-action cap.
If no permitted capture fits, return or stop. Apparent concerns will be
tentative human-review flags, never validated defect diagnoses.

## Frozen solo minimum

- One self-authored six-panel array, `solar-array-001`.
- Two historical input records: P01/overview (authored clear label) and
  P02/overview (authored unclear label). Their images and provenance manifest
  remain pending Part 2; neither label is a live assessment.
- At most three additional simulated capture actions, including follow-ups.
- Later deliverables: bounded next-inspection selection, one budget what-if,
  evidence review and feedback, a report, and saved-run reopen.
- Real flight, extra sites, and proprietary property-data layers/APIs are
  outside this release. Ground sensors are optional local context.

Part 1 delivers the brief, mission skeleton, and runnable preview only. Evidence
loading/capture, AI tools, numerical execution checks, the report, and actual
run save/reopen remain later work. Keep the scheduled 10:30pm boundary for
service-specific computation setup.

## Layout and eligibility review

Coordinates are site-local metres: x east, y north; launch and return are
(0, 0). There is no geographic/flight reference. The initial simulated position
is also (0, 0). Priority 3 is high, 2 medium, and 1 low.

| Panel ID | x (m) | y (m) | Operator priority | Reviewed state | Coverage at handoff |
| --- | ---: | ---: | ---: | --- | --- |
| P01 | 10 | 10 | 1 | Eligible | Prior clear annotation; image pending |
| P02 | 20 | 10 | 3 | Eligible | Prior unclear annotation; follow-up needed |
| P03 | 30 | 10 | 3 | Eligible | Uninspected |
| P04 | 10 | 20 | 2 | Eligible | Uninspected |
| P05 | 20 | 20 | 2 | Eligible | Uninspected |
| P06 | 30 | 20 | 1 | Excluded panel/point | Uninspected; operator exclusion |

Each panel's eligibility has been reviewed against this synthetic scenario.
P06 demonstrates an operator exclusion; no real-world permission review is
claimed. Each panel has planned `overview` and `follow-up` view IDs. A distinct
follow-up is paid separately; repeating a completed asset/view is prohibited.

## Action and energy contract

| Parameter | Frozen assumption |
| --- | --- |
| Battery available at handoff | 100 simulated energy units (EU) |
| Toy battery capacity | 100 EU |
| Required return reserve | 15 EU, still present after return |
| Travel | Euclidean distance in metres multiplied by 0.5 EU/m |
| Capture/dwell | 5 EU per executed new inspection or follow-up |
| New action budget | 3; each inspection or follow-up consumes 1 |
| Historical input records | Consume 0 new actions; do not debit current battery |
| Listing, proposing, reviewing, rejecting | Consume 0 actions and 0 EU |
| Return/stop | Consume 0 capture actions; executed return still costs travel energy |
| Model version | `toy-euclidean-energy-v1` |

For a candidate, protect `outbound + capture + return-to-launch + reserve`.
The energy margin must be nonnegative, an action must remain, and the
asset/view must be eligible. An eventual accepted capture debits outbound plus
capture once and moves the simulated position to the panel. Return energy is
protected at this step and debited once only when return actually executes.
The reserve is a floor, not a second travel debit.

Example contract, not an executed inspection: from launch to P02,
outbound = sqrt(20^2 + 10^2) * 0.5 = 11.18034 EU, return = 11.18034 EU,
capture = 5 EU, reserve = 15 EU. Initial protected margin = 57.63932 EU.
After capture, modeled battery would be 83.81966 EU and actions remaining 2.
The calculator and state transitions are Part 3/4 work.

These costs are invented and uncalibrated. They omit obstacle routing,
weather, altitude, takeoff, and landing; capture includes a toy dwell allowance.
They do not establish flight feasibility or aircraft endurance.

## Project and data boundaries

| Path (relative to STRATUS) | Role |
| --- | --- |
| `stratus/inspection/__main__.py` | Standard-library-only, read-only startup preview |
| `stratus/inspection/missions/solar-array-001.json` | Frozen mission input skeleton |
| `evidence/inspection/` | Future panel images, manifest, and separate annotations |
| `context/` | Optional local ground context, separate from aircraft state |
| `saved-runs/` | Future mutable runs, logs, reports, and reopen inputs |
| `docs/evidence/inspection-0.0.1/part1/` | Startup and setup verification |
| `.env.example` | Placeholder environment variables for later AI setup |
| `.venv/` | Local Python environment; ignored by git |

Use Python 3.10-3.12, matching `pyproject.toml`. The preview needs only Python's
standard library. No earlier project packages or web dependencies are required.
From the STRATUS folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -B -m stratus.inspection
```

The launch command prints mission identity, panel states, two prior records,
three remaining actions, modeled battery/reserve, and the pending-evidence
label. It performs no capture, service request, or state mutation. An optional
`--mission path/to/file.json` reads another skeleton; comprehensive validation
is deliberately pending Part 2.

Actual keys belong only in environment variables or an ignored local `.env`.
Part 1 does not read `.env` automatically. Never put keys in mission JSON,
saved reports, screenshots, logs, or committed files. This project's
`.env`/`.env.*` and `.venv/` ignore rules cover this folder; `.env.example`
is explicitly allowed and contains placeholders only.

Next: prepare traceable evidence and the mission loader in Part 2.
