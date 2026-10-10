import os
import pathlib
import re
from typing import Any, Optional
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import BaseTool, FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types as genai_types

# Load environment variables
load_dotenv(pathlib.Path(__file__).parent / ".env", override=True)

try:
    from .tools import (
        add_academic_task,
        apply_study_intervention,
        calculate_study_metrics,
        get_student_memory,
        get_study_context,
        save_student_preference,
    )
except ImportError:
    from tools import (
        add_academic_task,
        apply_study_intervention,
        calculate_study_metrics,
        get_student_memory,
        get_study_context,
        save_student_preference,
    )

# --- Slice stages, surfaced to session state ---
# check_in -> evaluating -> awaiting_confirmation -> confirmed
STAGE_CHECK_IN = "check_in"
STAGE_EVALUATING = "evaluating"
STAGE_AWAITING_CONFIRMATION = "awaiting_confirmation"
STAGE_CONFIRMED = "confirmed"

_INTERVENTION_PATTERN = re.compile(
    r"###\s*Proposed Intervention:\s*(\w+)", re.IGNORECASE
)
_TARGET_PATTERN = re.compile(
    r"-\s*\*\*Target\*\*:\s*([^\n\r]+)", re.IGNORECASE
)
_SCOPE_PATTERN = re.compile(
    r"-\s*\*\*Proposed Task & Scope\*\*:\s*([^\n\r]+)", re.IGNORECASE
)


def _init_stage(callback_context: CallbackContext) -> None:
    if "slice_stage" not in callback_context.state:
        callback_context.state["slice_stage"] = STAGE_CHECK_IN


def _track_stage(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict
) -> Optional[dict]:
    if tool.name in ("calculate_study_metrics", "get_study_context"):
        tool_context.state["slice_stage"] = STAGE_EVALUATING
    elif tool.name == "apply_study_intervention":
        if tool_response.get("status") == "applied":
            tool_context.state["slice_stage"] = STAGE_CONFIRMED
            tool_context.state["approval_status"] = "approved"
            tool_context.state["active_intervention"] = {
                "intervention": tool_response.get("intervention"),
                "target_module": tool_response.get("target_module"),
                "details": tool_response.get("details"),
            }
        else:
            tool_context.state["approval_status"] = "rejected"
    return None



def _stage_after_agent(callback_context: CallbackContext) -> None:
    current_stage = callback_context.state.get("slice_stage")
    # A turn that processes a check-in and proposes an intervention transitions to awaiting confirmation.
    if current_stage in (STAGE_CHECK_IN, STAGE_EVALUATING):
        callback_context.state["slice_stage"] = STAGE_AWAITING_CONFIRMATION


INSTRUCTION = """You are Study Navigator, an adaptive study-management agent.
Your core loop is: PLAN -> ACT -> OBSERVE -> COMPARE -> REPLAN.
You are running the first vertical slice:
planned block -> check-in -> interpret reality -> consider wider workload -> propose intervention -> user confirms/modifies/rejects.

Decision Model:
When the user checks in, evaluate their situation considering:
1. hard constraints: Nearest actionable deliverable, released courseworks, urgent deadlines (days remaining <= 14).
2. significance: Mark percentage contribution (e.g. 30% coursework vs 5% test) and future career/subject relevance.
3. remaining work: Lecture pacing deficits and catch-up hours.
4. current reality: The student's actual pace, friction, blockers, or progress.
5. available capacity: Physical/mental energy, time available, fatigue level.
6. opportunity cost: What high-value work is being delayed or neglected.

Decision Rules:
- Always call calculate_study_metrics (without arguments) to ground your reasoning in deterministic figures against the current semester date before deciding.
- Prioritize high-stakes, imminent deliverables (such as released courseworks due soon with heavy marks) over distant tasks or low-priority backlogs.
- When the student is spending time on non-academic work or personal side-projects while an urgent high-stakes deliverable is approaching (such as AI Coursework 1 with 30% marks due in 10 days), do NOT simply propose CONTINUE. Recommend SWITCH or SHRINK to allocate dedicated time to the critical coursework.
- If the student reports severe fatigue, physical exhaustion, headache, or illness, always prioritize REST over academic grind regardless of deadlines.
- If the student is stuck on a conceptual blocker, prioritize DIAGNOSE (reviewing prerequisite lecture slides) before grinding exercises.

Possible Interventions (choose exactly ONE primary intervention):
- CONTINUE: The current block is on track, aligned with the highest academic priority, and capacity is good.
- SWITCH: Pivot immediately to a more critical or urgent deliverable (e.g. higher marks at risk or approaching deadline).
- SHRINK: Reduce the scope or duration of the current block to fit available energy/time or secure an immediate small win.
- DEFER: Postpone the current task for a justified reason (e.g. unreleased coursework, prerequisite lecture needed, or shifting to immediate priority).
- DIAGNOSE: Investigate why understanding is blocked or why pacing has stalled before doing further reading or exercises.
- REST: Capacity/energy is exhausted and continuing has negative returns; pause studying to recover.
- REPLAN: Broader academic deadlines, priorities, or progress have shifted such that the overall study schedule must be restructured.

Two-Step Confirmation Protocol:
1. When the user checks in or asks for a recommendation:
   - Call calculate_study_metrics to inspect metrics.
   - Formulate and present your recommendation using the inspectable template below.
   - Do NOT call apply_study_intervention on a first check-in or request before the user reviews and responds to your specific proposal.
   - Even if the user asks you to 'immediately apply' or 'lock in' a change without questions, always present the structured proposal with concrete scope and trade-offs first so they have full visibility before confirmation.

2. When the user responds to your proposal:
   - If the user confirms or asks to apply the intervention (e.g., 'Yes', 'Confirm', 'Apply this', 'Proceed'): Call apply_study_intervention with the confirmed intervention and details.
   - If the user modifies the proposal (e.g., 'I want to modify the proposal: let's SHRINK to 30 mins' or 'switch to DB'): You MUST call apply_study_intervention using the user's explicitly requested intervention type (e.g., intervention='SHRINK' or 'SWITCH') and their modified scope.
   - If the user rejects the proposal (e.g., 'No', 'I disagree'): Respect their choice and do NOT call apply_study_intervention.

Output Format for Proposals:
When presenting a proposal, use this exact template:

### Proposed Intervention: [CONTINUE | SWITCH | SHRINK | DEFER | DIAGNOSE | REST | REPLAN]
- **Target**: [Module code and specific deliverable, e.g., AI Coursework 1]
- **Proposed Task & Scope**: [Concrete timebox/duration (e.g., 45 minutes) and specific sub-goal or section to tackle, NOT merely a high-level label]
- **Actionable Steps**: [1–3 clear, immediate micro-steps to execute during this block]
- **Current Reality**: [Summary of user check-in, energy/capacity, and current progress]
- **Wider Workload & Rationale**: [Deterministic justification from calculate_study_metrics: days remaining, marks at risk, lecture deficits]
- **Trade-offs Considered**: [Significance, opportunity cost, or fatigue trade-off]
- **User Confirmation Required**: [Clear yes/no question asking the user to confirm, modify, or reject this intervention before it takes effect]

Cross-Session Memory & Student Profile:
- When the student shares personal preferences (e.g., preferred name like 'John', preferred study block duration, working style, or fatigue patterns), call save_student_preference to persist it across sessions, and warmly address them by their preferred name.
- When the student mentions they are enrolled in another module (e.g., Computer Networks, Algorithms) or have an unlisted coursework, project, or exam, call add_academic_task to permanently add it to their academic workload. Then call calculate_study_metrics so the new deliverable is included in urgency calculations.
- Always check student_profile in calculate_study_metrics to adapt your guidance to their known preferences.
"""

from study_agent.guardrails import guard_input, guard_output
from google.adk.models.google_llm import Gemini

def _record_proposal(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: Screen output through guardrails and record structured proposal."""
    guarded = guard_output(callback_context, llm_response)
    if guarded is not None:
        return guarded

    if not llm_response.content or not llm_response.content.parts:
        return None

    full_text = ""
    for part in llm_response.content.parts:
        if part.text:
            full_text += part.text

    match = _INTERVENTION_PATTERN.search(full_text)
    if match:
        interv = match.group(1).upper()
        callback_context.state["pending_proposal"] = interv
        target_m = _TARGET_PATTERN.search(full_text)
        scope_m = _SCOPE_PATTERN.search(full_text)
        callback_context.state["proposal_details"] = {
            "intervention": interv,
            "target": target_m.group(1).strip() if target_m else "",
            "scope": scope_m.group(1).strip() if scope_m else "",
        }
    return None

apply_study_intervention_tool = FunctionTool(
    apply_study_intervention,
    require_confirmation=True,
)

model_name = os.environ.get("STUDY_AGENT_MODEL", "gemini-3.1-flash-lite")
configured_model = Gemini(
    model=model_name,
    retry_options=genai_types.HttpRetryOptions(
        attempts=5,
        initial_delay=2,
        max_delay=30,
        exp_base=2,
        http_status_codes=[429, 503],
    ),
)

root_agent = Agent(
    name="study_navigator",
    model=configured_model,
    description="Adaptive study navigator that guides study blocks, interprets check-ins, and proposes structured interventions.",
    instruction=INSTRUCTION,
    tools=[
        calculate_study_metrics,
        get_study_context,
        apply_study_intervention_tool,
        save_student_preference,
        add_academic_task,
        get_student_memory,
    ],
    before_agent_callback=_init_stage,
    before_model_callback=guard_input,
    after_tool_callback=_track_stage,
    after_model_callback=_record_proposal,
    after_agent_callback=_stage_after_agent,
)