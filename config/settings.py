from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    logs_dir: Path
    data_workspace: Path
    raw_data_dir: Path
    processed_cache_dir: Path
    final_reports_dir: Path
    reports_output_dir: Path

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    github_token: str
    github_api_base_url: str

    output_language: str
    request_timeout: int
    max_retry: int
    temperature: float
    max_tokens: int
    max_retry_rounds: int
    report_target_chars: int
    report_min_chars: int
    report_max_chars: int
    critic_score_threshold: float

    def ensure_workspace(self) -> None:
        for path in (
            self.logs_dir,
            self.data_workspace,
            self.raw_data_dir,
            self.processed_cache_dir,
            self.final_reports_dir,
            self.reports_output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parents[1]
    logs_dir = base_dir / "logs"
    data_workspace = base_dir / "data_workspace"
    raw_data_dir = data_workspace / "raw_data"
    processed_cache_dir = data_workspace / "processed_cache"
    final_reports_dir = data_workspace / "final_reports"
    reports_output_dir = final_reports_dir / "reports"

    settings = Settings(
        base_dir=base_dir,
        logs_dir=logs_dir,
        data_workspace=data_workspace,
        raw_data_dir=raw_data_dir,
        processed_cache_dir=processed_cache_dir,
        final_reports_dir=final_reports_dir,
        reports_output_dir=reports_output_dir,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/"),
        output_language=os.getenv("OUTPUT_LANGUAGE", "zh-CN").strip(),
        request_timeout=_env_int("REQUEST_TIMEOUT", 60),
        max_retry=_env_int("MAX_RETRY", 3),
        temperature=_env_float("TEMPERATURE", 0.4),
        max_tokens=_env_int("MAX_TOKENS", 2800),
        max_retry_rounds=_env_int("MAX_RETRY_ROUNDS", 3),
        report_target_chars=_env_int("REPORT_TARGET_CHARS", 2000),
        report_min_chars=_env_int("REPORT_MIN_CHARS", 1700),
        report_max_chars=_env_int("REPORT_MAX_CHARS", 2600),
        critic_score_threshold=_env_float("CRITIC_SCORE_THRESHOLD", 8.0),
    )
    settings.ensure_workspace()
    return settings
