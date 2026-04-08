from __future__ import annotations

import json
import logging
from typing import Any

from config import Settings
from config.prompts import ECON_AGENT_SYSTEM_PROMPT
from utils.deepseek_client import DeepSeekClient
from utils.github_parser import extract_project_facts
from utils.output_sanitizer import sanitize_report_markdown


class EconAgent:
    def __init__(
        self,
        client: DeepSeekClient,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger or logging.getLogger("github_project_analyzer.econ_agent")

    def generate(
        self,
        repo_payload: dict[str, Any],
        profile_markdown: str,
        code_insight_markdown: str,
        code_insight_payload: dict[str, Any] | None = None,
    ) -> str:
        self.logger.info("state=START | agent=econ_agent | 开始生成工程经济报告")
        facts = extract_project_facts(repo_payload)
        facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
        code_payload_json = json.dumps(code_insight_payload or {}, ensure_ascii=False, indent=2)

        user_prompt = f"""
请基于仓库事实与项目技术名片，撰写一篇“工程经济与项目管理分析报告”初稿。

硬性要求：
1. 正文有效字数控制在 {self.settings.report_target_chars} 字左右，可接受区间 {self.settings.report_min_chars}-{self.settings.report_max_chars}。
2. 必须采用总分总结构，且覆盖项目启动、实施、运行三个阶段。
3. 讨论要紧扣工程经济与项目管理课程，包括但不限于：投入产出、机会成本、敏捷协作、质量成本、技术债、维护成本、里程碑与风险控制。
4. 必须有观点论证、辩证讨论和可执行建议，避免空泛描述。
5. 输出为 Markdown，并使用以下标题框架：
   ## 引言
   ## 一、项目启动阶段的工程经济与项目管理分析
   ## 二、项目实施阶段的工程经济与项目管理分析
   ## 三、项目运行阶段的工程经济与项目管理分析
   ## 四、辩证讨论与改进路径
   ## 结语
6. 不使用列表符号，正文必须全部写成段落。
7. 必须显式引用代码级证据（目录树信号、依赖密度、复杂度估计、测试目录信号、潜在硬编码风险），不得仅做泛化概念讨论。

仓库事实：
{facts_json}

项目技术名片：
{profile_markdown}

代码级洞察摘要：
{code_insight_markdown}

代码级结构化证据（JSON）：
{code_payload_json}
""".strip()

        result_raw = self.client.ask(
            system_prompt=ECON_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
        ).strip()
        result = sanitize_report_markdown(result_raw)
        self.logger.info(
            (
                "state=DONE | agent=econ_agent | profile_chars=%s | code_insight_chars=%s | "
                "output_chars_raw=%s | output_chars_clean=%s"
            ),
            len(profile_markdown),
            len(code_insight_markdown),
            len(result_raw),
            len(result),
        )
        return result
