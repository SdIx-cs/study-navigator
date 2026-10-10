"""Unit tests verifying SQLite persistence for applied interventions (Milestone 5)."""

import pathlib
import sys
import unittest

STUDY_NAV_PATH = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_NAV_PATH))

from study_agent.db import clear_history, get_intervention_history, record_intervention
from study_agent.tools import apply_study_intervention


class TestPersistence(unittest.TestCase):

    def setUp(self):
        clear_history()

    def tearDown(self):
        clear_history()

    def test_direct_record_and_list(self):
        rec = record_intervention(
            intervention="SWITCH",
            target_module="AI",
            details="Switch to AI coursework 1 for 45 minutes",
            user_id="test_student",
            session_id="session_101",
        )
        self.assertIsNotNone(rec.get("id"))
        self.assertEqual(rec["intervention"], "SWITCH")
        self.assertEqual(rec["target_module"], "AI")

        history = get_intervention_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["intervention"], "SWITCH")
        self.assertEqual(history[0]["target_module"], "AI")
        self.assertEqual(history[0]["session_id"], "session_101")

    def test_apply_tool_persists_to_db(self):
        result = apply_study_intervention(
            intervention="REST",
            target_module="GENERAL",
            details="30 minute recovery walk",
        )
        self.assertEqual(result["status"], "applied")
        self.assertIsNotNone(result.get("record_id"))

        history = get_intervention_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["intervention"], "REST")
        self.assertEqual(history[0]["target_module"], "GENERAL")
        self.assertIn("30 minute recovery walk", history[0]["details"])


if __name__ == "__main__":
    unittest.main()
