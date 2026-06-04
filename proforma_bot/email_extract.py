"""Forwarded email body -> header JSON via Azure OpenAI gpt-4o-mini."""
import re
from typing import Any

from . import aoai

SYSTEM_PROMPT = """You are extracting a contractor's submission details from a FORWARDED email.
The text contains a forwarding preamble and quoted headers (From/Sent/To) — IGNORE those.
Extract ONLY the candidate's own stated answers.

Return ONLY valid JSON for the "header" object (omit rate_inc_charge and ltd_paye_umbrella —
those are set downstream).
Rules:
- Capture the candidate's requested rate into desired_day_rate. Never infer a charge rate.
- additional_comments = the candidate's "reasons suited" points, verbatim, as an array.
- Put right-to-work, current salary, previous PwC experience, other interview activity and
  interview availability into _intel.
- If a field is absent use "". Do not invent values.
- No prose, no markdown fences — JSON only."""


def html_to_text(html_or_text: str) -> str:
    """Cheap HTML strip; swap for bs4 / html2text if forwards arrive HTML-only."""
    # TODO: use a real HTML-to-text step if message body is HTML
    return re.sub(r"<[^>]+>", "", html_or_text)


def extract_header(body_text: str) -> dict[str, Any]:
    return aoai.extract_json(SYSTEM_PROMPT, body_text, max_tokens=2000)


def merge_manual_defaults(header: dict[str, Any]) -> dict[str, Any]:
    """rate_inc_charge / ltd_paye_umbrella / office_remote_line are NEVER inferred.
    Manual fields are non-negotiable per spec §7."""
    header.setdefault("rate_inc_charge", "[TBC]")
    header.setdefault("ltd_paye_umbrella", "[TBC]")
    header.setdefault("office_remote_line", "")
    return header
