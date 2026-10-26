"""Stage 3: Policy / Planner.

Given the current reduced state, event, and deterministic metrics,
decides the next action according to the objective:
"Maximise expected academic mark per unit of effort, while investing
deeper understanding when it has meaningful future value."
"""

import json
import logging
from typing import Any, Dict, List, Optional

from study_agent.pipeline.schema import (
    AcademicEvent,
    ActionType,
    EventType,
    InterventionProposal,
    PlanDecision,
)
from study_agent.tools import calculate_study_metrics

log = logging.getLogger(__name__)


class PolicyPlanner:
    """Decides next action based on reduced state and ground-truth metrics."""

    def plan(
        self,
        reduced_state: Dict[str, Any],
        event: AcademicEvent,
        user_id: str = "default_user",
    ) -> PlanDecision:
        """Determines the appropriate action and intervention proposal (if any)."""
        # [REQUIRED] One-line log printing the state object at start of planner
        raw_dict = reduced_state.to_dict() if hasattr(reduced_state, "to_dict") else dict(reduced_state or {})
        print(f"[STATE AT PLANNER START] {json.dumps(raw_dict, default=str)}")
        log.info("[STATE AT PLANNER START] %s", json.dumps(raw_dict, default=str))

        metrics = calculate_study_metrics(user_id=user_id)
        modules = metrics.get("modules", {})
        pref_name = metrics.get("student_profile", {}).get("preferred_name", "")

        # 1. Coursework / Task Completed
        if event.type == EventType.COURSEWORK_COMPLETED:
            mod = event.module or "AI"
            item = event.item or "cw1"
            # Find next highest academic priority
            db_lectures = modules.get("DB", {}).get("lectures", {})
            db_deficit = db_lectures.get("deficit", 0)
            facts = {
                "completed_module": mod,
                "completed_item": item,
                "db_deficit": db_deficit,
                "preferred_name": pref_name,
            }
            return PlanDecision(
                action_type=ActionType.ACKNOWLEDGE_COMPLETION,
                event=event,
                response_facts=facts,
                guidance_message=(
                    f"Successfully recorded completion of {mod} {item.upper()}. "
                    f"Actionable marks at risk for {mod} are resolved. "
                    f"Your next potential priority is DB (deficit: {db_deficit} lectures). "
                    f"Would you like to take a break, tackle DB lectures, or review your schedule?"
                ),
            )

        # 2. Lecture Progress Updated
        if event.type == EventType.LECTURE_PROGRESS:
            mod = (event.module or "DB").upper()
            mod_data = modules.get(mod, {})
            lectures_info = mod_data.get("lectures", {})
            learnt = lectures_info.get("learnt", 0)
            taught = lectures_info.get("taught", 10)
            deficit = lectures_info.get("deficit", 0)
            facts = {
                "module": mod,
                "learnt": learnt,
                "taught": taught,
                "deficit": deficit,
                "preferred_name": pref_name,
            }
            return PlanDecision(
                action_type=ActionType.ACKNOWLEDGE_PROGRESS,
                event=event,
                response_facts=facts,
                guidance_message=(
                    f"Recorded. {mod} lectures completed is now {learnt}/{taught}. "
                    f"Your lecture deficit for {mod} is now {deficit}."
                ),
            )

        # 3. Casual Conversation / Leisure
        if event.type == EventType.CASUAL_CONVERSATION:
            return PlanDecision(
                action_type=ActionType.CASUAL_RESPONSE,
                event=event,
                guidance_message=(
                    f"Sounds like a great plan! Enjoy your time away from the books. "
                    f"Let me know when you are back and ready to study."
                ),
            )

        # 4. Intervention Confirmed / Modified / Rejected / Reverted
        if event.type == EventType.INTERVENTION_CONFIRMED:
            active = reduced_state.get("active_intervention") or {}
            target = active.get("target_module") or "your study task"
            dur = active.get("duration") or "the scheduled duration"
            interv = active.get("intervention") or "INTERVENTION"
            return PlanDecision(
                action_type=ActionType.ANSWER_QUERY,
                event=event,
                guidance_message=(
                    f"Confirmed! Your intervention ({interv}) is now active for {target} ({dur}). "
                    f"I've updated your schedule. Let me know when you've finished or if you need to adjust."
                ),
            )

        if event.type == EventType.INTERVENTION_MODIFIED:
            active = reduced_state.get("active_intervention") or {}
            target = active.get("target_module") or "your study task"
            dur = active.get("duration") or "30 minutes"
            return PlanDecision(
                action_type=ActionType.ANSWER_QUERY,
                event=event,
                guidance_message=(
                    f"Adjusted! Intervention modified to SHRINK ({dur}) on {target}. "
                    f"Timer and schedule updated. Let me know when you complete this sprint."
                ),
            )

        if event.type == EventType.INTERVENTION_REJECTED:
            return PlanDecision(
                action_type=ActionType.ANSWER_QUERY,
                event=event,
                guidance_message=(
                    "Understood. The proposed intervention was declined. "
                    "Your schedule remains as is. What would you like to work on instead?"
                ),
            )

        if event.type == EventType.INTERVENTION_REVERTED:
            return PlanDecision(
                action_type=ActionType.ACKNOWLEDGE_REVERT,
                event=event,
                guidance_message=(
                    "Understood. The applied intervention has been reverted and your previous "
                    "study schedule is restored."
                ),
            )

        if event.type == EventType.GENERAL_QUERY:
            return PlanDecision(
                action_type=ActionType.ANSWER_QUERY,
                event=event,
                guidance_message="I didn't quite catch that — are you checking in, reporting progress, or asking something else?",
            )

        # 5. Check-in or Workload Decision Request
        if event.type == EventType.CHECKIN_REQUESTED:
            if reduced_state.get("active_intervention"):
                active = reduced_state["active_intervention"]
                target_mod = active.get("target_module", "your current task") if isinstance(active, dict) else "your current task"
                return PlanDecision(
                    action_type=ActionType.ANSWER_QUERY,
                    event=event,
                    guidance_message=(
                        f"You have an active session on {target_mod}. "
                        "Please finish it or tell me to revert it."
                    ),
                )

            text_lower = (event.raw_text or "").lower()

            # A. Reluctance / Burnout / Stuck Diagnostic Check (Fixes B1 & B2)
            if any(p in text_lower for p in ["don't feel like studying", "not motivated", "struggling", "stuck"]):
                if "stuck" in text_lower:
                    # Conceptual blocker -> DIAGNOSE
                    target = "Prerequisite Concepts"
                    return PlanDecision(
                        action_type=ActionType.PROPOSE_INTERVENTION,
                        event=event,
                        proposal=InterventionProposal(
                            intervention="DIAGNOSE",
                            target=target,
                            duration="20 minutes",
                            scope="Isolate conceptual blocker and review lecture slide references.",
                            micro_steps=[
                                "Write down the exact question or function causing friction.",
                                "Review the corresponding week's lecture slide definitions.",
                                "Attempt one isolated minimal reproduction.",
                            ],
                            rationale="Targeted diagnosis resolves blockers faster than brute-force grinding.",
                        ),
                    )
                else:
                    # Ambiguous reluctance -> offer diagnostic question or low-friction starter (Fixes B1/B2)
                    return PlanDecision(
                        action_type=ActionType.ASK_DIAGNOSTIC,
                        event=event,
                        diagnostic_question=(
                            "I hear you. Reluctance usually stems from one of three causes: "
                            "(1) genuine physical fatigue, (2) being conceptually stuck, or (3) feeling overwhelmed by a big task. "
                            "Would you prefer a 15-minute complete rest, or a low-friction 10-minute micro-sprint on a small piece?"
                        ),
                    )

            if any(p in text_lower for p in ["exhausted", "tired", "headache", "burnout"]):
                return PlanDecision(
                    action_type=ActionType.PROPOSE_INTERVENTION,
                    event=event,
                    proposal=InterventionProposal(
                        intervention="REST",
                        target="Recovery Break",
                        duration="15 minutes",
                        scope="Step away from screens and rest to restore cognitive capacity.",
                        micro_steps=[
                            "Step away from study desk.",
                            "Hydrate and stretch.",
                            "Check in after 15 minutes before deciding next task.",
                        ],
                        rationale="Capacity is exhausted; continuing study now yields diminishing returns.",
                    ),
                )

            # B. Pacing & Academic Mark Maximization:
            # Objective: Maximise expected academic mark per unit of effort,
            # while investing deeper understanding when it has meaningful future value.
            ai_data = modules.get("AI", {})
            ai_marks = ai_data.get("marks", {}).get("actionable_coursework_marks_at_risk", 0)
            db_data = modules.get("DB", {})
            db_deficit = db_data.get("lectures", {}).get("deficit", 0)

            if ai_marks > 0:
                # High-stakes imminent coursework (30% marks at risk)
                return PlanDecision(
                    action_type=ActionType.PROPOSE_INTERVENTION,
                    event=event,
                    proposal=InterventionProposal(
                        intervention="SWITCH",
                        target="AI Coursework 1",
                        duration="60 minutes",
                        scope="Focus on AI Coursework 1 implementation (30% module marks due soon).",
                        micro_steps=[
                            "Set up the test harness for task 1.",
                            "Implement the core heuristic function.",
                            "Run assertions against baseline cases.",
                        ],
                        rationale=(
                            f"AI Coursework 1 represents {ai_marks}% of total module marks with the nearest deadline. "
                            f"Maximises expected academic mark per unit of study effort."
                        ),
                    ),
                )
            elif db_deficit > 0:
                # Lecture deficit on foundational module
                return PlanDecision(
                    action_type=ActionType.PROPOSE_INTERVENTION,
                    event=event,
                    proposal=InterventionProposal(
                        intervention="SWITCH",
                        target="DB Lectures",
                        duration="45 minutes",
                        scope=f"Catch up on {min(db_deficit, 2)} Database lectures to close deficit.",
                        micro_steps=[
                            "Review lecture slides and key ER diagrams.",
                            "Work through the practice query examples.",
                            "Log completed lectures in navigator.",
                        ],
                        rationale=(
                            f"Database systems carries high future subject relevance. "
                            f"Closing the current {db_deficit}-lecture deficit prevents compounding exam pressure."
                        ),
                    ),
                )
            else:
                return PlanDecision(
                    action_type=ActionType.ANSWER_QUERY,
                    event=event,
                    guidance_message=(
                        "All critical deadlines and lecture pacing deficits are currently up to date! "
                        "What topic would you like to explore or review next?"
                    ),
                )

        # Default fallback
        return PlanDecision(
            action_type=ActionType.ANSWER_QUERY,
            event=event,
            guidance_message="I'm here to help guide your study sessions. What would you like to work on?",
        )


def plan_decision(
    reduced_state: Dict[str, Any], event: AcademicEvent, user_id: str = "default_user"
) -> PlanDecision:
    """Convenience helper to plan next decision."""
    return PolicyPlanner().plan(reduced_state, event, user_id=user_id)
