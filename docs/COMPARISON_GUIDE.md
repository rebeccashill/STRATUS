# Fair planner comparison

Saturday 0.0.2 Part 8 is complete: 17/17 actions. The saved comparison contains
three methods on three frozen, authored cases. It does not measure live AI image
accuracy or real aircraft performance.

Open the portable report at `saved-runs/reports/comparison-part8.html`, or while
STRATUS is running use:

http://127.0.0.1:8769/api/report/view?name=comparison-part8.html

## What the results say

| Case | Method | Usable priority | New gain | Captures | Distinct captured assets | Energy including return (EU) | Travel including return (m) | Open scripted tasks | Violations |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Clear | Fixed order | 11/11 | 7 | 3 | 3 | 61.134 | 92.268 | 0 | 0 |
| Clear | Nearest feasible | 11/11 | 7 | 3 | 3 | 54.063 | 78.126 | 0 | 0 |
| Clear | Adaptive | 11/11 | 7 | 3 | 3 | 54.063 | 78.126 | 0 | 0 |
| Unclear | Fixed order | 6/11 | 5 | 3 | 3 | 53.541 | 77.082 | 2 | 0 |
| Unclear | Nearest feasible | 7/11 | 6 | 3 | 2 | 46.992 | 63.983 | 2 | 0 |
| Unclear | Adaptive | 7/11 | 6 | 3 | 2 | 46.992 | 63.983 | 2 | 0 |
| Low battery | Fixed order | 4/11 | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 |
| Low battery | Nearest feasible | 4/11 | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 |
| Low battery | Adaptive | 4/11 | 0 | 0 | 0 | 0.000 | 0.000 | 0 | 0 |

Adaptive ties nearest feasible in these cases. Both improve unclear-case
coverage over fixed order while visiting fewer distinct assets: a follow-up
spends an action to make one high-priority asset usable. Two old unclear-image
review tasks remain open. In the clear case every method covers all eligible
priority; adaptive and nearest use less modeled energy than fixed order.
With insufficient energy, all methods gain nothing and return without a new
capture. These small examples establish no universal advantage.

## What makes the comparison fair

The inputs were frozen before measuring at 2026-11-14T17:09:31.667389+00:00.
`comparison-spec.json` has SHA256
`8ca23cf01b431aba1e93a42cfa7c744f6d0eb8d020c19b90211957855d47060d`.
`freeze-receipt.json` hashes all 26 input files. Do not edit them to improve
scores. The superseded first preflight is preserved in `preflight-history/`;
it was corrected before any scores because the exported Recorded input had a
stale Live display label. No measured values or planner rules changed.

Each method starts from identical inputs and priors within its case. All use
the actual inspection engine, common candidate eligibility, exclusions, return
reserve of 15 EU, three-capture cap and the same local cost calculator. Return
travel is debited exactly once. EU are invented simulation units.

Fixed order cycles through P01–P06 and advances after every capture; a new
follow-up waits until the next route pass. Nearest feasible minimizes outbound
distance, breaking ties by asset ID and view ID. Adaptive uses STRATUS's existing
deterministic ranking: requested view, descending priority, observed unclear
follow-up, outbound plus capture cost, then IDs. There are no fitted weights,
random draws, live LLM calls or post-score tuning.

All methods share a scripted benchmark reviewer that resolves only clear,
no-apparent-concern tasks, including priors. Unclear tasks remain open. This is
not actual human review or a defect-detection accuracy evaluation. Usable
priority counts an eligible asset once when it has a clear image. Common priors
are included; new gain subtracts that initial coverage. A follow-up cannot count
an asset twice. Raw findings and annotation human-review status stay unchanged.

## Ground and numerical evidence

All nine runs replay the exact same six actual BME280/PMSA003I observations from
the earlier physical USB recovery. Their original timestamps, environmental PM
mass convention, raw CSV provenance, unknown location and unreviewed quality
are retained. The snapshot is Recorded; its freshness is frozen. Ground values
do not change mission energy, priority, exclusions or image findings. No new
USB read is performed by the comparison. A separate sensor-parity record checks
raw CSV, normalized records, shared UI presentation and report values.

The numerical checks are separate from planner scores. Local Python checks
pass below/equal/above reserve, exhausted actions and explicit metre/kilometre
conversion. Absolute/relative tolerances are 1e-8/1e-10; feasibility sign remains
strict. Labeled injected tests check exact/stale cache, timeout, quota/access,
malformed replies and material disagreement blocking capture without changing
state. They are not actual Wolfram calls.

New Part 8 live Wolfram boundary calls are explicitly unrun in this handoff;
local kernel/cloud/Alpha counts are 0/0/0. Earlier actual Wolfram integration
success is recorded in Parts 1/2 and does not substitute for these new calls.
Consumed Cloud/Service Credits are unknown because account usage was not read.
The checklist expressly permits honest unrun live checks.

## Reproduce or finish optional live checks

From the STRATUS folder:

```powershell
# Full software gate plus the same nine deterministic runs; no hardware needed.
.\.venv\Scripts\python.exe -B scripts\verify_comparison.py

# Optional: run actual local Wolfram boundaries in your activated PowerShell
# session, updating the report without stopping an existing STRATUS server.
.\.venv\Scripts\python.exe -B scripts\finish_part8.py --checks-only

# Alternatively, after Ctrl+C stops the current server, run the checks and
# start STRATUS with the completed mission restored on port 8769.
.\.venv\Scripts\python.exe -B scripts\finish_part8.py
```

Refresh the report after updating numerical evidence. All nine planner runs use
local computation regardless of Wolfram availability. A numerical runtime
failure is recorded and remaining live attempts are left unrun; no retry loop
or invented success is used. Ordinary replay works without sensor libraries.

Full per-run JSON, CSV/JSON summary, frozen inputs, numerical evidence, sensor
parity, browser observations and the 194 Python/four frontend test logs are in
`docs/evidence/inspection-0.0.2/part8/`. The report embeds its two authored images
and can be opened offline. No calibration, image-accuracy, real-flight or
general planner-superiority claim is made.
