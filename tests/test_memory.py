"""Unit tests verifying cross-session student memory, profile preferences, and custom modules/tasks."""

import unittest
from study_agent.db import (
    add_custom_task,
    clear_history,
    get_custom_tasks,
    get_preferences,
    set_preference,
)
from study_agent.tools import (
    add_academic_task,
    calculate_study_metrics,
    get_student_memory,
    get_study_context,
    save_student_preference,
)


class TestStudentMemory(unittest.TestCase):

    def setUp(self):
        clear_history()

    def tearDown(self):
        clear_history()

    def test_student_preferences_persistence(self):
        """Verify student preferences persist across calls and are isolated per user."""
        res1 = save_student_preference(key="preferred_name", value="John", user_id="student_john")
        self.assertEqual(res1["status"], "success")

        save_student_preference(key="block_duration", value="30 mins", user_id="student_john")

        # Separate user
        save_student_preference(key="preferred_name", value="Alice", user_id="student_alice")

        john_prefs = get_preferences("student_john")
        self.assertEqual(john_prefs.get("preferred_name"), "John")
        self.assertEqual(john_prefs.get("block_duration"), "30 mins")

        alice_prefs = get_preferences("student_alice")
        self.assertEqual(alice_prefs.get("preferred_name"), "Alice")
        self.assertNotIn("block_duration", alice_prefs)

    def test_custom_academic_tasks_integration(self):
        """Verify adding a custom module dynamically incorporates into metrics calculations."""
        # Add a custom module: Computer Networks (CN) with Coursework 1 due 25-10-2026 (15 days away from 10-10-2026)
        res = add_academic_task(
            module="CN",
            task_name="Coursework 1",
            deadline="25-10-2026",
            percentage=25.0,
            is_coursework=True,
            user_id="student_john",
        )
        self.assertEqual(res["status"], "success")

        # Verify get_study_context merges CN
        ctx = get_study_context(user_id="student_john")
        self.assertIn("CN", ctx["modules"])
        self.assertIn("Coursework 1", ctx["modules"]["CN"]["Courseworks"])

        # Verify calculate_study_metrics includes CN in upcoming deadlines and metrics
        metrics = calculate_study_metrics(ref_date_str="10-10-2026", user_id="student_john")
        self.assertIn("CN", metrics["modules"])
        cn_metrics = metrics["modules"]["CN"]
        self.assertEqual(cn_metrics["marks"]["actionable_coursework_marks_at_risk"], 25.0)

        # Check deadlines list contains CN Coursework 1
        cn_deadlines = [d for d in metrics["upcoming_deadlines_sorted"] if d["module"] == "CN"]
        self.assertTrue(len(cn_deadlines) > 0)
        self.assertEqual(cn_deadlines[0]["item"], "Coursework 1")
        self.assertEqual(cn_deadlines[0]["days_remaining"], 15)

    def test_get_student_memory_summary(self):
        """Verify get_student_memory returns preferences and custom tasks together."""
        save_student_preference(key="preferred_name", value="John", user_id="student_john")
        add_academic_task(
            module="NETWORKS",
            task_name="cw1",
            deadline="25-10-2026",
            percentage=20.0,
            user_id="student_john",
        )

        mem = get_student_memory(user_id="student_john")
        self.assertEqual(mem["status"], "success")
        self.assertEqual(mem["preferences"]["preferred_name"], "John")
        self.assertEqual(len(mem["custom_tasks"]), 1)
        self.assertEqual(mem["custom_tasks"][0]["module"], "NETWORKS")


if __name__ == "__main__":
    unittest.main()
