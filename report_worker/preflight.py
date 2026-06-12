from __future__ import annotations

import re
from typing import Any


STYLE_PRESETS: dict[str, dict[str, str]] = {
    "executive-modern": {
        "label": "تنفيذي حديث",
        "report_type": "executive",
        "palette": "كحلي وفيروزي",
        "use_case": "تقارير الإدارة والإنجازات والملخصات التنفيذية.",
    },
    "official-formal": {
        "label": "رسمي مؤسسي",
        "report_type": "official",
        "palette": "كحلي ورمادي رسمي",
        "use_case": "الخطابات الرسمية والجهات الحكومية والمؤسسات.",
    },
    "academic-clean": {
        "label": "أكاديمي هادئ",
        "report_type": "academic",
        "palette": "رمادي وأزرق علمي",
        "use_case": "التقارير البحثية والجامعية والدراسات.",
    },
    "heritage-elegant": {
        "label": "تراثي أنيق",
        "report_type": "heritage",
        "palette": "ذهبي وبني هادئ",
        "use_case": "الموضوعات الشرعية والثقافية والتراثية.",
    },
    "data-dashboard": {
        "label": "لوحة مؤشرات",
        "report_type": "data",
        "palette": "أزرق تقني مع إبرازات متعددة",
        "use_case": "البيانات الكثيفة والمقارنات والمخططات.",
    },
    "minimal-neutral": {
        "label": "محايد بسيط",
        "report_type": "general",
        "palette": "رمادي محايد",
        "use_case": "التقارير العامة والطويلة التي تحتاج هدوءًا بصريًا.",
    },
}


def _score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def recommend_preset(report_text: str) -> str:
    text = report_text.lower()
    scores = {
        "data-dashboard": _score(
            text,
            (
                "مؤشر",
                "مؤشرات",
                "kpi",
                "بيانات",
                "نسبة",
                "نسب",
                "مخطط",
                "إحصاء",
                "احصاء",
                "مبيعات",
            ),
        ),
        "academic-clean": _score(
            text,
            (
                "جامعة",
                "أكاديمي",
                "اكاديمي",
                "بحث",
                "دراسة",
                "طلاب",
                "طالب",
                "مقرر",
                "برنامج",
            ),
        ),
        "official-formal": _score(
            text,
            (
                "رسمي",
                "جهة",
                "اعتماد",
                "قرار",
                "إدارة",
                "ادارة",
                "لجنة",
                "وزارة",
                "محضر",
            ),
        ),
        "heritage-elegant": _score(
            text,
            (
                "قرآن",
                "قران",
                "حديث",
                "فقه",
                "شرعي",
                "شريعة",
                "تراث",
                "وقف",
            ),
        ),
        "executive-modern": 1,
    }
    return max(scores, key=scores.get)


def report_setup_questions(report_text: str) -> list[dict[str, Any]]:
    recommended = recommend_preset(report_text)

    def option(option_id: str, label: str) -> dict[str, Any]:
        return {
            "id": option_id,
            "label": label,
            "recommended": option_id == recommended,
        }

    return [
        {
            "id": "delivery_profile",
            "question": "ما صورة التقرير المطلوبة؟",
            "reason": "تحديد الجمهور والطول قبل التحرير يمنع الإطالة أو الاختصار غير المناسب.",
            "required": True,
            "options": [
                {"id": "executive_brief", "label": "ملخص تنفيذي مركز", "recommended": True},
                {"id": "full_formal", "label": "تقرير رسمي كامل", "recommended": False},
                {"id": "academic_detail", "label": "تفصيل أكاديمي", "recommended": False},
                {"id": "data_story", "label": "تحليل بياني", "recommended": False},
            ],
        },
        {
            "id": "visual_style",
            "question": "أي نمط بصري تريد؟",
            "reason": "النمط يحدد ألوان الغلاف والعناوين والمخططات.",
            "required": True,
            "options": [
                option("executive-modern", "تنفيذي حديث"),
                option("official-formal", "رسمي مؤسسي"),
                option("academic-clean", "أكاديمي هادئ"),
                option("heritage-elegant", "تراثي أنيق"),
                option("data-dashboard", "لوحة مؤشرات"),
            ],
        },
        {
            "id": "brand_assets",
            "question": "كيف نتعامل مع الشعار والصور؟",
            "reason": "تحديد الشعار والغلاف والخلفية قبل البناء يحسن الغلاف ويتجنب ازدحام الصفحات.",
            "required": True,
            "options": [
                {"id": "uploaded_logo", "label": "استخدم الشعار المرفوع", "recommended": True},
                {"id": "logo_stamp", "label": "شعار وختم رسمي", "recommended": False},
                {"id": "cover_image", "label": "صورة غلاف فقط", "recommended": False},
                {"id": "no_assets", "label": "بدون صور", "recommended": False},
            ],
        },
        {
            "id": "evidence_and_charts",
            "question": "ما سياسة المصادر والمخططات؟",
            "reason": "تحديد مستوى التحقق والمخططات يمنع الاختلاق ويجعل الإخراج مناسبا للغرض.",
            "required": True,
            "options": [
                {"id": "balanced", "label": "مخططات عند الحاجة", "recommended": True},
                {"id": "chart_rich", "label": "مخططات كثيرة", "recommended": False},
                {"id": "source_strict", "label": "تحقق صارم من المصادر", "recommended": False},
                {"id": "text_first", "label": "نص رسمي قليل الرسوم", "recommended": False},
            ],
        },
    ]


def format_preset_catalog() -> str:
    lines = ["القوالب الجاهزة المتاحة:"]
    for preset_id, preset in STYLE_PRESETS.items():
        lines.append(
            f"• {preset['label']} ({preset_id}): {preset['use_case']} "
            f"الألوان: {preset['palette']}."
        )
    return "\n".join(lines)


def automatic_setup_brief(report_text: str, mode: str = "fast") -> str:
    preset_id = recommend_preset(report_text)
    preset = STYLE_PRESETS[preset_id]
    route = (
        "في المسار السريع اعتمد هذه الخيارات تلقائيًا ولا تسأل المستخدم."
        if mode == "fast"
        else "في المسار الموجه اعتبر هذه توصية أولية، ولا تعدلها إذا أجاب المستخدم بخلافها."
    )
    chart_density = (
        "اجعل المخططات بارزة ومختارة من البيانات الصالحة فقط."
        if preset_id == "data-dashboard"
        else "أضف المخططات فقط عندما توجد بيانات رقمية كافية."
    )
    return "\n".join(
        [
            "إعداد احترافي قبل التوليد:",
            route,
            f"- القالب المقترح: {preset['label']} ({preset_id}).",
            f"- نوع التقرير: {preset['report_type']}.",
            f"- لوحة الألوان المقترحة: {preset['palette']}.",
            "- إذا لم يرفع المستخدم شعارًا أو صورة، استخدم غلافًا هندسيًا نظيفًا وخلفية بيضاء.",
            "- لا تضع داخل التقرير أي عبارة تفيد أنه تقرير آلي أو صادر من نموذج.",
            f"- {chart_density}",
            "- إذا وُجد نقص غير حرج فاذكره في audit فقط، ولا تملأه من عندك.",
        ]
    )


def setup_answer_brief(report_text: str, user_answers: str) -> str:
    preset_id = recommend_preset(report_text)
    cleaned_answers = re.sub(r"\s+", " ", user_answers).strip()
    return "\n".join(
        [
            "إجابات المستخدم في مساعد إعداد التقرير قبل التوليد:",
            cleaned_answers or "لم يضف المستخدم إجابات واضحة؛ اعتمد الخيار الموصى به.",
            "",
            "تعليمات تنفيذية:",
            "- نفذ اختيارات المستخدم في النمط، الألوان، الصور، طول التقرير، وسياسة المخططات.",
            f"- إذا كانت الإجابات مختصرة أو غير واضحة فاعتمد القالب المقترح: {preset_id}.",
            "- لا تسأل مرة أخرى عن الهوية البصرية إلا إذا طلب المستخدم صورة أو شعارًا غير مرفوع.",
            "- أبقِ ملاحظات الأخطاء والتعارضات خارج التقرير المنشور.",
        ]
    )
