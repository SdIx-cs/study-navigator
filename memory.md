# Study Navigator — System Memory & State

## Current Pipeline State
The agent is decoupled into a 4-stage unidirectional pipeline (`study_agent/pipeline/`):
- `extractor.py`: LLM structured extraction with robust regex fallbacks.
- `reducer.py`: Deterministic database writes and state transitions (Zero LLM calls).
- `planner.py`: Policy planning optimizing academic mark per unit of effort.
- `presenter.py`: Formats output for A2UI with clean conversational guidance.

## Progress & Recent Changes
1. **Staged Lecture Progress Completed**:
   - `LECTURE_PROGRESS` events stage changes into `state["pending_progress_update"] = {"module": mod, "delta": delta}` with `slice_stage = "awaiting_confirmation"`.
   - `INTERVENTION_CONFIRMED` executes SQLite mutations via helper `_apply_lecture_progress`, clears pending state, and resets stage to `idle`.
   - `INTERVENTION_REJECTED` safely clears unconfirmed updates without altering ongoing interventions.
   - Planner returns `ActionType.ANSWER_QUERY` asking for user confirmation before applying.
   - Verified with unit tests (`tests/test_pipeline_stages.py` 15/15 passed).
   - Verified with test harness (`multi-word module name -> confirmed write uses full name` PASSED).

2. **Model & API Fixes**:
   - `test_harness.py` loads `study_agent/.env` and maps `GOOGLE_API_KEY` to `GEMINI_API_KEY`.
   - Extractor regexes updated to support multi-word module titles (`COMPUTER NETWORKS`).

3. **Intervention State Management**:
   - Guarded `INTERVENTION_CONFIRMED` so "yes" with nothing pending does not fabricate active sessions.

## Test Harness Status (10 Passed, 6 Gaps / Edge Cases)
- **Passed**:
  - Ambiguous message clarifying question
  - Typed duration change parsing
  - Post-timer 'not completed yet'
  - Completion with active-session context
  - 'review my schedule' after timer
  - 'give me my pending tasks'
  - Active session checkin guard
  - Stale proposal retention on general query
  - 'yes' with nothing pending
  - Multi-word module name confirmed write

- **Open Items / Next Steps**:
  1. Guard `INTERVENTION_REJECTED` when nothing is pending so "no thanks" does not claim an intervention was declined.
  2. Support natural conversational confirmation phrasing in extractor (e.g. "yeah let's go").
  3. Expand duration modification parsing in extractor (e.g. decimal `1.5h` -> 90 minutes, worded `half an hour` -> 30 minutes).
