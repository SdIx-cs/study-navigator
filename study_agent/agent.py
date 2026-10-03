import os
import pathlib
import re
from typing import Any, Optional
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

# Load environment variables
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

try:
    from .tools import calculate_study_metrics, get_study_context
except ImportError:
    from tools import calculate_study_metrics, get_study_context

# --- Slice stages, surfaced to session state ---
# check_in -> evaluating -> awaiting_confirmation
STAGE_CHECK_IN = "check_in"
STAGE_EVALUATING = "evaluating"
STAGE_AWAITING_CONFIRMATION = "awaiting_confirmation"

_INTERVENTION_PATTERN = re.compile(
    r"###\s*Proposed Intervention:\s*(\w+)", re.IGNORECASE
)


def _init_stage(callback_context: CallbackContext) -> None:
    if "slice_stage" not in callback_context.state:
        callback_context.state["slice_stage"] = STAGE_CHECK_IN


def _track_stage(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict
) -> Optional[dict]:
    if tool.name in ("calculate_study_metrics", "get_study_context"):
        tool_context.state["slice_stage"] = STAGE_EVALUATING
    return None


def _record_proposal(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    if llm_response.content and llm_response.content.parts:
        text = "\n".join(p.text for p in llm_response.content.parts if p.text)
        match = _INTERVENTION_PATTERN.search(text)
        if match:
            callback_context.state["pending_proposal"] = match.group(1).upper()
    return None


def _stage_after_agent(callback_context: CallbackContext) -> None:
    # A turn that processes a check-in and proposes an intervention transitions to awaiting confirmation
    if callback_context.state.get("slice_stage") in (STAGE_CHECK_IN, STAGE_EVALUATING):
        callback_context.state["slice_stage"] = STAGE_AWAITING_CONFIRMATION


INSTRUCTION = """You are Study Navigator, an adaptive study-management agent.
Your core loop is: PLAN -> ACT -> OBSERVE -> COMPARE -> REPLAN.
You are running the first vertical slice:
planned block -> check-in -> interpret reality -> consider wider workload -> propose intervention -> user confirms/modifies/rejects.

Decision Model:
When the user checks in, evaluate their situation considering:
1. hard constraints: Upcoming deadlines, released courseworks, assessment dates.
2. significance: Mark percentage contribution and future career/subject relevance.
3. remaining work: Lecture pacing deficits (taught vs learnt) and pending deliverables.
4. current reality: The student's actual pace, friction, blockers, or progress.
5. available capacity: Physical/mental energy, time available, fatigue level.
6. opportunity cost: What high-value work is being delayed or neglected.

Always call calculate_study_metrics to ground your reasoning in deterministic figures before deciding.

Possible Interventions (choose exactly ONE primary intervention):
- CONTINUE: The current block is on track, aligned with the highest academic priority, and capacity is good.
- SWITCH: Pivot immediately to a more critical or urgent deliverable (e.g. higher marks at risk or approaching deadline).
- SHRINK: Reduce the scope or duration of the current block to fit available energy/time or secure an immediate small win.
- DEFER: Postpone the current task for a justified reason (e.g. unreleased coursework, prerequisite lecture needed, or shifting to immediate priority).
- DIAGNOSE: Investigate why understanding is blocked or why pacing has stalled before doing further reading or exercises.
- REST: Capacity/energy is exhausted and continuing has negative returns; pause studying to recover.
- REPLAN: Broader academic deadlines, priorities, or progress have shifted such that the overall study schedule must be restructured.

Output Format:
You MUST format your proposed recommendation using this exact inspectable template:

### Proposed Intervention: [CONTINUE | SWITCH | SHRINK | DEFER | DIAGNOSE | REST | REPLAN]
- **Target**: [Module and specific task / coursework]
- **Current Reality**: [Summary of user check-in, energy/capacity, and current progress]
- **Wider Workload & Rationale**: [Deterministic justification from calculate_study_metrics: days remaining, marks at risk, lecture deficits]
- **Trade-offs Considered**: [Significance, opportunity cost, or fatigue trade-off]
- **User Confirmation Required**: [Clear yes/no question asking the user to confirm, modify, or reject this intervention before it takes effect]

Never finalize or execute schedule changes without the user's explicit confirmation.
"""

root_agent = Agent(
    name="study_navigator",
    model=os.environ.get("STUDY_AGENT_MODEL", "gemini-3.5-flash"),
    description="Adaptive study navigator that guides study blocks, interprets check-ins, and proposes structured interventions.",
    instruction=INSTRUCTION,
    tools=[calculate_study_metrics, get_study_context],
    before_agent_callback=_init_stage,
    after_tool_callback=_track_stage,
    after_model_callback=_record_proposal,
    after_agent_callback=_stage_after_agent,
)