# Study Navigator — Anomaly Backlog

**Purpose:** Keep a compact, reusable record of observed agent failures so they can be investigated and turned into regression tests later.

**Status:** Observed during exploratory testing; root causes have not yet been verified in code.

## Priority guide

- **P0 — Blocker:** Approval can be bypassed, rejected actions execute, or task/session state is corrupted. Verify before relying on the relevant production capability.
- **P1 — Architecture / evaluation risk:** A foundational behaviour is wrong in a way that could undermine governance, state handling, or future fixes.
- **P2 — Interaction / UX defect:** The agent behaves awkwardly or over-prescriptively, but the issue can likely be deferred if core controls remain sound.
- **P3 — Polish:** Presentation or wording issue with limited downstream impact.

Priorities below are **provisional**. They reflect potential impact, not confirmed root cause. Promote any issue to P0 if testing shows an approval or state-integrity violation.

## A. Intent recognition and conversation routing

### A1. No intent-specific response path
- **Observed:** Questions, progress reports, casual desires, typos, and scheduling requests are routed through the same intervention pipeline.
- **Examples:** “I've caught up on 2 DB lectures”; “I want to play basketball”; “I don't feel like studying.”
- **Expected:** Distinguish at least acknowledgement/update, casual conversation or preference, clarification/diagnosis, study decision request, and explicit scheduling/action request.
- **Priority:** P1
- **Why it matters:** This appears to drive several other anomalies; addressing the routing may fix multiple symptoms.
- **Regression check:** A progress report can be acknowledged and recorded without proposing an intervention; a casual desire can receive a natural response without being forced into scheduling.

### A2. Meta-instruction ignored
- **Observed:** The user explicitly said “just add it to the existing list,” but the simulated agent treated the embedded A2UI card as a new scheduling event and did not acknowledge the append request.
- **Expected:** Follow the user's current instruction about how to handle content; do not mistake quoted/embedded material for a fresh action request.
- **Priority:** P1
- **Regression check:** Ask to append a new anomaly to a list while including card-like content; verify the list is updated and no study intervention is proposed.

### A3. No acknowledgement-only response class
- **Observed:** The agent does not have a reliable “I heard you / noted” path; every input is treated as requiring intervention.
- **Expected:** Allow a concise acknowledgement, factual update, or natural follow-up without a recommendation.
- **Priority:** P1
- **Regression check:** “I've finished two database lectures.” → acknowledge and update the record; no forced pivot.

### A4. Casual desire reframed as a clinical/productivity intervention
- **Observed:** “I want to play basketball” is interpreted as a burnout-management protocol, including fatigue re-evaluation.
- **Expected:** Do not infer fatigue or burnout from the desire alone; acknowledge the desire or ask what help, if any, is wanted.
- **Priority:** P2
- **Regression check:** “I want to play basketball” → natural acknowledgement; no mandatory intervention or fatigue diagnosis.

## B. Decision quality and coaching behaviour

### B1. Binary studying/resting model
- **Observed:** “I don't feel like studying” has effectively one valid output: REST.
- **Expected:** Consider multiple plausible explanations, such as boredom, being stuck, unclear next steps, time-of-day effects, physical tiredness, or wanting a short reset.
- **Priority:** P1
- **Regression check:** On ambiguous reluctance, ask a brief diagnostic question or offer proportionate options rather than immediately prescribing a long break.

### B2. Zero diagnostic questions before prescribing
- **Observed:** The agent prescribes a 60-minute intervention before understanding the cause, then labels the feeling “a clear signal of fatigue or cognitive saturation.”
- **Expected:** Separate observed facts from hypotheses; ask a targeted question when the cause would materially change the recommendation.
- **Priority:** P1
- **Regression check:** “I don't feel like studying” → no diagnosis stated as fact without evidence; asks a useful, concise question where needed.

### B3. Mandatory break / controlling tone
- **Observed:** Scope says “Take a mandatory 60-minute break.”
- **Expected:** Present rest as a recommendation or option, not an order, except where an immediate safety concern justifies firm language.
- **Priority:** P2
- **Regression check:** Normal reluctance or a mid-session dip does not trigger an authoritative “mandatory” order.

### B4. No middle path / intervention granularity is all-or-nothing
- **Observed:** Options are full REST or waiting 60 minutes before attempting a small task; there is no small reset or low-friction restart option.
- **Expected:** Support proportionate alternatives, such as a 5-minute reset or opening the document and reading one paragraph, when appropriate.
- **Priority:** P2
- **Regression check:** For a mild dip, offer a small reversible option rather than only a full break or a long work block.

### B5. Performance-review tone
- **Observed:** Wording such as “Continuing under these conditions typically leads to diminishing returns and increased friction” sounds managerial and overconfident for a normal mid-session dip.
- **Expected:** Use supportive, non-clinical, non-commanding language and calibrate certainty to the evidence.
- **Priority:** P2
- **Regression check:** The response describes options plainly without presenting an unsupported diagnosis or performance verdict.

### B6. Military-briefing tone for leisure
- **Observed:** Basketball micro-steps read like an operations order: set a timer, engage in the activity as planned, re-evaluate upon return.
- **Expected:** Respond naturally to leisure; provide a structured plan only if requested.
- **Priority:** P2
- **Regression check:** Casual leisure statements do not produce tactical micro-step plans by default.

### B7. No “enjoy it” path; leisure treated as a sanctioned detour
- **Observed:** The agent only asks whether to set a reminder to return to coursework, implying basketball matters only as a productivity break.
- **Expected:** Allow a positive acknowledgement of leisure without making a return-to-work reminder the default.
- **Priority:** P2
- **Regression check:** “I want to play basketball” can end with a simple acknowledgement, without a reminder prompt.

### B8. `SHRINK` applied to a REST card
- **Observed:** “Shrink to 30m” appears on a REST card, making a break look like a productivity unit with an efficiency target.
- **Expected:** Only show controls that make semantic sense for the current intervention type; REST should not inherit study-block controls by default.
- **Priority:** P1
- **Regression check:** REST cards expose rest-appropriate choices, not study-scope or task-duration controls unless explicitly designed and justified.

## C. State integrity and lifecycle

### C1. Completing a session immediately creates a CONTINUE proposal
- **Observed:** User clicks “completed”; the session moves from Paused straight to a new CONTINUE proposal for the same task.
- **Expected:** Completion updates the current session/task state, then gives the user space to choose what happens next.
- **Priority:** P1
- **Regression check:** Marking a block complete does not automatically start another block or proposal.

### C2. Presumptuous auto-continuation after “done”
- **Observed:** The agent generates a follow-up proposal immediately after the user says “done,” without first asking whether they want to continue, rest, or switch.
- **Expected:** Treat completion as a state update, not implicit consent to continue; ask or acknowledge before proposing the next action.
- **Priority:** P1
- **Regression check:** “Done” does not imply “start another session.”

### C3. Invented task transition (`SWITCH`)
- **Observed:** User reports catching up on two DB lectures; agent invents a switch to DB to justify the `SWITCH` action, then steers back to AI CW1.
- **Expected:** Record what the user actually reported; do not manufacture a transition that was never requested or performed.
- **Priority:** P1
- **Regression check:** A DB progress report updates DB progress and does not create a task-switch event.

### C4. Progress record and user-facing UI not updated correctly
- **Observed:** After “I've caught up on 2 DB lectures,” the agent fails to register the update in its record/UI and instead pivots to AI CW1.
- **Expected:** Update the relevant progress record when supported by the input, reflect it in the UI where applicable, and distinguish a report from a request for a new plan.
- **Priority:** P1
- **Regression check:** After a progress report, verify both persisted/session state and visible UI reflect the reported change without an invented action.

### C5. Stage fast-forward / unsupported progress assumptions
- **Observed:** Micro-steps advance to “finalize the core implementation” and “perform a quick unit test,” although the prior known stage was only “outlining the implementation plan.” No card confirmed intermediate progress.
- **Expected:** Advance task stage only from explicit user updates or verified events; do not infer completed steps from elapsed turns.
- **Priority:** P1
- **Regression check:** Without a progress update, a new proposal preserves the last confirmed stage.

### C6. Missing lifecycle distinction between completion and next-task selection
- **Observed:** Completion, decision-making, and starting the next block appear coupled.
- **Expected:** Keep “block completed,” “user chooses next action,” “proposal created,” and “proposal accepted/applied” as distinct lifecycle events.
- **Priority:** P1
- **Regression check:** Inspect state transitions and verify each event changes only its intended state.

## D. Structured output and UI/card integrity

### D1. Contradictory duration fields
- **Observed:** Proposal scope says “90-minute focused session,” while “Confirmed Duration” says “60 minutes.”
- **Expected:** One authoritative duration value feeds all displayed duration fields.
- **Priority:** P1
- **Regression check:** Compare scope, duration, micro-steps, and action payload; they agree.

### D2. Confirmed Duration field contains the whole scope
- **Observed:** A field intended to contain a simple value such as “60 min” instead contains the scope paragraph and all three micro-steps.
- **Expected:** Enforce the schema and map each value to the correct UI field.
- **Priority:** P1
- **Regression check:** Assert duration field is a short duration value; scope and micro-steps render separately.

### D3. New verbose memo fields appear before the A2UI card
- **Observed:** “Current Reality,” “Wider Workload & Rationale,” and “Trade-offs Considered” are rendered as prose before the card, making the reply feel like a decision-support report.
- **Expected:** Keep internal reasoning/context separate from concise user-facing explanation; show extra detail only when useful or requested.
- **Priority:** P2
- **Regression check:** The default response contains a concise rationale and the intended card, not a long preamble.

### D4. Schema/control reuse causes semantic mismatch
- **Observed:** Controls designed for study blocks appear on REST cards, and action meanings have expanded beyond their original scope.
- **Expected:** Define allowed fields and controls by intervention type; reject or omit invalid combinations.
- **Priority:** P1
- **Regression check:** Validate each intervention type against its own schema and allowed controls.

## E. Intervention semantics

### E1. `SWITCH` meaning silently expands
- **Observed:** Previously meaning switch study subjects, `SWITCH` now also means switching to writing an essay as the coursework task.
- **Expected:** Give each intervention a stable, explicit meaning; distinguish switching tasks from changing the method or subtask within the same coursework.
- **Priority:** P1
- **Regression check:** Each intervention maps to one defined action class, with no ambiguous reuse across task-level and activity-level changes.

### E2. Free-form requests are captured as 60-minute interventions
- **Observed:** Some free-form requests are immediately converted into a study-scheduling intervention with a 60-minute duration.
- **Expected:** Only enter scheduling when the user asks for it or context clearly warrants it; do not apply a default duration to unrelated requests.
- **Priority:** P1
- **Regression check:** A general question or unrelated request receives an appropriate response and creates no intervention unless requested.

## F. Cross-cutting regression checks

These tests cover several anomaly clusters at once and should be retained as a compact smoke-test set.

1. **Progress report:** “I've caught up on two DB lectures.” Verify acknowledgement, correct progress update, no invented `SWITCH`, and no forced AI CW1 pivot.
2. **Leisure statement:** “I want to play basketball.” Verify natural acknowledgement, no clinical fatigue diagnosis, no mandatory break, no military-style micro-steps, and no default reminder.
3. **Ambiguous reluctance:** “I don't feel like studying.” Verify no automatic diagnosis or mandatory 60-minute REST; ask a useful question or offer proportionate options.
4. **Completion:** Mark a session complete. Verify state updates once and no next proposal is generated without user choice.
5. **Duration/schema consistency:** Use a proposal with a known duration. Verify the duration field, scope, micro-steps, and action payload are consistent and correctly separated.
6. **Intervention semantics:** Verify `SWITCH`, `SHRINK`, and `REST` expose only their intended meanings and valid controls.
7. **Instruction-following:** “Just add this to the existing anomaly list.” Verify append-only behaviour rather than treating embedded content as a new scheduling request.
8. **Approval integrity:** Reject or modify a proposal. Verify no rejected action executes and any applied action exactly matches the approved version.

## Suggested remediation order

1. **Protect state and approval integrity:** C1–C6 and the approval smoke test.
2. **Fix intent routing and intervention semantics:** A1–A4, E1–E2, B1–B2.
3. **Fix schema/UI contracts:** D1–D4 and B8.
4. **Improve conversational tone and proportionality:** B3–B7 and D3.
5. **Keep the smoke tests in the evaluation suite:** rerun them after governance, optimisation, or UI changes.

## Notes for future investigation

- This backlog records observed symptoms, not confirmed root causes.
- Multiple entries may share one underlying cause; avoid implementing a separate fix for every bullet without inspecting the architecture.
- When investigating an item, record: **reproduction input → actual result → expected result → root cause (confirmed/hypothesis) → fix → regression test**.
- Do not treat successful deployment, tracing, or approval UI as proof that recommendation quality is good.
