from __future__ import annotations

import re


_PROMPT_LEAK_LINE_PATTERNS = [
    r"^(好的[，,]?\s*)?作为一名.*智能体.*$",
    r"^我将基于.*(撰写|生成).*(报告|分析).*$",
    r"^(以下|下面)是.*(报告|分析).*$",
    r"^输出要求[:：]?$",
    r"^硬性要求[:：]?$",
    r"^仓库事实[:：]?$",
    r"^项目技术名片[:：]?$",
    r"^请基于仓库事实与项目技术名片.*$",
]


def _remove_prompt_leak_lines(markdown_text: str) -> str:
    if not markdown_text:
        return ""

    cleaned_lines: list[str] = []
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if any(re.search(pattern, stripped) for pattern in _PROMPT_LEAK_LINE_PATTERNS):
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _trim_to_first_heading(markdown_text: str, heading_patterns: list[str]) -> str:
    lines = markdown_text.splitlines()
    start_idx: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if any(re.search(pattern, stripped) for pattern in heading_patterns):
            start_idx = index
            break

    if start_idx is None:
        return markdown_text.strip()

    return "\n".join(lines[start_idx:]).strip()


def sanitize_profile_markdown(markdown_text: str) -> str:
    text = _remove_prompt_leak_lines(markdown_text)
    text = _trim_to_first_heading(text, [r"^##\s*项目技术名片\s*$"])
    return text.strip()


def sanitize_report_markdown(markdown_text: str) -> str:
    text = _remove_prompt_leak_lines(markdown_text)
    text = _trim_to_first_heading(text, [r"^##\s*引言\s*$", r"^#\s*引言\s*$"])
    return text.strip()
