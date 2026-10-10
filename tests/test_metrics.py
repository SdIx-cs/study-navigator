"""Unit tests for deterministic metrics and decision context (Milestone 1)."""

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from study_agent.tools import calculate_study_metrics, _parse_date, _parse_fraction


class TestStudyMetrics(unittest.TestCase):
    """Test suite verifying correctness of deterministic metrics calculation."""

    def test_parse_date_formats(self):
        d1 = _parse_date("20-10-2026")
        self.assertIsNotNone(d1)
        self.assertEqual(d1.year, 2026)
        self.assertEqual(d1.month, 10)
        self.assertEqual(d1.day, 20)

        # Single digit month/day
        d2 = _parse_date("12-1-2027")
        self.assertIsNotNone(d2)
        self.assertEqual(d2.month, 1)

    def test_parse_fraction(self):
        num, den = _parse_fraction("7/10")
        self.assertEqual(num, 7)
        self.assertEqual(den, 10)

        num, den = _parse_fraction("invalid")
        self.assertEqual(num, 0)
        self.assertEqual(den, 0)

    def test_calculate_metrics_correctness(self):
        # Using fixed reference date 10-10-2026
        metrics = calculate_study_metrics(ref_date_str="10-10-2026")
        self.assertEqual(metrics["status"], "success")
        self.assertEqual(metrics["reference_date"], "10-10-2026")

        ai = metrics["modules"]["AI"]
        db = metrics["modules"]["DB"]

        # 1. Lecture deficits
        self.assertEqual(ai["lectures"]["taught"], 7)
        self.assertEqual(ai["lectures"]["learnt"], 4)
        self.assertEqual(ai["lectures"]["deficit"], 3)
        self.assertEqual(ai["lectures"]["estimated_catchup_hours"], 6.0)

        self.assertEqual(db["lectures"]["taught"], 8)
        self.assertEqual(db["lectures"]["learnt"], 3)
        self.assertEqual(db["lectures"]["deficit"], 5)
        self.assertEqual(db["lectures"]["estimated_catchup_hours"], 10.0)

        # 2. Marks at risk
        # AI: cw1 is released (30%), cw2 is unreleased (10%), exam is 60%
        self.assertEqual(ai["marks"]["actionable_coursework_marks_at_risk"], 30)
        self.assertEqual(ai["marks"]["total_unsubmitted_coursework_marks"], 40)
        self.assertEqual(ai["marks"]["upcoming_assessment_marks"], 60)
        self.assertEqual(ai["marks"]["total_module_marks_at_risk"], 100)

        # DB: cw1 is released (20%), Test 1 passed (-15d, 5%), Test 2 upcoming (5%), Exam upcoming (70%)
        self.assertEqual(db["marks"]["actionable_coursework_marks_at_risk"], 20)
        self.assertEqual(db["marks"]["completed_assessment_marks"], 5)
        self.assertEqual(db["marks"]["upcoming_assessment_marks"], 75)
        self.assertEqual(db["marks"]["total_module_marks_at_risk"], 95)

        # 3. Urgency and actionability
        # Nearest actionable item must be AI cw1 (10 days remaining, released, 30%)
        nearest = metrics["decision_context"]["nearest_actionable_deliverable"]
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest["module"], "AI")
        self.assertEqual(nearest["item"], "cw1")
        self.assertEqual(nearest["days_remaining"], 10)
        self.assertEqual(nearest["urgency"], "high")
        self.assertTrue(nearest["is_actionable"])

        # AI cw2 must be marked unreleased and not actionable right now
        cw2_item = next(d for d in ai["deadlines"] if d["item"] == "cw2")
        self.assertFalse(cw2_item["is_actionable"])
        self.assertEqual(cw2_item["actionability_status"], "blocked_unreleased")


if __name__ == "__main__":
    unittest.main()
