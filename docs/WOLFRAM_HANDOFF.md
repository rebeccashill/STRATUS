# Wolfram setup and computation

The local Wolfram 15.0.1 kernel is working. The inspection adapter sends a
validated JSON batch to a fixed Wolfram Language script and independently
checks every returned cost in Python. Computation itself is read-only.
This completes W001–W007 using W003's local-adapter option.

## Run it yourself

Open PowerShell in the STRATUS folder:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --compute-options --computation wolfram
```

Look for `mode: wolfram_local`, `execution_permitted: true`,
`failure: null` and `disagreements: []`. `state_before` and `state_after`
should match. Each of the 12 numerical options has a separate `action_checks`
entry: affordable cost alone does not authorize an excluded or duplicate view.

To compare the Python calculation:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --compute-options --computation local
```

To rerun the behavior tests and actual local Wolfram parity checks:

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_wolfram.py
```

This updates the technical verification files below. It makes no cloud or
Alpha requests. Tests exercise simulated transitions in memory; no inspection
run is saved. Saved-run/reload and live vision are still separate pending work.

An explicitly requested ephemeral action can also use the checked adapter:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --agent fallback --execute --computation wolfram
```

Every CLI invocation starts fresh. Wolfram is opt-in; ordinary launch uses the
standard library and needs neither Wolfram nor sensor packages.

## What was verified

| Check | Result / evidence |
| --- | --- |
| Runtime | Wolfram 15.0.1, Windows-x86-64, actual local kernel calls. |
| Mission batch | All 12 asset/view cost results agreed with independent Python. |
| Toy fixture | Available 100 / 50 / 49 gave margins 50 / 0 / −1; feasible / feasible / rejected. Outbound 10, capture 5, return 20, reserve 15. |
| Action cap | Zero remaining actions rejected even with margin 50. |
| Units | Metres and simulated energy units. Equivalent kilometre input converts coordinates and travel coefficient together and reuses the exact normalized-input cache. |
| Cache | Per-calculator memory cache, at most 64 entries. A new CLI process starts with an empty cache. State/mission revision, coordinates, battery, actions, costs, units and fixed-script hash affect the key. |
| Failure | Injected timeout, access/quota and malformed-response tests use labeled Python fallback. These are tests of handling, not successful cloud service calls. |
| Disagreement | A material numeric or feasibility disagreement blocks capture execution for review. No permissive result is chosen. |
| Preservation | Frozen mission, images, raw/normalized ground data and saved-run files remain unchanged. |

See `docs/evidence/inspection-0.0.1/wolfram/verification.json` and `tests.txt`
for the exact test count and run time. Actual local evidence is in
`typed-input.json`, `typed-output.json`, `mission-computation.json` and
`arithmetic-parity.json`. `resource-access.json` records access and balances.

## Typed contract and model

Public tool: `compute_inspection_options(input, calculator)` in
`stratus/inspection/computation.py`. The mission wrapper supplies current
validated state, then applies the existing identity, evidence, duplicate-view,
exclusion and action rules separately. Wolfram uses the fixed
`stratus/inspection/wolfram/inspection_costs.wls` implementation.

| Input | Meaning |
| --- | --- |
| `contract_version`, `model_version` | `inspection-costs-v1`, `toy-euclidean-energy-v1`. Unknown versions reject. |
| `mission_id`, `mission_revision`, `state_revision` | Mission identity/string revision and current integer state revision. |
| `position`, `launch` | Point ID and finite x/y coordinates. |
| `candidates` | 1–128 unique asset/view IDs and x/y coordinates, evaluated in one batch. |
| `distance_unit`, `energy_unit` | m or km input, normalized to m; `simulated_energy_unit`. |
| `battery_available`, `remaining_actions` | Current available budget and nonnegative integer capture count. |
| `capture_cost`, `travel_energy_per_distance`, `return_reserve` | Nonnegative model coefficients in consistent units. |

Each output option includes asset/view IDs, outbound, capture, return and
reserve costs, margin and feasibility. Root metadata retains units, mission
and state revisions, model and contract versions; actual Wolfram replies
also carry runtime version/system ID.

Margin = available − outbound − capture − return − reserve. Travel uses
straight-line Euclidean distance. Feasibility requires margin >= 0 and at
least one capture action remaining; full action eligibility is checked by
Python afterward. These are invented simulation energy units, not a
calibrated aircraft model. Ground measurements never enter aircraft costs.

Numeric comparison tolerance is absolute 1e-8 / relative 1e-10; feasibility
and margin sign must match exactly. Non-finite numbers, booleans used as numbers, negative
budgets/costs, unknown fields/units, duplicate candidates and malformed results
are rejected. Input coordinates/coefficients are bounded to 1e12 after unit
normalization; action/revision counts to 1,000,000. No input is evaluated as
Wolfram code. The subprocess receives JSON file paths and a fixed script.

## Execution modes and limits

| Mode | Meaning |
| --- | --- |
| `wolfram_local` | Actual local kernel result validated against Python. |
| `cached_wolfram_local` | Previously validated result for identical normalized inputs and script. |
| `local_python` | Explicit Python-only computation. |
| `local_python_fallback` | Unavailable/failed Wolfram transport or invalid result; equivalent Python with failure reason. |
| `wolfram_disagreement` | Validly shaped results disagree; execution blocked. |

One kernel attempt per computation, zero retries. Wolfram has a 5-second
calculation limit, wolframscript a 15-second limit and Python a 25-second
subprocess limit (configurable up to 60). Invalid/mismatching results are
never cached. The existing Python engine revalidates current state and owns
all debits/commits; costs cannot mutate state. Stop/return remain available
through its ordinary rules.

The installed runtime is discovered automatically under
`C:\Program Files\Wolfram Research\Wolfram\15.0`. Optional process environment
overrides are `STRATUS_WOLFRAMSCRIPT` and `STRATUS_WOLFRAM_KERNEL`.
The Wolfram adapter does not read `.env` files and requires no API secret.

## Resource/access record

| Pool | Recorded amount | Verification |
| --- | --- | --- |
| Cloud Credits | 175,000 | Rebecca confirmed the balance. |
| Service Credits | 500 | Rebecca confirmed the balance. |
| Wolfram Alpha API calls | 6,200 reported allocation | Previously reported; current remaining balance/API access not reconfirmed. |

Expiry dates are unknown. The local session reports `$CloudConnected=False`;
no cloud endpoint was deployed and Alpha API access was not tested. Local
Wolfram computation is verified independently of those optional services.
This verification used zero cloud requests and zero Alpha calls. Those
counts do not establish account-wide credit consumption or an AI entitlement.

## Next implementation step

Use this adapter and its cost/model/mode records in the first saved inspection
and later what-if UI. Persistence and the ground-context backend/panel remain
pending. Reference measured ground records with their original provenance;
keep them separate from simulated position, energy, actions and findings.
