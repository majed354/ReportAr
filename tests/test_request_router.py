import unittest

from report_worker.request_router import is_chart_request, needs_web_research


class RequestRouterTests(unittest.TestCase):
    def test_formal_text_is_not_mistaken_for_chart(self):
        self.assertFalse(is_chart_request("أريد تقريرًا رسميًا عن الأداء"))

    def test_religion_and_dynamic_topics_are_both_chart_requests(self):
        self.assertTrue(is_chart_request("مخطط عن نسبة الأديان"))
        self.assertTrue(is_chart_request("اختبار المخططات الديناميكية"))

    def test_current_chart_without_numbers_needs_research(self):
        self.assertTrue(needs_web_research("أنشئ مخططًا عن أحدث نسب الاستخدام عالميًا"))


if __name__ == "__main__":
    unittest.main()
