# Ground hardware handoff

H006, H007 and H008 are complete: actual samples are preserved, the shared
live/replay record format is saved, and the hardware handoff is recorded.
Rebecca confirmed that timing does not block H008 completion. The actual
handoff time and original target remain in `context/hardware-status.json`.

## Verified acquisition

| Component | Board identity | Observed status |
| --- | --- | --- |
| USB bridge | Adafruit 4471, MCP2221A | Replacement USB cable enabled actual sensor reads. Original cable failure cause remains undiagnosed. |
| Atmospheric sensor | SparkFun 15440 / SEN-15440, BME280, 0x77 | Five individual and five shared-bus reads succeeded. |
| Particulate sensor | Adafruit 4632, PMSA003I, 0x12 | Five individual and five shared-bus reads succeeded at the requested 100 kHz setting. |

The shared connection uses one Qwiic cable from bridge to BME280 and a second
from BME280 to PMSA003I. Disconnect USB before changing wiring. Physical serial
numbers and actual location were not recorded. `ground-node-001` and its sensor
IDs are assigned logical identifiers, not manufacturer serials or simulated
panel/drone locations.

## Evidence map

| File | Contents |
| --- | --- |
| `context/bme280-20261114T110000Z.csv` | Five BME280 rows, with three quantities per row. |
| `context/ground-measurements/pmsa-20261114T111234Z-0fe78b.csv` | Fifteen channel rows: three PM channels across five reads. |
| `context/ground-measurements/both-20261114T111455Z-a371ef.csv` | Thirty channel rows: six channels across five rounds. |
| Matching `pmsa-...json` and `both-...json` | Raw scans, successful-read counts, requested bus frequency, channel convention and package versions. |
| `context/ground-measurements/observations-20261114.jsonl` | Sixty normalized recorded observations: 30 BME280 and 30 PMSA003I values. |
| `context/ground-record.schema.json` | Shared JSON Schema version 1.0.0. |
| `context/hardware-status.json` | Board/status registry, raw hashes/counts, unknowns, handoff timing and next step. |
| `context/hardware-packages.txt` | Installed package-version record. |

The raw CSVs are unchanged. Each normalized value references its raw file,
SHA-256 content hash and physical CSV row number (header is row 1). Separate
individual/shared runs remain separate acquisitions.

## Shared record contract

Use the same object structure for live readings and replay. Additional
top-level fields are excluded, including aircraft position, battery, actions
and image findings.

| Fields | Definition |
| --- | --- |
| `schema_version` | `1.0.0`; change deliberately when the contract changes. |
| `observation_id` | Stable identity derived from node, sensor, variable, acquisition time and raw provenance. Replay retains it. |
| `node_id`, `sensor_id`, `sensor_model` | Logical node/sensor IDs and model. Board product IDs and unknown serials live in the status registry. |
| `variable`, `value`, `unit` | One finite channel value. An unavailable value is null; missing readings are never filled with zero. |
| `acquired_at_utc`, `timestamp_basis` | Original host read-completion time in UTC, not a verified sensor clock. Unknown acquisition time is null. |
| `received_at_utc`, `receipt_time_status` | Original recorded UTC receipt time, or null/unknown if the source omitted it. |
| `normalized_at_utc` | Conversion time only; never measurement freshness or receipt time. |
| `location` | Real ground location status, label, position and coordinate frame. These records retain unknown/null values. |
| `source_mode`, `acquisition_source` | Live/recorded measurement, synthetic or unavailable delivery, with physical/synthetic/unknown acquisition origin. |
| `quality` | Unreviewed, reviewed, invalid or unavailable, with explicit flags. Current measurements remain unreviewed. |
| `calibration` | Unknown with null reference until documented. |
| `uncertainty` | Unknown with null value/unit/kind until an estimate and method exist. Unknown uncertainty is not zero uncertainty. |
| `provenance` | Raw file, content hash, row and original source label. |
| `context_role` | Always `ground_context_only`. |

| Sensor | Variable | Unit | Source |
| --- | --- | --- | --- |
| BME280 | `temperature` | `degC` | Temperature in Celsius. |
| BME280 | `relative_humidity` | `%RH` | Relative humidity. |
| BME280 | `pressure` | `hPa` | Barometric pressure. |
| PMSA003I | `pm1_0` | `ug/m3` | `pm10 env` library key. |
| PMSA003I | `pm2_5` | `ug/m3` | `pm25 env` library key. |
| PMSA003I | `pm10` | `ug/m3` | `pm100 env` library key. |

`ug/m3` means micrograms per cubic metre (µg/m³). PM variables use environmental
mass concentration, not the standard-concentration fields or particle counts.

## Live and replay rules

- A newly acquired physical reading uses `source_mode=live_measured`.
- Saved measurements use `source_mode=recorded_measured`; original source
  labels stay in provenance. All 60 normalized observations are recorded
  history, not a claim of a fresh physical poll.
- Replay retains IDs, acquisition/receipt times, location, quality, calibration
  and uncertainty. File-loading/conversion time is separate.
- Synthetic inputs stay labeled synthetic. Unavailable records use null values
  and invalid/unavailable quality; last-good readings remain separate history
  with their actual age.
- Fifteen first-run BME280 values have no source receipt time, so their receipt
  fields remain null/unknown. The other 45 retain recorded receipt times exactly.
- Ground context does not change simulated position, energy, action count,
  coverage or image findings.

## Unknowns and next step

No current acquisition blocker is recorded. Actual location, hardware serials,
calibration and uncertainty remain unknown. The PM channels reported zero in
both short tests; keep those values unreviewed without claiming zero particles,
calibrated accuracy or response under other conditions.

Raw scans also contained reserved-address entries 0x00 and 0x78. Their cause
remains undiagnosed; they are not extra inventoried sensors. The historical
Part 3 skipped decision in `context/sensor-decision.json` is unchanged.

H009/H010 are next for hardware application integration: feed live readings and
these recorded observations through one backend interface, then connect the
Ground conditions panel and report. Preserve source, time, identity and real
location. Acquisition and a record specification alone do not complete that UI.

Remaining Part 4 Wolfram work, the first saved inspection and save/reopen remain
separate pending work. Preparing this handoff required no API calls, physical
re-acquisition or simulated inspection actions.
