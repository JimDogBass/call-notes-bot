"""Per-submission pipeline. Takes a candidate form submission (raw form
dict + CV bytes) and produces the rendered PwC proforma + emails it to Chris.

Replaces the older email-triggered orchestrator. LLM call A (forwarded-email
body parse) is gone — the form supplies those answers deterministically. CV
parse (call B) is reused unchanged via cv_extract.extract_cv."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import assemble, config, cv_extract, deliver
from .outlook_sender import get_sender

log = logging.getLogger("proforma_bot")


def handle_submission(
    form: dict[str, str], cv_filename: str, cv_bytes: bytes
) -> None:
    """Build the proforma payload from a form submission, render the .docx,
    and send to Chris with the candidate's full Q&A in the body + the original
    CV attached. Raises on LLM/render/send failures so the caller can surface
    a retry message."""
    cv_text = cv_extract.extract_text(cv_filename, cv_bytes)
    cv = cv_extract.extract_cv(cv_text)
    log.info(
        "cv parsed: name=%r work_experience=%d",
        cv.get("name", ""), len(cv.get("work_experience", [])),
    )

    candidate_name = cv.get("name", "") or ""
    role = (form.get("role") or "").strip()
    header = _build_header(form, candidate_name)
    payload = {"header": header, "cv": cv}

    docx_path = assemble.render_proforma(payload, config.TEMPLATE_PATH)
    body_text = _build_email_body(form, candidate_name, role)
    deliver.deliver(
        docx_path,
        cv_filename=cv_filename,
        cv_bytes=cv_bytes,
        candidate_name=candidate_name,
        role=role,
        body_text=body_text,
    )


def _build_header(form: dict[str, str], candidate_name: str) -> dict:
    """Header dict consumed by assemble.render_proforma. Review fields are
    wrapped in RichText so docxtpl renders them with a yellow highlight —
    Chris must confirm/complete each before forwarding to PwC."""
    return {
        "name": candidate_name,
        # Recruiter-supplied — blank '[TBC]', highlighted.
        "grade": assemble.review_field(None),
        "rate_inc_charge": assemble.review_field(None),
        "ltd_paye_umbrella": assemble.review_field(None),
        # Candidate-supplied but rate-adjacent — prefilled, highlighted.
        "desired_day_rate": assemble.review_field(form.get("desired_day_rate")),
        "office_remote_line": assemble.review_field(form.get("office_remote")),
        # Straight pass-through from form to template.
        "base_location": form.get("location", ""),
        "available_from": form.get("notice_period", ""),
        "holidays_appointments": form.get("holidays", ""),
        "availability_to_interview": form.get("interview_availability", ""),
        "additional_comments": _collect_reasons(form),
    }


def _collect_reasons(form: dict[str, str]) -> list[str]:
    """Three separate form inputs (reason_1/2/3) -> ordered list, blanks
    dropped. Server-side required validation in app.py /submit means all
    three arrive non-empty in practice — defensive strip is for the
    bypass-the-form case."""
    out: list[str] = []
    for key in ("reason_1", "reason_2", "reason_3"):
        value = (form.get(key) or "").strip()
        if value:
            out.append(value)
    return out


# (label, form-key) in the order Chris expects to read them.
_EMAIL_ROWS = (
    ("Notice period / contract end date", "notice_period"),
    ("Current salary", "current_salary"),
    ("Desired day rate", "desired_day_rate"),
    ("Right to work in UK", "right_to_work"),
    ("Location", "location"),
    ("Previous PwC experience", "previous_pwc"),
    ("Other interview activity", "other_interviews"),
    ("Holidays upcoming", "holidays"),
    ("Availability to interview", "interview_availability"),
    ("Remote / hybrid / days in office", "office_remote"),
)


def _build_email_body(
    form: dict[str, str], candidate_name: str, role: str = ""
) -> str:
    """Full Q&A block. Replaces the candidate reply Chris used to forward —
    everything the candidate answered (including intel fields that don't
    render in the .docx) needs to land in this body."""
    parts: list[str] = [
        "Proforma attached, original CV also attached for your records. "
        "Highlighted fields need your review/confirmation before forwarding to PwC.",
        "",
    ]
    if role:
        parts.append(f"Role: {role}")
    if candidate_name:
        parts.append(f"Candidate: {candidate_name}")
    if role or candidate_name:
        parts.append("")
    parts.append("Candidate responses:")
    for label, key in _EMAIL_ROWS:
        value = (form.get(key) or "").strip() or "—"
        parts.append(f"• {label}: {value}")

    reasons = _collect_reasons(form)
    if reasons:
        parts.append("")
        parts.append("Reasons suited:")
        for i, reason in enumerate(reasons, 1):
            parts.append(f"{i}. {reason}")

    return "\n".join(parts)


def notify_failure(
    form: dict[str, str], cv_filename: str, cv_len: int, exc: BaseException
) -> None:
    """Best-effort alert to Chris (cc Joel) when the pipeline raises. Swallows
    its own send errors so it never masks the original failure or breaks the
    candidate's retry page response. Form data only — no CV attachment, since
    a Graph attachment-size failure is itself a likely cause of the original
    exception, and re-attaching would likely fail the alert too."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        exc_class = exc.__class__.__name__
        role = (form.get("role") or "").strip() or "(not provided)"

        parts: list[str] = [
            f"A candidate submission failed processing at {ts}.",
            "",
            f"Failure: {exc_class}",
            f"CV uploaded: {cv_filename} ({cv_len} bytes)",
            f"Role: {role}",
            "",
            "Candidate responses (raw form data, no proforma was rendered):",
        ]
        for label, key in _EMAIL_ROWS:
            value = (form.get(key) or "").strip() or "—"
            parts.append(f"• {label}: {value}")

        reasons = _collect_reasons(form)
        if reasons:
            parts.append("")
            parts.append("Reasons suited:")
            for i, reason in enumerate(reasons, 1):
                parts.append(f"{i}. {reason}")

        parts.append("")
        parts.append(
            "Candidate has been shown a retry page. Check Railway logs for "
            "the traceback."
        )

        subject = f"PwC Proforma — submission FAILED ({exc_class})"
        get_sender().send(
            to=config.CHRIS_PAINE_ADDRESS,
            cc=[config.OUTLOOK_SENDER_EMAIL],
            subject=subject,
            body_text="\n".join(parts),
        )
    except Exception:
        log.exception("failure-alert send failed; original error already logged")
