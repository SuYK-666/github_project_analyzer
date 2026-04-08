from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

from config import Settings
from config.prompts import CODE_INSIGHT_SYSTEM_PROMPT
from utils.deepseek_client import DeepSeekClient
from utils.output_sanitizer import sanitize_code_insight_markdown


class CodeInsightAgent:
    """Generate code-level insight summaries from sampled repository artifacts."""

    _COMPLEXITY_PATTERNS = (
        r"\bif\b",
        r"\belif\b",
        r"\bfor\b",
        r"\bwhile\b",
        r"\bcase\b",
        r"\bexcept\b",
        r"\bcatch\b",
        r"\btry\b",
        r"\band\b",
        r"\bor\b",
        r"\?",
        r"&&",
        r"\|\|",
    )

    _SECRET_PATTERNS = (
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][A-Za-z0-9_\-\./=]{8,}[\"']",
        r"(?i)ghp_[A-Za-z0-9]{20,}",
        r"(?i)sk-[A-Za-z0-9]{16,}",
    )

    def __init__(
        self,
        client: DeepSeekClient,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger or logging.getLogger("github_project_analyzer.code_insight_agent")

    @staticmethod
    def _safe_excerpt(text: str, max_chars: int = 3200) -> str:
        normalized = (text or "").replace("\r\n", "\n").strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars] + "\n\n# [Truncated for analysis]"

    @staticmethod
    def _summarize_tree(tree_entries: list[dict[str, Any]]) -> dict[str, Any]:
        top_levels: Counter[str] = Counter()
        has_tests = False
        has_docs = False
        has_src = False
        has_ci = False

        for item in tree_entries:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            top = path.split("/", 1)[0]
            top_levels[top] += 1

            lowered = path.lower()
            if "/tests/" in f"/{lowered}/" or "/test/" in f"/{lowered}/":
                has_tests = True
            if "/docs/" in f"/{lowered}/" or lowered.startswith("docs/"):
                has_docs = True
            if "/src/" in f"/{lowered}/" or lowered.startswith("src/"):
                has_src = True
            if lowered.startswith(".github/workflows/"):
                has_ci = True

        return {
            "entry_count": len(tree_entries),
            "top_level_paths": [name for name, _ in top_levels.most_common(12)],
            "has_tests_dir": has_tests,
            "has_docs_dir": has_docs,
            "has_src_dir": has_src,
            "has_ci_workflow": has_ci,
        }

    def _estimate_complexity(self, text: str) -> int:
        lowered = (text or "").lower()
        score = 1
        for pattern in self._COMPLEXITY_PATTERNS:
            score += len(re.findall(pattern, lowered))
        return score

    def _detect_secret_hits(self, text: str) -> int:
        content = text or ""
        hit_count = 0
        for pattern in self._SECRET_PATTERNS:
            hit_count += len(re.findall(pattern, content))
        return hit_count

    @staticmethod
    def _parse_requirements(content: str) -> list[str]:
        names: list[str] = []
        for line in (content or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _parse_package_json(content: str) -> list[str]:
        try:
            payload = json.loads(content or "{}")
        except json.JSONDecodeError:
            return []

        names: list[str] = []
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            dep_obj = payload.get(section, {})
            if isinstance(dep_obj, dict):
                names.extend(str(name) for name in dep_obj.keys())
        return names

    @staticmethod
    def _parse_go_mod(content: str) -> list[str]:
        names: list[str] = []
        in_block = False
        for line in (content or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("require ("):
                in_block = True
                continue
            if in_block and stripped == ")":
                in_block = False
                continue

            if stripped.startswith("require "):
                module = stripped.replace("require ", "", 1).split(" ", 1)[0].strip()
                if module:
                    names.append(module)
                continue

            if in_block:
                module = stripped.split(" ", 1)[0].strip()
                if module:
                    names.append(module)
        return names

    @staticmethod
    def _parse_pom_xml(content: str) -> list[str]:
        artifact_ids = re.findall(r"<artifactId>([^<]+)</artifactId>", content or "", flags=re.I)
        return [item.strip() for item in artifact_ids if item.strip()]

    @staticmethod
    def _parse_pyproject(content: str) -> list[str]:
        names: list[str] = []

        array_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content or "", flags=re.S)
        if array_match:
            entries = re.findall(r"[\"']([^\"']+)[\"']", array_match.group(1))
            for entry in entries:
                name = re.split(r"[<>=!~\[]", entry, maxsplit=1)[0].strip()
                if name:
                    names.append(name)
        return names

    def _build_dependency_overview(self, manifest_files: list[dict[str, Any]]) -> dict[str, Any]:
        all_dependencies: list[str] = []
        by_manifest: list[dict[str, Any]] = []

        for item in manifest_files:
            path = str(item.get("path", "")).strip()
            content = str(item.get("content", ""))
            lowered = path.lower()

            if lowered.endswith("requirements.txt"):
                deps = self._parse_requirements(content)
            elif lowered.endswith("package.json"):
                deps = self._parse_package_json(content)
            elif lowered.endswith("go.mod"):
                deps = self._parse_go_mod(content)
            elif lowered.endswith("pom.xml"):
                deps = self._parse_pom_xml(content)
            elif lowered.endswith("pyproject.toml"):
                deps = self._parse_pyproject(content)
            else:
                deps = []

            all_dependencies.extend(deps)
            by_manifest.append(
                {
                    "path": path,
                    "dependency_count": len(deps),
                    "dependency_samples": deps[:12],
                }
            )

        normalized = sorted({name.strip() for name in all_dependencies if name.strip()})
        return {
            "manifest_count": len(manifest_files),
            "dependency_count_total": len(normalized),
            "dependency_samples": normalized[:30],
            "by_manifest": by_manifest,
        }

    def _build_source_metrics(self, core_files: list[dict[str, Any]]) -> dict[str, Any]:
        file_metrics: list[dict[str, Any]] = []

        for item in core_files:
            content = str(item.get("content", ""))
            complexity = self._estimate_complexity(content)
            secret_hits = self._detect_secret_hits(content)
            line_count = len(content.splitlines()) if content else 0
            file_metrics.append(
                {
                    "path": str(item.get("path", "")),
                    "language": str(item.get("language", "")),
                    "line_count": line_count,
                    "complexity_estimate": complexity,
                    "secret_hits": secret_hits,
                }
            )

        complexity_values = [int(entry.get("complexity_estimate", 0)) for entry in file_metrics]
        avg_complexity = round(sum(complexity_values) / len(complexity_values), 2) if complexity_values else 0.0
        high_risk = [
            entry["path"]
            for entry in file_metrics
            if int(entry.get("complexity_estimate", 0)) >= 15 or int(entry.get("secret_hits", 0)) > 0
        ]

        return {
            "sampled_file_count": len(core_files),
            "avg_complexity_estimate": avg_complexity,
            "secret_hit_count": sum(int(entry.get("secret_hits", 0)) for entry in file_metrics),
            "high_risk_file_paths": high_risk,
            "sampled_file_metrics": file_metrics,
        }

    def _map_single_file(self, file_item: dict[str, Any]) -> dict[str, Any]:
        path = str(file_item.get("path", ""))
        language = str(file_item.get("language", ""))
        content = self._safe_excerpt(str(file_item.get("content", "")), max_chars=2400)

        if not content:
            return {
                "path": path,
                "summary": "证据不足：该文件未抓取到有效代码内容。",
            }

        user_prompt = f"""
请阅读以下仓库核心源码片段，并给出一段简洁的代码洞察摘要。

输出要求：
1. 仅输出一段中文，120-220 字。
2. 必须覆盖：模块职责、可维护性风险、安全或合规风险（若证据不足请明确说明）。
3. 不要使用列表符号。

文件路径：{path}
语言：{language}
源码片段：
{content}
""".strip()

        try:
            summary = self.client.ask(
                system_prompt=CODE_INSIGHT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=360,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "state=MAP_FALLBACK | agent=code_insight_agent | path=%s | error=%s",
                path,
                exc,
            )
            summary = "证据不足：该文件的 LLM 细读失败，建议在后续运行中重试。"

        return {
            "path": path,
            "summary": summary,
        }

    def _build_heuristic_fallback_markdown(
        self,
        analysis_label: str,
        tree_overview: dict[str, Any],
        dependency_overview: dict[str, Any],
        source_metrics: dict[str, Any],
    ) -> str:
        top_levels = ", ".join(tree_overview.get("top_level_paths", [])[:8]) or "证据不足"
        avg_complexity = source_metrics.get("avg_complexity_estimate", 0.0)
        secret_hits = source_metrics.get("secret_hit_count", 0)
        dep_count = dependency_overview.get("dependency_count_total", 0)

        return (
            "## 代码级洞察摘要\n"
            "### 架构与模块化观察\n"
            f"目录树显示该仓库当前可见的顶层路径主要包括 {top_levels}。"
            "从结构信号看，系统存在基础模块化痕迹，但仍需结合完整源码进一步验证边界划分与接口内聚性。\n"
            "### 依赖与技术债观察\n"
            f"依赖清单可识别到约 {dep_count} 个第三方依赖。"
            f"采样核心文件的平均复杂度估计值约为 {avg_complexity}，"
            "若核心模块复杂度持续抬升且缺乏配套测试，后续维护成本和重构成本将同步增加。\n"
            "### 安全与合规代码锚点\n"
            f"静态扫描在采样文件中检测到 {secret_hits} 处疑似敏感配置硬编码信号。"
            "该结果仅作为早期风险提示，建议在 CI 中接入专门的密钥扫描与依赖漏洞扫描。\n"
            "### 可复用事实清单\n"
            f"以上代码事实可直接作为{analysis_label}报告中的证据锚点，用于支撑维护成本、技术债、"
            "安全治理和合规风险等章节的论证。"
        )

    def analyze(self, repo_payload: dict[str, Any], analysis_label: str) -> dict[str, Any]:
        self.logger.info(
            "state=START | agent=code_insight_agent | analysis_label=%s",
            analysis_label,
        )

        tree_entries = repo_payload.get("repo_tree", [])
        manifests = repo_payload.get("manifest_files", [])
        core_files = repo_payload.get("sampled_core_files", [])

        if not isinstance(tree_entries, list):
            tree_entries = []
        if not isinstance(manifests, list):
            manifests = []
        if not isinstance(core_files, list):
            core_files = []

        tree_overview = self._summarize_tree(tree_entries)
        dependency_overview = self._build_dependency_overview(manifests)
        source_metrics = self._build_source_metrics(core_files)

        map_summaries: list[dict[str, Any]] = []
        for file_item in core_files[:5]:
            if not isinstance(file_item, dict):
                continue
            map_summaries.append(self._map_single_file(file_item))

        reduce_prompt = f"""
请将以下代码证据综合为“代码级洞察摘要”，供后续{analysis_label}报告使用。

输出要求：
1. 使用 Markdown 输出，并严格包含以下标题：
   ## 代码级洞察摘要
   ### 架构与模块化观察
   ### 依赖与技术债观察
   ### 安全与合规代码锚点
   ### 可复用事实清单
2. 每个小节写成连续段落，不使用列表符号。
3. 对没有充分证据的结论，明确写“证据不足”，禁止臆测。
4. 可复用事实清单部分必须可直接被领域报告引用。

目录树概览：
{json.dumps(tree_overview, ensure_ascii=False, indent=2)}

依赖概览：
{json.dumps(dependency_overview, ensure_ascii=False, indent=2)}

采样源码静态指标：
{json.dumps(source_metrics, ensure_ascii=False, indent=2)}

Map 阶段源码摘要：
{json.dumps(map_summaries, ensure_ascii=False, indent=2)}
""".strip()

        insight_raw = ""
        try:
            insight_raw = self.client.ask(
                system_prompt=CODE_INSIGHT_SYSTEM_PROMPT,
                user_prompt=reduce_prompt,
                temperature=0.2,
                max_tokens=min(max(900, self.settings.max_tokens), 1800),
            ).strip()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "state=REDUCE_FALLBACK | agent=code_insight_agent | error=%s",
                exc,
            )

        if not insight_raw:
            insight_raw = self._build_heuristic_fallback_markdown(
                analysis_label=analysis_label,
                tree_overview=tree_overview,
                dependency_overview=dependency_overview,
                source_metrics=source_metrics,
            )

        insight_markdown = sanitize_code_insight_markdown(insight_raw)
        if not insight_markdown:
            insight_markdown = self._build_heuristic_fallback_markdown(
                analysis_label=analysis_label,
                tree_overview=tree_overview,
                dependency_overview=dependency_overview,
                source_metrics=source_metrics,
            )

        self.logger.info(
            "state=DONE | agent=code_insight_agent | tree_entries=%s | manifests=%s | sampled_files=%s | output_chars=%s",
            len(tree_entries),
            len(manifests),
            len(core_files),
            len(insight_markdown),
        )

        return {
            "code_insight_markdown": insight_markdown,
            "tree_overview": tree_overview,
            "dependency_overview": dependency_overview,
            "source_metrics": source_metrics,
            "map_summaries": map_summaries,
        }
