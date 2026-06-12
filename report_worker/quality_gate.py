from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PUBLIC_BLOCKERS = (
    "تقرير آلي",
    "أُنشئ آلي",
    "انشئ آلي",
    "الذكاء الاصطناعي",
    "نموذج لغوي",
    "المذكور",
    "المحسوب",
)


def _collect_public_text(output: dict[str, Any]) -> str:
    report = output.get("report") or {}
    pieces: list[str] = [
        str(report.get("title", "")),
        str(report.get("subtitle", "")),
        str(report.get("executive_summary", "")),
    ]
    pieces.extend(str(item) for item in report.get("recommendations", []))
    pieces.extend(str(item) for item in report.get("unresolved_notes", []))
    for section in report.get("sections", []):
        pieces.append(str(section.get("heading", "")))
        pieces.append(str(section.get("body", "")))
    return "\n".join(pieces)


def review_output_quality(output: dict[str, Any]) -> dict[str, Any]:
    public_text = _collect_public_text(output)
    blockers = [
        term for term in PUBLIC_BLOCKERS if re.search(re.escape(term), public_text)
    ]
    raw_report = output.get("report")
    report = raw_report or {}
    warnings: list[str] = []
    if not str(report.get("title", "")).strip():
        warnings.append("لا يوجد عنوان واضح للتقرير.")
    if not str(report.get("executive_summary", "")).strip():
        warnings.append("لا يوجد ملخص تنفيذي واضح.")
    if output.get("status") == "ready_to_render" and raw_report is None:
        blockers.append("التقرير غير موجود رغم أن الحالة جاهزة للتصدير.")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def review_render_log(pdf_path: Path) -> list[str]:
    log_path = pdf_path.with_suffix(".log")
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    notes: list[str] = []
    if "Overfull \\hbox" in text:
        notes.append("يوجد تنبيه اتساع نص داخل صفحة واحدة.")
    if "Dimension too large" in text:
        notes.append("يوجد تنبيه أبعاد في أحد العناصر الرسومية.")
    return notes


def format_quality_notes(notes: list[str]) -> str:
    if not notes:
        return ""
    return "ملاحظات فحص الجودة بعد الإخراج:\n" + "\n".join(
        f"• {note}" for note in notes
    )
