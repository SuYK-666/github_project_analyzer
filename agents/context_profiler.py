from __future__ import annotations

import logging
from typing import Any

from config import Settings
from config.prompts import CONTEXT_PROFILER_SYSTEM_PROMPT
from utils.deepseek_client import DeepSeekClient
from utils.github_parser import build_analysis_context
from utils.output_sanitizer import sanitize_profile_markdown


class ContextProfilerAgent:
    def __init__(
        self,
        client: DeepSeekClient,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger or logging.getLogger("github_project_analyzer.context_profiler")

    def profile(self, repo_payload: dict[str, Any], analysis_label: str) -> dict[str, str]:
        self.logger.info(
            "state=START | agent=context_profiler | analysis_label=%s",
            analysis_label,
        )
        context_text = build_analysis_context(repo_payload, max_readme_chars=9000)
        user_prompt = f"""
请将以下 GitHub 项目信息压缩为后续分析可直接使用的技术名片。

输出要求：
1. 600-900 字中文。
2. 用 Markdown 输出。
3. 必须包含两部分标题：
   - ## 项目技术名片
   - ## 可用于{analysis_label}分析的事实锚点
4. 每部分写成连续段落，不使用列表符号。
5. 对不确定的信息明确写“证据不足”，不要猜测。

以下是项目上下文：
{context_text}
""".strip()

        profile_markdown_raw = self.client.ask(
            system_prompt=CONTEXT_PROFILER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.25,
            max_tokens=1200,
        )
        profile_markdown = sanitize_profile_markdown(profile_markdown_raw)

        self.logger.info(
            "state=DONE | agent=context_profiler | context_chars=%s | output_chars_raw=%s | output_chars_clean=%s",
            len(context_text),
            len(profile_markdown_raw),
            len(profile_markdown),
        )

        return {
            "profile_markdown": profile_markdown.strip(),
            "analysis_context": context_text,
        }
