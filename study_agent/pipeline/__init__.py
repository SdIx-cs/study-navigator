"""4-Stage Modular Pipeline for Study Navigator.

1. EventExtractor  - Raw message -> AcademicEvent
2. StateReducer    - AcademicEvent -> Deterministic DB & State update (reduce)
3. PolicyPlanner   - Ground-truth State & Metrics -> PlanDecision
4. Presenter       - PlanDecision -> PresenterOutput (A2UI & text)
"""

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

__all__ = [
    "AcademicEvent",
    "EventType",
    "ActionType",
    "InterventionProposal",
    "PlanDecision",
    "PresenterOutput",
    "EventExtractor",
    "extract_event",
    "reduce",
    "PolicyPlanner",
    "plan_decision",
    "Presenter",
    "format_presentation",
    "PipelineOrchestrator",
    "process_study_message",
]
