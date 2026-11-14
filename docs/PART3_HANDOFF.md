# Part 3: local action checks, bounded AI tools, and explicit fallback

Source: [STRATUS 0.0.1, Part 3 (S021-S031)](https://app.notion.com/p/4185b396b48e81c3b6e9c07502d50958).
Workspace: `C:\Users\shill\OneDrive\Desktop\STRATUS`.
Only new code authored in this standalone workspace was added.

**Part 3 is complete: 11/11 actions verified, including the live gate.**
Rebecca ran `python -B scripts\verify_part3.py --live` in normal PowerShell
at 10:38pm America/New_York on November 13, 2026. All 54 behavior tests passed.
The saved actual OpenAI exchange completed `get_mission_context` and
`propose_next_action` using gpt-5-mini (returned gpt-5-mini-2025-08-07).
The P02/follow-up proposal passed independent Python constraints; it was not
executed and did not change mission state. `live_ai_failure` is null.

Earlier HTTP 429 and restricted-session DNS error 11001 are historical.
Use normal PowerShell for live checks while the agent's restricted command
environment cannot resolve external hosts. The successful API interaction
does not establish a particular remaining credit balance or live vision access.
Provider mocks validate the adapter contract only.

| Actions | Implementation and verification |
| --- | --- |
| S021 | `actions.py`: strict inspect/follow_up/return/stop proposals with known asset/view, reason and alternative; extra fields, unknown actions, malformed/duplicate-key JSON rejected. |
| S022-S023 | `engine.py`: local Euclidean costs in metres and simulated energy units, using current position. Protect outbound + capture + return + reserve. Toy margins 50/0/-1 at available 100/50/49 produce allow/allow/reject. |
| S024-S025 | Prior and executed views are completed; duplicates, exhausted actions, exclusions and invalid state reject. Follow-up is a distinct paid action. Listing/evaluating/rejecting never changes state. |
| S026 | `agent.py`: actual two-request OpenAI Responses tool exchange completed. Loaded mission context, proposed P02/follow-up due to its unclear prior overview, and offered P04/overview as an alternative. Python allowed the proposal with no state mutation. Actual tool events and provider response IDs are saved in `ai-live-check.json`. |
| S027-S028 | Only allowlisted data tools are exposed; inputs and annotations stay task data. HTTP/auth/rate-limit/timeout/malformed/unknown tool/invalid proposal failures preserve state and surface a labeled fallback. Keys and raw provider error bodies are not logged. |
| S029 | CLI and JSON label deterministic_rule_based versus live_ai and authored replay versus live vision. The fallback uses observed history, priority and local costs; no unseen-image annotation oracle. |
| S030 | Sensors skipped; decision recorded separately after the scheduled cutoff. No on-time decision, hardware check, electrical compatibility, or measured reading is claimed. Ground context has no aircraft-state effect. |
| S031 | `verification.json`: gate passed, 11/11 actions verified, 54 tests passed, `live_ai_verified=true`, `live_ai_failure=null`. Inputs/images unchanged and no saved inspection run created. Part 4 is next. |

## Commands

```powershell
python -B -S -m stratus.inspection --agent fallback
python -B -S -m stratus.inspection --agent fallback --execute
python -B -S -m stratus.inspection --candidates
python -B scripts\verify_part3.py
```

Each CLI call begins a fresh in-memory state. `--capture` is an evidence preview;
it never executes an action. `--agent` proposes without execution unless
`--execute` is supplied. When a live request fails, that command executes no
action; explicitly select fallback to continue. No saved-run resume or Part 4
first-inspection completion is claimed.

Live use reads `OPENAI_API_KEY` or `STRATUS_AI_API_KEY` from the process
environment or ignored local `.env`. Keep keys out of chat, logs, screenshots,
mission files, and source control. The provider defaults to OpenAI and model
to gpt-5-mini; both are visible in successful live results. Live verification
has passed from normal PowerShell. To reproduce, use a shell that can resolve
and reach `api.openai.com` and run:

```powershell
python -B scripts\verify_part3.py --live
```

The verifier exits 4 when the live gate is blocked, despite passed local tests.
It saves actual fallback, rejection, reserve-boundary, in-memory execution,
provider-attempt, and test observations under
`docs/evidence/inspection-0.0.1/part3/`. Mocked provider unit tests never satisfy
the live gate. Verification logs are separate from `saved-runs/`.

## State and next integration

`initial_state(mission)` creates a frozen `RunState`, retaining two prior records
without spending new actions. `evaluate(mission, state, proposal)` and
`list_candidates(...)` are read-only. `execute_action(...)` revalidates against
the supplied current state and returns `(new_state, event)`. Rejections return
the original state. Callers must retain the returned state for subsequent
actions; reusing an old immutable snapshot is a separate branch, not a resume.

Capture debits outbound + capture once, updates position, consumes one action,
and adds one evidence record. Return energy and reserve are protected at capture,
not charged then. Return later debits only return travel once and closes the run.
Closed runs reject further execution. The adapter rechecks evidence before
committing; missing/changed evidence cannot spend battery or mark coverage.

Part 4 can reuse these pure checks and immutable transitions for the numerical
adapter, first saved inspection and reopen. No Wolfram setup or integration was
performed in Part 3. Human review, live vision, reports, and saved-run persistence
remain separate pending work.

API implementation references checked during this part:

- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://developers.openai.com/api/docs/models/gpt-5-mini
