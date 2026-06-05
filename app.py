"""Flask web entrypoint. Candidates open `GET /`, fill the form, attach a CV,
and submit; we run the proforma pipeline synchronously and email Chris.

Replaces the previous Gmail/IMAP polling worker. Same package internals
(cv_extract, assemble, deliver) — only the trigger surface changed."""
from __future__ import annotations

import logging

from flask import Flask, render_template_string, request

from proforma_bot import config, orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("proforma_bot.app")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — matches handoff cap
ALLOWED_EXTENSIONS = (".docx", ".pdf")


FORM_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Candidate Submission — Meraki Talent</title>
<style>
  :root{--ink:#1a1a2e;--muted:#6b6b7b;--line:#e4e4ec;--accent:#2d6a4f;--bg:#f7f7fa}
  *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg);line-height:1.5}
  .wrap{max-width:640px;margin:0 auto;padding:32px 20px 64px}.brand{font-weight:700;font-size:20px}
  h1{font-size:22px;margin:18px 0 4px}p.sub{color:var(--muted);margin:0 0 24px}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:24px}
  label{display:block;font-weight:600;font-size:14px;margin:16px 0 6px}.hint{font-weight:400;color:var(--muted);font-size:13px}
  input[type=text],textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:15px;font-family:inherit;background:#fff}
  textarea{min-height:96px;resize:vertical}
  button{margin-top:28px;width:100%;padding:14px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-size:16px;font-weight:600;cursor:pointer}
  .note{font-size:12px;color:var(--muted);margin-top:14px;text-align:center}
</style></head><body><div class="wrap">
  <div class="brand">Meraki Talent</div>
  <h1>Candidate Submission</h1><p class="sub">A few quick details and your CV. We'll handle the rest.</p>
  <form class="card" action="/submit" method="post" enctype="multipart/form-data">
    <label>Role applying for <span class="hint">(e.g. Senior Data Engineer)</span></label><input type="text" name="role" />
    <label>Notice Period / contract end date</label><input type="text" name="notice_period" />
    <label>Current Salary</label><input type="text" name="current_salary" />
    <label>Desired Day Rate</label><input type="text" name="desired_day_rate" />
    <label>Right to work in UK <span class="hint">(UK passport, visa etc)</span></label><input type="text" name="right_to_work" />
    <label>Location</label><input type="text" name="location" />
    <label>Previous PWC experience</label><input type="text" name="previous_pwc" />
    <label>Other interview activity <span class="hint">(outline if you're in a process and could be engaged ahead of the contract)</span></label><input type="text" name="other_interviews" />
    <label>Any holidays upcoming</label><input type="text" name="holidays" />
    <label>Availability to interview</label><input type="text" name="interview_availability" />
    <label>Remote / hybrid / days in office <span class="hint">(e.g. happy with 3 days a week in office, or fully remote)</span></label><input type="text" name="office_remote" />
    <label>Reasons you are good for the role <span class="hint">(one per line)</span></label>
    <textarea name="reasons" placeholder="1.&#10;2.&#10;3."></textarea>
    <label>Upload your CV <span class="hint">(.docx or .pdf)</span></label>
    <input type="file" name="cv" accept=".docx,.pdf" required />
    <button type="submit">Submit</button>
    <p class="note">Your CV is processed to generate a submission document and is not stored.</p>
  </form>
</div></body></html>
"""

SUCCESS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Submission received — Meraki Talent</title>
<style>
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;background:#f7f7fa;line-height:1.5}
  .wrap{max-width:560px;margin:0 auto;padding:64px 20px;text-align:center}
  .brand{font-weight:700;font-size:20px;margin-bottom:32px}
  .card{background:#fff;border:1px solid #e4e4ec;border-radius:12px;padding:32px}
  h1{font-size:22px;margin:0 0 12px}p{color:#6b6b7b;margin:0}
</style></head><body><div class="wrap">
  <div class="brand">Meraki Talent</div>
  <div class="card">
    <h1>Thanks — submission received.</h1>
    <p>We've passed your details and CV on to the team. They'll be in touch shortly.</p>
  </div>
</div></body></html>
"""

ERROR_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Something went wrong — Meraki Talent</title>
<style>
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;background:#f7f7fa;line-height:1.5}
  .wrap{max-width:560px;margin:0 auto;padding:64px 20px;text-align:center}
  .brand{font-weight:700;font-size:20px;margin-bottom:32px}
  .card{background:#fff;border:1px solid #e4e4ec;border-radius:12px;padding:32px}
  h1{font-size:22px;margin:0 0 12px}p{color:#6b6b7b;margin:0 0 18px}
  a{display:inline-block;padding:10px 18px;border-radius:8px;background:#2d6a4f;color:#fff;text-decoration:none;font-weight:600}
</style></head><body><div class="wrap">
  <div class="brand">Meraki Talent</div>
  <div class="card">
    <h1>Something went wrong.</h1>
    <p>{{ message }}</p>
    <a href="/">Try again</a>
  </div>
</div></body></html>
"""

FORM_FIELDS = (
    "role", "notice_period", "current_salary", "desired_day_rate",
    "right_to_work", "location", "previous_pwc", "other_interviews",
    "holidays", "interview_availability", "office_remote", "reasons",
)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.get("/")
def index():
    return render_template_string(FORM_HTML)


@app.get("/healthz")
def healthz():
    return ("ok", 200)


@app.post("/submit")
def submit():
    form_data = {k: (request.form.get(k) or "").strip() for k in FORM_FIELDS}

    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return _error("Please attach your CV (.docx or .pdf)."), 400
    filename = upload.filename
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        return _error("Your CV must be a .docx or .pdf file."), 400

    cv_bytes = upload.read()
    if not cv_bytes:
        return _error("The uploaded CV was empty. Please re-upload."), 400

    # PII: never log form values or CV content — lengths and counts only.
    log.info(
        "submission received: cv=%s cv_len=%d non_empty_fields=%d test_mode=%s",
        filename, len(cv_bytes),
        sum(1 for v in form_data.values() if v),
        config.TEST_MODE,
    )

    try:
        orchestrator.handle_submission(form_data, filename, cv_bytes)
    except Exception:
        log.exception("submission pipeline failed")
        # DECISION (rescope #4): on failure we currently show the candidate a
        # retry page only. Adding a Chris Teams/email alert is Joel's call —
        # wire it here if/when he confirms.
        return _error(
            "Something went wrong on our end. Please refresh and try again."
        ), 500

    return render_template_string(SUCCESS_HTML)


@app.errorhandler(413)
def upload_too_large(_e):
    return _error("Your CV exceeds the 10 MB limit. Please upload a smaller file."), 413


def _error(message: str) -> str:
    return render_template_string(ERROR_HTML, message=message)
