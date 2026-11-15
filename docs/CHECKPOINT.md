# STRATUS documentation and verification index

Start with the [project README](../README.md) and [judging demo](FLEET_DEMO.md).
The application runs locally; Recorded ground data and Local Python need no
sensor hardware, API key or Wolfram installation.

| Guide | Purpose |
| --- | --- |
| [Demo](FLEET_DEMO.md) | A short fleet, reported-hazard and report walkthrough. |
| [Operator guide](OPERATOR_GUIDE.md) | Single-drone inspection, feedback, saving and reopening. |
| [Fleet guide](FLEET_GUIDE.md) | Independent drone budgets, allocation, scaling and limitations. |
| [Hardware](HARDWARE_HANDOFF.md) | Purchased sensors, connections, recorded fallback and recovery. |
| [Wolfram](WOLFRAM_HANDOFF.md) | Optional local computation, Python validation and failure modes. |
| [Planner comparisons](COMPARISON_GUIDE.md) | Same-budget baselines, measurements and retained regressions. |
| [Fleet/hazard contracts](FLEET_CONTRACT.md) | Revision checks, shared state and integration boundaries. |
| [Verified demonstration](FINAL_FREEZE.md) | The recorded release walkthrough and its limits. |

## Retained evidence

- `docs/evidence/inspection-0.0.2/part8/`: single-drone comparisons.
- `docs/evidence/inspection-0.0.2/part12/`: fleet benchmarks and numerical checks.
- `docs/evidence/inspection-0.0.2/part13/joined/`: shared hazard integration.
- `docs/evidence/inspection-0.0.2/part9/`: original release freeze and browser checks.
- `docs/evidence/inspection-0.0.3/`: final hardware/fallback and regression records.

Evidence files are dated snapshots. A historical checksum or test result describes
that recorded build, not every later documentation or display change. The latest
documentation cleanup checks are recorded under
`docs/evidence/inspection-0.0.3/docs-cleanup/`.

Aircraft motion, energy and inspection imagery are simulated. Ground sensing is
a separate physical or recorded context source. No field-flight or collision
prevention result is claimed.
