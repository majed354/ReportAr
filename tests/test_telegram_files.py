import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from docx import Document

from report_worker.settings_vault import SettingsVault
from report_worker.telegram_bot import (
    TelegramReportBot,
    format_report_preview,
    format_questions,
    review_message,
    report_setup_questions,
    visual_identity_questions,
)


class TelegramFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bot = TelegramReportBot(
            SettingsVault(Path(self.temp.name) / "settings.json")
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_extracts_txt(self):
        path = Path(self.temp.name) / "report.txt"
        path.write_text("هذا تقرير عربي تجريبي يحتوي على نص كافٍ للاختبار.", encoding="utf-8")
        self.assertIn("تقرير عربي", self.bot._extract_text(path))

    def test_extracts_docx(self):
        path = Path(self.temp.name) / "report.docx"
        document = Document()
        document.add_paragraph("هذا تقرير عربي تجريبي يحتوي على نص كافٍ للاختبار.")
        document.save(path)
        self.assertIn("تقرير عربي", self.bot._extract_text(path))

    def test_guided_visual_identity_questions_cover_required_choices(self):
        questions = visual_identity_questions("تقرير أداء عام")
        self.assertEqual(
            [question["id"] for question in questions],
            ["identity_assets", "cover_background", "visual_style", "color_palette"],
        )
        rendered = format_questions(questions)
        self.assertIn("شعار أو ختم", rendered)
        self.assertIn("خلفيات الصفحات", rendered)
        self.assertIn("النمط البصري", rendered)
        self.assertIn("لوحة الألوان", rendered)

    def test_guided_visual_identity_does_not_repeat_explicit_choices(self):
        questions = visual_identity_questions(
            "استخدم شعار الجهة مع خلفية بيضاء وتصميم رسمي وألوان الشعار"
        )
        self.assertEqual(questions, [])

    def test_review_message_keeps_audit_outside_report(self):
        message = review_message(
            {
                "audit": {
                    "contradictions": [{"note": "يوجد فرق يحتاج اعتمادًا."}],
                    "missing_information": ["رقم الإصدار"],
                }
            }
        )
        self.assertIn("خارج التقرير", message)
        self.assertIn("يوجد فرق", message)
        self.assertIn("رقم الإصدار", message)

    async def _run_guided_preflight(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"report_mode": "guided"}
        await self.bot._process_report(update, context, "تقرير أداء عام يحتاج تنسيقًا")
        return update, context

    def test_guided_path_starts_with_visual_identity_preflight(self):
        import asyncio

        update, context = asyncio.run(self._run_guided_preflight())
        sent = update.message.reply_text.call_args.args[0]
        self.assertIn("مساعد إعداد التقرير", sent)
        self.assertIn("صورة التقرير", sent)
        self.assertIn("الشعار والصور", sent)
        self.assertEqual(context.user_data["guided_output"]["stage"], "report_setup")

    def test_report_setup_questions_always_include_professional_choices(self):
        questions = report_setup_questions("استخدم شعار الجهة وتصميم رسمي وألوان الشعار")
        ids = [question["id"] for question in questions]
        self.assertEqual(
            ids,
            ["delivery_profile", "visual_style", "brand_assets", "evidence_and_charts"],
        )
        rendered = format_questions(questions)
        self.assertIn("نمط بصري", rendered)
        self.assertIn("الشعار والصور", rendered)
        self.assertIn("المصادر والمخططات", rendered)

    def test_preview_summarizes_report_before_pdf(self):
        message = format_report_preview(
            {
                "report": {
                    "title": "تقرير الأداء",
                    "subtitle": "ربع سنوي",
                    "sections": [{"heading": "أ", "body": "ب"}],
                    "kpis": [{"label": "الجودة", "value": 90, "unit": "%"}],
                },
                "decisions": {"theme_id": "data-dashboard"},
                "audit": {"missing_information": ["مصدر"], "contradictions": []},
                "chart_intents": [{"kind": "column_comparison"}],
            },
            {"model": "gemma4:31b"},
            [{"path": "/tmp/logo.jpg", "role": "logo", "file_name": "logo.jpg"}],
        )
        self.assertIn("معاينة قبل إنشاء PDF", message)
        self.assertIn("تقرير الأداء", message)
        self.assertIn("data-dashboard", message)
        self.assertIn("اعتماد PDF", message)

    def test_profile_identity_is_remembered_and_used_as_instruction(self):
        update = MagicMock()
        update.effective_user.id = 42
        self.bot._remember_output_identity(
            update,
            {"decisions": {"theme_id": "official-formal"}},
        )
        instruction = self.bot._profile_instruction(update)
        self.assertIn("official-formal", instruction)

    @patch("report_worker.telegram_bot.generate_report")
    def test_every_topic_is_sent_to_the_selected_model(self, generate):
        result = MagicMock()
        result.parsed = {"status": "ready_to_render", "report": {"title": "نتيجة مرنة"}}
        result.provider = "local"
        result.model = "gemma4:31b"
        generate.return_value = (result, False, None)
        output, provider = self.bot._generate(
            "fast", "أنشئ مخططًا عن نسبة الأديان في العالم"
        )
        self.assertEqual(output["report"]["title"], "نتيجة مرنة")
        self.assertEqual(provider["model"], "gemma4:31b")
        self.assertIn("نسبة الأديان", generate.call_args.kwargs["user"])


if __name__ == "__main__":
    unittest.main()
