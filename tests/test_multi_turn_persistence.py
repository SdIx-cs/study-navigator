"""Test Multi-Turn Session Persistence and State Logging across Turns."""

import asyncio
import io
import pathlib
import sys
import unittest
from unittest.mock import patch

from google.adk.events.event import Event, EventActions
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from study_agent.db import init_db
from study_agent.pipeline import process_study_message


class TestMultiTurnSessionPersistence(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        init_db()
        self.db_path = pathlib.Path(__file__).parent / "test_session_persist.db"
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except Exception:
                pass
        self.db_url = f"sqlite+aiosqlite:///{self.db_path.as_posix()}"
        self.session_service = DatabaseSessionService(db_url=self.db_url)

    async def asyncTearDown(self):
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except Exception:
                pass

    async def test_multi_turn_durable_state_pipeline(self):
        """Simulates 3 consecutive turns through DatabaseSessionService and verifies state survives across turns."""
        user_id = "student_persist_test"
        session_id = "sess_persist_123"

        # Turn 1: User asks checkin
        session = await self.session_service.get_session(
            app_name="study_navigator", user_id=user_id, session_id=session_id
        )
        if not session:
            session = await self.session_service.create_session(
                app_name="study_navigator", user_id=user_id, session_id=session_id
            )

        storage_state_t1 = dict(session.state) if session and session.state else {}
        self.assertEqual(storage_state_t1, {})  # Initially empty before defaults

        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            out1, final_state1, mut1 = process_study_message(
                message="What's best to do now?",
                current_state=storage_state_t1,
                user_id=user_id,
                session_id=session_id,
            )

        # Verify required one-line logs were printed
        stdout_t1 = captured_stdout.getvalue()
        self.assertIn("[STATE AT REDUCER START] {}", stdout_t1)
        self.assertIn("[STATE AT PLANNER START]", stdout_t1)

        # Persist final_state1 into DatabaseSessionService SQLite
        await self.session_service.append_event(
            session,
            Event(
                author="agent",
                content=types.Content(parts=[types.Part(text=out1.text)]),
                actions=EventActions(state_delta=final_state1),
            ),
        )

        # Turn 2: User confirms proposal ("yes")
        # Read FRESH from storage
        session_t2 = await self.session_service.get_session(
            app_name="study_navigator", user_id=user_id, session_id=session_id
        )
        storage_state_t2 = dict(session_t2.state) if session_t2 and session_t2.state else {}

        # Critical assertion: The state read from storage MUST contain Turn 1's pending proposal!
        self.assertEqual(storage_state_t2.get("pending_proposal"), "SWITCH")
        self.assertEqual(storage_state_t2.get("slice_stage"), "awaiting_confirmation")

        captured_stdout_t2 = io.StringIO()
        with patch("sys.stdout", captured_stdout_t2):
            out2, final_state2, mut2 = process_study_message(
                message="Yes, please apply this intervention.",
                current_state=storage_state_t2,
                user_id=user_id,
                session_id=session_id,
            )

        stdout_t2 = captured_stdout_t2.getvalue()
        # Verify reducer saw the persisted state at start
        self.assertIn('"pending_proposal": "SWITCH"', stdout_t2)
        self.assertIn('"slice_stage": "awaiting_confirmation"', stdout_t2)

        # Persist final_state2 into DatabaseSessionService SQLite
        await self.session_service.append_event(
            session_t2,
            Event(
                author="agent",
                content=types.Content(parts=[types.Part(text=out2.text)]),
                actions=EventActions(state_delta=final_state2),
            ),
        )

        # Turn 3: Read FRESH from storage again
        session_t3 = await self.session_service.get_session(
            app_name="study_navigator", user_id=user_id, session_id=session_id
        )
        storage_state_t3 = dict(session_t3.state) if session_t3 and session_t3.state else {}

        self.assertIsNotNone(storage_state_t3.get("active_intervention"))
        self.assertEqual(storage_state_t3.get("active_intervention", {}).get("intervention"), "SWITCH")
        self.assertEqual(storage_state_t3.get("approval_status"), "approved")


if __name__ == "__main__":
    unittest.main()
