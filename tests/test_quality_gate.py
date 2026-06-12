import unittest

from report_worker.quality_gate import review_output_quality


class QualityGateTests(unittest.TestCase):
    def test_blocks_public_audit_and_ai_language(self):
        result = review_output_quality(
            {
                "status": "ready_to_render",
                "report": {
                    "title": "تقرير آلي",
                    "subtitle": "",
                    "executive_summary": "المذكور 10 والمحسوب 12",
                    "sections": [],
                    "kpis": [],
                    "recommendations": [],
                    "unresolved_notes": [],
                },
            }
        )
        self.assertFalse(result["ok"])
        self.assertIn("تقرير آلي", result["blockers"])
        self.assertIn("المذكور", result["blockers"])

    def test_allows_clean_report_with_minor_warnings(self):
        result = review_output_quality(
            {
                "status": "ready_to_render",
                "report": {
                    "title": "تقرير الأداء",
                    "subtitle": "",
                    "executive_summary": "يعرض التقرير أبرز النتائج.",
                    "sections": [],
                    "kpis": [],
                    "recommendations": [],
                    "unresolved_notes": [],
                },
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["blockers"], [])


if __name__ == "__main__":
    unittest.main()
