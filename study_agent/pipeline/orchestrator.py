"""End-to-End Orchestrator for the 4-Stage Pipeline.

Coordinates:
(1) Event Extractor -> AcademicEvent
(2) State Reducer   -> Deterministic Memory & DB Updates
(3) Policy/Planner  -> PlanDecision (Academic Mark & Understanding Maximization)
(4) Presenter       -> PresenterOutput (A2UI & Markdown)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from study_agent.pipeline.extractor import EventExtractor
from study_agent.pipeline.planner import PolicyPlanner
from study_agent.pipeline.presenter import Presenter
from study_agent.pipeline.reducer import reduce
from study_agent.pipeline.schema import AcademicEvent, PlanDecision, PresenterOutput
from study_agent.pipeline.tracer import log_turn_trace

log = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Coordinates the 4-stage processing pipeline."""

    def __init__(self, use_llm_fallback: bool = True):
        self.extractor = EventExtractor(use_llm_fallback=use_llm_fallback)
        self.planner = PolicyPlanner()
        self.presenter = Presenter()

    def process(
        self,
        message: str,
        current_state: Optional[Dict[str, Any]] = None,
        user_id: str = "default_user",
        session_id: str = "default_session",
    ) -> Tuple[PresenterOutput, Dict[str, Any], List[str]]:
        """Executes all 4 stages in strict sequence.

        Returns:
            Tuple of (PresenterOutput, final_state_dict, applied_mutations_list)
        """
        state = current_state or {}
        state_before = dict(state)

        # Stage 1: Event Extractor (Turns raw message into structured event and NOTHING else)
        event: AcademicEvent = self.extractor.extract(message, context=state)

        # Stage 2: State Reducer (Real code owns writing to SQLite memory bank)
        reduced_state, mutations = reduce(state, event, user_id=user_id, session_id=session_id)

        # Stage 3: Policy / Planner (Decides next action based on ground-truth state & metrics)
        decision: PlanDecision = self.planner.plan(reduced_state, event, user_id=user_id)

        # Stage 4: Presenter (Formats output for chat and A2UI)
        output: PresenterOutput = self.presenter.present(decision, state=reduced_state)

        # Final state sync
        final_state = dict(reduced_state)
        final_state["slice_stage"] = output.slice_stage
        final_state["pending_proposal"] = output.pending_proposal
        final_state["proposal_details"] = output.proposal_details
        if output.active_intervention:
            final_state["active_intervention"] = output.active_intervention

        # Turn Trace Logging (Dumped as JSON per session)
        turn_trace = log_turn_trace(
            session_id=session_id,
            user_id=user_id,
            raw_input=message,
            extracted_event=event,
            state_before=state_before,
            state_after=final_state,
            mutations=mutations,
            planner_decision=decision,
            final_output=output,
        )
        output.trace = turn_trace

        return output, final_state, mutations


_default_orchestrator = PipelineOrchestrator()


def process_study_message(
    message: str,
    current_state: Optional[Dict[str, Any]] = None,
    user_id: str = "default_user",
    session_id: str = "default_session",
) -> Tuple[PresenterOutput, Dict[str, Any], List[str]]:
    """Convenience entry point for the 4-stage pipeline."""
    return _default_orchestrator.process(
        message=message, current_state=current_state, user_id=user_id, session_id=session_id
    )
