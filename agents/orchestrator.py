from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agents.context_profiler import ContextProfilerAgent
from agents.code_insight_agent import CodeInsightAgent
from agents.crawler_agent import CrawlerAgent
from agents.critic_agent import CriticAgent
from agents.econ_agent import EconAgent
from agents.ethics_agent import EthicsAgent
from config import Settings, get_settings
from renderers.report_renderer import ReportRenderer
from utils.deepseek_client import DeepSeekClient


class Orchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        progress_callback: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.progress_callback = progress_callback
        self.logger = logger or logging.getLogger("github_project_analyzer.orchestrator")

        self.deepseek_client = DeepSeekClient(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
            model=self.settings.deepseek_model,
            timeout=self.settings.request_timeout,
            max_retry=self.settings.max_retry,
        )

        self.crawler_agent = CrawlerAgent(
            settings=self.settings,
            logger=self.logger.getChild("crawler_agent"),
        )
        self.context_profiler = ContextProfilerAgent(
            client=self.deepseek_client,
            settings=self.settings,
            logger=self.logger.getChild("context_profiler"),
        )
        self.code_insight_agent = CodeInsightAgent(
            client=self.deepseek_client,
            settings=self.settings,
            logger=self.logger.getChild("code_insight_agent"),
        )
        self.econ_agent = EconAgent(
            client=self.deepseek_client,
            settings=self.settings,
            logger=self.logger.getChild("econ_agent"),
        )
        self.ethics_agent = EthicsAgent(
            client=self.deepseek_client,
            settings=self.settings,
            logger=self.logger.getChild("ethics_agent"),
        )
        self.critic_agent = CriticAgent(
            client=self.deepseek_client,
            settings=self.settings,
            logger=self.logger.getChild("critic_agent"),
        )
        self.renderer = ReportRenderer(settings=self.settings)

    @staticmethod
    def normalize_analysis_type(analysis_type: str) -> str:
        raw = analysis_type.strip().lower()
        mapping = {
            "1": "econ",
            "工程经济": "econ",
            "工程经济与项目管理": "econ",
            "经济": "econ",
            "econ": "econ",
            "engineering_economics": "econ",
            "2": "ethics",
            "伦理": "ethics",
            "伦理法规": "ethics",
            "伦理法规与工程伦理": "ethics",
            "安全法规": "ethics",
            "ethics": "ethics",
            "safety_ethics": "ethics",
        }
        if raw not in mapping:
            raise ValueError(
                "Invalid analysis type. Use: econ / ethics / 工程经济 / 伦理法规 / 1 / 2"
            )
        return mapping[raw]

    @staticmethod
    def analysis_label(analysis_type: str) -> str:
        if analysis_type == "econ":
            return "工程经济与项目管理"
        return "伦理法规与工程安全"

    def _log(self, message: str, agent: str = "orchestrator", state: str = "RUNNING") -> None:
        self.logger.info("state=%s | agent=%s | %s", state, agent, message)
        if self.progress_callback:
            self.progress_callback(message)

    def _write_cache(self, stage: str, payload: dict[str, Any]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.settings.processed_cache_dir / f"{stamp}_{stage}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("state=CACHE | agent=orchestrator | stage=%s | path=%s", stage, path)
        return path

    def run(self, repo_url: str, analysis_type: str) -> dict[str, Any]:
        self._log(
            f"任务启动 | repo_url={repo_url} | analysis_type={analysis_type}",
            agent="orchestrator",
            state="START",
        )
        normalized_type = self.normalize_analysis_type(analysis_type)
        analysis_label = self.analysis_label(normalized_type)

        self._log("开始抓取 GitHub 项目数据...", agent="crawler_agent", state="RUNNING")
        repo_payload = self.crawler_agent.fetch_repository_data(repo_url)
        self._write_cache("01_crawler_payload", repo_payload)
        repo_meta = repo_payload.get("repository") or {}
        self._log(
            (
                "抓取完成 | full_name="
                f"{repo_meta.get('full_name', 'unknown/repo')} | "
                f"stars={repo_meta.get('stargazers_count', 0)} | "
                f"issues={len(repo_payload.get('issues', []))} | "
                f"contributors={len(repo_payload.get('top_contributors', []))}"
            ),
            agent="crawler_agent",
            state="DONE",
        )

        self._log("开始生成项目技术名片...", agent="context_profiler", state="RUNNING")
        profile_result = self.context_profiler.profile(repo_payload, analysis_label=analysis_label)
        self._write_cache("02_context_profile", profile_result)
        self._log(
            f"技术名片生成完成 | 字符数={len(profile_result.get('profile_markdown', ''))}",
            agent="context_profiler",
            state="DONE",
        )

        self._log("开始生成代码级洞察摘要...", agent="code_insight_agent", state="RUNNING")
        code_insight_result = self.code_insight_agent.analyze(
            repo_payload=repo_payload,
            analysis_label=analysis_label,
        )
        self._write_cache("03_code_insight", code_insight_result)
        self._log(
            f"代码级洞察完成 | 字符数={len(code_insight_result.get('code_insight_markdown', ''))}",
            agent="code_insight_agent",
            state="DONE",
        )

        self._log(
            f"开始生成 {analysis_label} 报告初稿...",
            agent=f"{normalized_type}_agent",
            state="RUNNING",
        )
        if normalized_type == "econ":
            report_markdown = self.econ_agent.generate(
                repo_payload=repo_payload,
                profile_markdown=profile_result["profile_markdown"],
                code_insight_markdown=code_insight_result["code_insight_markdown"],
                code_insight_payload=code_insight_result,
            )
        else:
            report_markdown = self.ethics_agent.generate(
                repo_payload=repo_payload,
                profile_markdown=profile_result["profile_markdown"],
                code_insight_markdown=code_insight_result["code_insight_markdown"],
                code_insight_payload=code_insight_result,
            )
        self._log(
            f"初稿生成完成 | 字符数={len(report_markdown)}",
            agent=f"{normalized_type}_agent",
            state="DONE",
        )

        self._write_cache(
            "04_draft_report",
            {
                "analysis_type": normalized_type,
                "analysis_label": analysis_label,
                "report_markdown": report_markdown,
            },
        )

        review_history: list[dict[str, Any]] = []
        reviewed_reports: list[dict[str, Any]] = []
        final_report = report_markdown
        max_rounds = min(max(1, self.settings.max_retry_rounds), 3)
        if max_rounds != self.settings.max_retry_rounds:
            self._log(
                f"Critic 轮次上限已限制为 {max_rounds} 轮。",
                agent="critic_agent",
                state="WARN",
            )

        for round_index in range(1, max_rounds + 1):
            self._log(
                f"Critic 审核第 {round_index} 轮...",
                agent="critic_agent",
                state="RUNNING",
            )
            review = self.critic_agent.review(
                report_markdown=final_report,
                analysis_label=analysis_label,
                repo_payload=repo_payload,
            )
            review["round"] = round_index
            review_history.append(review)
            reviewed_reports.append(
                {
                    "round": round_index,
                    "score": float(review.get("score", 0.0)),
                    "report_markdown": final_report,
                    "incomplete": bool(review.get("incomplete", False)),
                    "prompt_leakage": bool(review.get("prompt_leakage", False)),
                }
            )
            self._write_cache(
                f"05_critic_round_{round_index}",
                {
                    "review": review,
                    "report_markdown": final_report,
                },
            )

            self._log(
                f"Critic 第 {round_index} 轮评分: {review['score']:.2f}, "
                f"字数: {review['effective_length']}, 通过: {review['pass']}",
                agent="critic_agent",
                state="DONE",
            )

            if review["pass"]:
                self._log(
                    f"评分达到阈值 {self.settings.critic_score_threshold:.2f}，提前结束 Critic 轮次。",
                    agent="critic_agent",
                    state="DONE",
                )
                break

            if round_index >= max_rounds:
                self._log(
                    "达到最大重写轮次，使用当前版本作为最终报告。",
                    agent="critic_agent",
                    state="WARN",
                )
                break

            self._log("未通过，触发重写...", agent="critic_agent", state="RUNNING")
            final_report = self.critic_agent.rewrite(
                current_markdown=final_report,
                review_result=review,
                analysis_label=analysis_label,
                repo_payload=repo_payload,
            )
            self._log(
                f"重写完成 | 字符数={len(final_report)}",
                agent="critic_agent",
                state="DONE",
            )

        selected_round = 0
        selected_score = 0.0
        selected_incomplete = False
        selected_prompt_leakage = False
        if reviewed_reports:
            best_review = max(
                reviewed_reports,
                key=lambda item: (
                    not item["incomplete"],
                    not item["prompt_leakage"],
                    item["score"],
                    item["round"],
                ),
            )
            final_report = best_review["report_markdown"]
            selected_round = int(best_review["round"])
            selected_score = float(best_review["score"])
            selected_incomplete = bool(best_review["incomplete"])
            selected_prompt_leakage = bool(best_review["prompt_leakage"])
            self._log(
                (
                    f"选择第 {selected_round} 轮（最高分 {selected_score:.2f}，"
                    f"完整性={'残缺' if selected_incomplete else '完整'}，"
                    f"提示词泄露={'是' if selected_prompt_leakage else '否'}）作为最终输出版本。"
                ),
                agent="critic_agent",
                state="DONE",
            )

        repo_full_name = (repo_payload.get("repository") or {}).get("full_name", "unknown/repo")
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report_title = f"{repo_full_name} {analysis_label}分析报告"
        subtitle = f"分析模型：{self.settings.deepseek_model}"

        report_payload = {
            "title": report_title,
            "subtitle": subtitle,
            "analysis_type": normalized_type,
            "analysis_label": analysis_label,
            "repo_url": repo_payload.get("repo_url", repo_url),
            "repo_full_name": repo_full_name,
            "generated_at": generated_at,
            "model_name": self.settings.deepseek_model,
            "project_profile_markdown": profile_result["profile_markdown"],
            "body_markdown": final_report,
        }

        self._log("开始渲染 HTML/MD/DOCX 报告...", agent="renderer", state="RUNNING")
        report_paths = self.renderer.render(report_payload)
        self._log(
            (
                "渲染完成 | "
                f"md={report_paths['md']} | html={report_paths['html']} | docx={report_paths['docx']}"
            ),
            agent="renderer",
            state="DONE",
        )

        final_state = {
            "repo_url": repo_payload.get("repo_url", repo_url),
            "analysis_type": normalized_type,
            "analysis_label": analysis_label,
            "generated_at": generated_at,
            "report_paths": {key: str(path) for key, path in report_paths.items()},
            "critic_history": review_history,
            "selected_critic_round": selected_round,
            "selected_critic_score": selected_score,
            "selected_critic_incomplete": selected_incomplete,
            "selected_critic_prompt_leakage": selected_prompt_leakage,
            "raw_cache_path": repo_payload.get("raw_cache_path", ""),
            "code_insight_markdown": code_insight_result.get("code_insight_markdown", ""),
            "code_insight_payload": code_insight_result,
        }
        final_state_path = self._write_cache("06_final_state", final_state)
        self._log(
            f"任务结束 | final_state_path={final_state_path}",
            agent="orchestrator",
            state="DONE",
        )

        return {
            "analysis_type": normalized_type,
            "analysis_label": analysis_label,
            "report_paths": {key: str(path) for key, path in report_paths.items()},
            "final_state_path": str(final_state_path),
            "critic_history": review_history,
            "selected_critic_round": selected_round,
            "selected_critic_score": selected_score,
            "selected_critic_incomplete": selected_incomplete,
            "selected_critic_prompt_leakage": selected_prompt_leakage,
        }
