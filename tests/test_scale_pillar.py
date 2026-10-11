"""Scale Pillar (Lab 2) Validation Test Suite.

Verifies:
1. Agent Runtime config & engine resolution (APP_URL parsing).
2. Externalized Session Persistence (DatabaseSessionService survives scale-to-zero container restart).
3. Multi-user isolation across sessions and durable memory bank.
"""

import asyncio
import os
import pathlib
import unittest

from google.adk.events.event import Event
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from study_agent.config import resolve_agent_engine, resolve_project
from study_agent.db import get_preferences, init_db, set_preference


class TestScalePillar(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        init_db()
        self.test_db_path = pathlib.Path(__file__).parent / "test_scale_sessions.db"
        if self.test_db_path.exists():
            try:
                self.test_db_path.unlink()
            except Exception:
                pass
        self.db_url = f"sqlite+aiosqlite:///{self.test_db_path.as_posix()}"

    async def asyncTearDown(self):
        if self.test_db_path.exists():
            try:
                self.test_db_path.unlink()
            except Exception:
                pass

    def test_agent_runtime_resolution(self):
        """Validates that APP_URL injected by Google Cloud Agent Runtime is parsed correctly."""
        # Scenario A: Local dev (no APP_URL)
        os.environ.pop("APP_URL", None)
        os.environ.pop("AGENT_ENGINE_ID", None)
        self.assertIsNone(resolve_agent_engine())

        # Scenario B: Agent Runtime deployed container
        os.environ["APP_URL"] = (
            "https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/"
            "projects/123456789/locations/us-central1/reasoningEngines/987654321/api"
        )
        resolved = resolve_agent_engine()
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["project"], "123456789")
        self.assertEqual(resolved["location"], "us-central1")
        self.assertEqual(resolved["engine"], "987654321")

        # Cleanup
        os.environ.pop("APP_URL", None)

    async def test_session_survives_scale_to_zero_restart(self):
        """Simulates container termination and rebirth: conversation state must survive."""
        # 1. Container Instance 1 creates a session and records a turn
        service_instance_1 = DatabaseSessionService(db_url=self.db_url)
        initial_state = {
            "slice_stage": "awaiting_confirmation",
            "pending_proposal": "SHRINK",
            "proposal_details": {"intervention": "SHRINK", "target": "AI Coursework 1"},
        }
        session_1 = await service_instance_1.create_session(
            app_name="study_navigator",
            user_id="student_scale_test",
            session_id="sess_101",
            state=initial_state,
        )
        
        event = Event(
            author="agent",
            content=types.Content(parts=[types.Part(text="Proposed 30-minute sprint.")]),
        )
        await service_instance_1.append_event(session_1, event)

        # 2. Simulate Container Scale-to-Zero (Process Memory Destroyed)
        del service_instance_1
        del session_1

        # 3. Container Instance 2 boots up in a new process / container
        service_instance_2 = DatabaseSessionService(db_url=self.db_url)
        recovered_session = await service_instance_2.get_session(
            app_name="study_navigator", user_id="student_scale_test", session_id="sess_101"
        )

        self.assertIsNotNone(recovered_session)
        self.assertEqual(recovered_session.state.get("slice_stage"), "awaiting_confirmation")
        self.assertEqual(recovered_session.state.get("pending_proposal"), "SHRINK")
        self.assertEqual(recovered_session.state.get("proposal_details", {}).get("target"), "AI Coursework 1")
        self.assertEqual(len(recovered_session.events), 1)
        self.assertIn("Proposed 30-minute sprint", recovered_session.events[0].content.parts[0].text)

    async def test_multi_user_session_and_memory_isolation(self):
        """Ensures student A and student B have partitioned session state and preferences."""
        service = DatabaseSessionService(db_url=self.db_url)

        # User A session
        sess_a = await service.create_session(
            app_name="study_navigator",
            user_id="student_alpha",
            session_id="sess_alpha",
            state={"pending_proposal": "REST"},
        )
        await service.append_event(
            sess_a, Event(author="user", content=types.Content(parts=[types.Part(text="Alpha check-in")]))
        )

        # User B session
        sess_b = await service.create_session(
            app_name="study_navigator",
            user_id="student_beta",
            session_id="sess_beta",
            state={"pending_proposal": "SWITCH"},
        )
        await service.append_event(
            sess_b, Event(author="user", content=types.Content(parts=[types.Part(text="Beta check-in")]))
        )

        # Verify session state isolation
        loaded_a = await service.get_session(app_name="study_navigator", user_id="student_alpha", session_id="sess_alpha")
        loaded_b = await service.get_session(app_name="study_navigator", user_id="student_beta", session_id="sess_beta")

        self.assertEqual(loaded_a.state.get("pending_proposal"), "REST")
        self.assertEqual(loaded_b.state.get("pending_proposal"), "SWITCH")

        # Verify durable memory bank isolation
        set_preference("student_alpha", "preferred_name", "AlphaStudent")
        set_preference("student_beta", "preferred_name", "BetaStudent")

        self.assertEqual(get_preferences("student_alpha")["preferred_name"], "AlphaStudent")
        self.assertEqual(get_preferences("student_beta")["preferred_name"], "BetaStudent")


if __name__ == "__main__":
    unittest.main()
