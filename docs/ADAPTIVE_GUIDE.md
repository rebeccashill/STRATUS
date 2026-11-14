# STRATUS Part 2: plan, review and report

Open a **new PowerShell window** in the STRATUS folder. Start the current app:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part2.py
```

Wait for `STRATUS Part 2 ready: http://127.0.0.1:8768`, then open that address.
Keep the window open. The earlier Part 1 server can stay open in its own window;
Part 2 uses a different port and loads the new Python routes. Stop with Ctrl+C.

Startup makes one bounded Wolfram calculation and at most two bounded OpenAI
requests to provide a proposal with ground context. It saves the actual mode,
result or disclosed fallback under `docs/evidence/inspection-0.0.2/part2/`.
It **does not execute a capture**. Services remain optional:

```powershell
.\.venv\Scripts\python.exe -B scripts\finish_part2.py --computation local --ai fallback
```

The default still uses earlier actual **Recorded** ground measurements. The
bridge was undetected at the Part 2 handoff. Part 6 later verified actual live
readings, USB loss and recovery; see RECOVERY_GUIDE.md. Ground source,
image assessment and numerical/AI modes have independent labels.

## Work through an inspection

1. The saved Friday run starts with a tentative P03 concern, battery 79.19
   simulated units and two capture actions left. A review hold prevents another
   capture until the operator handles the concern.
2. In the P03 review entry, **Accept for review** acknowledges the tentative
   concern for human follow-up. It remains tentative. **Resolve review** closes
   that operator task. Neither button charges battery/actions or changes the
   image finding. Feedback is saved and the next proposal is recomputed.
3. **Plan next** applies the priority/observed-uncertainty/cost rule. **AI
   proposal** uses the bounded configured OpenAI tool adapter; failed or
   ineligible AI proposals use an explicit local fallback. All proposals must
   pass the same Python checks and review eligibility.
4. To choose a particular view, select an asset and Overview/Follow-up, then
   click **Plan this view**. Inspect the selected and alternative costs, reason,
   remaining actions and linked ground snapshot.
5. **Execute … (simulated)** is the separate action that can spend modeled
   energy and one capture. It recomputes/validates the current numerical inputs,
   exclusions, evidence identity, duplicate views, action count and reserve
   before committing. After a capture or checkpoint load, explicitly review a
   new plan before Execute is enabled again. A stale proposal must be replanned. Repeated execution of
   the same proposal cannot debit again, including after save/reopen.
6. **Request another view** records an operator request for a distinct mapped
   view. The next proposal prioritizes it only if it still passes all resource
   and identity checks. After capture, the old request becomes “follow-up
   captured, review pending.” No third undeclared view is invented.
7. **Save run** writes the current checkpoint. Feedback, frozen ground
   references, plans, numerical records and request receipts are saved together.
   The original Friday checkpoints are preserved. Use Saved checkpoint → Load
   to reopen the new `adaptive-…json` run.

The review status shown beside the viewer is separate from image quality and
finding. Resolving an unclear image's review task never makes it clear or
turns an unknown finding into “no defect.” Live vision remains pending; the
current images and assessments are authored synthetic replay.

## Reproduce the unclear-image example

Use **Fresh mission** → **Load** to start with three actions. This creates a
separate run; it does not overwrite Friday's run.

1. Select P05 / Overview → **Plan this view** → **Execute P05/overview**.
   The simulated result is unclear and its finding stays unknown. Two actions
   remain.
2. In that review entry, click **Request another view**. The proposed view must
   be **P05 / Follow-up**, with another eligible asset shown for comparison.
3. Click **Execute P05/follow-up**. It spends a second action and yields the
   distinct clear replay fixture; one action remains. The original unclear
   overview stays unknown in the history and report.
4. Use **Resolve review** to close an operator task and watch the plan/status
   update. This is feedback on work status, not model training or diagnosis.
5. Set reserve to **50** and capture cost to **20**; click **Preview budget**.
   In this example no capture fits. The preview explains the changed feasible
   set and leaves battery/actions/evidence unchanged. Reset changes only the
   preview controls. Preview parameters cannot be applied to the active mission.

## Export the report

Click **Export report**. The app saves the run, saves an HTML report and its
technical JSON companion under `saved-runs/reports/`, then downloads the HTML.
The “View report” link opens the saved report in the browser.

The HTML embeds the images, so they remain visible when the file is shared or
opened without the server. It includes asset/view provenance, separate quality
and findings, feedback, actual simulated actions/rejections and budgets,
numerical source/model/comparison, unresolved human follow-up, and read-only
what-if comparisons. Its Ground conditions section includes the exact decision
snapshot IDs, source labels, sensor IDs, values/units, original acquisition and
receipt times, real/unknown location, freshness and raw CSV/hash references.
Driver and account diagnostics stay in technical evidence.

The agent's allowlisted context tool, each linked action and the report use the
same frozen snapshot ID. New live polls cannot silently change that historical
context. Ground measurements cannot change aircraft costs, exclusions, capture
count or image findings, and do not establish wind, flight clearance, airborne
conditions or panel damage.

## Verify the saved example

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_adaptive.py
```

This runs the 162-test Python behavior suite and four Node.js frontend regressions,
then saves a simulated unclear/follow-up example, feedback-only replanning,
context linkage, what-if, a resumable checkpoint and the report. The browser
gate passes only when its saved walkthrough matches the current source hashes.
Injected API tests are labeled separately from actual live startup evidence.
