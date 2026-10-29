"""Unit tests for the 4-Stage Study Navigator Pipeline.

Verifies that each stage is independently callable and testable:
1. Event Extractor -> AcademicEvent
2. State Reducer   -> Deterministic SQLite & State update (Zero LLM)
3. Policy/Planner  -> PlanDecision (Academic Mark Maximization)
4. Presenter       -> PresenterOutput (A2UI & clean text)
"""

import unittest

from study_agent.db import (
    clear_history,
    get_all_module_progress,
    get_completed_deliverables,
    get_preferences,
    init_db,
    update_module_lectures,
)
from study_agent.pipeline.extractor import EventExtractor, extract_event
from study_agent.pipeline.orchestrator import PipelineOrchestrator, process_study_message
from study_agent.pipeline.planner import PolicyPlanner, plan_decision
from study_agent.pipeline.presenter import Presenter, format_presentation
from study_agent.pipeline.reducer import reduce
from study_agent.pipeline.schema import (
    AcademicEvent,
    ActionType,
    EventType,
    InterventionProposal,
    PlanDecision,
    PresenterOutput,
)


class TestPipelineStages(unittest.TestCase):
    def setUp(self):
        clear_history()
        init_db()
        from study_agent.pipeline.tracer import TRACES_DIR
        for p in TRACES_DIR.glob("test_*.json"):
            try:
                p.unlink()
            except Exception:
                pass

    # --- Stage 1: Event Extractor Tests ---
    def test_stage_1_event_extractor_lecture_progress(self):
        msg = "I've caught up on 2 DB lectures"
        event = extract_event(msg)
        self.assertEqual(event.type, EventType.LECTURE_PROGRESS)
        self.assertEqual(event.module, "DB")
        self.assertEqual(event.delta, 2)

    def test_stage_1_event_extractor_coursework_completed(self):
        msg = "I have completed my scheduled study block for AI Coursework 1"
        event = extract_event(msg)
        self.assertEqual(event.type, EventType.COURSEWORK_COMPLETED)
        self.assertEqual(event.module, "AI")
        self.assertEqual(event.item, "cw1")

    def test_stage_1_event_extractor_preferences(self):
        msg = "Please call me John from now on"
        event = extract_event(msg)
        self.assertEqual(event.type, EventType.PREFERENCE_UPDATED)
        self.assertEqual(event.key, "preferred_name")
        self.assertEqual(event.value, "John")

    def test_stage_1_event_extractor_casual_leisure(self):
        msg = "I want to play basketball"
        event = extract_event(msg)
        self.assertEqual(event.type, EventType.CASUAL_CONVERSATION)

    def test_stage_1_event_extractor_revert(self):
        msg = "Please revert the applied intervention"
        event = extract_event(msg)
        self.assertEqual(event.type, EventType.INTERVENTION_REVERTED)

    # --- Stage 2: State Reducer Tests (Deterministic, Zero LLM) ---
    def test_stage_2_state_reducer_stages_and_confirms_lecture_progress(self):
        event = AcademicEvent(
            type=EventType.LECTURE_PROGRESS,
            module="DB",
            delta=3,
        )
        initial_state = {"slice_stage": "idle"}
        staged_state, mutations = reduce(initial_state, event, user_id="test_student")

        # Verify it is staged and not yet written to DB
        self.assertEqual(staged_state.get("pending_progress_update"), {"module": "DB", "delta": 3})
        self.assertEqual(staged_state.get("slice_stage"), "awaiting_confirmation")
        self.assertEqual(len(mutations), 0)
        progress = get_all_module_progress("test_student")
        self.assertNotIn("DB", progress)

        # Confirm the progress update
        confirm_event = AcademicEvent(type=EventType.INTERVENTION_CONFIRMED)
        final_state, confirm_mutations = reduce(staged_state, confirm_event, user_id="test_student")
        progress_after = get_all_module_progress("test_student")
        # 3 baseline from study_context + 3 delta = 6
        self.assertEqual(progress_after.get("DB"), 6)
        self.assertTrue(any("Recorded progress: DB" in m for m in confirm_mutations))
        self.assertEqual(final_state.get("slice_stage"), "idle")

    def test_stage_2_state_reducer_rejects_pending_lecture_progress(self):
        staged_state = {
            "slice_stage": "awaiting_confirmation",
            "pending_progress_update": {"module": "DB", "delta": 3},
        }
        reject_event = AcademicEvent(type=EventType.INTERVENTION_REJECTED)
        final_state, mutations = reduce(staged_state, reject_event, user_id="test_student")
        self.assertIsNone(final_state.get("pending_progress_update"))
        self.assertEqual(final_state.get("slice_stage"), "idle")
        progress = get_all_module_progress("test_student")
        self.assertNotIn("DB", progress)
        self.assertTrue(any("Discarded" in m for m in mutations))

    def test_stage_2_state_reducer_applies_coursework_completed_to_db(self):
        event = AcademicEvent(
            type=EventType.COURSEWORK_COMPLETED,
            module="AI",
            item="cw1",
            notes="Session completed",
        )
        initial_state = {
            "slice_stage": "confirmed",
            "active_intervention": {"intervention": "SWITCH", "target": "AI cw1"},
        }
        new_state, mutations = reduce(initial_state, event, user_id="test_student")

        # Verify SQLite DB has completed deliverable recorded
        completed = get_completed_deliverables("test_student")
        self.assertTrue(any(c["module"] == "AI" and c["deliverable"] == "cw1" for c in completed))
        # Verify active intervention was closed
        self.assertIsNone(new_state["active_intervention"])
        self.assertEqual(new_state["slice_stage"], "idle")

    def test_stage_2_state_reducer_applies_preference_to_db(self):
        event = AcademicEvent(
            type=EventType.PREFERENCE_UPDATED,
            key="preferred_name",
            value="Elena",
        )
        _, _ = reduce({}, event, user_id="test_student")
        prefs = get_preferences("test_student")
        self.assertEqual(prefs.get("preferred_name"), "Elena")

    # --- Stage 3: Policy / Planner Tests ---
    def test_stage_3_policy_planner_handles_lecture_progress(self):
        event = AcademicEvent(
            type=EventType.LECTURE_PROGRESS,
            module="DB",
            delta=2,
        )
        decision = plan_decision({}, event, user_id="test_student")
        self.assertEqual(decision.action_type, ActionType.ANSWER_QUERY)
        self.assertIn("logging 2 lecture(s) for DB as completed. Confirm?", decision.guidance_message)

    def test_stage_3_policy_planner_handles_coursework_completion(self):
        # When coursework is completed, it should acknowledge and direct focus to next priorities
        event = AcademicEvent(
            type=EventType.COURSEWORK_COMPLETED,
            module="AI",
            item="cw1",
        )
        decision = plan_decision({}, event, user_id="test_student")
        self.assertEqual(decision.action_type, ActionType.ACKNOWLEDGE_COMPLETION)
        self.assertIn("Successfully recorded completion of AI CW1", decision.guidance_message)

    def test_stage_3_policy_planner_diagnoses_reluctance(self):
        # Fixes B1 & B2: Ambiguous reluctance triggers diagnostic question, not mandatory 60m REST
        event = AcademicEvent(
            type=EventType.CHECKIN_REQUESTED,
            raw_text="I don't feel like studying",
        )
        decision = plan_decision({}, event, user_id="test_student")
        self.assertEqual(decision.action_type, ActionType.ASK_DIAGNOSTIC)
        self.assertIsNotNone(decision.diagnostic_question)
        self.assertIn("Reluctance usually stems from one of three causes", decision.diagnostic_question)

    def test_stage_3_policy_planner_maximises_academic_mark_for_checkin(self):
        # Unsubmitted AI cw1 has 30% marks at risk -> Policy must propose SWITCH/SHRINK to AI cw1
        event = AcademicEvent(
            type=EventType.CHECKIN_REQUESTED,
            raw_text="What's best to do now?",
        )
        decision = plan_decision({}, event, user_id="test_student")
        self.assertEqual(decision.action_type, ActionType.PROPOSE_INTERVENTION)
        self.assertIsNotNone(decision.proposal)
        self.assertEqual(decision.proposal.intervention, "SWITCH")
        self.assertEqual(decision.proposal.target, "AI Coursework 1")
        self.assertIn("30%", decision.proposal.rationale)

    # --- Stage 4: Presenter Tests ---
    def test_stage_4_presenter_formats_clean_a2ui_card(self):
        proposal = InterventionProposal(
            intervention="SWITCH",
            target="AI Coursework 1",
            duration="60 minutes",
            scope="Complete assignment task 1",
            micro_steps=["Write test harness", "Implement function"],
            rationale="Protects 30% module marks.",
        )
        decision = PlanDecision(
            action_type=ActionType.PROPOSE_INTERVENTION,
            event=AcademicEvent(type=EventType.CHECKIN_REQUESTED),
            proposal=proposal,
        )
        output = format_presentation(decision, state={})

        self.assertEqual(output.slice_stage, "awaiting_confirmation")
        self.assertEqual(output.pending_proposal, "SWITCH")
        self.assertIsNotNone(output.a2ui_card)
        self.assertEqual(output.a2ui_card["intervention"], "SWITCH")
        # Ensure NO verbose internal memo preambles in text
        self.assertNotIn("Current Reality", output.text)
        self.assertNotIn("Wider Workload & Rationale", output.text)
        self.assertNotIn("Trade-offs Considered", output.text)
        self.assertIn("### Proposed Intervention: SWITCH", output.text)

    # --- End-to-End Orchestrator Integration Test & Trace Logger ---
    def test_end_to_end_orchestrator_pipeline(self):
        from study_agent.pipeline.tracer import TraceLogger
        session_id = "test_trace_session_99"
        orchestrator = PipelineOrchestrator()

        # Turn 1: User reports DB progress -> Staged awaiting confirmation
        out1, state1, mut1 = orchestrator.process(
            "I've caught up on 2 DB lectures", user_id="student_e2e", session_id=session_id
        )
        self.assertIn("logging 2 lecture(s) for DB as completed", out1.text)
        self.assertEqual(state1.get("pending_progress_update"), {"module": "DB", "delta": 2})
        self.assertIsNotNone(out1.trace)
        self.assertEqual(out1.trace["turn_index"], 1)

        # Turn 1b: User confirms -> Writes to DB (3 baseline + 2 = 5)
        out1b, state1b, mut1b = orchestrator.process(
            "yes", current_state=state1, user_id="student_e2e", session_id=session_id
        )
        self.assertEqual(get_all_module_progress("student_e2e")["DB"], 5)
        self.assertEqual(out1b.trace["turn_index"], 2)

        # Turn 2: User completes AI coursework 1
        out2, state2, mut2 = orchestrator.process(
            "I have completed my scheduled study block for AI Coursework 1",
            current_state=state1b,
            user_id="student_e2e",
            session_id=session_id,
        )
        self.assertIn("Successfully recorded completion of AI CW1", out2.text)
        self.assertEqual(len(get_completed_deliverables("student_e2e")), 1)
        self.assertIsNotNone(out2.trace)
        self.assertEqual(out2.trace["turn_index"], 3)

        # Verify trace file dumped as JSON per session
        tracer = TraceLogger()
        dumped = tracer.load_trace(session_id)
        self.assertEqual(dumped["session_id"], session_id)
        self.assertEqual(dumped["user_id"], "student_e2e")
        self.assertEqual(len(dumped["turns"]), 3)

        turn1 = dumped["turns"][0]
        self.assertIn("raw_input", turn1)
        self.assertIn("extracted_event", turn1)
        self.assertIn("state_diff_applied", turn1)
        self.assertIn("planner_decision", turn1)
        self.assertIn("final_output", turn1)


if __name__ == "__main__":
    unittest.main()
