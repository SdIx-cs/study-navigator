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
                session_id TEXT NOT NULL
            )
            """
        )
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
        conn.commit()


# --- Interventions Audit ------------------------------------------------------

def record_intervention(
    intervention: str,
    target_module: str,
    details: str,
    user_id: str = "default_user",
    session_id: str = "",
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
    }

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO applied_interventions (id, timestamp, intervention, target_module, details, user_id, session_id)
            VALUES (:id, :timestamp, :intervention, :target_module, :details, :user_id, :session_id)
            """,
            record,
        )
        conn.commit()

    log.info("Persisted intervention record %s (%s on %s)", rec_id, intervention, target_module)
    return record


def get_intervention_history(limit: int = 50, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves applied interventions in reverse chronological order."""
    init_db()
    with _get_connection() as conn:
        if user_id:
            cursor = conn.execute(
                """
                SELECT id, timestamp, intervention, target_module, details, user_id, session_id
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
                SELECT id, timestamp, intervention, target_module, details, user_id, session_id
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


def clear_history() -> None:
    """Clears all persisted data (used for testing)."""
    init_db()
    with _get_connection() as conn:
        conn.execute("DELETE FROM applied_interventions")
        conn.execute("DELETE FROM student_preferences")
        conn.execute("DELETE FROM custom_academic_tasks")
        conn.commit()
