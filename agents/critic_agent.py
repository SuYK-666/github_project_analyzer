from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import Settings
from config.prompts import CRITIC_REWRITE_PROMPT, CRITIC_RUBRIC, CRITIC_SCORE_PROMPT
from utils.deepseek_client import DeepSeekClient
from utils.github_parser import extract_project_facts


class CriticAgent:
    def __init__(
        self,
        client: DeepSeekClient,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger or logging.getLogger("github_project_analyzer.critic_agent")

    @staticmethod
    def _effective_length(markdown_text: str) -> int:
        text = markdown_text
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
        text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
        text = re.sub(r"[*_`~]", "", text)
        text = re.sub(r"\s+", "", text)
        return len(text)

    @staticmethod
    def _coerce_score(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        if score < 0:
            return 0.0
        if score > 10:
            return 10.0
        return score

    def _heuristic_feedback(self, length: int, analysis_label: str) -> str:
        if length < 1200:
            return "请适度扩展关键论证与案例关联，增强分析深度与说服力。"
        return f"请进一步增强{analysis_label}课程术语的落地论证，并确保建议具备可操作步骤。"

    @staticmethod
    def _missing_required_headings(report_markdown: str) -> list[str]:
        required_patterns = {
            "引言": r"^##\s*引言\s*$",
            "一、章节": r"^##\s*一、",
            "二、章节": r"^##\s*二、",
            "三、章节": r"^##\s*三、",
            "四、章节": r"^##\s*四、",
            "结语": r"^##\s*结语\s*$",
        }
        missing: list[str] = []
        for heading, pattern in required_patterns.items():
            if not re.search(pattern, report_markdown, flags=re.M):
                missing.append(heading)
        return missing

    @staticmethod
    def _has_unbalanced_symbols(text: str) -> list[str]:
        pairs = [
            ("(", ")"),
            ("（", "）"),
            ("[", "]"),
            ("【", "】"),
            ("“", "”"),
            ("‘", "’"),
        ]
        issues: list[str] = []
        for left, right in pairs:
            if text.count(left) > text.count(right):
                issues.append(f"存在未闭合符号 {left}{right}")
        return issues

    def _detect_incomplete_reasons(self, report_markdown: str) -> list[str]:
        reasons: list[str] = []
        stripped = report_markdown.strip()
        if not stripped:
            return ["报告内容为空"]

        missing_headings = self._missing_required_headings(report_markdown)
        if missing_headings:
            reasons.append("缺少必需章节: " + "、".join(missing_headings))

        lines = [line.strip() for line in report_markdown.splitlines() if line.strip()]
        if lines:
            tail = lines[-1]
            if not tail.startswith("##"):
                if not re.search(r"[。！？.!?）\)】\]”’]$", tail):
                    reasons.append("结尾疑似未完整收束")
                if re.search(r"(例如|比如|包括|如|以及|和|与|或|并且|并|但|而)$", tail):
                    reasons.append("结尾停在连接词，疑似被截断")

        reasons.extend(self._has_unbalanced_symbols(stripped))
        return reasons

    @staticmethod
    def _detect_prompt_leakage_reasons(report_markdown: str) -> list[str]:
        patterns = [
            (r"作为一名.*智能体", "出现智能体身份提示语"),
            (r"我将基于.*(撰写|生成).*(报告|分析)", "出现任务执行元描述"),
            (r"^(以下|下面)是.*(报告|分析)", "出现模板化引导语"),
            (r"^输出要求[:：]?$", "出现提示词字段“输出要求”"),
            (r"^硬性要求[:：]?$", "出现提示词字段“硬性要求”"),
            (r"^仓库事实[:：]?$", "出现提示词字段“仓库事实”"),
            (r"^项目技术名片[:：]?$", "出现提示词字段“项目技术名片”"),
            (r"请根据以下评审意见重写报告", "出现重写提示词原文"),
        ]
        reasons: list[str] = []

        for raw_line in report_markdown.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for pattern, reason in patterns:
                if re.search(pattern, line):
                    reasons.append(reason)
                    break

        dedup_reasons: list[str] = []
        for item in reasons:
            if item not in dedup_reasons:
                dedup_reasons.append(item)
        return dedup_reasons

    def review(
        self,
        report_markdown: str,
        analysis_label: str,
        repo_payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.logger.info(
            "state=START | agent=critic_agent | action=review | analysis_label=%s",
            analysis_label,
        )
        effective_length = self._effective_length(report_markdown)
        facts = extract_project_facts(repo_payload)

        user_prompt = f"""
{CRITIC_RUBRIC}

当前任务信息：
- 分析方向：{analysis_label}
- 目标字数：{self.settings.report_target_chars}
- 合理区间：{self.settings.report_min_chars}-{self.settings.report_max_chars}
- 当前有效字数：{effective_length}

仓库事实摘要：
{json.dumps(facts, ensure_ascii=False, indent=2)}

待评审报告：
{report_markdown}
""".strip()

        raw_result = self.client.ask(
            system_prompt=CRITIC_SCORE_PROMPT,
            user_prompt=user_prompt,
            temperature=0.15,
            max_tokens=900,
        )
        parsed = self.client.try_parse_json(raw_result) or {}

        score = self._coerce_score(parsed.get("score"))
        feedback = str(parsed.get("feedback", "")).strip()
        missing_dimensions = parsed.get("missing_dimensions", [])
        if not isinstance(missing_dimensions, list):
            missing_dimensions = []
        if not feedback:
            feedback = self._heuristic_feedback(effective_length, analysis_label)

        incomplete_reasons = self._detect_incomplete_reasons(report_markdown)
        is_incomplete = bool(incomplete_reasons)
        prompt_leakage_reasons = self._detect_prompt_leakage_reasons(report_markdown)
        has_prompt_leakage = bool(prompt_leakage_reasons)

        hard_fail_messages: list[str] = []

        if is_incomplete:
            score = min(score, max(0.0, self.settings.critic_score_threshold - 0.5))
            hard_fail_messages.append("检测到报告残缺或被截断：" + "；".join(incomplete_reasons))
            self.logger.warning(
                "state=INCOMPLETE | agent=critic_agent | reasons=%s",
                " | ".join(incomplete_reasons),
            )

        if has_prompt_leakage:
            score = min(score, max(0.0, self.settings.critic_score_threshold - 0.5))
            hard_fail_messages.append("检测到提示词泄露：" + "；".join(prompt_leakage_reasons))
            self.logger.warning(
                "state=PROMPT_LEAKAGE | agent=critic_agent | reasons=%s",
                " | ".join(prompt_leakage_reasons),
            )

        if hard_fail_messages:
            feedback = "；".join(hard_fail_messages) + "。请清理提示词痕迹并补全内容后再提交。"

        passed = (
            (score >= self.settings.critic_score_threshold)
            and (not is_incomplete)
            and (not has_prompt_leakage)
        )

        result = {
            "score": score,
            "pass": passed,
            "feedback": feedback,
            "missing_dimensions": missing_dimensions,
            "effective_length": effective_length,
            "incomplete": is_incomplete,
            "incomplete_reasons": incomplete_reasons,
            "prompt_leakage": has_prompt_leakage,
            "prompt_leakage_reasons": prompt_leakage_reasons,
            "raw_result": raw_result,
        }
        self.logger.info(
            "state=DONE | agent=critic_agent | action=review | score=%.2f | pass=%s | effective_length=%s | incomplete=%s | prompt_leakage=%s",
            score,
            passed,
            effective_length,
            is_incomplete,
            has_prompt_leakage,
        )
        return result

    def rewrite(
        self,
        current_markdown: str,
        review_result: dict[str, Any],
        analysis_label: str,
        repo_payload: dict[str, Any],
    ) -> str:
        self.logger.info(
            "state=START | agent=critic_agent | action=rewrite | analysis_label=%s",
            analysis_label,
        )
        facts = extract_project_facts(repo_payload)
        user_prompt = f"""
请根据以下评审意见重写报告。

方向：{analysis_label}
评审意见：{review_result.get('feedback', '')}
缺失维度：{review_result.get('missing_dimensions', [])}
当前有效字数：{review_result.get('effective_length', 0)}
目标字数：{self.settings.report_target_chars}，合理区间 {self.settings.report_min_chars}-{self.settings.report_max_chars}

仓库事实摘要：
{json.dumps(facts, ensure_ascii=False, indent=2)}

当前报告：
{current_markdown}
""".strip()

        rewritten = self.client.ask(
            system_prompt=CRITIC_REWRITE_PROMPT,
            user_prompt=user_prompt,
            temperature=0.25,
            max_tokens=self.settings.max_tokens,
        )
        result = rewritten.strip()
        self.logger.info(
            "state=DONE | agent=critic_agent | action=rewrite | output_chars=%s",
            len(result),
        )
        return result
