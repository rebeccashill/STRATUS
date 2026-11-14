# Using the STRATUS inspection desk

For the verified 2-50-drone mode, see [FLEET_GUIDE.md](FLEET_GUIDE.md) and
[FLEET_DEMO.md](FLEET_DEMO.md). The current fleet preview runs on port 8774.
The single-drone instructions below describe the preserved inspection desk.

STRATUS helps choose which solar panel or follow-up view to inspect next while
respecting a simulated battery, return reserve and capture limit. Images are
authored illustrations with replay annotations. The separate ground panel can
show real sensor readings. Neither a simulation nor an image flag certifies a
panel fault, flight safety or air quality.

## Start or reopen

From the STRATUS folder in normal PowerShell:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part11.py
```

Keep that window open and visit http://127.0.0.1:8769/. The launcher checks the
actual local Wolfram runtime, then creates a fresh demo with 100 simulated
energy units and three capture actions. Earlier saved runs remain intact.
For a device-independent Python-only start, append `--local`. Sensor libraries
are optional for replay. An occupied port means another STRATUS window is still
running; stop that window with Ctrl+C before restarting on the same port.

Use **Mission / saved run** and **Load mission** to reopen work, or choose
**Fresh mission** to start another simulation. Loading waits until the list is
ready and cannot race an in-progress inspection. It does not refill a saved
run's budget. The original Part 11 walkthrough used `saved-runs/adaptive-e43ba3f0-cdedd7.json`
at 75.85786437626905 EU with one capture left, two P05 views and two feedback
actions. Its report preserves that verified state. The active run later advanced;
`saved-runs/ui11-browser-final.json` preserves a separate later
snapshot with 65.85786437626905 EU, three captures and zero actions remaining.

## Follow the next step

The five-step strip shows the current task. The budget and proposed view appear
before the map. Choose **Review next action**, read the reason and compare the
proposed view with its alternative. **Run simulated inspection** stays disabled
until a proposal has been reviewed; its enabled label names the exact view.
It commits one capture and opens the returned image. A new view always uses one
action. Repeated execution clicks do not create another capture.

The cost table shows travel to the view, taking the image, returning to launch,
the protected reserve, and energy left after that reserve. Reserve means energy
kept after the return trip. EU are invented simulation units, not measured
aircraft capacity. Excluded panels, missing evidence, review holds, exhausted
actions and numerical disagreement can block a capture. The instruction beside
the disabled button explains how to continue.

Selecting a panel or reference view on the map spends nothing. The selected
image identifies its panel/view, quality, tentative finding and review status.
An image marked not inspected is a reference fixture. An unclear image remains
unknown. A captured follow-up is a distinct image, not a relabeling of the
original. Map buttons work with Enter/Space and show a focus indicator.

For an explicit alternative, select the panel/view, expand **Other planning
options**, and choose **Plan selected view**. **Ask AI for a suggestion** is
optional; a proposal still passes the same checks and never executes itself.
A successful AI suggestion does not imply live vision or a sensor read.

## Review images and feedback

**Needs human review** links each task to its image. **Accept for review**
acknowledges a tentative concern. **Resolve task** closes that task while leaving
the original image finding unchanged. **Request another view** proposes an
eligible distinct follow-up without taking it automatically. Review the costs
before explicitly running that follow-up. When no capture remains, review and
save the run, or load a Fresh mission.

The verified example explicitly captured P05 overview (unclear/unknown),
requested and captured P05 follow-up (clear replay), and resolved only the
follow-up task. The original overview remains unknown and in the review queue.

## Wolfram and budget previews

The calculation card distinguishes **Local Wolfram**, **Cached Wolfram**,
**Local Python**, **Python fallback** and a numerical disagreement. Expand
**How costs are checked** to choose **Wolfram + Python check** or
**Local Python only**, then **Recalculate**. This prepares a new proposal without
changing aircraft state. Review it before execution.

Actual local Wolfram outputs must match independent Python within absolute
1e-8 / relative 1e-10 tolerance, with a strict feasibility sign. Cached means
the same normalized inputs and script; it is not a new runtime call. If the
runtime is unavailable, the screen says Python fallback. A material
disagreement blocks execution. Technical errors, model IDs and request counts
stay in expandable details, separate from mission energy.

Use **Budget preview** to try reserve/capture-cost values, then **Preview budget
change**. No active setting, battery, image or action changes. The verified
50-EU reserve / 20-EU capture preview ran through actual Wolfram and showed no
feasible capture while preserving 75.86 EU and one action. **Reset preview**
restores the controls to the active values, without executing anything.

Part 11 actual Wolfram 15.0.1 passed below/equal/above-reserve boundaries,
exhausted actions and metre/kilometre normalization, plus typed mission costs,
exact-input cache reuse and the browser preview. The earlier restricted-session
timeout is retained separately. This proves the declared toy arithmetic, not
aircraft endurance. Cloud and Alpha requests are zero; account credit
consumption was not retrieved and remains unknown. Optional Alpha explanations
are not part of this interface.

## Read the separate ground panel

**Live sensors on this computer** acquires actual BME280 atmosphere readings and
PMSA003I environmental particle mass readings. Their status and original UTC
acquisition times are visible beside the values. Particulates settle for
30 seconds; the bridge retries after reconnection. A failing channel stays
missing while other working readings remain available.

**Recorded measurement** replays earlier real values without refreshing their
acquisition times. **Synthetic example** uses invented values and cannot export
them as measured data. **Unavailable** displays dashes and leaves the inspection
usable. Each source has its own explanation. A zero PM value remains a measured
zero; it is not missing data or clean-air certification. Location, calibration
and uncertainty remain unknown unless separately verified.

Temperature is degrees Celsius; relative humidity is %RH; pressure is hPa.
PM1.0, PM2.5 and PM10 are the environmental mass channels in micrograms per cubic
metre. They are not the sensor's particle-count bins or standard-concentration
channels. These ground-node readings do not determine wind, airborne conditions,
flight clearance, image findings or mission energy.

**Refresh readings** never executes an inspection. **Save measured sample**
exports permitted real observations as Recorded data, preserving IDs, units,
quality and original acquisition/receipt times. Driver details and complete
records are expandable. Both physical sensors were fresh during the final
walkthrough; all six downloaded values matched raw CSV and report records.

## Report and save

Choose **Create report**, then **Open inspection report** or **Download report**.
The report includes evidence, tentative findings, unresolved work, actual/cached/
local computation, budget previews and the exact frozen ground context for each
decision. Its images are embedded for offline use. Historical Live describes
original acquisition, not a new measurement when viewing a saved report.

**Save run** preserves the current budget, actions, feedback and context.
Reopen it with the mission selector. The Part 11 browser walkthrough confirmed
the same saved checkpoint, original sensor times, 75.86 EU and one capture left;
the downloaded report matched the saved HTML byte for byte.

The interface was checked at desktop width and a 390-pixel browser override
(375-pixel content area) without horizontal overflow. The black/amber/off-white
palette and IBM Plex Sans/Mono font stacks are retained. Software evidence:
201 Python tests and 10 frontend checks, plus actual browser/Wolfram/hardware
observations under `docs/evidence/inspection-0.0.2/part11/`.

Part 11 is complete. Part 9 still owns final integration and code freeze;
Part 10 still owns the final pitch/package/recording. The newly planned Part 12
fleet and Part 13 hazard extensions remain pending; these single-drone UI checks
do not verify them.
