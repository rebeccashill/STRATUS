# Saved inspection runs

Part 11 original example: `adaptive-e43ba3f0-cdedd7.json` was verified with P05's
unclear overview and distinct clear follow-up, feedback, 75.85786437626905 EU
and one remaining capture. That active run later advanced. A separate byte-copy
`ui11-browser-final.json` preserves its later three-capture state
at 65.85786437626905 EU and zero actions; see part11/final-snapshot.json. Its portable report is
`reports/inspection-e43ba3f0-20261114T192313934149Z.html`, with a JSON companion.
Use `scripts/finish_part11.py` for the current interface and actual Wolfram
checks; see `docs/OPERATOR_GUIDE.md`. Reopening preserves the saved budget.

JSON checkpoints now preserve run state, computation/action logs, pending
review, ground snapshots and request receipts. `first-inspection.json` is the
verified Friday acceptance run. Adaptive checkpoints also retain review
feedback, frozen decision contexts and retry receipts. Portable HTML reports
and technical JSON companions are under `reports/`.
The immutable input skeleton is under `stratus/inspection/missions/`; do not
overwrite it with run state. Generated runs are ignored by git. Sanitized,
deliberately selected acceptance evidence belongs under `docs/evidence/`.

Use `--load saved-runs/first-inspection.json --summary` to reopen it. Opening
does not refresh ground observations or reset budgets. To continue, combine
`--load` with an inspection/agent/proposal and `--execute`; include `--save`
to commit the updated run. Stale writers are rejected. Do not delete a `.lock`
file while another process is saving; a crash may leave a lock requiring review.

Saturday Part 6 adds `part6-partial-*.json` and `part6-final-*.json` acceptance
runs. The partial run has two new captures and one action left; the final run
has three captures, a rejected fourth request and an explicit return to launch.
The current launcher is `scripts/start_stratus.py` at port 8769. See
`docs/RECOVERY_GUIDE.md` and the current
`docs/evidence/inspection-0.0.2/part6/verification.json` for exact filenames.
Loading a saved run displays its own last ground snapshot as recorded history;
its observation IDs and original measurement times are never refreshed.

Saturday Part 8 adds `reports/comparison-part8.html` and its JSON companion.
This portable report compares all nine frozen method/case runs, with numeric
checks and ground provenance separate from planner scores. Per-run technical
JSON is under `docs/evidence/inspection-0.0.2/part8/runs/`; these are benchmark
traces rather than operator mission checkpoints. See `docs/COMPARISON_GUIDE.md`.
