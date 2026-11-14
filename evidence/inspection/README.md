# Inspection evidence inputs

Part 2 contains 12 newly authored 480x320 RGB PNG illustrations: overview and
distinct follow-up views for each of P01-P06. Every image visibly says
SYNTHETIC - NO REAL FLIGHT. P06 is indexed for completeness but stays excluded
from simulated capture requests.

| Asset | Overview | Distinct follow-up |
| --- | --- | --- |
| P01 | Clear grid; prior record | Clear closer view |
| P02 | Box-blurred grid; prior record, unknown finding | Clear closer view |
| P03 | Authored apparent-concern mark | Closer view of the authored mark |
| P04 | Clear grid | Clear closer view |
| P05 | Authored glare/occlusion, unknown finding | Clear closer view |
| P06 | Excluded fixture | Excluded fixture |

`manifest.json` indexes scenario/asset/view, image path, SHA-256, source mode,
authorship, and rights. `annotations.json` keeps scenario quality/finding
labels outside the image records. These are AI-assisted authored replay
annotations awaiting human review, never live vision-model output or verified
defect diagnoses. There are no source photographs or third-party datasets.

Regenerate this fixed demo pack deliberately with
`python -B scripts/prepare_part2_evidence.py`. This resets this case's mission
input to the declared initial state; it does not create an inspection run.
All planners use the same immutable indexed case. Load-time missing images
are rejected; files missing, unreadable, corrupt, or changed after load return
unavailable/unknown without replaying their annotation.
