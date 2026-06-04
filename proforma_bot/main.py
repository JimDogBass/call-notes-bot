"""Orchestration. handle_message is the single per-message entry point;
the trigger module is what actually invokes it on a schedule."""
import logging

from . import assemble, config, cv_extract, deliver, email_extract, graph_client

log = logging.getLogger("proforma_bot")

# Terminal outcomes — the trigger uses these to decide whether to mark-as-read.
# Anything not listed here means an uncaught exception; the trigger leaves the
# message unread so a human can investigate.
RESULT_PROCESSED = "processed"
RESULT_NO_ATTACHMENT = "ignored_no_attachment"
RESULT_WRONG_SENDER = "ignored_wrong_sender"  # belt-and-braces; Graph $filter should pre-exclude
TERMINAL_RESULTS = frozenset({RESULT_PROCESSED, RESULT_NO_ATTACHMENT, RESULT_WRONG_SENDER})


def handle_message(message_id: str) -> str:
    """Per-message pipeline. Returns one of the RESULT_* constants on terminal
    outcomes; raises on unexpected failures (LLM, Graph, render)."""
    msg = graph_client.get_message(message_id)

    if graph_client.sender_address(msg) != config.CHRIS_PAINE_ADDRESS.lower():
        log.info("ignore: sender not Chris Paine")
        return RESULT_WRONG_SENDER

    attachments = graph_client.list_attachments(message_id)
    cv_att = cv_extract.pick_cv_attachment(attachments)
    if not cv_att:
        log.info("ignore: no usable CV attachment")
        return RESULT_NO_ATTACHMENT

    body_html = msg.get("body", {}).get("content", "")
    body_text = email_extract.html_to_text(body_html)

    header = email_extract.extract_header(body_text)
    header = email_extract.merge_manual_defaults(header)

    blob = graph_client.download_attachment(message_id, cv_att["id"])
    cv_text = cv_extract.extract_text(cv_att["name"], blob)
    cv = cv_extract.extract_cv(cv_text)

    payload = {"header": header, "cv": cv}

    # PII: do NOT log payload contents (passport/right-to-work/salary/phone live in _intel).
    docx_path = assemble.render_proforma(payload, config.TEMPLATE_PATH)
    deliver.deliver(docx_path, candidate_name=header.get("name", ""))
    return RESULT_PROCESSED
