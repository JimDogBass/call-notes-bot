"""Shared Azure OpenAI client. gpt-4o-mini deployment, same as call-notes-bot pattern."""
import json
import re
from typing import Any

from openai import AzureOpenAI

from . import config

_client: AzureOpenAI | None = None


def client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=config.AOAI_ENDPOINT,
            api_key=config.AOAI_API_KEY,
            api_version=config.AOAI_API_VERSION,
        )
    return _client


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s


def extract_json(system_prompt: str, user_content: str, *, max_tokens: int = 4000) -> dict[str, Any]:
    """Call gpt-4o-mini; defensive JSON parse with one retry on failure."""

    def _call() -> str:
        resp = client().chat.completions.create(
            model=config.AOAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=0,
            timeout=120,
        )
        return resp.choices[0].message.content or ""

    raw = _call()
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        raw = _call()
        return json.loads(_strip_fences(raw))
