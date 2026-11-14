# State transitions and review: S032-S036

The working source now initializes a fresh inspection run, executes one
validated capture, applies an explicitly authored replay assessment, updates
the pending review queue, and prevents repeated requests from charging or
adding the same finding twice. Ground measurements stay in a separate snapshot.

## Try it

Open PowerShell in the STRATUS folder. Show the fresh run:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --run-state
```

The aircraft starts at x=0, y=0 with 100 simulated energy units, two prior
records and three new capture actions remaining. P03/P04/P05 have no prior
capture; P06 is excluded. Prior records retain their original pending/unknown
findings and consume no new action. Invocations create a fresh run unless `--load` opens a checkpoint.

Preview an inspection, then explicitly execute it:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --inspect P03 overview
.\.venv\Scripts\python.exe -B -m stratus.inspection --inspect P03 overview --execute --computation local
```

The preview changes no state. Execution returns the complete before/after run
and event. P03/overview costs 15.8113883 outbound plus 5 capture energy units,
leaving 79.1886117 and two actions. Return cost and reserve remain protected;
they are not charged on capture. The replay labels its authored concern as
tentative and adds one pending assessment, making three entries including
the two priors. This is a simulated capture of a synthetic drawing.

Wolfram is optional. Use `--computation local` for explicit Python computation.
`wolfram_local` means an actual local kernel result passed independent Python
checks. `local_python_fallback` identifies unavailable/invalid Wolfram output;
material disagreement blocks execution. No cloud, Alpha or live AI call is
required for this section. The Python engine still owns validation and debits.

Run the complete behavior checks and the state/review verification:

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_state_review.py
```

The verification uses explicitly labeled Python costs. Add `--wolfram` to
require an actual kernel-backed inspection; that check fails if the adapter
falls back. During this session the local kernel timed out, including with
the installed companion launcher. The actual timeout and successful fallback
execution are retained in `wolfram-initial-timeout.json` and
`wolfram-fallback-execution.json`. Root cause is not established. Earlier
successful Wolfram parity is historical evidence; it is not a successful call
in this state/review verification. Kernel discovery now also finds an installed
kernel when Windows PATH selects the separate WolframScript launcher.

Verification snapshots and test observations go under
`docs/evidence/inspection-0.0.1/state-review/`. They are technical evidence;
saved-run loading and continuation are now implemented; see `PERSISTENCE_HANDOFF.md`.

## What the run exposes

| Field | Meaning |
| --- | --- |
| `aircraft_state` | Position, battery, paid capture counts, completed views, history, revision and status. |
| `assets` | Captured views, current image quality/finding, coverage status and unresolved work for each panel. |
| `assessments` / `review_queue` | Prior records plus new capture assessments, with evidence IDs/hashes, mode, quality, concern flags and pending human review. All assessments currently await human review. |
| `uninspected_assets` | Eligible assets that have no captured view. |
| `incomplete_assets` | Eligible assets with unresolved capture or review work. A clear image alone does not establish a reviewed or defect-free asset. |
| `ground_context` | A separate Recorded measured snapshot or Unavailable, with node location and original observation times/source/quality. |
| `events` | Exactly one event for each processed valid action request. Replaying a request returns a receipt without appending another event. |

Image review uses `authored_replay_annotation`, `live_model_output=false` and
`model=null`. No new live-vision inference is claimed. Unclear/unavailable
assessments retain unknown findings. An apparent concern stays tentative and
requires human review. A clear follow-up changes the current image-quality
summary while retaining prior unknown records in history; a historical
tentative concern cannot be silently cleared by a later clear drawing.

## Ground context

The default reader validates `context/hardware-status.json` and the SHA-256
of its normalized recorded observations. It checks the 60 recorded rows and
selects the latest observation per sensor/channel, currently six channels.
Original observation IDs, acquisition/receipt times, measured values, source
references, unreviewed quality and unknown calibration/uncertainty are retained.
The ground location remains unknown rather than inheriting aircraft coordinates.

Reading recorded context performs no physical acquisition and imports no sensor
drivers. Ground data does not alter budget, coverage or image findings. Missing,
changed or invalid records become Unavailable with technical error details;
core startup and execution still work. To choose this mode explicitly:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --run-state --ground-context unavailable
```

Snapshot age is measured at snapshot creation; original acquisition times do
not become fresh on replay. A future acquisition timestamp is explicitly flagged.
The raw CSV files are not revalidated by this reader; their original provenance
is retained in the normalized observations and hardware registry.

## Repeat protection

`InspectionSession` in `stratus/inspection/review.py` owns one current immutable
aircraft state and serializes execution with a per-session lock. API callers
provide a bounded `request_id` and `expected_revision`:

1. A new request must match the current revision and pass the existing Python
   identity, exclusion, action, evidence and protected-return-budget checks.
2. A matching repeat request returns `already_processed`, the original event
   ID/status, zero new debit and no added assessment. It does not recalculate
   or recapture. The original expected revision must be retained on a retry.
3. Reusing an ID with changed proposal/revision returns
   `idempotency_key_conflict`. A new ID with an outdated revision returns
   `stale_state_revision` before computation or capture.
4. Reusing the same asset/view under another ID is rejected by the existing
   completed-view check. Repeated rejected requests cannot later become an
   implicit execution. Stop/return add no image assessment.

The request fingerprint includes the complete normalized proposal and expected
revision; clients must retry the same request rather than rewriting its reason.
Records are not evicted during a session. After 1,024 processed requests the
session rejects further requests. Saving/reopening now retains the request
receipts and original budgets. Load the checkpoint to retry a previous action;
do not reconstruct a fresh session. See `PERSISTENCE_HANDOFF.md` for file write
conflict protection and the limits of local JSON checkpoints.

## Evidence and next step

`verification.json` records the exact test count, execution/computation mode,
budget, ground status and preservation checks. `initial-run.json` and
`first-inspection.json` contain actual in-memory before/after observations.
`idempotence.json` records same-request, duplicate-view, stale and conflicting
request behavior. `replay-review-cases.json` includes clear, unclear, follow-up
and excluded cases. `tests.txt` records the full behavior suite; injected
failures in those tests do not count as successful live service access.

S032-S036 are implemented and verified. The operator summary and S038/S039
save/reload path are also complete; see `PERSISTENCE_HANDOFF.md`. Live vision,
human approval and the live ground backend remain separate pending work.
Frozen mission files, synthetic evidence and ground measurements are preserved.
