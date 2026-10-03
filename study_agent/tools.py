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

    Args:
        ref_date_str: Optional reference date in DD-MM-YYYY format (defaults to current date).

    Returns:
        dict containing per-module metrics (lecture deficit, unsubmitted coursework marks,
        upcoming deadlines with days remaining) and an overall urgent deadlines list sorted by due date.
    """
    if ref_date_str:
        today = _parse_date(ref_date_str) or date.today()
    else:
        today = date.today()

    data = get_study_context()
    if not data:
        return {"status": "error", "error": f"Context file not found: {CONTEXT_FILE}"}

    modules_data = data.get("modules", {})
    modules_metrics: Dict[str, Any] = {}
    all_upcoming_deadlines: List[Dict[str, Any]] = []

    for mod_code, mod_info in modules_data.items():
        # 1. Lecture deficit: taught vs learnt
        taught_str = mod_info.get("lectures", {}).get("taught", "0/0")
        learnt_str = mod_info.get("lectures", {}).get("learnt", "0/0")
        taught_count, total_lectures = _parse_fraction(taught_str)
        learnt_count, _ = _parse_fraction(learnt_str)
        lecture_deficit = max(0, taught_count - learnt_count)

        # 2. Courseworks & Assessments
        unsubmitted_cw_marks = 0
        mod_deadlines: List[Dict[str, Any]] = []

        courseworks = mod_info.get("Courseworks", {})
        for cw_name, cw_info in courseworks.items():
            is_submitted = cw_info.get("Is submitted", False)
            pct = cw_info.get("Percentage", 0)
            deadline_str = cw_info.get("Deadline", "")
            d_date = _parse_date(deadline_str)

            if not is_submitted:
                unsubmitted_cw_marks += pct

            days_remaining = (d_date - today).days if d_date else None

            deadline_entry = {
                "module": mod_code,
                "item": cw_name,
                "type": "Coursework",
                "percentage": pct,
                "deadline": deadline_str,
                "days_remaining": days_remaining,
                "is_released": cw_info.get("Is released", False),
                "is_submitted": is_submitted,
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

            deadline_entry = {
                "module": mod_code,
                "item": ass_name,
                "type": "Assessment",
                "percentage": pct,
                "deadline": date_str,
                "days_remaining": days_remaining,
                "is_released": True,
                "is_submitted": days_remaining is not None and days_remaining < 0,
            }

            if days_remaining is not None and days_remaining >= 0:
                all_upcoming_deadlines.append(deadline_entry)
            mod_deadlines.append(deadline_entry)

        modules_metrics[mod_code] = {
            "future_relevance": mod_info.get("Future Relevance", "unknown"),
            "lectures": {
                "taught": taught_count,
                "learnt": learnt_count,
                "total": total_lectures,
                "deficit": lecture_deficit,
            },
            "unsubmitted_coursework_marks": unsubmitted_cw_marks,
            "deadlines": mod_deadlines,
        }

    # Sort upcoming items chronologically by days_remaining
    all_upcoming_deadlines.sort(
        key=lambda x: x["days_remaining"] if x["days_remaining"] is not None else 9999
    )

    return {
        "status": "success",
        "reference_date": today.strftime("%d-%m-%Y"),
        "modules": modules_metrics,
        "upcoming_deadlines_sorted": all_upcoming_deadlines,
    }
