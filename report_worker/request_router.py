from __future__ import annotations

import re


CHART_WORDS = (
    "مخطط",
    "مخططات",
    "المخطط",
    "المخططات",
    "رسم",
    "رسوم",
    "الرسم",
    "الرسوم",
    "chart",
    "charts",
)
CHART_PHRASES = ("رسم بياني", "رسوم بيانية")
RESEARCH_WORDS = (
    "أحدث",
    "احدث",
    "حالي",
    "اليوم",
    "الآن",
    "الان",
    "ابحث",
    "مصدر",
    "إحصائيات",
    "احصائيات",
    "عالمي",
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w\u0600-\u06ff]+", text.lower()))


def _matches(text: str, words: tuple[str, ...], phrases: tuple[str, ...] = ()) -> bool:
    lowered = text.lower()
    tokens = _words(lowered)
    return any(word in tokens for word in words) or any(
        phrase in lowered for phrase in phrases
    )


def is_chart_request(text: str) -> bool:
    return _matches(text, CHART_WORDS, CHART_PHRASES)


def needs_web_research(text: str) -> bool:
    lowered = text.lower()
    has_number = any(character.isdigit() for character in lowered)
    return any(word in lowered for word in RESEARCH_WORDS) or (
        is_chart_request(lowered) and not has_number
    )
