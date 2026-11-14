# Part 2 completion: local evidence, loader, and simulated capture

Source: [STRATUS 0.0.1, Part 2 (S010-S020)](https://app.notion.com/p/4185b396b48e81c3b6e9c07502d50958).
Continuing workspace: `C:\Users\shill\OneDrive\Desktop\STRATUS`.
The fresh Part 1 handoff was extracted here and all 20 archive entries matched.
This part adds only newly authored work; no earlier project was imported.

| Actions | Implemented evidence |
| --- | --- |
| S010 | 12 procedural PNG views, including a visibly blurred P02 overview, clear views, and an authored apparent-concern P03 mark. Three representative images visually inspected. |
| S011-S012 | `evidence/inspection/manifest.json`: complete six-asset/two-view index, case identity, hashes, source label, authorship and rights for every image. Follow-up has a separate ID, file, and hash. |
| S013 | `evidence/inspection/annotations.json`: separate prepared replay labels; AI-assisted authoring is explicit; human review pending; no live model output. |
| S014-S016 | `stratus/inspection/loader.py` and completed mission JSON: full input retained and frozen, numeric/reference/path/PNG checks, two traceable prior records, all three actions and 100 simulated energy units retained. |
| S017-S019 | `stratus/inspection/capture.py`: case-bound read-only evidence response with reference, provenance, response timestamp, simulated mode, and explicit unavailable/unknown failures. Fixed evidence is shared by every planner. |
| S020 | `scripts/verify_part2.py`: standard-library-only launch, 24 behavior tests, saved example responses, validation errors, and checksums in `docs/evidence/inspection-0.0.1/part2/`. |

## Reproduce

Use Python 3.10-3.12 from the workspace. No third-party runtime dependency,
account, download, proprietary service, or earlier environment is needed.

```powershell
python -B -S -m stratus.inspection
python -B -S -m stratus.inspection --capture P03 overview
python -B -S -m stratus.inspection --capture P02 follow-up
python -B scripts\verify_part2.py
```

The loader rejects malformed JSON, duplicate or unknown IDs, missing references,
image-path escapes, missing/unreadable PNGs, hash mismatches, invalid battery or
costs, missing coordinate units, and misleading provenance/annotation labels.
After load, a lost, unreadable, corrupt, or changed image returns unavailable
with unknown quality/finding and no annotation. Tests mutate disposable copies.

## Contract for Part 3

`load_mission()` returns a frozen document and indexed evidence/annotations.
`simulated_capture(mission, asset_id, view_id, scenario_id=...)` returns JSON-ready
data. Its timestamp is when the response was created, never a real camera event.
The same case and asset/view resolve to the same image and annotation. With an
injected response clock the entire response is reproducible.

The evidence adapter does not execute an action, debit energy, move position,
or mark coverage complete. Part 3 must validate and execute state changes once,
including duplicate-view prevention and each paid follow-up. Prior records
consume no new actions. P06 remains excluded. Part 2 tests and evidence previews
are not saved inspection runs or completion of Parts 3/4.

Live AI/vision, human evidence review, optional ground sensor acquisition,
Wolfram access/integration, reports, and save/reopen remain pending. Part 2
does not perform Wolfram setup or claim service access.
