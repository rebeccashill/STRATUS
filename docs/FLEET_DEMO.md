# STRATUS fleet demo and recorded walkthrough

The verified preview is http://127.0.0.1:8774/fleet. Aircraft and imagery are
simulated/authored replay. The physical BME280/PMSA003I is one separate node.

1. Choose two drones, seed 11. Preview allocation: battery and captures stay
   unchanged. Step through independent assignments and travel/capture events.
   Select each drone to compare its own budget, margin and alternative.
2. Save and reopen. The verified partial two-drone state retained two captures
   and 187.59 EU exactly. Changing a priority/requesting a distinct follow-up
   proposes work; it does not execute it.
3. Choose 50 and confirm New simulation. One map and table contain all 50 records.
   Select D050. Run, pause and save. The recorded paused state had 78 captures,
   4464.60 EU and 12.41289163 logical seconds. A fresh page reopened it exactly.
4. Resume. The nominal run completed 150 captures, all 50 participated, and
   129/200 assets had a usable replay view. Battery remaining was 3632.98 EU;
   1367.02 EU was used. Unclear views and human review remain visible.
5. Demonstrate recovery using the explicitly labeled paused-run replay fork:
   scripts/prepare_fleet_recovery.py prints a new saved checkpoint to open.
   In the recorded demonstration D002 became unavailable with 84.97 EU and one
   capture left. These amounts stayed unchanged; the other 49 completed, for
   149 captures. This is an injected event, not a real lost aircraft.
6. Show one frozen Live ground snapshot and original UTC times. Attaching it
   changed no aircraft budget. The actual PMSA003I zero readings remain valid
   unreviewed measurements, not clean-air certification.
7. Open the report. It embeds illustrations and lists every drone, captured view,
   unresolved work and source/numerical modes. Save/Open never acquires a new
   sensor sample or duplicates a capture.

## Saved browser checkpoints

| File in saved-runs/fleet | Recorded role |
| --- | --- |
| fleet-11ff17177b6544a387f92f2c2869e31b.json | Final nominal 50-drone run, Live ground context, 150 captures |
| fleet-ab9aa6cabea84b07b058e77ed85ae412.json | Two-drone feedback/recovery, four captures, D001 unavailable |
| fleet-a77e4cb4580b44c0b0b8182bc12388ff.json | 50-drone replay/recovery, 149 captures, D002 unavailable |

The initial paused snapshots are preserved separately in the Part 12 evidence
folder. The replay fork keeps its provenance and starts with a new run ID so
the completed nominal checkpoint is not overwritten.

Actual startup Wolfram proof covers two and 50 drones plus reserve boundaries;
the large nominal UI playback used Local Python. One live AI explanation was
retained as raw evidence but its incorrect numeric restatement was set aside in
the UI. Verified numerical summaries remain authoritative.

This document records the observed walkthrough and provides a short demo script;
it is not a claim that a video or real flight demonstration was recorded.
