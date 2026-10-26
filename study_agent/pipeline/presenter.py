"""Stage 4: Presenter.

Formats the PlanDecision for the chat stream and A2UI surface.
Generates clean, non-patronizing text without internal memo preambles,
and produces structured A2UI card representations.
"""

import logging
from typing import Any, Dict, Optional

from study_agent.pipeline.schema import (
    ActionType,
    PlanDecision,
    PresenterOutput,
)

log = logging.getLogger(__name__)


class Presenter:
    """Formats decisions into user-facing text and structured A2UI payloads."""

    def present(
        self,
        decision: PlanDecision,
        state: Optional[Dict[str, Any]] = None,
    ) -> PresenterOutput:
        """Formats a PlanDecision into a PresenterOutput."""
        current_state = state or {}

        if decision.action_type == ActionType.PROPOSE_INTERVENTION and decision.proposal:
            p = decision.proposal
            micro_steps_md = "\n".join(f"{i+1}. {step}" for i, step in enumerate(p.micro_steps))
            
            # Format text in clean inspectable markdown compatible with A2UI cards
            text = (
                f"I recommend a structured study intervention based on your current deadlines and workload:\n\n"
                f"### Proposed Intervention: {p.intervention}\n"
                f"- **Target**: {p.target}\n"
                f"- **Duration**: {p.duration}\n"
                f"- **Proposed Task & Scope**: {p.scope}\n"
                f"- **Actionable Steps**:\n{micro_steps_md}\n"
                f"- **Rationale**: {p.rationale}\n"
                f"- **User Confirmation Required**: Please confirm, modify, or decline this proposed intervention."
            )

            a2ui_card = {
                "type": "intervention_proposal",
                "intervention": p.intervention,
                "target": p.target,
                "duration": p.duration,
                "scope": p.scope,
                "micro_steps": p.micro_steps,
                "rationale": p.rationale,
                "actions": ["confirm", "shrink_30", "decline"],
            }

            proposal_details = {
                "intervention": p.intervention,
                "target": p.target,
                "duration": p.duration,
                "scope": p.scope,
            }

            return PresenterOutput(
                text=text,
                a2ui_card=a2ui_card,
                slice_stage="awaiting_confirmation",
                pending_proposal=p.intervention,
                proposal_details=proposal_details,
                active_intervention=current_state.get("active_intervention"),
                approval_status=current_state.get("approval_status"),
            )

        elif decision.action_type == ActionType.ASK_DIAGNOSTIC:
            return PresenterOutput(
                text=decision.diagnostic_question or "Could you share a bit more detail on what's blocking you?",
                a2ui_card=None,
                slice_stage="idle",
                pending_proposal=None,
                proposal_details=None,
                active_intervention=current_state.get("active_intervention"),
                approval_status=current_state.get("approval_status"),
            )

        else:
            # Acknowledgements or answers
            preferred_name = (
                decision.response_facts.get("preferred_name")
                if decision.response_facts
                else None
            )
            msg = decision.guidance_message or "Understood."
            if preferred_name:
                msg = f"{preferred_name}, {msg}"
            return PresenterOutput(
                text=msg,
                a2ui_card=None,
                slice_stage=current_state.get("slice_stage", "idle"),
                pending_proposal=None,
                proposal_details=None,
                active_intervention=current_state.get("active_intervention"),
                approval_status=current_state.get("approval_status"),
            )


def format_presentation(
    decision: PlanDecision, state: Optional[Dict[str, Any]] = None
) -> PresenterOutput:
    """Convenience helper to format presentation."""
    return Presenter().present(decision, state)
