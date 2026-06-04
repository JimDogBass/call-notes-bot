"""Forwarded email body -> header JSON via Azure OpenAI gpt-4o-mini."""
import re
from typing import Any

from . import aoai

# The candidate's email looks like a Q&A reply. Labels vary between candidates
# but follow consistent patterns. Mapping table below was reverse-engineered
# from a real Chris Paine forward (2026-06-04). Update as new label variants
# appear in production.
SYSTEM_PROMPT = """You extract a contractor's submission details from a FORWARDED email. The candidate has replied to a recruiter with answers to questions; the recruiter has forwarded the reply into this mailbox.

IGNORE:
- The forwarding preamble at the top of the message
- Quoted "From: / Sent: / To: / Subject:" headers
- Any text outside the candidate's own reply

The candidate's reply uses formats like:
  * Label - Value
  * Label: Value
  - Label - Value
  Label: Value

Map labels FLEXIBLY (the wording varies; recognise paraphrases and partial matches):

CANDIDATE'S LABEL                              ->  JSON FIELD
"Notice Period / contract end date"           ->  available_from
"Notice Period" / "Notice period"             ->  available_from
"Available from"                              ->  available_from
"Location" / "Base Location" / "City"         ->  base_location
"Any holidays upcoming" / "Holidays"          ->  holidays_appointments
"Holidays / Appointments booked"              ->  holidays_appointments
"Desired Day Rate" / "Rate" / "Day Rate"      ->  desired_day_rate
"Current Salary" / "Salary"                   ->  _intel.current_salary
"Right to work in UK" / "Right to work"       ->  _intel.right_to_work
"Previous PWC experience"                     ->  _intel.previous_pwc_experience
"Previous PwC experience"                     ->  _intel.previous_pwc_experience
"Other interview activity"                    ->  _intel.other_interview_activity
"Availability to interview"                   ->  availability_to_interview

The candidate often includes a "Reasons for why I am suited for the role" (or "Reasons suited" / "Reasons") section with numbered or bulleted points. Capture EACH point as a VERBATIM string in the additional_comments array, preserving punctuation and order. Do NOT shorten or summarise.

DO NOT extract:
- name (comes from the CV, not the email)
- grade (set downstream by the recruiter)
- rate_inc_charge (set downstream)
- ltd_paye_umbrella (set downstream)
- office_remote_line (set downstream)

If a field is absent from the email use "" (or [] for additional_comments). NEVER invent values.

Return ONLY valid JSON. No prose. No markdown fences.

Shape:
{
  "desired_day_rate": "",
  "base_location": "",
  "available_from": "",
  "holidays_appointments": "",
  "availability_to_interview": "",
  "additional_comments": [],
  "_intel": {
    "current_salary": "",
    "right_to_work": "",
    "previous_pwc_experience": "",
    "other_interview_activity": ""
  }
}"""


def html_to_text(html_or_text: str) -> str:
    """Cheap HTML strip; swap for bs4 / html2text if forwards arrive HTML-only."""
    return re.sub(r"<[^>]+>", "", html_or_text)


def extract_header(body_text: str) -> dict[str, Any]:
    return aoai.extract_json(SYSTEM_PROMPT, body_text, max_tokens=2000)


def merge_manual_defaults(header: dict[str, Any]) -> dict[str, Any]:
    """Fields the recruiter (Chris) fills in manually after the proforma renders.
    The candidate doesn't supply these — default to [TBC] so the recipient knows
    to complete them rather than seeing a blank line that looks like an oversight."""
    header.setdefault("name", "")  # filled by orchestrator from cv.name
    header.setdefault("grade", "[TBC]")
    header.setdefault("rate_inc_charge", "[TBC]")
    header.setdefault("ltd_paye_umbrella", "[TBC]")
    header.setdefault("office_remote_line", "[TBC]")
    header.setdefault("availability_to_interview", "[TBC]")
    return header
