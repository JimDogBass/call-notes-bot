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

    log.info(
        "uid %s: body source=%s len=%d",
        incoming.uid,
        "plain" if incoming.body_text else "html-stripped",
        len(body),
    )

    header = email_extract.extract_header(body)
    header = email_extract.merge_manual_defaults(header)
    log.info("uid %s: extracted header keys=%s name=%r",
             incoming.uid, sorted(k for k, v in header.items() if v and k != "_intel"),
             header.get("name"))

    cv_text = cv_extract.extract_text(incoming.cv_filename, incoming.cv_bytes)
    cv = cv_extract.extract_cv(cv_text)

    # Candidate's name lives on the CV, not in the email body — copy it across
    # so the proforma header renders with the actual name.
    if not header.get("name"):
        header["name"] = cv.get("name", "")

    payload = {"header": header, "cv": cv}

    # PII: do NOT log payload contents (passport/right-to-work/salary/phone live in _intel).
    docx_path = assemble.render_proforma(payload, config.TEMPLATE_PATH)
    deliver.deliver(docx_path, candidate_name=header.get("name", ""))
    return RESULT_PROCESSED
