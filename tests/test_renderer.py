import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from report_worker.renderer import _latex_error, render_report, tex, tex_bidi


class RendererTests(unittest.TestCase):
    def test_tex_bidi_wraps_mixed_latin_tokens(self):
        rendered = tex_bidi("تكامل Core_API مع R&D والحزمة release_candidate#2")
        self.assertIn(r"\foreignlanguage{english}{Core\_API}", rendered)
        self.assertIn(r"\foreignlanguage{english}{R\&D}", rendered)
        self.assertIn(r"\foreignlanguage{english}{release\_candidate\#2}", rendered)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_resolves_relative_output_paths(self, run):
        output = {
            "report": {
                "title": "اختبار",
                "subtitle": "",
                "executive_summary": "",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "chart_intents": [],
        }

        def compile_pdf(command, **kwargs):
            output_directory = Path(command[3].split("=", 1)[1])
            output_directory.mkdir(parents=True, exist_ok=True)
            (output_directory / "report.pdf").write_bytes(b"%PDF-test")
            return MagicMock(returncode=0, stdout="")

        run.side_effect = compile_pdf
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            relative = Path(folder).relative_to(Path.cwd())
            pdf = render_report(output, relative)
            environment = run.call_args.kwargs["env"]
            self.assertTrue(pdf.is_absolute())
            self.assertTrue(Path(environment["TEXMFCACHE"]).is_absolute())

    def test_tex_escapes_special_characters_without_double_escaping(self):
        escaped = tex(r"نسبة 85% & ملف_name")
        self.assertIn(r"85\%", escaped)
        self.assertIn(r"\&", escaped)
        self.assertIn(r"ملف\_name", escaped)
        self.assertEqual(tex(0), "0")

    def test_latex_error_ignores_trailing_warnings(self):
        output = """Underfull warning
! Dimension too large.
<to be read again>
l.98 chart command
Underfull trailing warning
!  ==> Fatal error occurred"""
        self.assertEqual(
            _latex_error(output),
            "Dimension too large. عند السطر 98: chart command",
        )

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_maps_general_chart_intents_to_templates(self, run):
        run.return_value.returncode = 0
        output = {
            "report": {
                "title": "تقرير عام",
                "subtitle": "",
                "executive_summary": "",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {"contradictions": [], "missing_information": []},
            "chart_intents": [
                {
                    "kind": "distribution_four",
                    "title": "توزيع الميزانية",
                    "values": [40, 30, 20, 10],
                    "labels": ["تقنية", "تشغيل", "تسويق", "تطوير"],
                    "reason": "مناسب للتوزيع",
                },
                {
                    "kind": "project_milestones",
                    "title": "مراحل المشروع",
                    "stages": [
                        {"label": "البدء", "date": "يناير"},
                        {"label": "التحليل", "date": "مارس"},
                        {"label": "التجربة", "date": "يونيو"},
                        {"label": "الإطلاق", "date": "أكتوبر"},
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            render_report(output, destination)
            document = (destination / "report.tex").read_text()
            self.assertIn(r"\chartDonutThreeD", document)
            self.assertIn(r"\chartTimelineDepth", document)
            self.assertNotIn("مناسب للتوزيع", document)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_keeps_audit_and_duplicate_sections_out_of_pdf(self, run):
        run.return_value.returncode = 0
        output = {
            "report": {
                "title": "تقرير نظيف",
                "subtitle": "",
                "executive_summary": "",
                "sections": [
                    {"heading": "مؤشرات الأداء الرئيسية", "body": "قسم مكرر"},
                    {"heading": "تحليل الخدمة", "body": "نص للنشر"},
                ],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {
                "contradictions": [
                    {"field": "x", "reported": "10", "calculated": "12", "note": "فرق"}
                ],
                "missing_information": ["مرجع"],
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            render_report(output, destination)
            document = (destination / "report.tex").read_text()
            self.assertIn("تحليل الخدمة", document)
            self.assertNotIn("قسم مكرر", document)
            self.assertNotIn("التعارضات الرقمية", document)
            self.assertNotIn(r"\textbf{المذكور}", document)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_scales_large_waterfall_values(self, run):
        run.return_value.returncode = 0
        output = {
            "report": {
                "title": "تقرير مالي",
                "subtitle": "",
                "executive_summary": "",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {"contradictions": [], "missing_information": []},
            "chart_intents": [
                {
                    "kind": "cumulative_change",
                    "title": "تغير الأرباح",
                    "start": 500000,
                    "changes": [
                        {"label": "المبيعات", "value": 220000},
                        {"label": "التشغيل", "value": -90000},
                        {"label": "التسويق", "value": -40000},
                        {"label": "التوفير", "value": 60000},
                    ],
                    "calculated_end": 650000,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            render_report(output, destination)
            document = (destination / "report.tex").read_text()
            self.assertIn("تغير الأرباح (بالآلاف)", document)
            self.assertIn("البداية/500", document)
            self.assertNotIn("البداية/500000", document)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_writes_tex_and_returns_pdf(self, run):
        run.return_value.returncode = 0
        output = {
            "report": {
                "title": "تقرير تجريبي",
                "subtitle": "",
                "executive_summary": "ملخص",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {"contradictions": [], "missing_information": []},
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            pdf = render_report(output, destination)
            self.assertTrue(pdf.exists())
            document = (destination / "report.tex").read_text()
            self.assertIn("تقرير تجريبي", document)
            self.assertNotIn("آلي", document)
            self.assertNotIn("الذكاء الاصطناعي", document)
            self.assertIn(
                r"\rule{\textwidth}{0.7pt}\par%",
                document,
            )
            self.assertEqual(run.call_count, 2)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_applies_selected_theme_and_logo_asset(self, run):
        run.return_value.returncode = 0
        output = {
            "decisions": {
                "theme_id": "heritage-elegant",
                "report_type": "heritage",
                "use_logo": True,
                "use_cover_image": False,
                "background_usage": "plain",
                "theme_reason": "",
                "decision_notes": [],
            },
            "report": {
                "title": "تقرير تراثي",
                "subtitle": "",
                "executive_summary": "ملخص",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {"contradictions": [], "missing_information": []},
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            logo = destination / "logo.png"
            logo.write_bytes(b"not-a-real-image")
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            render_report(output, destination, [{"path": str(logo), "file_name": "logo.png"}])
            document = (destination / "report.tex").read_text()
            self.assertIn(r"\definecolor{primary}{HTML}{A16207}", document)
            self.assertIn(r"\includegraphics", document)

    @patch("report_worker.renderer.subprocess.run")
    def test_renderer_places_cover_and_stamp_assets_by_role(self, run):
        run.return_value.returncode = 0
        output = {
            "decisions": {"theme_id": "official-formal"},
            "report": {
                "title": "تقرير رسمي",
                "subtitle": "",
                "executive_summary": "ملخص",
                "sections": [],
                "kpis": [],
                "recommendations": [],
            },
            "audit": {"contradictions": [], "missing_information": []},
        }
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            cover = destination / "cover.jpg"
            stamp = destination / "stamp.jpg"
            cover.write_bytes(b"cover")
            stamp.write_bytes(b"stamp")
            (destination / "report.pdf").write_bytes(b"%PDF-test")
            render_report(
                output,
                destination,
                [
                    {"path": str(cover), "file_name": "cover.jpg", "role": "cover"},
                    {"path": str(stamp), "file_name": "stamp.jpg", "role": "stamp"},
                ],
            )
            document = (destination / "report.tex").read_text()
            self.assertIn("height=4.2cm", document)
            self.assertIn(r"\begin{flushleft}", document)


if __name__ == "__main__":
    unittest.main()
