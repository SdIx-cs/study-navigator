"""Durable storage for study interventions, student preferences, and custom modules/tasks.

Adapted from DevCamp db.py:
Provides local SQLite persistence for:
1. Confirmed interventions and session audits (survives restarts).
2. Cross-session student preferences (e.g., preferred name, block duration, fatigue sensitivities).
3. Dynamic user-enrolled modules and academic tasks across sessions.
"""

import datetime
import json
import logging
import os
import pathlib
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DB_PATH = pathlib.Path(__file__).resolve().parents[1] / "study_navigator.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes the database schema if not already present."""
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applied_interventions (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                intervention TEXT NOT NULL,
                target_module TEXT NOT NULL,
                details TEXT NOT NULL,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'applied'
            )
            """
        )
        try:
            conn.execute("ALTER TABLE applied_interventions ADD COLUMN status TEXT NOT NULL DEFAULT 'applied'")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS student_preferences (
                user_id TEXT NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, pref_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_academic_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                module TEXT NOT NULL,
                task_name TEXT NOT NULL,
                deadline TEXT NOT NULL,
                percentage REAL NOT NULL,
                is_coursework INTEGER NOT NULL DEFAULT 1,
                is_submitted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS module_progress (
                user_id TEXT NOT NULL,
                module TEXT NOT NULL,
                lectures_learnt INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, module)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS completed_deliverables (
                user_id TEXT NOT NULL,
                module TEXT NOT NULL,
                deliverable TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, module, deliverable)
            )
            """
        )
        conn.commit()


# --- Interventions Audit ------------------------------------------------------

def record_intervention(
    intervention: str,
    target_module: str,
    details: str,
    user_id: str = "default_user",
    session_id: str = "",
    status: str = "applied",
) -> Dict[str, Any]:
    """Persists an applied intervention record to the database."""
    init_db()
    rec_id = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    record = {
        "id": rec_id,
        "timestamp": now_iso,
        "intervention": intervention,
        "target_module": target_module,
        "details": details,
        "user_id": user_id,
        "session_id": session_id,
        "status": status,
    }

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO applied_interventions (id, timestamp, intervention, target_module, details, user_id, session_id, status)
            VALUES (:id, :timestamp, :intervention, :target_module, :details, :user_id, :session_id, :status)
            """,
            record,
        )
        conn.commit()

    log.info("Persisted intervention record %s (%s on %s, status=%s)", rec_id, intervention, target_module, status)
    return record


def update_latest_intervention_status(
    user_id: str, new_status: str, details_suffix: str = ""
) -> Optional[Dict[str, Any]]:
    """Updates the status of the most recent applied intervention for a user."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, intervention, target_module, details, status
            FROM applied_interventions
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        rec_id = row["id"]
        updated_details = row["details"]
        if details_suffix:
            updated_details = f"{updated_details} | {details_suffix}"
        conn.execute(
            """
            UPDATE applied_interventions
            SET status = ?, details = ?
            WHERE id = ?
            """,
            (new_status, updated_details, rec_id),
        )
        conn.commit()
        return {
            "id": rec_id,
            "intervention": row["intervention"],
            "target_module": row["target_module"],
            "status": new_status,
        }


def mark_custom_task_completed(user_id: str, task_or_module: str) -> bool:
    """Marks matching custom coursework task as submitted/completed."""
    init_db()
    with _get_connection() as conn:
        term = f"%{task_or_module.lower().strip()}%"
        cursor = conn.execute(
            """
            UPDATE custom_academic_tasks
            SET is_submitted = 1
            WHERE user_id = ? AND (LOWER(task_name) LIKE ? OR LOWER(module) LIKE ?)
            """,
            (user_id, term, term),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_intervention_history(limit: int = 50, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves applied interventions in reverse chronological order."""
    init_db()
    with _get_connection() as conn:
        if user_id:
            cursor = conn.execute(
                """
                SELECT id, timestamp, intervention, target_module, details, user_id, session_id, status
                FROM applied_interventions
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, timestamp, intervention, target_module, details, user_id, session_id, status
                FROM applied_interventions
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


# --- Student Preferences (Cross-Session Memory) --------------------------------

def set_preference(user_id: str, key: str, value: str) -> None:
    """Saves or updates a student preference (e.g. name, work style)."""
    init_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO student_preferences (user_id, pref_key, pref_value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, pref_key) DO UPDATE SET
                pref_value = excluded.pref_value,
                updated_at = excluded.updated_at
            """,
            (user_id, key.strip().lower(), str(value).strip(), now_iso),
        )
        conn.commit()


def get_preferences(user_id: str = "default_user") -> Dict[str, str]:
    """Retrieves all stored preferences for a user, falling back to default_user if not found."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT pref_key, pref_value
            FROM student_preferences
            WHERE user_id = ?
            """,
            (user_id,),
        )
        res = {row["pref_key"]: row["pref_value"] for row in cursor.fetchall()}
        if not res and user_id != "default_user":
            cursor = conn.execute(
                """
                SELECT pref_key, pref_value
                FROM student_preferences
                WHERE user_id = 'default_user'
                """
            )
            res = {row["pref_key"]: row["pref_value"] for row in cursor.fetchall()}
        return res


# --- Custom Academic Tasks & Dynamic Modules ----------------------------------

def add_custom_task(
    user_id: str,
    module: str,
    task_name: str,
    deadline: str,
    percentage: float,
    is_coursework: bool = True,
) -> Dict[str, Any]:
    """Adds a custom academic task/deliverable for a student."""
    init_db()
    rec_id = f"task_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    record = {
        "id": rec_id,
        "user_id": user_id,
        "module": module.strip().upper(),
        "task_name": task_name.strip(),
        "deadline": deadline.strip(),
        "percentage": float(percentage),
        "is_coursework": 1 if is_coursework else 0,
        "is_submitted": 0,
        "created_at": now_iso,
    }

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO custom_academic_tasks (id, user_id, module, task_name, deadline, percentage, is_coursework, is_submitted, created_at)
            VALUES (:id, :user_id, :module, :task_name, :deadline, :percentage, :is_coursework, :is_submitted, :created_at)
            """,
            record,
        )
        conn.commit()
    return record


def get_custom_tasks(user_id: str = "default_user") -> List[Dict[str, Any]]:
    """Retrieves all active custom tasks for a user, falling back to default_user if none found."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, user_id, module, task_name, deadline, percentage, is_coursework, is_submitted, created_at
            FROM custom_academic_tasks
            WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        if not rows and user_id != "default_user":
            cursor = conn.execute(
                """
                SELECT id, user_id, module, task_name, deadline, percentage, is_coursework, is_submitted, created_at
                FROM custom_academic_tasks
                WHERE user_id = 'default_user'
                ORDER BY created_at ASC
                """
            )
            rows = cursor.fetchall()

        return [
            {
                "id": r["id"],
                "module": r["module"],
                "task_name": r["task_name"],
                "deadline": r["deadline"],
                "percentage": r["percentage"],
                "is_coursework": bool(r["is_coursework"]),
                "is_submitted": bool(r["is_submitted"]),
            }
            for r in rows
        ]


def update_module_lectures(user_id: str, module: str, count: int, is_delta: bool = True) -> int:
    """Updates the number of lectures learnt for a user on a given module."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT lectures_learnt FROM module_progress WHERE user_id = ? AND module = ?",
            (user_id, module.upper()),
        )
        row = cursor.fetchone()
        current = row["lectures_learnt"] if row else 0
        new_val = max(0, current + count if is_delta else count)
        conn.execute(
            """
            INSERT INTO module_progress (user_id, module, lectures_learnt, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, module) DO UPDATE SET
                lectures_learnt = excluded.lectures_learnt,
                updated_at = excluded.updated_at
            """,
            (user_id, module.upper(), new_val, datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()
        return new_val


def get_all_module_progress(user_id: str) -> Dict[str, int]:
    """Retrieves map of module -> lectures_learnt for a user."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT module, lectures_learnt FROM module_progress WHERE user_id = ?",
            (user_id,),
        )
        return {r["module"]: r["lectures_learnt"] for r in cursor.fetchall()}


def mark_deliverable_completed(user_id: str, module: str, deliverable: str) -> None:
    """Records that a syllabus or custom deliverable has been completed/submitted."""
    init_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO completed_deliverables (user_id, module, deliverable, completed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, module, deliverable) DO UPDATE SET completed_at = excluded.completed_at
            """,
            (user_id, module.upper().strip(), deliverable.lower().strip(), now_iso),
        )
        conn.commit()


def get_completed_deliverables(user_id: str = "default_user") -> List[Dict[str, str]]:
    """Retrieves all completed deliverables for a student."""
    init_db()
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT module, deliverable FROM completed_deliverables WHERE user_id = ?",
            (user_id,),
        )
        rows = cursor.fetchall()
        if not rows and user_id != "default_user":
            cursor = conn.execute(
                "SELECT module, deliverable FROM completed_deliverables WHERE user_id = 'default_user'",
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]


def clear_history() -> None:
    """Clears all persisted data (used for testing)."""
    init_db()
    with _get_connection() as conn:
        conn.execute("DELETE FROM applied_interventions")
        conn.execute("DELETE FROM student_preferences")
        conn.execute("DELETE FROM custom_academic_tasks")
        conn.execute("DELETE FROM module_progress")
        conn.execute("DELETE FROM completed_deliverables")
        conn.commit()
