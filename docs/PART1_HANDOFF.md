# Part 1 completion and standalone handoff

**Relocation resolved:** The verified 20-file standalone ZIP was extracted into
`C:\Users\shill\OneDrive\Desktop\STRATUS` and every entry matched the archive.
Part 2 is now implemented in that folder; see `PART2_HANDOFF.md`. Access-denied
notes below describe the earlier handoff session, not a current blocker.
The Part 1 verification script/logs describe the historical skeleton; use
`python -B scripts\verify_part2.py` for the current complete evidence input.

S001-S009 are complete. The source checklist is
[STRATUS 0.0.1](https://app.notion.com/p/4185b396b48e81c3b6e9c07502d50958).

The user selected `C:\Users\shill\OneDrive\Desktop\STRATUS` as the continuing
workspace. That folder was inspected and was empty. Creating its `stratus`
subfolder failed with `Access to the path ... is denied` in this session.
No destination files were written. The original Part 1 files have been kept
intact until the standalone handoff can be placed there safely.

This handoff contains only newly authored Part 1 work from this session:
the inspection module and mission input, operator brief, placeholder variables,
folder role notes, and setup evidence. The top-level package initializer,
standalone project metadata, README, ignore rules, future-work instructions,
and verification script were authored for this independent handoff.

No earlier project code, website demo, dataset, test suite, virtual environment,
or Git history is included. The package needs no third-party runtime dependency.

Actual standalone observations are saved under
`docs/evidence/inspection-0.0.1/part1/`:

- `startup.txt`: successful read-only mission preview using Python 3.10.11.
- `verification.json`: six reviewed unique panels, two prior placeholders,
  three unused actions, unchanged mission bytes, no fabricated saved run,
  readable malformed/missing-file errors, and fresh ignore-rule checks.
- `quality-checks.txt`: formatting and lint checks on the four new Python files.
- `checksums.sha256`: handoff file hashes.

From this folder, reproduce setup with `python -m venv .venv`, then run
`.\.venv\Scripts\python.exe -B -m stratus.inspection`.
Run `.\.venv\Scripts\python.exe -B scripts\verify_part1.py` to refresh setup
observations. After the move succeeds, update the migration status in that
script and this note, and remove only this session's Part 1 additions from the
old folder while preserving all earlier user work.

Next implementation: Part 2 evidence views/rights/manifest and validated loader.
