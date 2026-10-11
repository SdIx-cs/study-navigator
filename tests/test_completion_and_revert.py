import unittest
import asyncio
from study_agent.db import (
    clear_history,
    init_db,
    record_intervention,
    add_custom_task,
    get_custom_tasks,
    get_intervention_history,
    update_module_lectures,
    get_all_module_progress,
)
from study_agent.tools import (
    record_task_completion,
    revert_study_intervention,
    update_lecture_progress,
)


class TestCompletionAndRevert(unittest.TestCase):
    def setUp(self):
        clear_history()
        init_db()

    def test_record_task_completion_updates_intervention_and_coursework(self):
        # 1. Simulate an applied intervention for AI Coursework 1
        record_intervention(
            intervention="SWITCH",
            target_module="AI Coursework 1",
            details="Pivot to coursework due in 10 days",
            user_id="test_student",
            session_id="sess_123",
        )
        # 2. Add an academic task
        add_custom_task(
            user_id="test_student",
            module="AI",
            task_name="AI Coursework 1",
            deadline="21-10-2026",
            percentage=30.0,
            is_coursework=True,
        )

        # 3. Call record_task_completion
        res = record_task_completion(
            task_or_module="AI Coursework 1",
            notes="Finished code implementation and test suite",
            user_id="test_student",
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["coursework_marked_submitted"])

        # 4. Verify DB status
        history = get_intervention_history(limit=5, user_id="test_student")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "completed")

        tasks = get_custom_tasks(user_id="test_student")
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["is_submitted"])

    def test_revert_study_intervention_restores_prior_standing(self):
        # 1. Simulate applied intervention
        record_intervention(
            intervention="SWITCH",
            target_module="AI Coursework 1",
            details="Pivot to AI Coursework 1",
            user_id="test_student",
            session_id="sess_123",
        )

        # 2. Revert intervention
        res = revert_study_intervention(
            reason="Student requested rollback",
            user_id="test_student",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["reverted_intervention"], "SWITCH")

        # 3. Verify DB status
        history = get_intervention_history(limit=5, user_id="test_student")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "reverted")

    def test_task_completion_does_not_mutate_unrelated_lecture_progress(self):
        # Set up DB lectures at 6
        update_module_lectures("test_student", "DB", 6, is_delta=False)
        self.assertEqual(get_all_module_progress("test_student")["DB"], 6)

        # Call record_task_completion for AI Coursework 1
        record_task_completion(
            task_or_module="AI Coursework 1",
            notes="Session complete",
            user_id="test_student",
        )

        # DB lectures MUST remain strictly unchanged at 6
        self.assertEqual(get_all_module_progress("test_student")["DB"], 6)

    def test_task_completion_syncs_to_syllabus_metrics_and_clears_actionable_status(self):
        from study_agent.tools import calculate_study_metrics
        # 1. Before completion, AI cw1 is actionable (30% marks at risk)
        metrics_before = calculate_study_metrics(ref_date_str="11-10-2026", user_id="test_student")
        ai_before = metrics_before["modules"]["AI"]
        self.assertEqual(ai_before["marks"]["actionable_coursework_marks_at_risk"], 30)

        # 2. Record completion of AI cw1
        record_task_completion(
            task_or_module="AI Coursework 1",
            notes="Submitted AI coursework 1",
            user_id="test_student",
        )

        # 3. After completion, AI cw1 is marked submitted and actionable marks at risk drop to 0!
        metrics_after = calculate_study_metrics(ref_date_str="11-10-2026", user_id="test_student")
        ai_after = metrics_after["modules"]["AI"]
        self.assertEqual(ai_after["marks"]["actionable_coursework_marks_at_risk"], 0)
        self.assertEqual(ai_after["marks"]["total_unsubmitted_coursework_marks"], 10)  # cw2 (10%) remains unreleased


if __name__ == "__main__":
    unittest.main()
