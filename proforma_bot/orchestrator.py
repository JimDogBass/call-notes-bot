"""Per-message pipeline. Takes an IncomingEmail from gmail_client, returns
a result code the trigger uses to decide mark-as-read."""
from __future__ import annotations

import logging

from . import assemble, config, cv_extract, deliver, email_extract
from .gmail_client import IncomingEmail

log = logging.getLogger("proforma_bot")

RESULT_PROCESSED = "processed"
RESULT_NO_CV_ATTACHMENT = "ignored_no_attachment"  # shouldn't fire — gmail_client pre-filters
TERMINAL_RESULTS = frozenset({RESULT_PROCESSED, RESULT_NO_CV_ATTACHMENT})


def handle(incoming: IncomingEmail) -> str:
    """Returns a RESULT_* string on terminal outcomes; raises on unexpected
    failures (LLM, render, send)."""
    if not incoming.cv_bytes:
        log.info("uid %s: no attachment in IncomingEmail; skip", incoming.uid)
        return RESULT_NO_CV_ATTACHMENT

    # Prefer plain text; fall back to stripped HTML if the forward is HTML-only.
    body = incoming.body_text or email_extract.html_to_text(incoming.body_html)

    header = email_extract.extract_header(body)
    header = email_extract.merge_manual_defaults(header)

    cv_text = cv_extract.extract_text(incoming.cv_filename, incoming.cv_bytes)
    cv = cv_extract.extract_cv(cv_text)

    payload = {"header": header, "cv": cv}

    # PII: do NOT log payload contents (passport/right-to-work/salary/phone live in _intel).
    docx_path = assemble.render_proforma(payload, config.TEMPLATE_PATH)
    deliver.deliver(docx_path, candidate_name=header.get("name", ""))
    return RESULT_PROCESSED
