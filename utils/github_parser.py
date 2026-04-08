from __future__ import annotations

import re
from typing import Any


_REPO_URL_PATTERN = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def parse_github_url(repo_url: str) -> tuple[str, str]:
    text = repo_url.strip()
    match = _REPO_URL_PATTERN.match(text)
    if not match:
        raise ValueError(
            "Invalid GitHub repository URL. Use https://github.com/<owner>/<repo> or <owner>/<repo>."
        )
    owner = match.group("owner")
    repo = match.group("repo")
    return owner, repo


def normalize_markdown(text: str, max_chars: int = 12000) -> str:
    content = text or ""
    content = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    content = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", content)
    content = re.sub(r"<img[^>]*>", "", content, flags=re.I)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[Content truncated for analysis]"
    return content


def extract_project_facts(repo_payload: dict[str, Any]) -> dict[str, Any]:
    meta = repo_payload.get("repository", {})
    languages = repo_payload.get("languages", {})
    contributors = repo_payload.get("top_contributors", [])

    language_sorted = sorted(languages.items(), key=lambda item: item[1], reverse=True)
    top_languages = [name for name, _ in language_sorted[:5]]

    return {
        "full_name": meta.get("full_name", ""),
        "description": meta.get("description", ""),
        "stars": meta.get("stargazers_count", 0),
        "forks": meta.get("forks_count", 0),
        "open_issues_count": meta.get("open_issues_count", 0),
        "watchers": meta.get("subscribers_count", 0),
        "default_branch": meta.get("default_branch", "main"),
        "license": (meta.get("license") or {}).get("spdx_id", "UNKNOWN"),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "topics": meta.get("topics", []),
        "top_languages": top_languages,
        "contributors": [item.get("login", "") for item in contributors[:10]],
    }


def _list_to_bullets(items: list[Any]) -> str:
    if not items:
        return "- N/A"
    return "\n".join(f"- {item}" for item in items)


def build_analysis_context(repo_payload: dict[str, Any], max_readme_chars: int = 12000) -> str:
    facts = extract_project_facts(repo_payload)
    readme = normalize_markdown(repo_payload.get("readme", ""), max_chars=max_readme_chars)

    topics = _list_to_bullets(facts.get("topics", []))
    languages = _list_to_bullets(facts.get("top_languages", []))
    contributors = _list_to_bullets(facts.get("contributors", []))

    return (
        "[Repository Facts]\n"
        f"- Full Name: {facts.get('full_name', '')}\n"
        f"- Description: {facts.get('description', '')}\n"
        f"- Stars: {facts.get('stars', 0)}\n"
        f"- Forks: {facts.get('forks', 0)}\n"
        f"- Open Issues: {facts.get('open_issues_count', 0)}\n"
        f"- Watchers: {facts.get('watchers', 0)}\n"
        f"- Default Branch: {facts.get('default_branch', 'main')}\n"
        f"- License: {facts.get('license', 'UNKNOWN')}\n"
        f"- Created At: {facts.get('created_at', '')}\n"
        f"- Updated At: {facts.get('updated_at', '')}\n\n"
        "[Topics]\n"
        f"{topics}\n\n"
        "[Main Languages]\n"
        f"{languages}\n\n"
        "[Top Contributors]\n"
        f"{contributors}\n\n"
        "[README]\n"
        f"{readme}\n"
    )
