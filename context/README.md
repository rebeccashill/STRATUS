# Ground sensor context

Actual BME280 and PMSA003I acquisition is verified individually and on the
shared bus. Original CSVs and their summaries remain measurement evidence.
Ordinary project startup does not require the sensors to be attached.

- `hardware-status.json`: board IDs, acquisition status, raw hashes, unknowns
  and actual handoff timing.
- `ground-record.schema.json`: versioned shared live/replay record format.
- `ground-measurements/observations-20261114.jsonl`: 60 normalized recorded
  observations with original times, stable IDs and source references.
- `hardware-packages.txt`: installed package versions.
- `sensor-decision.json`: unchanged historical Part 3 skipped-acquisition decision.

Location, calibration and uncertainty remain unknown. Measurements remain
unreviewed. Missing receipt times remain null/unknown. Ground context must not
overwrite simulated aircraft position, battery, actions, findings or coverage.

See [the hardware handoff](../docs/HARDWARE_HANDOFF.md) for field definitions,
provenance, source-mode rules and next integration work.
