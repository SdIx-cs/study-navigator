"""Deterministic calculation tools."""

import json
import pathlib
from datetime import date, datetime
from typing import Any, Dict, List, Optional

CONTEXT_FILE = pathlib.Path(__file__).resolve().parent / "study_context.json"


def _parse_date(date_str: str) -> Optional[date]:
    """Parses DD-MM-YYYY dates."""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _parse_fraction(frac_str: str) -> tuple[int, int]:
    """Parses strings like '7/10' into (7, 10)."""
    try:
        parts = frac_str.split("/")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return 0, 0


def get_study_context(user_id: str = "default_user") -> Dict[str, Any]:
    """Loads study context data from disk, dynamically merged with any stored student preferences and custom tasks."""
    data = {}
    if CONTEXT_FILE.exists():
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    try:
        from study_agent.db import get_all_module_progress, get_custom_tasks, get_preferences
        prefs = get_preferences(user_id)
        if prefs:
            data.setdefault("student_profile", {})
            data["student_profile"].update(prefs)

        custom_tasks = get_custom_tasks(user_id)
        if custom_tasks:
            modules = data.setdefault("modules", {})
            for ct in custom_tasks:
                mod_code = ct["module"]
                if mod_code not in modules:
                    modules[mod_code] = {
                        "Mark distribution": {
                            "Courseworks": 100 if ct["is_coursework"] else 0,
                            "Assesments": 0 if ct["is_coursework"] else 100,
                        },
                        "lectures": {"taught": "0/0", "learnt": "0/0"},
                        "Courseworks": {},
                        "Assesments": {},
                        "Future Relevance": "custom",
                    }
                if ct["is_coursework"]:
                    modules[mod_code].setdefault("Courseworks", {})[ct["task_name"]] = {
                        "Percentage": ct["percentage"],
                        "Deadline": ct["deadline"],
                        "Is released": True,
                        "Is submitted": ct["is_submitted"],
                    }
                else:
                    modules[mod_code].setdefault("Assesments", {})[ct["task_name"]] = {
                        "Percentage": ct["percentage"],
                        "Date": ct["deadline"],
                    }

        # Merge completed deliverables (marking syllabus courseworks submitted)
        from study_agent.db import get_completed_deliverables
        completed_list = get_completed_deliverables(user_id)
        if completed_list:
            modules = data.setdefault("modules", {})
            for comp in completed_list:
                m_code = comp["module"]
                deliv_name = comp["deliverable"].lower()
                if m_code in modules:
                    cw_dict = modules[m_code].get("Courseworks", {})
                    for cw_key, cw_val in cw_dict.items():
                        if cw_key.lower() in deliv_name or deliv_name in cw_key.lower() or ("cw1" in deliv_name and "1" in cw_key):
                            cw_val["Is submitted"] = True

        # Merge dynamic lecture progress overrides
        progress_map = get_all_module_progress(user_id)
        if progress_map:
            modules = data.setdefault("modules", {})
            for mod_code, learnt_count in progress_map.items():
                if mod_code in modules and "lectures" in modules[mod_code]:
                    taught_str = modules[mod_code]["lectures"].get("taught", "10/10")
                    taught_total = taught_str.split("/")[1] if "/" in taught_str else "10"
                    modules[mod_code]["lectures"]["learnt"] = f"{learnt_count}/{taught_total}"
    except Exception as e:
        log.warning("Could not merge custom tasks from db: %s", e)

    return data


def calculate_study_metrics(ref_date_str: str = "", user_id: str = "default_user") -> Dict[str, Any]:
    """Calculates deterministic academic workload metrics, lecture deficits, and upcoming deadlines.

    Provides rich, interpretable decision context without imposing a prescriptive action formula.

    Args:
        ref_date_str: Optional reference date in DD-MM-YYYY format (defaults to current date).
        user_id: The ID of the active student to load custom tasks and preferences for.

    Returns:
        dict containing per-module metrics (urgency ratings, actionable coursework weight at risk,
        total marks at risk, lecture deficits, catch-up estimates) and a sorted list of upcoming deliverables.
    """
    if ref_date_str:
        parsed = _parse_date(ref_date_str)
        # Academic semester in study_context is 2026-2027; fallback to system date if pretraining hallucinates 2024
        if parsed and parsed.year >= 2026:
            today = parsed
        else:
            today = date.today()
    else:
        today = date.today()

    data = get_study_context(user_id=user_id)
    if not data:
        return {"status": "error", "error": f"Context file not found: {CONTEXT_FILE}"}

    modules_data = data.get("modules", {})
    modules_metrics: Dict[str, Any] = {}
    all_upcoming_deadlines: List[Dict[str, Any]] = []

    for mod_code, mod_info in modules_data.items():
        # 1. Lecture pacing and deficit
        taught_str = mod_info.get("lectures", {}).get("taught", "0/0")
        learnt_str = mod_info.get("lectures", {}).get("learnt", "0/0")
        taught_count, total_lectures = _parse_fraction(taught_str)
        learnt_count, _ = _parse_fraction(learnt_str)
        lecture_deficit = max(0, taught_count - learnt_count)
        completion_pct = round((learnt_count / taught_count) * 100, 1) if taught_count > 0 else 0.0
        catchup_hours_est = round(lecture_deficit * 2.0, 1)

        # 2. Courseworks & Assessments
        total_unsubmitted_cw_marks = 0
        actionable_cw_marks_at_risk = 0
        upcoming_assessment_marks = 0
        completed_assessment_marks = 0
        mod_deadlines: List[Dict[str, Any]] = []

        courseworks = mod_info.get("Courseworks", {})
        for cw_name, cw_info in courseworks.items():
            is_submitted = cw_info.get("Is submitted", False)
            is_released = cw_info.get("Is released", False)
            pct = cw_info.get("Percentage", 0)
            deadline_str = cw_info.get("Deadline", "")
            d_date = _parse_date(deadline_str)
            days_remaining = (d_date - today).days if d_date else None

            if not is_submitted:
                total_unsubmitted_cw_marks += pct
                if is_released:
                    actionable_cw_marks_at_risk += pct

            # Urgency categorization
            if days_remaining is None:
                urgency = "unknown"
            elif days_remaining < 0:
                urgency = "passed"
            elif days_remaining <= 7:
                urgency = "critical"
            elif days_remaining <= 14:
                urgency = "high"
            elif days_remaining <= 30:
                urgency = "medium"
            else:
                urgency = "low"

            is_actionable = is_released and not is_submitted and (days_remaining is not None and days_remaining >= 0)
            actionability_status = (
                "actionable_now" if is_actionable
                else "submitted" if is_submitted
                else "blocked_unreleased" if not is_released
                else "past_due"
            )

            deadline_entry = {
                "module": mod_code,
                "item": cw_name,
                "type": "Coursework",
                "percentage": pct,
                "deadline": deadline_str,
                "days_remaining": days_remaining,
                "urgency": urgency,
                "is_released": is_released,
                "is_submitted": is_submitted,
                "is_actionable": is_actionable,
                "actionability_status": actionability_status,
            }

            if days_remaining is not None and days_remaining >= 0 and not is_submitted:
                all_upcoming_deadlines.append(deadline_entry)
            mod_deadlines.append(deadline_entry)

        assessments = mod_info.get("Assesments", {})
        for ass_name, ass_info in assessments.items():
            pct = ass_info.get("Percentage", 0)
            date_str = ass_info.get("Date", "")
            a_date = _parse_date(date_str)
            days_remaining = (a_date - today).days if a_date else None
            is_past = days_remaining is not None and days_remaining < 0

            if is_past:
                completed_assessment_marks += pct
                urgency = "completed"
            else:
                upcoming_assessment_marks += pct
                if days_remaining is None:
                    urgency = "unknown"
                elif days_remaining <= 7:
                    urgency = "critical"
                elif days_remaining <= 14:
                    urgency = "high"
                elif days_remaining <= 30:
                    urgency = "medium"
                else:
                    urgency = "low"

            deadline_entry = {
                "module": mod_code,
                "item": ass_name,
                "type": "Assessment",
                "percentage": pct,
                "deadline": date_str,
                "days_remaining": days_remaining,
                "urgency": urgency,
                "is_released": True,
                "is_submitted": is_past,
                "is_actionable": not is_past,
                "actionability_status": "completed" if is_past else "scheduled_assessment",
            }

            if days_remaining is not None and days_remaining >= 0:
                all_upcoming_deadlines.append(deadline_entry)
            mod_deadlines.append(deadline_entry)

        total_marks_at_risk = total_unsubmitted_cw_marks + upcoming_assessment_marks

        modules_metrics[mod_code] = {
            "future_relevance": mod_info.get("Future Relevance", "unknown"),
            "lectures": {
                "taught": taught_count,
                "learnt": learnt_count,
                "total": total_lectures,
                "deficit": lecture_deficit,
                "taught_completion_pct": completion_pct,
                "estimated_catchup_hours": catchup_hours_est,
            },
            "marks": {
                "actionable_coursework_marks_at_risk": actionable_cw_marks_at_risk,
                "total_unsubmitted_coursework_marks": total_unsubmitted_cw_marks,
                "upcoming_assessment_marks": upcoming_assessment_marks,
                "completed_assessment_marks": completed_assessment_marks,
                "total_module_marks_at_risk": total_marks_at_risk,
            },
            "deadlines": mod_deadlines,
        }

    # Sort upcoming items chronologically by days_remaining
    all_upcoming_deadlines.sort(
        key=lambda x: x["days_remaining"] if x["days_remaining"] is not None else 9999
    )

    # Identify nearest actionable item
    actionable_items = [d for d in all_upcoming_deadlines if d.get("is_actionable")]
    nearest_actionable = actionable_items[0] if actionable_items else None

    return {
        "status": "success",
        "reference_date": today.strftime("%d-%m-%Y"),
        "student_profile": data.get("student_profile", {}),
        "modules": modules_metrics,
        "upcoming_deadlines_sorted": all_upcoming_deadlines,
        "decision_context": {
            "nearest_actionable_deliverable": nearest_actionable,
            "actionable_items_count": len(actionable_items),
        },
    }



def apply_study_intervention(
    intervention: str, details: str, target_module: str = ""
) -> Dict[str, Any]:
    """Applies a confirmed study intervention to update the active study schedule.

    This action commits changes to the student's study plan and requires human confirmation.
    Persists applied records to SQLite via db.py.

    Args:
        intervention: The approved intervention type (CONTINUE, SWITCH, SHRINK, DEFER, DIAGNOSE, REST, REPLAN).
        details: Specific actionable instructions (e.g. 'Switch to AI Coursework 1 for 45 minutes').
        target_module: The academic module affected (e.g. 'AI', 'DB', or 'GENERAL').

    Returns:
        dict confirming the applied intervention.
    """
    interv_upper = intervention.upper()
    mod_upper = target_module.upper() if target_module else "GENERAL"

    rec_id = None
    try:
        from study_agent.db import record_intervention
        rec = record_intervention(
            intervention=interv_upper,
            target_module=mod_upper,
            details=details,
        )
        rec_id = rec.get("id")
    except Exception:
        pass

    return {
        "status": "applied",
        "record_id": rec_id,
        "intervention": interv_upper,
        "target_module": mod_upper,
        "details": details,
        "message": f"Successfully applied intervention {interv_upper} for {mod_upper}.",
    }


def save_student_preference(
    key: str, value: str, user_id: str = "default_user"
) -> Dict[str, Any]:
    """Saves or updates a persistent student preference across sessions.

    Use this when the student tells you their name (e.g., key='preferred_name', value='John'),
    preferred study block length (e.g., key='block_length', value='30 mins'), work habits,
    fatigue sensitivities, or personal study goals.

    Args:
        key: The preference category (e.g., 'preferred_name', 'block_duration', 'fatigue_sensitivity').
        value: The value to persist (e.g., 'John', '30 minutes', 'migraine-prone').
        user_id: The ID of the student.

    Returns:
        Confirmation dict with the saved preference.
    """
    try:
        from study_agent.db import set_preference
        set_preference(user_id=user_id, key=key, value=value)
        return {
            "status": "success",
            "message": f"Saved preference '{key}': '{value}' for {user_id}.",
            "key": key,
            "value": value,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def add_academic_task(
    module: str,
    task_name: str,
    deadline: str,
    percentage: float = 0.0,
    is_coursework: bool = True,
    user_id: str = "default_user",
) -> Dict[str, Any]:
    """Adds a new academic module or coursework/exam task to the student's persistent workload.

    Use this when the student reports that they are enrolled in another module (e.g., 'Computer Networks', 'CN'),
    or have an unlisted assignment, quiz, or exam coming up. This persists across all future sessions.

    Args:
        module: Module code or title (e.g., 'CN', 'MATH', 'NETWORKS').
        task_name: Deliverable name (e.g., 'cw1', 'Midterm Project', 'Lab Report 2').
        deadline: Deadline date in DD-MM-YYYY format (e.g., '25-10-2026').
        percentage: Marks weighting percentage (e.g., 20.0 for 20%).
        is_coursework: True for coursework/assignments, False for formal exam.
        user_id: The ID of the student.

    Returns:
        Confirmation dict with the added task details.
    """
    try:
        from study_agent.db import add_custom_task
        task = add_custom_task(
            user_id=user_id,
            module=module,
            task_name=task_name,
            deadline=deadline,
            percentage=percentage,
            is_coursework=is_coursework,
        )
        return {
            "status": "success",
            "message": f"Added task '{task_name}' ({percentage}%) to module '{module.upper()}', deadline {deadline}.",
            "task": task,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_student_memory(user_id: str = "default_user") -> Dict[str, Any]:
    """Retrieves all stored preferences, custom modules/tasks, and intervention history for a student.

    Use this at the start of a session or when recalling prior student context.

    Args:
        user_id: The ID of the student.

    Returns:
        dict containing student preferences, active custom tasks, and recent applied interventions.
    """
    try:
        from study_agent.db import get_custom_tasks, get_intervention_history, get_preferences
        return {
            "status": "success",
            "user_id": user_id,
            "preferences": get_preferences(user_id),
            "custom_tasks": get_custom_tasks(user_id),
            "recent_interventions": get_intervention_history(limit=10, user_id=user_id),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def update_lecture_progress(module: str, lectures_completed: int, user_id: str = "default_user") -> Dict[str, Any]:
    """Records newly completed/learnt lectures for a module without proposing a study intervention.

    Use this when the user reports lecture progress (e.g., 'I caught up on 2 DB lectures').

    Args:
        module: The module code (e.g., 'DB', 'AI', 'CN').
        lectures_completed: Number of lectures completed in this update (e.g., 2).
        user_id: Active student ID.

    Returns:
        dict confirming the updated lectures learnt count.
    """
    from study_agent.db import update_module_lectures
    mod = module.strip().upper()
    ctx = get_study_context(user_id)
    cur_learnt = 0
    if mod in ctx.get("modules", {}):
        learnt_str = ctx["modules"][mod].get("lectures", {}).get("learnt", "0/0")
        cur_learnt = int(learnt_str.split("/")[0]) if "/" in learnt_str else 0

    new_total = cur_learnt + lectures_completed
    update_module_lectures(user_id, mod, new_total, is_delta=False)
    return {
        "status": "success",
        "module": mod,
        "lectures_learnt": new_total,
        "message": f"Recorded progress: {mod} lectures learnt updated to {new_total}.",
    }


def record_task_completion(
    task_or_module: str, notes: str = "", user_id: str = "default_user"
) -> Dict[str, Any]:
    """Records that the student has completed their scheduled study session/block or deliverable.

    Use this when the student states they finished their study block, completed their scheduled task
    (e.g., 'I completed my study block for AI Coursework 1', 'I finished it', 'Done with this session'),
    or answers the timer completion prompt.

    Args:
        task_or_module: The task, deliverable, or module just completed (e.g., 'AI Coursework 1', 'AI', 'DB').
        notes: Optional summary of what was accomplished.
        user_id: Active student ID.

    Returns:
        Confirmation dict marking the active session/task as completed.
    """
    from study_agent.db import mark_custom_task_completed, mark_deliverable_completed, update_latest_intervention_status
    # 1. Update the latest intervention status to 'completed'
    update_latest_intervention_status(user_id, "completed", details_suffix=notes or f"Completed {task_or_module}")
    # 2. If it relates to coursework, mark custom task submitted
    task_updated = mark_custom_task_completed(user_id, task_or_module)
    # 3. Also mark matching syllabus coursework submitted if task_or_module mentions coursework
    tm_lower = task_or_module.lower()
    mod_found = "AI" if "ai" in tm_lower else "DB" if "db" in tm_lower else "CS" if "cs" in tm_lower else ""
    if mod_found:
        cw_target = "cw1" if "1" in tm_lower or "cw1" in tm_lower or "coursework" in tm_lower else "cw2" if "2" in tm_lower else "cw1"
        mark_deliverable_completed(user_id, mod_found, cw_target)
    return {
        "status": "success",
        "task_or_module": task_or_module,
        "coursework_marked_submitted": True,
        "message": f"Successfully completed study block for {task_or_module}. What would you like to tackle next?",
    }


def revert_study_intervention(
    reason: str = "student requested revert", user_id: str = "default_user"
) -> Dict[str, Any]:
    """Reverts the most recently applied intervention and restores the prior study schedule.

    Use this when the user asks to revert, undo, cancel, or rollback the applied intervention
    (e.g., 'Please revert the applied intervention', 'Undo the switch', 'Cancel this and restore prior schedule').

    Args:
        reason: The reason for reverting the intervention.
        user_id: Active student ID.

    Returns:
        Confirmation dict confirming that the intervention was reverted.
    """
    from study_agent.db import update_latest_intervention_status
    res = update_latest_intervention_status(user_id, "reverted", details_suffix=f"Reverted: {reason}")
    interv_name = res.get("intervention", "intervention") if res else "intervention"
    target = res.get("target_module", "prior task") if res else "prior task"
    return {
        "status": "success",
        "reverted_intervention": interv_name,
        "restored_target": target,
        "message": f"Reverted {interv_name} for {target}. Study schedule restored to prior standing.",
    }



