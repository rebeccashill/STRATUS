# STRATUS judging demo

## Start

Follow [the README](../README.md) to create the Python environment, then run:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part12.py --port 8774 --local
```

Open http://127.0.0.1:8774/fleet. The launcher uses recorded ground data and
Local Python, so the walkthrough needs no API key, hardware or Wolfram.
Use the running server if it is already available.

## Fleet overview

1. Start with two drones and seed 11. Preview allocation and inspect each
   drone's battery, protected return reserve and three-picture allowance.
   Previewing spends no aircraft resources.
2. Use Step one event or explicitly Run. The map, inspection evidence and
   per-drone table update together. Save and reopen to demonstrate preserved
   progress; reopening pauses playback.
3. To demonstrate scale, choose 50 drones and explicitly confirm a new
   simulation. Run the nominal seed-11 case without a reported obstacle.
   The recorded reference result is 150 captures, all 50 drones participating,
   129 usable assets of 200 and 71 still needing usable evidence.

## Reported crane scenario

1. Begin a new paused fleet and open http://127.0.0.1:8774/hazards.
   Both desks refer to the same authoritative fleet run.
2. Choose Prepare selected action, then Report example crane. The dashboard
   assesses every drone and marks paths affected by the reported exclusion.
3. Choose Try prepared simulation. The old assignment is rejected because
   its hazard revision is stale, without charging battery or recording a capture.
4. Choose Replan clear work. Eligible inspections are reassigned; work requiring
   operator review stays held. Completed work and prior costs remain recorded.
5. Save or create a fleet report. Review the decisions, independent budgets,
   evidence, reported areas and unfinished work.

The crane case and nominal case are separate runs. Do not present the nominal
150-capture result as the outcome after reporting the crane. A reported exclusion
can reduce the amount of eligible work.

## Ground context and fallback

Show the separate ground panel and the readings' original collection times.
The BME280 provides temperature, humidity and pressure; the PMSA003I provides
particle measurements. Recorded mode retains the original timestamps.
Changing or attaching ground context does not spend aircraft resources.

The station does not detect the crane or measure conditions at every drone.
An operator reports obstacles. Use Recorded or Unavailable if hardware is absent;
see [the hardware guide](HARDWARE_HANDOFF.md) for the optional physical setup.
Keep playback paused while reviewing hazard reports.

## What the demo establishes

This is a local software prototype with simulated aircraft movement, toy energy
units and authored replay illustrations. It demonstrates shared task ownership,
resource guards, updated hazard checks and preserved decision records.
It does not establish real flight clearance, collision avoidance or image-based
fault diagnosis. OpenAI explanations are optional and never authorize execution;
Wolfram is an optional independent cost calculation path.

For additional controls, use [the fleet guide](FLEET_GUIDE.md) or
[the single-drone operator guide](OPERATOR_GUIDE.md). Dated release observations
are retained in [the verified demonstration](FINAL_FREEZE.md).
