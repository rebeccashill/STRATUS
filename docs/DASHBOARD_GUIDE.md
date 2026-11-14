# STRATUS inspection desk

From the STRATUS folder in PowerShell, start the one local application:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part1.py
```

Keep that terminal open and visit **http://127.0.0.1:8767** in your browser.
Stop with Ctrl+C. This launcher performs one bounded actual Wolfram check,
saves its typed result, and uses Wolfram when it passes or explicit Python
fallback when blocked. No API key or sensor library is needed for Recorded.
If needed, choose another port with `--port 8768`. The module commands below
use port 8765 by default; the verified fresh-launch command above uses 8767.

The app opens `saved-runs/first-inspection.json`: P03/overview is captured,
battery is **79.19 simulated units**, and **two of three capture actions remain**.
P03 has a tentative concern awaiting human review. Image evidence and aircraft
state are simulated; the ground panel independently identifies its source.

## Try it yourself

1. Select P01, P02, P03, P04 and P05 on the map. Change the Evidence view between
   Overview and Follow-up. The asset/view IDs and image provenance should match.
   P06 is excluded: its viewer explicitly says unavailable and the finding stays
   unknown. Viewing evidence does not execute a capture.
2. Open an item in the review queue. Image quality and tentative findings are
   separate labels. A clear image can still contain a tentative concern; an
   unclear image never becomes a no-defect result.
3. Read the next decision and the suggested/alternative numerical costs. The
   saved run has a review hold. The suggested inspection after review is
   P02/follow-up, selected by a deterministic priority/uncertainty/cost rule.
4. In Ground conditions, select Recorded, Unavailable or Synthetic example.
   Recorded uses actual earlier sensor measurements and their original UTC
   times. Synthetic example is authored demonstration data. Neither is Live.
   Missing or invalid values display dashes. Age and status are per sensor.
5. Set Return reserve to 50 and Capture cost to 20, then click Preview budget.
   No capture should fit. Battery should stay 79.19 and actions should stay two.
   Reset restores the preview controls; it never changes the active mission.
6. Refresh ground data several times. Load the saved checkpoint again.
   Battery, actions, pending review and evidence should stay the same.

This screen is a read-only inspection desk in Part 1. Explicit capture execution
remains available through the existing CLI. Feedback controls, replanning,
reports and attaching a newly selected ground feed to saved runs are later
checklist work. Loading a mission does not silently attach a newer ground sample.

## Use the connected kit

Keep the previously verified shared connection: MCP2221A (Adafruit 4471) to
BME280 (SparkFun SEN-15440), then BME280 to PMSA003I (Adafruit 4632), using the
two supplied 100 mm Qwiic cables. Disconnect USB before changing wiring.
Use the working USB **data** cable that solved the earlier detection problem.
No COM-port setup or firmware upload is required.

The same project environment can optionally install the sensor dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install hidapi adafruit-blinka adafruit-circuitpython-bme280 adafruit-circuitpython-pm25
$env:BLINKA_MCP2221="1"
.\.venv\Scripts\python.exe -B -m stratus.inspection.dashboard
```

Select **Live USB reader** in Ground conditions. The host sets the MCP2221
environment flag before lazily importing board/busio and reads at 100 kHz.
The BME280 should appear at 0x77 (0x76 supported); the PMSA003I at 0x12.
Extra scan addresses do not establish additional working sensors.
PMSA003I settling is 30 seconds after initialization. Polling is every five
seconds, with stale status after 20 seconds. A failing sensor leaves the other
sensor usable. Reconnection is retried without changing aircraft budgets.

| Quantity | Unit | PMSA003I driver channel |
| --- | --- | --- |
| Temperature | °C | BME280 temperature |
| Relative humidity | %RH | BME280 relative_humidity |
| Pressure | hPa | BME280 pressure |
| Environmental PM1.0 | µg/m³ | pm10 env |
| Environmental PM2.5 | µg/m³ | pm25 env |
| Environmental PM10 | µg/m³ | pm100 env |

Standard-concentration fields and particle bins are not used as environmental
mass concentration. CSV samples and matching normalized JSONL records are saved
under `context/ground-measurements/live/<session>/`. The observation format stays
the same for measured Live and Recorded data. Calibration/uncertainty and node
location remain unknown until verified; values are unreviewed. Project sanity
bounds reject non-finite values, humidity outside 0–100, temperature outside
−50–100 °C, pressure outside 100–1200 hPa and negative PM values. These checks
do not establish calibrated accuracy.

For a connection error, expand Connection & technical details. Close any other
sensor reader, reconnect the known working data cable, then reselect Live. Use
Recorded or Unavailable while blocked. The latest fresh normal-host app
also could not find the MCP2221; earlier successful physical samples remain
available. The completed demo uses those Recorded measurements. No new physical
success is claimed for this build.

## Export actual measured context

Click **Export sample** while actual Live or Recorded data is available. This
downloads `stratus-recorded-ground.json`, labeled Recorded with original times.
Synthetic examples cannot be exported as measured data. A matching file is also
saved at `docs/evidence/inspection-0.0.2/part1/recorded-ground.json`.

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection.dashboard --recorded-ground docs\evidence\inspection-0.0.2\part1\recorded-ground.json
```

That is the device-independent backend path for offline or later hosted use;
the browser does not access USB. This local launch does not publish a website
or provide a remote connection to the laptop's bridge.

## Optional Wolfram computation

The default uses local Python. To attempt the fixed typed local Wolfram adapter:

```powershell
.\.venv\Scripts\python.exe -B -m stratus.inspection.dashboard --computation wolfram
```

Each real call is bounded to 25 seconds. Successful results are independently
checked against Python; matching cached results have their own mode label.
Timeouts use labeled Python fallback. Numerical disagreement blocks candidates.
The fresh normal-host check on November 14 at 14:15 UTC **passed** for all
12 candidates with independent Python agreement, using Wolfram 15.0.1.
The actual what-if also passed through Wolfram and cached Wolfram was observed
after checkpoint reload. Earlier restricted-session timeouts remain historical
evidence; use normal PowerShell for the installed kernel. Typed input/output,
model and mode are saved in `wolfram-final-check.json` under the Part 1 evidence
folder. The launch script saves `fresh-start.json` with its source hashes.
Cloud/Service Credits and Alpha allocations are developer resources, separate
from simulated battery/actions. This app uses no Cloud or Alpha requests.

## Verification and current limits

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_dashboard.py
```

The saved verification passed **142 tests**, including real local HTTP requests
in the test process. All twelve asset/view mappings were checked, including
explicit unavailable states for excluded P06. Preview/refresh preserved the
entire run, and original mission, images, ground records and checkpoints kept
their hashes. JavaScript syntax checking also passed.

**Part 1 is complete: 18/18 actions verified.** The browser walkthrough passed
on the fresh normal-host server at port 8767. All twelve asset/view cases,
mouse/keyboard map selection, review links, fresh/checkpoint loading, all four
ground modes, export and repeated refresh were checked. Reserve 50 / capture
20 returned a Wolfram-backed hold with battery 79.19 and two actions unchanged.
Recorded export matched all six original observations exactly. Synthetic export
as measured data was disabled. The one-page layout was visually reviewed; no
browser console errors were reported. `browser-walkthrough.json` records the
observations and source/checkpoint hashes. A frontend regression also proves
that a late response cannot overwrite a newer asset/view and its provenance.
Verification uses the installed Node.js for that regression; app startup itself
requires only Python plus any explicitly selected optional sensor libraries.
Ground measurements do not establish wind, flight clearance, airborne
conditions or panel defects. Human review and live vision remain pending.
