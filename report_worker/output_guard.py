from __future__ import annotations

import math
import re
from typing import Any


AUDIT_PUBLIC_TERMS = (
    "المذكور",
    "المحسوب",
    "تعارض",
    "التعارض",
    "فرق رقمي",
)
FOUR_VALUE_KINDS = {
    "distribution_four",
    "column_comparison",
    "executive_scorecard",
    "long_label_comparison",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value))


def _valid_chart(chart: dict[str, Any], source_text: str = "") -> dict[str, Any] | None:
    kind = chart.get("kind")
    labels = chart.get("labels", [])
    values = chart.get("values", [])
    if kind in FOUR_VALUE_KINDS:
        if len(labels) != 4 or len(values) != 4 or any(_number(value) is None for value in values):
            return None
        if kind == "distribution_four" and any(float(value) <= 0 for value in values):
            kind = "column_comparison"
        if kind == "column_comparison":
            chart_context = f"{chart.get('title', '')} {chart.get('reason', '')}"
            if max(map(len, map(str, labels)), default=0) >= 24:
                kind = "long_label_comparison"
            elif (
                any(term in chart_context for term in ("مؤشرات الأداء", "بطاقات"))
                and all(0 <= float(value) <= 100 for value in values)
            ):
                kind = "executive_scorecard"
        if kind == "executive_scorecard" and any(
            not 0 <= float(value) <= 100 for value in values
        ):
            kind = "column_comparison"
        if kind == "long_label_comparison" and max(
            map(len, map(str, labels)), default=0
        ) < 18:
            kind = "column_comparison"
        return {**chart, "kind": kind}
    if kind == "time_trend":
        if len(values) < 2 or len(values) != len(labels):
            return None
        return chart if all(_number(value) is not None for value in values) else None
    if kind == "cumulative_change":
        changes = chart.get("changes", [])
        if _number(chart.get("start")) is None or not changes:
            return None
        if any(_number(item.get("value")) is None for item in changes):
            return None
        return chart
    if kind == "project_milestones":
        return chart if len(chart.get("stages", [])) == 4 else None
    return None


def normalize_output(output: dict[str, Any], source_text: str = "") -> dict[str, Any]:
    output["chart_intents"] = [
        normalized
        for chart in output.get("chart_intents", [])
        if (normalized := _valid_chart(chart, source_text)) is not None
    ]
    report = output.get("report")
    audit = output.get("audit") or {}
    unsafe_terms = (
        "تجاهل",
        "تعليمات النظام",
        "latex",
        "tikz",
        "html",
        "احذف",
        "اختلق",
        "اخترع",
        "غيّر الأرقام",
        "غير الأرقام",
        "ذكاء اصطناعي",
        "نموذج لغوي",
        "أوامر تنفيذية",
        "مسار ملفات",
    )
    audit["rejected_instructions"] = [
        instruction
        for instruction in audit.get("rejected_instructions", [])
        if any(term in str(instruction).lower() for term in unsafe_terms)
    ]
    output["audit"] = audit
    if not isinstance(report, dict):
        return output

    report["unresolved_notes"] = [
        note
        for note in report.get("unresolved_notes", [])
        if not any(term in str(note) for term in AUDIT_PUBLIC_TERMS)
    ]
    contradictions = (output.get("audit") or {}).get("contradictions", [])
    conflicted_values = {
        digits
        for contradiction in contradictions
        for digits in (
            _digits(contradiction.get("reported")),
            _digits(contradiction.get("calculated")),
        )
        if digits
    }
    report["kpis"] = [
        item
        for item in report.get("kpis", [])
        if _digits(item.get("value")) not in conflicted_values
    ]
    return output
