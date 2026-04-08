from __future__ import annotations

import base64
import html
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import Settings
from utils.github_parser import normalize_markdown, parse_github_url


class GitHubCrawlerError(RuntimeError):
    """Raised when GitHub crawling fails."""


class CrawlerAgent:
    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.logger = logger or logging.getLogger("github_project_analyzer.crawler_agent")

    def _build_headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "github-project-analyzer/1.0",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        url = f"{self.settings.github_api_base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_retry + 1):
            try:
                self.logger.info(
                    "state=REQUEST | agent=crawler_agent | endpoint=%s | attempt=%s",
                    endpoint,
                    attempt,
                )
                response = self.session.get(
                    url,
                    headers=self._build_headers(accept=accept),
                    params=params,
                    timeout=self.settings.request_timeout,
                )
                if response.status_code == 404:
                    raise GitHubCrawlerError(f"GitHub resource not found: {endpoint}")
                if response.status_code == 403:
                    body = response.text.lower()
                    if "rate limit" in body:
                        reset_at = response.headers.get("X-RateLimit-Reset", "")
                        suffix = f" reset={reset_at}" if reset_at else ""
                        raise GitHubCrawlerError(
                            "GitHub API rate limit exceeded. "
                            "Please provide GITHUB_TOKEN (or Web UI GitHub Token) and retry."
                            f"{suffix}"
                        )
                if response.status_code >= 400:
                    msg = response.text[:300]
                    raise GitHubCrawlerError(
                        f"GitHub API HTTP {response.status_code} on {endpoint}: {msg}"
                    )
                self.logger.info(
                    "state=REQUEST_OK | agent=crawler_agent | endpoint=%s | status=%s",
                    endpoint,
                    response.status_code,
                )
                return response.json()
            except (requests.RequestException, ValueError, GitHubCrawlerError) as exc:
                last_error = exc
                self.logger.warning(
                    "state=REQUEST_RETRY | agent=crawler_agent | endpoint=%s | attempt=%s | error=%s",
                    endpoint,
                    attempt,
                    exc,
                )
                if attempt < self.settings.max_retry:
                    time.sleep(min(2 * attempt, 6))
                else:
                    break

        self.logger.error(
            "state=REQUEST_FAIL | agent=crawler_agent | endpoint=%s | error=%s",
            endpoint,
            last_error,
        )
        raise GitHubCrawlerError(f"Failed to crawl {endpoint}: {last_error}")

    def _request_text(
        self,
        url: str,
        accept: str = "text/plain,*/*;q=0.9",
    ) -> tuple[int, str, dict[str, str]]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retry + 1):
            try:
                response = self.session.get(
                    url,
                    headers={
                        "Accept": accept,
                        "User-Agent": "github-project-analyzer/1.0",
                    },
                    timeout=self.settings.request_timeout,
                )
                return response.status_code, response.text, dict(response.headers)
            except requests.RequestException as exc:
                last_error = exc
                self.logger.warning(
                    "state=REQUEST_TEXT_RETRY | agent=crawler_agent | url=%s | attempt=%s | error=%s",
                    url,
                    attempt,
                    exc,
                )
                if attempt < self.settings.max_retry:
                    time.sleep(min(2 * attempt, 6))

        self.logger.error(
            "state=REQUEST_TEXT_FAIL | agent=crawler_agent | url=%s | error=%s",
            url,
            last_error,
        )
        return 0, "", {}

    @staticmethod
    def _detect_language_by_path(path: str) -> str:
        lowered = path.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".c": "c",
            ".cs": "csharp",
            ".rb": "ruby",
            ".php": "php",
            ".kt": "kotlin",
            ".swift": "swift",
        }
        for suffix, lang in mapping.items():
            if lowered.endswith(suffix):
                return lang
        return "unknown"

    @staticmethod
    def _is_manifest_path(path: str) -> bool:
        lowered = path.lower().strip()
        if lowered.endswith("requirements.txt"):
            return True
        if lowered.endswith("package.json"):
            return True
        if lowered.endswith("pom.xml"):
            return True
        if lowered.endswith("go.mod"):
            return True
        if lowered.endswith("pyproject.toml"):
            return True
        return False

    @staticmethod
    def _is_source_file(path: str) -> bool:
        lowered = path.lower().strip()
        if any(
            lowered.endswith(ext)
            for ext in (
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".jsx",
                ".java",
                ".go",
                ".rs",
                ".cpp",
                ".cc",
                ".cxx",
                ".c",
                ".cs",
                ".rb",
                ".php",
                ".kt",
                ".swift",
            )
        ):
            return True
        return False

    @staticmethod
    def _tree_item_score(path: str) -> int:
        lowered = path.lower()
        score = 0

        if "/src/" in f"/{lowered}/" or lowered.startswith("src/"):
            score += 6
        if "/core/" in f"/{lowered}/" or "/service/" in f"/{lowered}/":
            score += 4
        if lowered.endswith("main.py") or lowered.endswith("main.ts") or lowered.endswith("main.go"):
            score += 7
        if "app" in lowered or "server" in lowered:
            score += 3
        if lowered.endswith("index.js") or lowered.endswith("index.ts"):
            score += 3
        if "/test/" in f"/{lowered}/" or "/tests/" in f"/{lowered}/":
            score -= 4
        if "/docs/" in f"/{lowered}/" or lowered.startswith("docs/"):
            score -= 5
        if lowered.endswith(".min.js"):
            score -= 5
        return score

    def _fetch_text_file_by_raw_url(self, raw_url: str) -> str:
        status, content, _ = self._request_text(raw_url)
        if status != 200:
            return ""
        return normalize_markdown(content, max_chars=18000)

    def _fetch_repo_tree(self, owner: str, repo: str, default_branch: str) -> list[dict[str, Any]]:
        endpoint = f"/repos/{owner}/{repo}/git/trees/{default_branch}"
        payload = self._request_json(endpoint, params={"recursive": "1"})
        tree = payload.get("tree", []) if isinstance(payload, dict) else []

        normalized: list[dict[str, Any]] = []
        for item in tree:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "path": str(item.get("path", "")),
                    "type": str(item.get("type", "")),
                    "size": int(item.get("size", 0) or 0),
                    "sha": str(item.get("sha", "")),
                }
            )
        return normalized

    def _fetch_manifest_files(
        self,
        owner: str,
        repo: str,
        default_branch: str,
        repo_tree: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []

        for item in repo_tree:
            path = str(item.get("path", ""))
            item_type = str(item.get("type", ""))
            if item_type != "blob":
                continue
            if not self._is_manifest_path(path):
                continue

            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"
            content = self._fetch_text_file_by_raw_url(raw_url)
            manifests.append(
                {
                    "path": path,
                    "raw_url": raw_url,
                    "content": content,
                }
            )

        manifests.sort(key=lambda row: row.get("path", ""))
        return manifests[:12]

    def _fetch_sampled_core_files(
        self,
        owner: str,
        repo: str,
        default_branch: str,
        repo_tree: list[dict[str, Any]],
        max_files: int = 5,
    ) -> list[dict[str, Any]]:
        candidates: list[tuple[int, dict[str, Any]]] = []

        for item in repo_tree:
            path = str(item.get("path", ""))
            item_type = str(item.get("type", ""))
            if item_type != "blob":
                continue
            if not self._is_source_file(path):
                continue

            score = self._tree_item_score(path)
            size = int(item.get("size", 0) or 0)
            if 0 < size < 50000:
                score += 2
            if size > 120000:
                score -= 3

            candidates.append((score, item))

        candidates.sort(key=lambda row: (row[0], -len(str(row[1].get("path", "")))), reverse=True)

        sampled: list[dict[str, Any]] = []
        used_paths: set[str] = set()
        for _, item in candidates:
            path = str(item.get("path", ""))
            if not path or path in used_paths:
                continue

            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}"
            content = self._fetch_text_file_by_raw_url(raw_url)
            if not content:
                continue

            sampled.append(
                {
                    "path": path,
                    "raw_url": raw_url,
                    "language": self._detect_language_by_path(path),
                    "content": content,
                }
            )
            used_paths.add(path)
            if len(sampled) >= max_files:
                break

        return sampled

    def _fetch_readme(self, owner: str, repo: str) -> str:
        try:
            payload = self._request_json(f"/repos/{owner}/{repo}/readme")
        except GitHubCrawlerError:
            self.logger.warning(
                "state=README_MISSING | agent=crawler_agent | owner=%s | repo=%s",
                owner,
                repo,
            )
            return ""

        content = payload.get("content", "")
        encoding = payload.get("encoding", "")
        if not content:
            return ""

        if encoding == "base64":
            try:
                decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            except (ValueError, UnicodeDecodeError):
                decoded = ""
        else:
            decoded = str(content)

        return normalize_markdown(decoded, max_chars=20000)

    @staticmethod
    def _extract_repo_description(repo_html: str) -> str:
        if not repo_html:
            return ""
        pattern = re.compile(
            r'<meta\s+property="og:description"\s+content="([^"]*)"',
            flags=re.I,
        )
        match = pattern.search(repo_html)
        if not match:
            return ""
        text = html.unescape(match.group(1)).strip()
        if text.lower().startswith("git hub is where"):
            return ""
        return text

    def _fetch_readme_without_api(self, owner: str, repo: str) -> tuple[str, str]:
        candidates = [
            "README.md",
            "README.MD",
            "Readme.md",
            "readme.md",
            "README.rst",
            "README.txt",
        ]
        for branch in ("main", "master"):
            for name in candidates:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{name}"
                status, content, _ = self._request_text(raw_url)
                if status == 200 and content.strip():
                    return normalize_markdown(content, max_chars=20000), branch
        return "", "main"

    def _fetch_repository_data_without_api(
        self,
        owner: str,
        repo: str,
        fallback_reason: str,
    ) -> dict[str, Any]:
        repo_url = f"https://github.com/{owner}/{repo}"
        status, repo_html, _ = self._request_text(
            repo_url,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        if status == 404:
            raise GitHubCrawlerError(f"GitHub repository not found: {owner}/{repo}")
        if status <= 0:
            raise GitHubCrawlerError(
                "Failed to access GitHub repository page in no-API fallback mode."
            )

        readme, default_branch = self._fetch_readme_without_api(owner=owner, repo=repo)
        description = self._extract_repo_description(repo_html)

        repository = {
            "full_name": f"{owner}/{repo}",
            "name": repo,
            "description": description,
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "subscribers_count": 0,
            "default_branch": default_branch or "main",
            "license": {"spdx_id": "UNKNOWN"},
            "created_at": "",
            "updated_at": "",
            "topics": [],
        }

        repo_tree: list[dict[str, Any]] = []
        manifest_files: list[dict[str, Any]] = []
        sampled_core_files: list[dict[str, Any]] = []

        payload = {
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "repository": repository,
            "readme": readme,
            "languages": {},
            "issues": [],
            "top_contributors": [],
            "repo_tree": repo_tree,
            "manifest_files": manifest_files,
            "sampled_core_files": sampled_core_files,
            "data_source": "github_web_fallback",
            "fallback_reason": fallback_reason,
        }

        cache_path = self._cache_raw_payload(owner=owner, repo=repo, payload=payload)
        payload["raw_cache_path"] = str(cache_path)

        self.logger.warning(
            "state=FALLBACK_DONE | agent=crawler_agent | mode=no_api | full_name=%s/%s | readme_chars=%s",
            owner,
            repo,
            len(readme),
        )
        return payload

    @staticmethod
    def _simplify_issues(raw_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for issue in raw_issues:
            if "pull_request" in issue:
                continue
            labels = issue.get("labels", [])
            rows.append(
                {
                    "number": issue.get("number"),
                    "title": issue.get("title", ""),
                    "state": issue.get("state", ""),
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                    "comments": issue.get("comments", 0),
                    "user": (issue.get("user") or {}).get("login", ""),
                    "labels": [label.get("name", "") for label in labels if isinstance(label, dict)],
                    "html_url": issue.get("html_url", ""),
                }
            )
        return rows[:10]

    @staticmethod
    def _simplify_contributors(raw_contributors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "login": item.get("login", ""),
                "contributions": item.get("contributions", 0),
                "html_url": item.get("html_url", ""),
            }
            for item in raw_contributors[:20]
            if isinstance(item, dict)
        ]

    def _cache_raw_payload(self, owner: str, repo: str, payload: dict[str, Any]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.settings.raw_data_dir / f"{owner}_{repo}_{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info(
            "state=CACHE | agent=crawler_agent | stage=raw_data | path=%s",
            path,
        )
        return path

    def fetch_repository_data(self, repo_url: str) -> dict[str, Any]:
        owner, repo = parse_github_url(repo_url)
        self.logger.info(
            "state=START | agent=crawler_agent | repo_url=%s | owner=%s | repo=%s",
            repo_url,
            owner,
            repo,
        )

        try:
            repository = self._request_json(f"/repos/{owner}/{repo}")
            readme = self._fetch_readme(owner, repo)
            languages = self._request_json(f"/repos/{owner}/{repo}/languages")
            issues_raw = self._request_json(
                f"/repos/{owner}/{repo}/issues",
                params={"state": "all", "per_page": 30, "sort": "updated", "direction": "desc"},
            )
            contributors_raw = self._request_json(
                f"/repos/{owner}/{repo}/contributors",
                params={"per_page": 30},
            )

            default_branch = str((repository or {}).get("default_branch", "main") or "main")
            repo_tree = self._fetch_repo_tree(owner=owner, repo=repo, default_branch=default_branch)
            manifest_files = self._fetch_manifest_files(
                owner=owner,
                repo=repo,
                default_branch=default_branch,
                repo_tree=repo_tree,
            )
            sampled_core_files = self._fetch_sampled_core_files(
                owner=owner,
                repo=repo,
                default_branch=default_branch,
                repo_tree=repo_tree,
                max_files=5,
            )

            payload = {
                "repo_url": f"https://github.com/{owner}/{repo}",
                "owner": owner,
                "repo": repo,
                "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "repository": repository,
                "readme": readme,
                "languages": languages if isinstance(languages, dict) else {},
                "issues": self._simplify_issues(issues_raw if isinstance(issues_raw, list) else []),
                "top_contributors": self._simplify_contributors(
                    contributors_raw if isinstance(contributors_raw, list) else []
                ),
                "repo_tree": repo_tree,
                "manifest_files": manifest_files,
                "sampled_core_files": sampled_core_files,
                "data_source": "github_api",
            }

            cache_path = self._cache_raw_payload(owner=owner, repo=repo, payload=payload)
            payload["raw_cache_path"] = str(cache_path)
            self.logger.info(
                (
                    "state=DONE | agent=crawler_agent | full_name=%s/%s | readme_chars=%s | "
                    "issues=%s | contributors=%s | tree=%s | manifests=%s | sampled_core_files=%s"
                ),
                owner,
                repo,
                len(readme),
                len(payload["issues"]),
                len(payload["top_contributors"]),
                len(repo_tree),
                len(manifest_files),
                len(sampled_core_files),
            )
            return payload
        except GitHubCrawlerError as exc:
            if "rate limit" not in str(exc).lower():
                raise
            self.logger.warning(
                "state=FALLBACK | agent=crawler_agent | reason=%s",
                exc,
            )
            return self._fetch_repository_data_without_api(
                owner=owner,
                repo=repo,
                fallback_reason=str(exc),
            )
