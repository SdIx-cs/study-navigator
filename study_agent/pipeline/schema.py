"""Schema definitions for the 4-Stage Study Navigator Pipeline.

Stages:
1. Event Extractor -> AcademicEvent
2. State Reducer   -> Deterministic State & DB mutation
3. Policy/Planner  -> PlanDecision
4. Presenter       -> PresenterOutput (A2UI payload & clean chat text)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class EventType(str, Enum):
    LECTURE_PROGRESS = "lecture_progress_updated"
    COURSEWORK_COMPLETED = "coursework_completed"
    TASK_ADDED = "task_added"
    PREFERENCE_UPDATED = "preference_updated"
    CHECKIN_REQUESTED = "checkin_requested"
    CASUAL_CONVERSATION = "casual_conversation"
    INTERVENTION_CONFIRMED = "intervention_confirmed"
    INTERVENTION_MODIFIED = "intervention_modified"
    INTERVENTION_REJECTED = "intervention_rejected"
    INTERVENTION_REVERTED = "intervention_reverted"
    GENERAL_QUERY = "general_query"


@dataclass
class AcademicEvent:
    """Structured event extracted from raw user input."""
    type: EventType
    module: Optional[str] = None
    item: Optional[str] = None
    delta: Optional[int] = None
    total: Optional[int] = None
    notes: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None
    reason: Optional[str] = None
    modified_details: Optional[str] = None
    raw_text: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class ActionType(str, Enum):
    ACKNOWLEDGE_PROGRESS = "acknowledge_progress"
    ACKNOWLEDGE_COMPLETION = "acknowledge_completion"
    ACKNOWLEDGE_REVERT = "acknowledge_revert"
    PROPOSE_INTERVENTION = "propose_intervention"
    ASK_DIAGNOSTIC = "ask_diagnostic"
    CASUAL_RESPONSE = "casual_response"
    ANSWER_QUERY = "answer_query"


@dataclass
class InterventionProposal:
    """Structured proposal for study intervention."""
    intervention: str  # SWITCH, SHRINK, REST, DIAGNOSE, CONTINUE, DEFER, REPLAN
    target: str
    duration: str
    scope: str
    micro_steps: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class PlanDecision:
    """Decision made by the Policy/Planner stage based on reduced state and metrics."""
    action_type: ActionType
    event: AcademicEvent
    proposal: Optional[InterventionProposal] = None
    diagnostic_question: Optional[str] = None
    response_facts: Dict[str, Any] = field(default_factory=dict)
    guidance_message: Optional[str] = None


@dataclass
class PresenterOutput:
    """Output formatted for the user chat and A2UI surface."""
    text: str
    a2ui_card: Optional[Dict[str, Any]] = None
    slice_stage: str = "idle"
    pending_proposal: Optional[str] = None
    proposal_details: Optional[Dict[str, Any]] = None
    active_intervention: Optional[Dict[str, Any]] = None
    approval_status: Optional[str] = None
    trace: Optional[Dict[str, Any]] = None
