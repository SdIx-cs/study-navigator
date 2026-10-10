"""Durable storage for study interventions and session audits.

Adapted from DevCamp db.py:
Provides local SQLite persistence for confirmed interventions and session lifecycle records,
ensuring history survives process restarts and session terminations.
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
        conn.commit()


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


def get_intervention_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves applied interventions in reverse chronological order."""
    init_db()
    with _get_connection() as conn:
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


def clear_history() -> None:
    """Clears all persisted interventions (used for testing)."""
    init_db()
    with _get_connection() as conn:
        conn.execute("DELETE FROM applied_interventions")
        conn.commit()
