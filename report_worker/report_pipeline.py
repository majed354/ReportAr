from __future__ import annotations

import json
import re
from typing import Any

from .config import Settings
from .output_guard import normalize_output
from .providers import ProviderResult, generate_with_fallback


LONG_REPORT_THRESHOLD = 24_000
TARGET_CHUNK_CHARS = 11_000
MAX_SYNTHESIS_CHARS = 60_000
MAX_REDUCTION_ROUNDS = 3

CHUNK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "sections",
        "facts",
        "kpis",
        "recommendations",
        "audit_notes",
        "chart_candidates",
        "continuity_notes",
    ],
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["heading", "body"],
                "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "facts": {"type": "array", "items": {"type": "string"}},
        "kpis": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "audit_notes": {"type": "array", "items": {"type": "string"}},
        "chart_candidates": {"type": "array", "items": {"type": "string"}},
        "continuity_notes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

CHUNK_SYSTEM = """أنت مرحلة استخراج أمينة ضمن محرك تقارير عربية طويلة.
أعد JSON فقط وفق المخطط. لا تكتب تقريرًا نهائيًا ولا LaTeX.

- استخرج محتوى الجزء دون إسقاط أسماء أو أرقام أو تواريخ أو وحدات أو مراجع.
- لا تخترع معلومة ولا تحسم تعارضًا. ضع التعارض والنقص في audit_notes.
- حافظ على المصطلحات والهوية المحددة في المرجع الثابت.
- اجعل sections موجزة لكن كاملة المعنى، وسجل الحقائق الرقمية الدقيقة منفصلة.
- سجل مجموعات البيانات المناسبة للمخططات في chart_candidates بوصف واضح.
- استخدم continuity_notes لما يحتاج الربط بالأجزاء الأخرى.
"""


def should_use_staged_generation(report_text: str) -> bool:
    return len(report_text) > LONG_REPORT_THRESHOLD


def numeric_ledger(report_text: str) -> list[str]:
    unsafe_words = ("تجاهل تعليمات", "تعليمات النظام", "اكتب latex", "احذف")
    entries = []
    for block in re.split(r"\n\s*\n|(?<=[.!؟])\s+", report_text):
        text = re.sub(r"\s+", " ", block).strip()
        if (
            text
            and re.search(r"\d", text)
            and not any(word in text.lower() for word in unsafe_words)
        ):
            entries.append(text[:700])
    return list(dict.fromkeys(entries))[:300]


def _split_oversized_block(block: str, target: int) -> list[str]:
    if len(block) <= target:
        return [block]
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) > 1:
        pieces: list[str] = []
        current = ""
        for line in lines:
            line_pieces = (
                _split_oversized_block(line, target) if len(line) > target else [line]
            )
            for line_piece in line_pieces:
                if current and len(current) + len(line_piece) + 1 > target:
                    pieces.append(current)
                    current = line_piece
                else:
                    current = f"{current}\n{line_piece}".strip()
        if current:
            pieces.append(current)
        return pieces

    words = block.split()
    pieces = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > target:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_report(report_text: str, target: int = TARGET_CHUNK_CHARS) -> list[str]:
    normalized = report_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = [
        piece
        for block in re.split(r"\n\s*\n", normalized)
        for piece in _split_oversized_block(block.strip(), target)
        if piece.strip()
    ]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > target:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        chunks.append(current)
    return chunks or [normalized]


def build_document_profile(report_text: str, instructions: str = "") -> str:
    identity_words = (
        "شعار",
        "ختم",
        "خلفية",
        "غلاف",
        "لون",
        "ألوان",
        "الوان",
        "نمط",
        "تصميم",
        "خط",
        "هوية",
    )
    identity_lines = []
    heading_lines = []
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(word in line.lower() for word in identity_words):
            identity_lines.append(line)
        if (
            len(line) <= 110
            and (
                line.endswith(":")
                or line.startswith(("#", "الفصل", "القسم", "الباب", "المحور"))
            )
        ):
            heading_lines.append(line)

    profile = {
        "trusted_user_instructions": instructions or "لا توجد تعليمات منفصلة.",
        "identity_and_style_requirements": list(dict.fromkeys(identity_lines))[:30]
        or ["لم تُذكر هوية بصرية صريحة؛ التزم بنمط واحد مناسب طوال التقرير."],
        "document_outline_clues": list(dict.fromkeys(heading_lines))[:80],
        "numeric_reference_ledger": numeric_ledger(report_text),
        "opening_context": report_text[:2500],
        "closing_context": report_text[-3500:] if len(report_text) > 3500 else "",
    }
    return json.dumps(profile, ensure_ascii=False, separators=(",", ":"))


def _chunk_prompt(profile: str, chunk: str, index: int, total: int) -> str:
    return f"""المرجع الثابت الذي يجب الالتزام به في جميع الأجزاء:
{profile}

هذا الجزء رقم {index} من {total}. قد يبدأ أو ينتهي في سياق متصل بجزء آخر.
استخرج كل ما يلزم لبناء التقرير النهائي، ولا تكرر المرجع الثابت ضمن الناتج.

نص الجزء:
---
{chunk}
---
"""


def _reduction_prompt(profile: str, items: list[dict[str, Any]]) -> str:
    return f"""ادمج الاستخراجات التالية في استخراج واحد أمين وموجز.
لا تسقط أي رقم أو تاريخ أو اسم أو تعارض أو توصية فريدة، ولا تنشئ معلومات جديدة.
وحّد الأقسام المتطابقة مع الحفاظ على المرجع الثابت.

المرجع الثابت:
{profile}

الاستخراجات:
{json.dumps(items, ensure_ascii=False, separators=(",", ":"))}
"""


def _final_prompt(
    mode: str,
    profile: str,
    extractions: list[dict[str, Any]],
) -> str:
    mode_text = (
        "الوضع المطلوب: guided. إذا بقي قرار محتوى حرج فاطلبه قبل البناء."
        if mode == "guided"
        else "الوضع المطلوب: fast. أنجز التقرير وسجل النقص والتعارض في audit فقط."
    )
    return f"""{mode_text}

هذا تقرير طويل عولج على مراحل. ابنِ JSON النهائي من الاستخراجات الموثوقة أدناه.
التزم بالهوية والمصطلحات في المرجع الثابت عبر جميع الأقسام، وأزل التكرار فقط.
لا تُسقط أي حقيقة أو رقم أو تاريخ أو توصية فريدة، ولا تعرض تفاصيل audit داخل التقرير.
أنشئ chart_intents لكل مجموعة بيانات مناسبة، وراجع الاتساق بين الأجزاء.
ركّز على جودة العنوان والملخص والقرارات والمراجعة العامة. يمكن أن تكون sections
موجزة لأن المحرك سيعيد دمج مسودات الفصول المرحلية الأمينة بعد هذه المراجعة.

المرجع الثابت:
{profile}

استخراجات أجزاء التقرير:
{json.dumps(extractions, ensure_ascii=False, separators=(",", ":"))}
"""


def _payload_size(items: list[dict[str, Any]]) -> int:
    return len(json.dumps(items, ensure_ascii=False, separators=(",", ":")))


def _unique_strings(values: list[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        normalized = re.sub(r"\s+", " ", text)
        if text and normalized not in seen:
            seen.add(normalized)
            unique.append(text)
    return unique


def merge_staged_content(
    final_output: dict[str, Any],
    extractions: list[dict[str, Any]],
    reference_facts: list[str] | None = None,
) -> dict[str, Any]:
    if final_output.get("status") != "ready_to_render" or not final_output.get("report"):
        return final_output

    headings: dict[str, dict[str, Any]] = {}
    for extraction in extractions:
        for section in extraction.get("sections", []):
            heading = str(section.get("heading", "")).strip()
            body = str(section.get("body", "")).strip()
            if not heading or not body:
                continue
            key = re.sub(r"\s+", " ", heading)
            if key not in headings:
                headings[key] = {"heading": heading, "bodies": []}
            headings[key]["bodies"].append(body)

    staged_sections = [
        {
            "heading": item["heading"],
            "body": "\n\n".join(_unique_strings(item["bodies"])),
        }
        for item in headings.values()
    ]
    if staged_sections:
        final_output["report"]["sections"] = staged_sections
    extracted_facts = [
        fact
        for extraction in extractions
        for fact in extraction.get("facts", [])
    ]
    facts = _unique_strings(list(reference_facts or []) or extracted_facts)
    public = json.dumps(final_output["report"]["sections"], ensure_ascii=False)
    missing_facts = [
        fact
        for fact in facts
        if any(character.isdigit() for character in fact) and fact not in public
    ]
    if missing_facts:
        final_output["report"]["sections"].append(
            {
                "heading": "البيانات الرقمية المرجعية",
                "body": "\n\n".join(missing_facts),
            }
        )

    staged_recommendations = [
        recommendation
        for extraction in extractions
        for recommendation in extraction.get("recommendations", [])
    ]
    if not final_output["report"].get("recommendations"):
        final_output["report"]["recommendations"] = _unique_strings(
            staged_recommendations
        )
    return final_output


def generate_report(
    *,
    settings: Settings,
    primary: str,
    fallback: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    mode: str,
    report_text: str,
    instructions: str = "",
    model_override: str | None = None,
) -> tuple[ProviderResult, bool, str | None]:
    if not should_use_staged_generation(report_text):
        result, used, error = generate_with_fallback(
            settings=settings,
            primary=primary,
            fallback=fallback,
            system=system,
            user=user,
            schema=schema,
            model_override=model_override,
        )
        result.parsed = normalize_output(result.parsed, report_text)
        return result, used, error

    chunks = split_report(report_text)
    profile = build_document_profile(report_text, instructions)
    fallback_used = False
    errors: list[str] = []
    stage_results: list[ProviderResult] = []
    extractions: list[dict[str, Any]] = []

    def run_stage(stage_system: str, stage_user: str, stage_schema: dict[str, Any]) -> ProviderResult:
        nonlocal fallback_used
        result, used, error = generate_with_fallback(
            settings=settings,
            primary=primary,
            fallback=fallback,
            system=stage_system,
            user=stage_user,
            schema=stage_schema,
            model_override=model_override,
        )
        fallback_used = fallback_used or used
        if error:
            errors.append(error)
        stage_results.append(result)
        return result

    for index, chunk in enumerate(chunks, 1):
        result = run_stage(
            CHUNK_SYSTEM,
            _chunk_prompt(profile, chunk, index, len(chunks)),
            CHUNK_SCHEMA,
        )
        extractions.append(result.parsed)

    reduction_rounds = 0
    while (
        len(extractions) > 1
        and _payload_size(extractions) > MAX_SYNTHESIS_CHARS
        and reduction_rounds < MAX_REDUCTION_ROUNDS
    ):
        reduced: list[dict[str, Any]] = []
        for start in range(0, len(extractions), 4):
            group = extractions[start : start + 4]
            reduced.append(
                run_stage(CHUNK_SYSTEM, _reduction_prompt(profile, group), CHUNK_SCHEMA).parsed
            )
        extractions = reduced
        reduction_rounds += 1

    final = run_stage(system, _final_prompt(mode, profile, extractions), schema)
    final.parsed = merge_staged_content(
        final.parsed, extractions, numeric_ledger(report_text)
    )
    final.parsed = normalize_output(final.parsed, report_text)
    totals: dict[str, int] = {}
    for result in stage_results:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = result.usage.get(key)
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    final.usage = {
        **totals,
        "pipeline": {
            "mode": "staged",
            "source_characters": len(report_text),
            "chunks": len(chunks),
            "reduction_rounds": reduction_rounds,
            "model_calls": len(stage_results),
        },
    }
    return final, fallback_used, " | ".join(errors)[:500] or None
