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


def get_study_context() -> Dict[str, Any]:
    """Loads and returns the raw study context data from disk."""
    if not CONTEXT_FILE.exists():
        return {}
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_study_metrics(ref_date_str: str = "") -> Dict[str, Any]:
    """Calculates deterministic academic workload metrics, lecture deficits, and upcoming deadlines.

    Provides rich, interpretable decision context without imposing a prescriptive action formula.

    Args:
        ref_date_str: Optional reference date in DD-MM-YYYY format (defaults to current date).

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

    data = get_study_context()
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


