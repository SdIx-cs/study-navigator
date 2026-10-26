"""Stage 2: State Reducer.

A plain deterministic function (NOT an LLM call) that applies an AcademicEvent
to the database memory bank and session state.
Guarantees that state and database mutations happen immediately and reliably.
"""

import copy
import json
import logging
from typing import Any, Dict, List, Tuple

from study_agent.db import (
    add_custom_task,
    mark_deliverable_completed,
    record_intervention,
    set_preference,
    update_latest_intervention_status,
    update_module_lectures,
)
from study_agent.pipeline.schema import AcademicEvent, EventType

log = logging.getLogger(__name__)


def reduce(
    current_state: Dict[str, Any],
    event: AcademicEvent,
    user_id: str = "default_user",
    session_id: str = "default_session",
) -> Tuple[Dict[str, Any], List[str]]:
    """Applies an AcademicEvent to the memory bank and state deterministically.

    Args:
        current_state: Active session state dictionary as read from storage.
        event: The extracted structured AcademicEvent.
        user_id: Active student identifier.
        session_id: Active session identifier.

    Returns:
        Tuple of (updated_state_dict, list_of_applied_mutations)
    """
    # [REQUIRED] One-line log printing the state object as read from storage, before any defaults
    raw_dict = current_state.to_dict() if hasattr(current_state, "to_dict") else dict(current_state or {})
    print(f"[STATE AT REDUCER START] {json.dumps(raw_dict, default=str)}")
    log.info("[STATE AT REDUCER START] %s", json.dumps(raw_dict, default=str))

    state = copy.deepcopy(current_state or {})
    mutations: List[str] = []

    if event.type == EventType.LECTURE_PROGRESS:
        mod = (event.module or "DB").upper()
        delta = event.delta or 1
        new_total = update_module_lectures(user_id, mod, delta, is_delta=True)
        mutations.append(f"Recorded progress: {mod} lectures updated to {new_total} (+{delta}).")

    elif event.type == EventType.COURSEWORK_COMPLETED:
        mod = (event.module or "AI").upper()
        item = (event.item or "cw1").lower()
        mark_deliverable_completed(user_id, mod, item)
        update_latest_intervention_status(
            user_id, "completed", details_suffix=event.notes or f"Completed {mod} {item}"
        )
        state["active_intervention"] = None
        state["pending_proposal"] = None
        state["proposal_details"] = None
        state["slice_stage"] = "idle"
        state["approval_status"] = "idle"
        mutations.append(f"Marked deliverable {mod} {item} as completed in database.")
        mutations.append("Closed active intervention and reset stage to idle.")

    elif event.type == EventType.PREFERENCE_UPDATED:
        key = (event.key or "preferred_name").lower()
        val = str(event.value or "")
        set_preference(user_id, key, val)
        mutations.append(f"Saved student preference: {key} = {val}.")

    elif event.type == EventType.TASK_ADDED:
        mod = (event.module or "GENERAL").upper()
        task_name = event.item or "Custom Task"
        pct = float(event.extra.get("percentage", 20.0))
        deadline = event.extra.get("deadline", "30-11-2026")
        add_custom_task(user_id, mod, task_name, deadline, pct)
        mutations.append(f"Added custom academic task: {mod} {task_name} ({pct}% due {deadline}).")

    elif event.type == EventType.INTERVENTION_CONFIRMED:
        if current_state.get("slice_stage") != "awaiting_confirmation":
                mutations.append("Ignored confirm/modify — nothing was pending.")
                return state, mutations
        details = state.get("proposal_details") or {}
        interv = details.get("intervention") or state.get("pending_proposal") or "CONTINUE"
        target = details.get("target") or "Study Task"
        desc = details.get("scope") or "Applied intervention"
        record_intervention(interv, target, desc, user_id=user_id, session_id=session_id, status="applied")
        state["slice_stage"] = "confirmed"
        state["just_confirmed"] = True
        state["approval_status"] = "approved"
        state["active_intervention"] = {
            "intervention": interv,
            "target_module": target,
            "details": desc,
            "duration": details.get("duration", "30 minutes"),
        }
        state["pending_proposal"] = None
        state["proposal_details"] = None
        mutations.append(f"Recorded confirmed intervention: {interv} for {target}.")

    elif event.type == EventType.INTERVENTION_MODIFIED:
        if current_state.get("slice_stage") != "awaiting_confirmation":
                mutations.append("Ignored confirm/modify — nothing was pending.")
                return state, mutations
        mod_details = event.modified_details or "SHRINK the session to 30 minutes"
        details = state.get("proposal_details") or {}
        target = details.get("target") or "Current Task"
        record_intervention("SHRINK", target, mod_details, user_id=user_id, session_id=session_id, status="applied")
        state["slice_stage"] = "confirmed"
        state["just_confirmed"] = True
        state["approval_status"] = "approved"
        state["active_intervention"] = {
            "intervention": "SHRINK",
            "target_module": target,
            "details": mod_details,
            "duration": event.modified_details.split("to ")[-1] if "to " in (event.modified_details or "") else "30 minutes",
        }
        state["pending_proposal"] = None
        state["proposal_details"] = None
        mutations.append(f"Recorded modified intervention: SHRINK for {target} ({mod_details}).")

    elif event.type == EventType.INTERVENTION_REVERTED:
        if current_state.get("slice_stage") != "awaiting_confirmation":
                mutations.append("Ignored confirm/modify — nothing was pending.")
                return state, mutations
        reason = event.reason or "Student requested rollback"
        update_latest_intervention_status(user_id, "reverted", details_suffix=reason)
        state["slice_stage"] = "idle"
        state["active_intervention"] = None
        state["pending_proposal"] = None
        state["proposal_details"] = None
        state["approval_status"] = "idle"
        mutations.append(f"Reverted intervention: {reason}.")

    elif event.type == EventType.INTERVENTION_REJECTED:
        state["slice_stage"] = "idle"
        state["pending_proposal"] = None
        state["proposal_details"] = None
        state["approval_status"] = "rejected"
        mutations.append("Declined intervention proposal.")

    elif event.type == EventType.CHECKIN_REQUESTED:
        state["slice_stage"] = "evaluating"

    return state, mutations
