from __future__ import annotations

import json
import re
import time
from typing import Any

import requests


class DeepSeekAPIError(RuntimeError):
    """Raised when DeepSeek API request fails after retry."""


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
        max_retry: int = 3,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retry = max_retry
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DeepSeekAPIError("DEEPSEEK_API_KEY is empty. Please set it in environment.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 1800,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retry + 1):
            try:
                response = self.session.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    snippet = response.text[:300]
                    raise DeepSeekAPIError(
                        f"DeepSeek API HTTP {response.status_code}: {snippet}"
                    )

                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not content:
                    raise DeepSeekAPIError("DeepSeek returned empty content.")
                return content
            except (requests.RequestException, ValueError, KeyError, IndexError, DeepSeekAPIError) as exc:
                last_error = exc
                if attempt < self.max_retry:
                    time.sleep(min(2 * attempt, 6))
                else:
                    break

        raise DeepSeekAPIError(f"DeepSeek request failed after retries: {last_error}")

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 1800,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)

    @staticmethod
    def try_parse_json(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()

        fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", cleaned, flags=re.I)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            object_match = re.search(r"(\{[\s\S]*\})", cleaned)
            if not object_match:
                return None
            try:
                parsed = json.loads(object_match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return None
        return None
