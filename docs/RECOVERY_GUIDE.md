# Part 6: bounded run and recovery

Start the current app from PowerShell in STRATUS:

```powershell
.\.venv\Scripts\python.exe -B scripts\start_stratus.py
```

Open http://127.0.0.1:8769 and leave that window open. Startup restores the
latest completed browser run when one exists. For the acceptance walkthrough,
load a `part6-partial-*.json` checkpoint: it has two new captures,
75.85786437626905 simulated battery units and one action remaining.
The app uses local Python costs by default,
does not call AI, and does not contact USB until you explicitly select Live.
The two original prior records never count as new captures.

## Finish a bounded run

1. Review **Plan next**, then execute the proposed P02/follow-up. This spends
   the third capture action. Follow-ups use the same three-action budget.
2. The next plan must show a hold with zero capture actions remaining. The
   Execute button remains disabled. A direct fourth request is independently
   rejected by Python; it cannot change battery or findings.
3. Viewing images, refreshing ground data, planning, feedback and what-if
   never add a capture. Retrying an already processed action returns its receipt
   without charging again, including after saving and reopening.
4. Export the report, then load the saved checkpoint. Its action count,
   battery, position, feedback and evidence references must match. Saved live
   measurements appear as **Recorded** history with their original IDs/times;
   they do not become a fresh sensor reading when opened.

The automated acceptance run also explicitly returns to launch after all three
captures. Return spends only modeled return energy and consumes no capture
action. Its final report and checkpoint record the returned state.

## USB loss and recovery

Save/export a working sample before disconnecting USB. Leave the Qwiic sensor
cables connected. Both sensors must become unavailable or stale, with missing
channels shown as dashes, while the app remains usable and mission resources
stay unchanged. A partial failure must affect only the failing sensor.

Select **Recorded measurement** to continue with the last good saved sample.
It retains its acquisition times, source CSV hashes, location and quality.
The recorded path never starts the USB reader. A new actual Live sample alone
can restore Live status; allow the PMSA003I its 30-second settling period.

Leave **Live USB reader** selected when unplugging and replugging USB. STRATUS
automatically retires a failed USB session and tries a fresh connection on a
later five-second live poll. The app stays responsive, atmospheric data returns
first, and the PMSA003I shows warming up until its 30-second settling period
finishes. No app restart is needed for ordinary USB reconnection.

Reads have a 12-second timeout. A blocked or failed USB connection cannot leave
the UI waiting indefinitely or make an old measurement fresh. Selecting Recorded
pauses USB acquisition and retains the last good measurement's original times.
Selecting Live again starts fresh acquisition. This behavior was verified with
actual unplug/replug and fresh readings from both sensors without a server
restart; the physical proof is under `docs/evidence/inspection-0.0.2/hotplug/`.

## Repeat the failure checks

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_resilience.py
```

This runs all Python/frontend tests and saves the three-action/return example,
fourth-capture and duplicate rejections, reserve/no-feasible cases, missing and
corrupt evidence recovery, numerical cache invalidation, timeouts, access/quota
failures, malformed responses, numerical disagreement and hardware integration
mocks. Failed computation/capture never spends a mission action.

Failures are injected into isolated test cases; they do not imply a real API
outage, physical hardware success or live vision inference. Physical unplug
observations are saved separately in
`docs/evidence/inspection-0.0.2/part6/physical-recovery.json`.
`verification.json` lists the actual saved checkpoints/reports and gate state;
the browser gate requires matching current application source hashes.
