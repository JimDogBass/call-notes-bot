"""docxtpl render -> .docx in /tmp.

The template at templates/pwc_proforma_template.docx is the PwC submittal doc
converted to docxtpl placeholders + {% for %} loops (see spec §6). Branding,
fonts, logo, and tabbed layout come from the template — this file only fills
content."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from docxtpl import DocxTemplate

log = logging.getLogger("proforma_bot.assemble")


def _ensure_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Backfill the spec §7 contract so the jinja loops never iterate over None.
    The LLM is told to return arrays, but missing keys would still crash the
    {% for %} blocks — easier to backfill here than to harden the template."""
    header = payload.setdefault("header", {})
    for key in (
        "name", "grade", "rate_inc_charge", "desired_day_rate",
        "ltd_paye_umbrella", "base_location", "available_from",
        "holidays_appointments", "office_remote_line",
    ):
        header.setdefault(key, "")
    header.setdefault("additional_comments", [])

    cv = payload.setdefault("cv", {})
    cv.setdefault("candidate_profile", [])
    cv.setdefault("education", [])
    cv.setdefault("work_experience", [])
    cv.setdefault("key_skills_tools", [])
    cv.setdefault("achievements", [])

    for role in cv["work_experience"]:
        role.setdefault("bullets", [])

    return payload


def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    return cleaned.replace(" ", "_") or "candidate"


def _xml_escape(v: Any) -> Any:
    """Pre-escape XML entities in every string before docxtpl substitutes them
    into the docx body. docxtpl 0.20.x does not auto-escape `&`/`<`/`>`, so a
    label like 'Transaction Monitoring & Analysis' becomes malformed XML
    (`<w:t>... & ...</w:t>`) and lxml/Word silently drops the orphan `&`.
    Recurse through dicts/lists so nested fields are covered."""
    if isinstance(v, str):
        return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if isinstance(v, list):
        return [_xml_escape(x) for x in v]
    if isinstance(v, dict):
        return {k: _xml_escape(val) for k, val in v.items()}
    return v


def render_proforma(payload: dict[str, Any], template_path: str) -> str:
    """payload follows the spec §7 contract: {"header": {...}, "cv": {...}}.
    Returns path to the rendered .docx in /tmp."""
    if not os.path.exists(template_path):
        raise FileNotFoundError(
            f"Template missing at {template_path} — drop "
            "pwc_proforma_template.docx into templates/"
        )

    payload = _xml_escape(_ensure_shape(payload))

    doc = DocxTemplate(template_path)
    doc.render(payload)

    safe = _safe_filename(payload["header"].get("name", ""))
    out_path = os.path.join(
        tempfile.gettempdir(), f"PwC_Proforma_{safe}.docx"
    )
    doc.save(out_path)
    log.info("Rendered proforma -> %s", out_path)
    return out_path
