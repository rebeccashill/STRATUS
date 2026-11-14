# STRATUS inspection prototype

**Part 9 integration and code freeze is complete (14/14).** The final single-drone and two/50-drone hazard browser workflows, actual local Wolfram what-if, offline modes, hardware parity and recovery are verified. Read [the final freeze record](docs/FINAL_FREEZE.md). Part 10 is documentation, recording and packaging of that exact version.

**Part 12 Fleet Intelligence is complete (32/32).** The 2-50-drone mode
has independent budgets, exclusive tasks, recovery, save/reopen and portable
reports. All 276 Python tests and frontend checks pass; all 15 size/seed cases
and six same-size baselines are saved. Actual two/50-drone Wolfram batches,
desktop browser workflows and one shared live ground node were verified.
The bounded heuristic retains its baseline ties/regression rather than claiming
optimality. See [the fleet guide](docs/FLEET_GUIDE.md) and
[demo script](docs/FLEET_DEMO.md). Open http://127.0.0.1:8774/fleet.
The PowerShell startup diagnostic sender was identified and suppressed for checks.

**Completed: Saturday 0.0.2 Part 11 is complete (12/12).** The next action and
cost tradeoff come first, with a five-step workflow, readable source/freshness
help, explicit review controls and visible report/save outcomes. Actual local
Wolfram 15.0.1 passed numerical boundaries, units, typed costs, cache and the
browser budget preview. All 201 Python tests and 10 frontend checks pass.
See [the operator guide](docs/OPERATOR_GUIDE.md). Part 9 is now frozen; Part 10 packaging remains pending.

**Completed: Saturday 0.0.2 Part 8 (17/17).** All nine frozen
method/case runs are saved with identical starting states and one shared
Recorded sensor snapshot. Adaptive ties nearest feasible in these cases;
both improve unclear-case coverage over fixed order. All methods stop when
battery is insufficient. All 194 Python tests and four frontend regressions
pass. New live Wolfram boundary calls are explicitly unrun; local arithmetic,
unit and injected failure checks pass. See [the comparison guide](docs/COMPARISON_GUIDE.md).

Open the [comparison report](http://127.0.0.1:8769/api/report/view?name=comparison-part8.html)
while STRATUS is running, or open `saved-runs/reports/comparison-part8.html`
offline. Parts 1, 2 and 6 remain complete. USB reconnection, mission budgets,
save/reopen and Aevaryn styling retain their verified behavior.

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part11.py
```

Open **http://127.0.0.1:8769** while the terminal stays open. The current app is
already running there. See [the recovery guide](docs/RECOVERY_GUIDE.md).
Choose **Live sensors on this computer**: unplugging and replugging the kit now
recovers both sensors automatically without restarting STRATUS. Atmospheric
data returns first; the PMSA003I settles for 30 seconds. Failed USB reads are
bounded, unavailable channels stay empty, and mission resources stay intact.
The dashboard uses Aevaryn's black/amber palette and IBM Plex Sans/Mono stacks.
The browser example finished three captures at 65.85786437626905 simulated
battery units and zero actions, then visibly held. A separate automated run
also explicitly returned to launch. No physical aircraft or live vision ran.

## Completed Part 1 and Part 2 handoff

Saturday 0.0.2 Parts 1 and 2 are complete. The inspection dashboard now supports
explicit simulated captures, feedback-driven replanning, saved ground context,
and a portable evidence-linked report. Use the current Part 2 launcher:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part2.py
```

Open **http://127.0.0.1:8768** while that terminal stays open. The launcher uses
the installed Wolfram adapter and bounded live AI for a proposal, with explicit
fallback modes; startup never executes a capture. See [the adaptive guide](docs/ADAPTIVE_GUIDE.md)
for the P05 unclear/follow-up example, review controls, save/reopen and report export.
**Part 2 is complete (13/13):** 162 Python tests, four frontend regressions,
actual live AI context calls, Wolfram-backed planning/preview, and the browser
capture/review/report walkthrough pass. Execute remains a separate reviewed action.
**Part 1 is complete (18/18).** Its dashboard, sensor interface and numerical
checks remain covered; [its guide](docs/DASHBOARD_GUIDE.md) records that handoff.
At the Part 2 handoff the bridge was undetected and the demo used earlier
Recorded measurements. Part 6 later verified fresh readings from both physical
sensors, actual USB loss, recorded fallback and fresh recovery after restarting
the reader. Original acquisition times and raw CSV references are retained.

Parts 1-4: a standalone solar-inspection prototype with validated local inputs, resumable inspection checkpoints,
traceable synthetic evidence, deterministic action checks, and an optional
bounded OpenAI tool adapter with a visible offline fallback. This folder
contains the fresh Part 1 handoff and newly authored additions; no earlier
project code, dataset, or environment was imported.

The [operator brief](docs/INSPECTION_BRIEF_0_0_1.md) freezes one six-panel
synthetic array, two prior records, three new capture actions,
and explicit battery/return-reserve assumptions.

From this folder, use Python 3.10-3.12:

```powershell
python -B -m stratus.inspection
python -B -m stratus.inspection --capture P03 overview
python -B -m stratus.inspection --capture P02 follow-up
python -B -m stratus.inspection --agent fallback
python -B -m stratus.inspection --agent fallback --execute
python -B -m stratus.inspection --candidates
python -B scripts\verify_part3.py
```

The launch uses only Python's standard library. It validates the mission,
12 PNG images, manifest, and separate replay annotations. A capture request
returns fixed synthetic evidence and a response timestamp without changing
battery, position, or actions. The Part 3 engine validates proposals and
explicitly executes paid actions and return exactly once in memory.
All images are procedural illustrations, not photos or live vision results;
human review remains pending. Missing/changed images return unavailable/unknown.
CLI invocations start fresh unless `--load` opens an existing checkpoint.
Exit codes: 0 success, 2 invalid input, 3 rejected/unavailable, 4 AI service
failure with labeled fallback. A failed live request never implicitly executes
the fallback, even if `--execute` was supplied; choose `--agent fallback` to
continue locally.

Live use requires a valid API credential in `OPENAI_API_KEY` or
`STRATUS_AI_API_KEY`, optionally the ignored `.env` described by `.env.example`.
`STRATUS_AI_PROVIDER=openai` and `STRATUS_AI_MODEL=gpt-5-mini` select the adapter.
Startup and fallback need no key and make no network calls. Live proposals
are limited to two requests to the official Responses endpoint; no model tool
can execute code, call arbitrary URLs, or change state directly.

```powershell
python -B -m stratus.inspection --agent live
python -B scripts\verify_part3.py --live
```

Part 3 is complete (11/11). Rebecca's normal PowerShell verification passed
all 54 behavior tests and a real two-request OpenAI tool exchange using
gpt-5-mini. The model loaded context and proposed P02/follow-up; independent
Python checks allowed it without executing an action or changing state.
Earlier HTTP 429 and restricted-session DNS failures are historical. Use
normal PowerShell for live API checks while this agent's command environment
cannot resolve external hosts. Live vision remains pending; mocked provider
tests and synthetic annotations are not live vision evidence.

## Project layout

The working source tree is the main project. Historical ZIP handoffs are kept
under `archives/`, excluded from Git. Continue development directly in this
folder; new work does not need a separate ZIP for each part.

| Location | Contents |
| --- | --- |
| `stratus/` | Python application and the frozen mission under `inspection/missions/`. |
| `tests/` | Automated behavior tests. |
| `scripts/` | Evidence preparation and verification commands. |
| `evidence/inspection/` | Synthetic images, manifest, and separate replay annotations. |
| `context/` | Ground measurements, shared record schema, hardware status and the historical sensor decision. |
| `saved-runs/` | Resumable inspection checkpoints; portable HTML reports and technical JSON in `reports/`. |
| `docs/` | Operator guides, handoffs, and verification records under `evidence/inspection-0.0.1/` and `evidence/inspection-0.0.2/`. |
| `archives/` | Historical Part 2 and Part 3 ZIP handoffs. |

`pyproject.toml` contains package configuration. `.env.example` contains
credential placeholders; actual `.env` files are ignored.

The continuing workspace is `C:\Users\shill\OneDrive\Desktop\STRATUS`.
The 20-file Part 1 handoff has been extracted and verified here.
See [Part 2 handoff](docs/PART2_HANDOFF.md) for scope and verification.
See [Part 3 handoff](docs/PART3_HANDOFF.md) for the verified live exchange,
state contract, and Part 4 handoff. BME280 and PMSA003I acquisition is now verified
individually and on the shared bus; the prior skipped decision is retained as
history. See [the hardware handoff](docs/HARDWARE_HANDOFF.md) for raw samples,
60 normalized recorded observations, the shared format and remaining unknowns.
The dashboard/backend sensor feed is implemented with explicit fallback modes. Local Wolfram computation
is implemented and verified; see [Wolfram setup and testing](docs/WOLFRAM_HANDOFF.md).
Earlier restricted-session timeouts remain historical. The fresh normal-host
Part 1 check now passes for all twelve candidates; use `scripts/finish_part1.py`
for the verified Wolfram-backed dashboard and explicit failure fallback.
Save/reopen is implemented. Reports remain later work. No live aircraft or proprietary data service is used.

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --compute-options --computation wolfram
.\.venv\Scripts\python.exe -B scripts\verify_wolfram.py
```

Wolfram is optional and runs locally in this mode. The first command computes
all candidate costs and checks them against Python without changing state.
The second saves actual kernel parity evidence alongside the behavior tests.
Cloud and Alpha services are not called.

## State and image review

The run now includes explicit replay assessments, a pending review queue,
per-asset unresolved work and a separate recorded ground snapshot. Repeated
requests cannot silently charge another action or duplicate a finding within
one in-memory session. See [state/review commands and evidence](docs/STATE_REVIEW_HANDOFF.md).

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --run-state
.\.venv\Scripts\python.exe -B -m stratus.inspection --inspect P03 overview --execute --computation local
.\.venv\Scripts\python.exe -B scripts\verify_state_review.py
```

These commands start fresh runs. Image findings remain authored replay with
human review pending. Use the checkpoint commands below to preserve progress.

## Save and reopen

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --inspect P03 overview --execute --computation local --save saved-runs\my-inspection.json --summary
.\.venv\Scripts\python.exe -B -m stratus.inspection --load saved-runs\my-inspection.json --summary
.\.venv\Scripts\python.exe -B scripts\verify_persistence.py
```

An existing checkpoint is protected against accidental overwrite: load it
before saving updates, or choose a new filename. Reopening preserves battery,
action counts, evidence, pending review, original ground observations and
request receipts. The verified first run is in `saved-runs/first-inspection.json`.
See [the persistence handoff](docs/PERSISTENCE_HANDOFF.md) and
[current checkpoint/blockers](docs/CHECKPOINT.md). Live vision remains pending;
this checkpoint uses local Python and replay. The new ground feed runs beside
the mission and does not silently replace the ground snapshot saved in this run.
