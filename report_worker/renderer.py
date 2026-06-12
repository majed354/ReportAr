from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


THEME_PALETTES: dict[str, dict[str, str]] = {
    "executive-modern": {
        "primary": "0F766E",
        "navy": "172554",
        "surface": "F0FDFA",
        "accent": "14B8A6",
        "tagline": "ملخص تنفيذي منسق لعرض النتائج والقرارات بوضوح.",
    },
    "official-formal": {
        "primary": "1D4ED8",
        "navy": "111827",
        "surface": "EFF6FF",
        "accent": "64748B",
        "tagline": "تقرير رسمي منسق للعرض المؤسسي والاعتماد.",
    },
    "academic-clean": {
        "primary": "475569",
        "navy": "1E293B",
        "surface": "F8FAFC",
        "accent": "2563EB",
        "tagline": "تقرير أكاديمي هادئ يعرض المنهجية والنتائج بوضوح.",
    },
    "heritage-elegant": {
        "primary": "A16207",
        "navy": "422006",
        "surface": "FEFCE8",
        "accent": "CA8A04",
        "tagline": "تقرير أنيق بطابع رصين مناسب للموضوعات الثقافية والتراثية.",
    },
    "data-dashboard": {
        "primary": "2563EB",
        "navy": "0F172A",
        "surface": "EFF6FF",
        "accent": "7C3AED",
        "tagline": "تقرير مؤشرات يبرز البيانات والمقارنات والمخططات.",
    },
    "minimal-neutral": {
        "primary": "52525B",
        "navy": "18181B",
        "surface": "F4F4F5",
        "accent": "71717A",
        "tagline": "تقرير هادئ ومحايد يركز على وضوح المحتوى.",
    },
}


def tex(value: Any) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def tex_bidi(value: Any) -> str:
    text = "" if value is None else str(value)
    pattern = re.compile(r"(?:[$#]?[A-Za-z][A-Za-z0-9_#.&/$%+\-]*|\$[0-9][0-9.,]*)")
    parts = []
    previous = 0
    for match in pattern.finditer(text):
        parts.append(tex(text[previous : match.start()]))
        parts.append(r"\foreignlanguage{english}{" + tex(match.group()) + "}")
        previous = match.end()
    parts.append(tex(text[previous:]))
    return "".join(parts)


def _items(values: list[Any]) -> str:
    return "\n".join(rf"\item {tex_bidi(value)}" for value in values)


def _itemize(values: list[Any], empty_message: str) -> str:
    if not values:
        return tex_bidi(empty_message)
    return "\\begin{itemize}\n" + _items(values) + "\n\\end{itemize}"


def _report_sections(report: dict[str, Any]) -> list[dict[str, Any]]:
    reserved = (
        "الملخص التنفيذي",
        "مؤشرات الأداء",
        "التوصيات",
        "التعارض",
        "معلومات تحتاج",
        "المخططات",
    )
    return [
        item
        for item in report.get("sections", [])
        if not any(title in str(item.get("heading", "")) for title in reserved)
    ]


def _arguments(values: list[Any]) -> str:
    return "".join("{" + tex(value) + "}" for value in values)


def _graphic_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _copy_asset_blocks(
    assets: list[dict[str, str]] | None,
    destination: Path,
) -> dict[str, str]:
    blocks = {"logo": "", "cover": "", "stamp": ""}
    if not assets:
        return blocks
    for index, asset in enumerate(assets, 1):
        source = Path(asset.get("path", ""))
        if not source.exists() or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        target = destination / f"brand-asset-{index}{source.suffix.lower()}"
        shutil.copyfile(source, target)
        role = asset.get("role", "logo")
        if role == "stamp" and not blocks["stamp"]:
            blocks["stamp"] = (
                rf"\begin{{flushleft}}\includegraphics[width=3.2cm,height=3.2cm,keepaspectratio]"
                rf"{{{_graphic_path(target)}}}\end{{flushleft}}"
            )
        elif role == "cover" and not blocks["cover"]:
            blocks["cover"] = (
                rf"\vspace{{0.7cm}}\includegraphics[width=0.72\textwidth,height=4.2cm,keepaspectratio]"
                rf"{{{_graphic_path(target)}}}\\[0.4cm]"
            )
        elif not blocks["logo"]:
            blocks["logo"] = (
                rf"\includegraphics[width=3.4cm,height=3.4cm,keepaspectratio]"
                rf"{{{_graphic_path(target)}}}\\[0.8cm]"
            )
    return blocks


def _compact_number(value: float) -> int | float:
    rounded = round(value, 3)
    return int(rounded) if rounded.is_integer() else rounded


def _scaled_values(values: list[Any]) -> tuple[list[int | float], str]:
    numbers = [float(value) for value in values]
    if not numbers or not all(math.isfinite(value) for value in numbers):
        raise ValueError("تحتوي بيانات المخطط على قيمة رقمية غير صالحة")
    maximum = max(abs(value) for value in numbers)
    units = ["", "بالآلاف", "بالملايين", "بالمليارات", "بالتريليونات"]
    divisor = 1.0
    unit_index = 0
    while maximum / divisor > 1000:
        divisor *= 1000
        unit_index += 1
    unit = (
        units[unit_index]
        if unit_index < len(units)
        else f"بمقياس 10 أس {unit_index * 3}"
    )
    return [_compact_number(value / divisor) for value in numbers], unit


def _scaled_title(title: Any, unit: str) -> str:
    return f"{title} ({unit})" if unit else str(title)


def _latex_error(output: str) -> str:
    match = re.search(
        r"(?ms)^! (?!==>)(.+?)\n.*?^l\.(\d+)\s+(.+?)$",
        output,
    )
    if match:
        return (
            f"{match.group(1).strip()} عند السطر {match.group(2)}: "
            f"{match.group(3).strip()}"
        )
    return re.sub(r"\s+", " ", output[-800:])


def _four_values(chart: dict[str, Any]) -> tuple[list[Any], list[Any]] | None:
    values = chart.get("values", [])
    labels = chart.get("labels", [])
    if len(values) != 4 or len(labels) != 4:
        return None
    return values, labels


def _time_trend(chart: dict[str, Any]) -> str:
    values = chart.get("values", [])
    labels = chart.get("labels", [])
    if len(values) < 2 or len(values) != len(labels):
        return ""
    values, unit = _scaled_values(values)
    coordinates = " ".join(f"({index},{value})" for index, value in enumerate(values, 1))
    ticks = ",".join(str(index) for index in range(1, len(values) + 1))
    tick_labels = ",".join(
        "{" + rf"\foreignlanguage{{arabic}}{{{tex(label)}}}" + "}" for label in labels
    )
    title = tex(_scaled_title(chart.get("title", "الاتجاه الزمني"), unit))
    return rf"""
\begin{{figure}}[H]\centering
\begin{{otherlanguage}}{{english}}
\begin{{tikzpicture}}
\begin{{axis}}[
  width=11cm,height=6.5cm,
  title={{\foreignlanguage{{arabic}}{{{title}}}}},
  xtick={{{ticks}}},
  xticklabels={{{tick_labels}}},
  x tick label style={{rotate=35,anchor=east,font=\scriptsize}},
  ylabel={{\foreignlanguage{{arabic}}{{القيمة}}}},
  grid=major,grid style={{gray!18}},
  line width=1.5pt
]
\addplot[modernblue2,mark=*,mark options={{fill=modernblue4}}] coordinates {{{coordinates}}};
\end{{axis}}
\end{{tikzpicture}}
\end{{otherlanguage}}
\caption{{\foreignlanguage{{arabic}}{{{title}}}}}
\end{{figure}}
"""


def _waterfall(chart: dict[str, Any]) -> str:
    start = chart.get("start")
    changes = chart.get("changes", [])
    if start is None or not changes:
        return ""
    normalized = list(changes[:2])
    remaining = changes[2:]
    if remaining:
        normalized.append(
            {
                "label": remaining[0].get("label", "تغييرات أخرى")
                if len(remaining) == 1
                else "تغييرات أخرى",
                "value": sum(float(item.get("value", 0)) for item in remaining),
            }
        )
    while len(normalized) < 3:
        normalized.append({"label": "لا تغيير", "value": 0})
    raw_numbers = [start, *[item.get("value", 0) for item in normalized]]
    scaled_numbers, unit = _scaled_values(raw_numbers)
    start = scaled_numbers[0]
    normalized = [
        {**item, "value": scaled_numbers[index + 1]}
        for index, item in enumerate(normalized)
    ]
    cumulative = float(start)
    points = [cumulative]
    for change in normalized:
        cumulative += float(change.get("value", 0))
        points.append(cumulative)
    maximum = max(max(abs(point) for point in points) * 1.15, 1)

    def pair(item: dict[str, Any]) -> str:
        label = str(item.get("label", "")).replace("/", "–")
        return f"{label}/{item.get('value', 0)}"

    end_label = (
        "النهاية المحسوبة"
        if chart.get("calculated_end") is not None
        else "النهاية"
    )
    title = _scaled_title(chart.get("title", "التغير التراكمي"), unit)
    return "\\chartWaterfallThreeD" + _arguments(
        [
            title,
            round(maximum, 2),
            f"البداية/{start}",
            *[pair(item) for item in normalized],
            end_label,
        ]
    )


def _milestones(chart: dict[str, Any]) -> str:
    stages = chart.get("stages", [])
    if len(stages) != 4:
        return ""
    return "\\chartTimelineDepth" + _arguments(
        [
            chart.get("title", "المراحل الزمنية"),
            *[stage.get("label", "") for stage in stages],
            *[stage.get("date") or "غير محدد" for stage in stages],
        ]
    )


def _chart_intents(output: dict[str, Any]) -> str:
    rendered = []
    four_commands = {
        "distribution_four": "chartDonutThreeD",
        "column_comparison": "chartColumnThreeD",
        "executive_scorecard": "chartKpiDepthCards",
        "long_label_comparison": "chartHorizontalBar",
    }
    for chart in output.get("chart_intents", []):
        kind = chart.get("kind")
        content = ""
        if kind in four_commands:
            four = _four_values(chart)
            if four:
                values, labels = four
                if kind == "distribution_four" and any(float(value) <= 0 for value in values):
                    kind = "column_comparison"
                title = chart.get("title", "مخطط")
                if kind != "executive_scorecard":
                    values, unit = _scaled_values(values)
                    title = _scaled_title(title, unit)
                content = "\\" + four_commands[kind] + _arguments(
                    [title, *values, *labels]
                )
        elif kind == "time_trend":
            content = _time_trend(chart)
        elif kind == "cumulative_change":
            content = _waterfall(chart)
        elif kind == "project_milestones":
            content = _milestones(chart)
        if content:
            rendered.append(content)
    if not rendered:
        return ""
    return "\\sectiontitle{المخططات}\n" + "\n".join(rendered)


def render_report(
    output: dict[str, Any],
    destination: Path,
    assets: list[dict[str, str]] | None = None,
) -> Path:
    report = output.get("report") or {}
    decisions = output.get("decisions") or {}
    theme_id = decisions.get("theme_id") or "executive-modern"
    palette = THEME_PALETTES.get(theme_id, THEME_PALETTES["executive-modern"])
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    tex_path = destination / "report.tex"
    pdf_path = destination / "report.pdf"
    asset_blocks = _copy_asset_blocks(assets, destination)

    sections = "\n".join(
        rf"\sectiontitle{{{tex_bidi(item.get('heading'))}}}{tex_bidi(item.get('body'))}\par"
        for item in _report_sections(report)
    )
    kpis = "\n".join(
        rf"{tex_bidi(item.get('label'))} & {tex_bidi(item.get('value'))} & {tex_bidi(item.get('unit'))} \\[0.14cm]"
        for item in report.get("kpis", [])
    )
    kpi_rows = kpis or r"\multicolumn{3}{c}{لا توجد مؤشرات رقمية} \\"
    recommendation_block = _itemize(
        report.get("recommendations", []), "لا توجد توصيات إضافية."
    )
    charts = _chart_intents(output)

    document = rf"""%!TEX program = lualatex
\documentclass[12pt,a4paper]{{article}}
\usepackage[bidi=basic,english]{{babel}}
\babelprovide[import=ar,main,mapdigits]{{arabic}}
\babelprovide[import=en]{{english}}
\usepackage{{fontspec,xcolor,geometry,array,booktabs,fancyhdr,float,needspace,graphicx}}
\IfFontExistsTF{{Tajawal}}{{\setmainfont{{Tajawal}}\babelfont[arabic]{{rm}}{{Tajawal}}}}{{\setmainfont{{Amiri}}\babelfont[arabic]{{rm}}{{Amiri}}}}
\geometry{{top=2cm,bottom=2cm,left=1.8cm,right=1.8cm}}
\setlength{{\emergencystretch}}{{3em}}
\raggedbottom
\definecolor{{primary}}{{HTML}}{{{palette["primary"]}}}
\definecolor{{navy}}{{HTML}}{{{palette["navy"]}}}
\definecolor{{surface}}{{HTML}}{{{palette["surface"]}}}
\definecolor{{accent}}{{HTML}}{{{palette["accent"]}}}
\input{{charts-fifteen.tex}}
\renewcommand{{\chartscalefactor}}{{0.72}}
\pagestyle{{fancy}}\fancyhf{{}}\fancyhead[R]{{\color{{navy}}{tex_bidi(report.get('title', 'تقرير احترافي'))}}}\fancyfoot[C]{{\thepage}}
\setlength{{\headheight}}{{26pt}}
\newcommand{{\sectiontitle}}[1]{{%
  \par\Needspace{{6\baselineskip}}\vspace{{0.5cm}}%
  {{\Large\bfseries\color{{primary}}#1}}\par%
  \noindent\color{{primary!35}}\rule{{\textwidth}}{{0.7pt}}\par%
  \nobreak\vspace{{0.2cm}}\noindent\color{{black}}%
}}
\begin{{document}}
\begin{{titlepage}}\thispagestyle{{empty}}
\vspace*{{3cm}}\begin{{center}}
{asset_blocks["logo"]}
{{\Huge\bfseries\color{{navy}}{tex_bidi(report.get('title', 'تقرير احترافي'))}\par}}
\vspace{{0.6cm}}{{\Large\color{{primary}}{tex_bidi(report.get('subtitle', 'تقرير عربي منسق'))}\par}}
{asset_blocks["cover"]}
\vfill
\colorbox{{surface}}{{\parbox{{0.82\textwidth}}{{\centering {tex_bidi(palette["tagline"])}}}}}
\end{{center}}\end{{titlepage}}

\sectiontitle{{الملخص التنفيذي}}
{tex_bidi(report.get('executive_summary', ''))}

\sectiontitle{{مؤشرات الأداء}}
\begin{{center}}\renewcommand{{\arraystretch}}{{1.35}}
\begin{{tabular}}{{p{{9cm}}cc}}
\toprule
\textbf{{المؤشر}} & \textbf{{القيمة}} & \textbf{{الوحدة}} \\
\midrule
{kpi_rows}
\bottomrule
\end{{tabular}}\end{{center}}

{sections}

\sectiontitle{{التوصيات}}
{recommendation_block}

{charts}
{asset_blocks["stamp"]}
\end{{document}}
"""
    tex_path.write_text(document, encoding="utf-8")
    (destination / "model-output.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    command = [
        "lualatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={destination}",
        str(tex_path),
    ]
    environment = {
        **os.environ,
        "TEXMFCACHE": str(destination / ".tex-cache"),
        "TEXMFVAR": str(destination / ".tex-var"),
        "TEXINPUTS": str(Path(__file__).resolve().parents[2] / "chart-library-prototype")
        + "//:"
        + os.environ.get("TEXINPUTS", ""),
    }
    Path(environment["TEXMFCACHE"]).mkdir(parents=True, exist_ok=True)
    Path(environment["TEXMFVAR"]).mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            env=environment,
        )
        if result.returncode:
            raise RuntimeError(f"فشل بناء PDF: {_latex_error(result.stdout)}")
    if not pdf_path.exists():
        raise RuntimeError("لم يتم إنشاء ملف PDF")
    return pdf_path
