"""Flask web entrypoint. Candidates open `GET /`, fill the form, attach a CV,
and submit; we run the proforma pipeline synchronously and email Chris.

Replaces the previous Gmail/IMAP polling worker. Same package internals
(cv_extract, assemble, deliver) — only the trigger surface changed."""
from __future__ import annotations

import hashlib
import logging
import threading
import time

from flask import Flask, redirect, render_template_string, request, url_for

from proforma_bot import config, orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("proforma_bot.app")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB — outlook_sender routes large
# attachments through Graph's draft + upload-session path, so CVs above the
# ~3 MB inline ceiling deliver instead of falling back to the failure alert.
ALLOWED_EXTENSIONS = (".docx", ".pdf")


# Brand colour sampled from Meraki_Logo_Blue.ai; kept in CSS only.
FORM_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Candidate Submission — Meraki Talent</title>
<style>
  :root{--ink:#104070;--muted:#6b6b7b;--line:#d8dde6;--accent:#104070;--accent-hover:#0b2e52;--bg:#f4f6fb}
  *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;background:var(--bg);line-height:1.5}
  .wrap{max-width:640px;margin:0 auto;padding:32px 20px 64px}
  .logo{display:block;max-width:220px;height:auto;margin:0 0 24px}
  h1{font-size:22px;margin:18px 0 4px;color:var(--ink)}p.sub{color:var(--muted);margin:0 0 24px}
  .card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(16,64,112,0.04)}
  label{display:block;font-weight:600;font-size:14px;margin:16px 0 6px;color:var(--ink)}
  .hint{font-weight:400;color:var(--muted);font-size:13px}
  input[type=text]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:15px;font-family:inherit;background:#fff}
  input[type=text]:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(16,64,112,0.12)}
  textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:15px;font-family:inherit;background:#fff;resize:vertical;min-height:110px;line-height:1.5}
  textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(16,64,112,0.12)}
  .reasons-group{margin-top:6px}
  .reasons-group textarea{margin-bottom:10px}
  button{margin-top:28px;width:100%;padding:14px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-size:16px;font-weight:600;cursor:pointer}
  button:hover{background:var(--accent-hover)}
  .note{font-size:12px;color:var(--muted);margin-top:14px;text-align:center}
</style></head><body><div class="wrap">
  <img class="logo" src="/static/meraki_logo.png" alt="Meraki Talent" />
  <h1>Candidate Submission</h1><p class="sub">A few quick details and your CV. We'll handle the rest.</p>
  <form class="card" action="/submit" method="post" enctype="multipart/form-data">
    <label>Role you're applying for</label><input type="text" name="role" required />
    <label>What's your notice period or contract end date?</label><input type="text" name="notice_period" required />
    <label>What's your current salary?</label><input type="text" name="current_salary" required />
    <label>What's your desired day rate?</label><input type="text" name="desired_day_rate" required />
    <label>Do you have the right to work in the UK? <span class="hint">(UK passport, visa, etc.)</span></label><input type="text" name="right_to_work" required />
    <label>Where are you based?</label><input type="text" name="location" required />
    <label>Have you worked with PwC before?</label><input type="text" name="previous_pwc" required />
    <label>Are you involved in any other interview processes? <span class="hint">(outline anything that could engage you ahead of this contract)</span></label><input type="text" name="other_interviews" required />
    <label>Do you have any upcoming holidays?</label><input type="text" name="holidays" required />
    <label>When are you available to interview?</label><input type="text" name="interview_availability" required />
    <label>Office, hybrid, or fully remote? <span class="hint">(e.g. happy with 3 days a week in office, or fully remote)</span></label><input type="text" name="office_remote" required />
    <label>Why are you a good fit for this role?</label>
    <div class="reasons-group">
      <textarea name="reason_1" rows="4" placeholder="Reason 1" required></textarea>
      <textarea name="reason_2" rows="4" placeholder="Reason 2" required></textarea>
      <textarea name="reason_3" rows="4" placeholder="Reason 3" required></textarea>
    </div>
    <label>Upload your CV <span class="hint">(.docx or .pdf)</span></label>
    <input type="file" name="cv" accept=".docx,.pdf" required />
    <button type="submit" id="submitBtn">Submit</button>
    <p class="note">Your CV is processed to generate a submission document and forwarded to the hiring team.</p>
  </form>
</div>
<script>
  (function(){
    var form = document.querySelector('form');
    var btn = document.getElementById('submitBtn');
    var submitted = false;
    form.addEventListener('submit', function(e){
      if (submitted) { e.preventDefault(); return; }
      submitted = true;
      btn.disabled = true;
      btn.textContent = 'Submitting… this can take up to 30 seconds';
    });
  })();
</script>
</body></html>
"""

SUCCESS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Submission received — Meraki Talent</title>
<style>
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;background:#f4f6fb;line-height:1.5}
  .wrap{max-width:560px;margin:0 auto;padding:64px 20px;text-align:center}
  .logo{max-width:220px;height:auto;margin:0 auto 32px;display:block}
  .card{background:#fff;border:1px solid #d8dde6;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(16,64,112,0.04)}
  h1{font-size:22px;margin:0 0 12px;color:#104070}p{color:#6b6b7b;margin:0}
</style></head><body><div class="wrap">
  <img class="logo" src="/static/meraki_logo.png" alt="Meraki Talent" />
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
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;background:#f4f6fb;line-height:1.5}
  .wrap{max-width:560px;margin:0 auto;padding:64px 20px;text-align:center}
  .logo{max-width:220px;height:auto;margin:0 auto 32px;display:block}
  .card{background:#fff;border:1px solid #d8dde6;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(16,64,112,0.04)}
  h1{font-size:22px;margin:0 0 12px;color:#104070}p{color:#6b6b7b;margin:0 0 18px}
  a{display:inline-block;padding:10px 18px;border-radius:8px;background:#104070;color:#fff;text-decoration:none;font-weight:600}
  a:hover{background:#0b2e52}
</style></head><body><div class="wrap">
  <img class="logo" src="/static/meraki_logo.png" alt="Meraki Talent" />
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
    "holidays", "interview_availability", "office_remote",
    "reason_1", "reason_2", "reason_3",
)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# Dedup: the pipeline takes ~20–30s, during which an impatient candidate may
# click Submit repeatedly. Browser-side button-lock + PRG cover the common
# cases; this server-side check is the last line of defence (e.g. a fresh tab,
# or a refresh of the pre-PRG history entry). Window is 10 min — long enough
# to absorb any sensible retry, short enough that a genuine resubmission
# (corrected typo) is still possible afterwards. State lives in process memory;
# Procfile pins gunicorn to 1 worker so it's effectively a global lock.
_DEDUP_WINDOW_SECONDS = 600
_recent_submissions: dict[str, float] = {}
_dedup_lock = threading.Lock()


def _submission_fingerprint(cv_bytes: bytes, role: str) -> str:
    h = hashlib.sha256()
    h.update(cv_bytes)
    h.update(b"\x00")
    h.update(role.strip().lower().encode("utf-8"))
    return h.hexdigest()


def _register_submission(fingerprint: str) -> bool:
    """Returns True if this fingerprint was already seen within the dedup
    window (i.e. duplicate). Otherwise records it now and returns False."""
    now = time.time()
    with _dedup_lock:
        for k in [k for k, t in _recent_submissions.items()
                  if now - t > _DEDUP_WINDOW_SECONDS]:
            del _recent_submissions[k]
        if fingerprint in _recent_submissions:
            return True
        _recent_submissions[fingerprint] = now
        return False


def _release_submission(fingerprint: str) -> None:
    """Drop a fingerprint so the candidate's retry-after-failure can succeed."""
    with _dedup_lock:
        _recent_submissions.pop(fingerprint, None)


@app.get("/")
def index():
    return render_template_string(FORM_HTML)


@app.get("/healthz")
def healthz():
    return ("ok", 200)


@app.get("/success")
def success():
    return render_template_string(SUCCESS_HTML)


@app.post("/submit")
def submit():
    form_data = {k: (request.form.get(k) or "").strip() for k in FORM_FIELDS}

    # Server-side required check (HTML `required` is the primary UX; this
    # catches anyone bypassing the browser).
    missing = [k for k, v in form_data.items() if not v]
    if missing:
        return _error(
            "Please fill in every field before submitting."
        ), 400

    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return _error("Please attach your CV (.docx or .pdf)."), 400
    filename = upload.filename
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        return _error("Your CV must be a .docx or .pdf file."), 400

    cv_bytes = upload.read()
    if not cv_bytes:
        return _error("The uploaded CV was empty. Please re-upload."), 400

    fingerprint = _submission_fingerprint(cv_bytes, form_data["role"])
    if _register_submission(fingerprint):
        log.info(
            "duplicate submission ignored (same CV+role within %ds)",
            _DEDUP_WINDOW_SECONDS,
        )
        return redirect(url_for("success"), code=303)

    # PII: never log form values or CV content — lengths and counts only.
    log.info(
        "submission received: cv=%s cv_len=%d test_mode=%s",
        filename, len(cv_bytes), config.TEST_MODE,
    )

    try:
        orchestrator.handle_submission(form_data, filename, cv_bytes)
    except Exception as exc:
        # Release so the candidate's retry isn't silently swallowed by dedup.
        # Edge case: if delivery actually happened-but-something-after-it-raised,
        # Chris could get one duplicate on retry — acceptable vs blocking retry.
        _release_submission(fingerprint)
        log.exception("submission pipeline failed")
        orchestrator.notify_failure(form_data, filename, len(cv_bytes), exc)
        return _error(
            "Something went wrong on our end. Please refresh and try again."
        ), 500

    return redirect(url_for("success"), code=303)


@app.errorhandler(413)
def upload_too_large(_e):
    return _error("Your CV exceeds the 25 MB limit. Please upload a smaller file."), 413


def _error(message: str) -> str:
    return render_template_string(ERROR_HTML, message=message)
