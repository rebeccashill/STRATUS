# Persistence and handoff: S037-S042

The first validated inspection is saved in `saved-runs/first-inspection.json`.
Reopening preserves the same run ID, battery 79.1886117, two remaining capture
actions, three pending image assessments and the exact original ground snapshot.
The completion gate passed 117 behavior tests plus a real file save/reload.

## Open the project and saved run

From the STRATUS folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection
.\.venv\Scripts\python.exe -B -m stratus.inspection --load saved-runs\first-inspection.json --summary
```

The summary shows what changed, remaining budget, the next action or hold and
its reason, plus Recorded/Unavailable ground conditions and reading age. P03's
tentative replay concern produces a hold for human review. Technical driver
details stay in structured data, outside the concise message.

To inspect all saved fields, replace `--summary` with `--run-state`.
Reading a checkpoint never runs the capture adapter, contacts a service, reads
current sensor data, or resets the mission. Ages in the operator view increase
from the original acquisition time; Recorded data is never relabeled Live.

## Start, save and continue your own run

Choose a new filename for a new run:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --inspect P03 overview --execute --computation local --save saved-runs\my-inspection.json --summary
```

To explicitly continue that run, load it, choose an action, execute, and save:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection --load saved-runs\my-inspection.json --inspect P04 overview --execute --computation local --save saved-runs\my-inspection.json --summary
```

The displayed concern hold is operator guidance; explicit execution still uses
the existing deterministic constraints. Human approval workflow remains later
work. An inspection without `--execute` is a read-only proposal and may be
saved in the proposal audit without consuming energy/actions. Failed live AI
requests still require an explicit fallback choice before execution.

`--load` retains the saved ground mode/snapshot, so it cannot be combined with
`--ground-context`. For a fresh run, `--ground-context unavailable` remains
available. Ordinary startup/replay requires no hardware or Wolfram packages.

## What is saved

| Component | Preserved fields |
| --- | --- |
| Mission binding | Mission/revision and a fingerprint of the frozen mission, image-manifest records and annotations. |
| Aircraft state | Position, available battery, actions used/remaining, completed views, history, revision/status. |
| Actions | Read-only proposal decisions and rejected/executed request events. Events contain asset/view, costs, model, computation mode, evidence and assessment mode. |
| Review | Original prior findings, new replay assessments, tentative flags, evidence IDs/hashes and pending review queue. |
| Ground | Exact recorded/unavailable snapshot, node location, observation IDs, original acquisition/receipt times, source, quality, calibration/uncertainty labels and provenance. |
| Retry receipts | Request IDs, original proposal/revision fingerprints and event receipts, retained across reopening. |

The format is bounded JSON (`stratus-run-1`, at most 8 MB), not executable code
or pickle. A checksum detects accidental file edits. It is not a digital
signature or proof that someone has not deliberately rewritten a file.
Restoration independently reconciles budget/history/assessments with the
action log and current mission/evidence, and rejects inconsistent records.
Changed missions/images or broken checkpoints produce an error; they do not
silently create a fresh run.

## Repeat and write protection

For an API/CLI retry, retain the complete proposal, original request ID and
original expected revision. For example, a new command may use
`--request-id capture-001 --expected-revision 0`; retry with those same fields
after reopening. Matching repeats add no second debit, capture, finding or
event. Another ID cannot charge an already completed view again.

Writes use a temporary file, flush/fsync and atomic replace. A per-file writer
lock serializes application writers; the saved-file hash detects stale loaded
copies. A new session cannot overwrite an existing checkpoint, and a stale
session must reload before saving. Interrupted-write tests preserve the prior
valid file. A process crash may leave a `.lock` file; review whether another
writer is active before removing a stale lock. This is a local JSON checkpoint,
not a multi-user database or distributed transaction system.

## Verify it yourself

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_persistence.py
```

This runs the full behavior suite, creates a new acceptance run without
overwriting previous runs, saves/reopens it, and verifies retry protection,
unchanged ground provenance and protected input files. Repeated verification
uses a timestamped run filename when `first-inspection.json` already exists.

Evidence is under `docs/evidence/inspection-0.0.1/persistence/`: `tests.txt`,
`verification.json`, `save-reload.json`, `operator-summary.json`,
`operator-summary.txt` and `checkpoint.json`. These are technical observations;
the resumable file itself is under `saved-runs/`.

## Current modes, blockers and next step

Current checkpoint: local Python costs, authored replay image labels, recorded
measured ground context. No live vision, new physical acquisition, cloud,
Alpha or live AI call was needed. The latest Windows Wolfram attempts timed
out; older successful parity remains historical evidence. Keep Python mode
until a new actual kernel check passes. BME280/PMSA003I standalone and shared
acquisition already succeeded; live backend polling and the operator ground
panel remain Saturday H009/H010 work. Ground location, calibration and
uncertainty remain unknown. Human review is pending, with no confirmed defect.

See `docs/CHECKPOINT.md` and the machine-readable `checkpoint.json` for actual
handoff time, original stop target, blockers and next steps. The original
midnight target was missed; no timestamp was backdated and no claim is made
that work stopped at midnight. No new per-part ZIP was created. Continue
STRATUS 0.0.2 from the saved run and preserved hardware evidence.
