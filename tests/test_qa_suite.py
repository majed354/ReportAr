import unittest

from pathlib import Path
import tempfile
from unittest.mock import patch

from report_worker.qa_suite import Scenario, evaluate_output, run_local_qa_suite, scenarios


class QaSuiteTests(unittest.TestCase):
    def test_suite_contains_ten_distinct_scenarios(self):
        cases = scenarios()
        self.assertEqual(len(cases), 10)
        self.assertEqual(len({case.id for case in cases}), 10)
        self.assertTrue(any(len(case.report_text) > 24_000 for case in cases))

    def test_evaluator_detects_missing_chart_and_public_audit_language(self):
        scenario = Scenario(
            id="test",
            name="test",
            mode="fast",
            report_text="x",
            expected_charts=("time_trend",),
        )
        output = {
            "version": "1.0",
            "mode": "fast",
            "status": "ready_to_render",
            "user_message": "",
            "questions": [],
            "audit": {
                "issues": [],
                "missing_information": [],
                "contradictions": [],
                "rejected_instructions": [],
            },
            "decisions": {},
            "report": {"title": "المذكور والمحسوب"},
            "chart_intents": [],
        }
        checks = evaluate_output(scenario, output, None, None)
        failures = [check["name"] for check in checks if not check["passed"]]
        self.assertIn("عدم نشر عبارات محظورة", failures)
        self.assertIn("أنواع المخططات المطلوبة", failures)

    @patch("report_worker.qa_suite.generate_report")
    def test_suite_can_filter_selected_scenarios(self, generate):
        generate.side_effect = RuntimeError("expected test stop")
        from report_worker.config import Settings

        with tempfile.TemporaryDirectory() as folder:
            result = run_local_qa_suite(
                Settings(),
                Path(folder),
                scenario_ids=["03-guided-critical-missing"],
            )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["id"], "03-guided-critical-missing")


if __name__ == "__main__":
    unittest.main()
