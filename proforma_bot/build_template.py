"""Generate a starter PwC proforma docxtpl template.

This produces a STRUCTURALLY correct template — all placeholders and {% for %}
loops in the right places, sections in the right order, labels matching the spec.

What it does NOT include: the PwC logo, brand colours, the exact SME-submittal
font stack, or the tabbed layout. Open the resulting .docx in Word and either:
  (a) overlay it onto the existing SME submittal doc by copy-pasting the
      placeholder paragraphs into the right sections (keeping SME branding), or
  (b) use this as-is for testing and add PwC styling later.

Run:
    python -m proforma_bot.build_template
"""
from __future__ import annotations

import os

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.shared import Pt, RGBColor

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "templates", "pwc_proforma_template.docx"
)

PWC_ORANGE = RGBColor(0xE6, 0x6C, 0x37)  # close to PwC's signature orange


def _label_value(doc, label: str, placeholder: str):
    """Bold label, then docxtpl placeholder on the same paragraph."""
    p = doc.add_paragraph()
    run = p.add_run(f"{label}: ")
    run.bold = True
    p.add_run(placeholder)


def _section_heading(doc, text: str):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = PWC_ORANGE


def build() -> str:
    doc = Document()

    # ----- Title -----
    title = doc.add_paragraph()
    title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    run = title.add_run("PwC Contractor Submittal")
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = PWC_ORANGE

    note = doc.add_paragraph()
    note.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    note_run = note.add_run("[Replace this header with the PwC-branded SME logo block]")
    note_run.italic = True
    note_run.font.size = Pt(9)
    note_run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    doc.add_paragraph()

    # ----- Header fields (spec §6) -----
    _label_value(doc, "Name", "{{ header.name }}")
    _label_value(doc, "Grade", "{{ header.grade }}")

    # Rate line — composite per spec: charge rate [TBC] + candidate's ask alongside
    p = doc.add_paragraph()
    r = p.add_run("Rate (Inc. Charge): ")
    r.bold = True
    p.add_run("{{ header.rate_inc_charge }}    (candidate asked: {{ header.desired_day_rate }})")

    _label_value(doc, "LTD/PAYE/Umbrella", "{{ header.ltd_paye_umbrella }}")
    _label_value(doc, "Base Location", "{{ header.base_location }}")
    _label_value(doc, "Available from", "{{ header.available_from }}")
    _label_value(doc, "Holidays / Appointments booked", "{{ header.holidays_appointments }}")

    # Office/remote line — free-form, no label
    doc.add_paragraph("{{ header.office_remote_line }}")

    doc.add_paragraph()

    # ----- Additional Comments -----
    p = doc.add_paragraph()
    r = p.add_run("Additional Comments:")
    r.bold = True
    doc.add_paragraph("{% for c in header.additional_comments %}")
    doc.add_paragraph("- {{ c }}")
    doc.add_paragraph("{% endfor %}")

    doc.add_paragraph()

    # ----- Candidate Profile -----
    _section_heading(doc, "CANDIDATE PROFILE")
    doc.add_paragraph("{% for p in cv.candidate_profile %}")
    doc.add_paragraph("- {{ p }}")
    doc.add_paragraph("{% endfor %}")

    doc.add_paragraph()

    # ----- Education -----
    _section_heading(doc, "EDUCATION")
    doc.add_paragraph("{% for e in cv.education %}")
    doc.add_paragraph("{{ e.year }}    {{ e.qualification }} — {{ e.institution }}")
    doc.add_paragraph("{% endfor %}")

    doc.add_paragraph()

    # ----- Work Experience (nested loop) -----
    _section_heading(doc, "WORK EXPERIENCE")
    doc.add_paragraph("{% for role in cv.work_experience %}")

    # Dates + employer on one bold line
    p = doc.add_paragraph()
    r = p.add_run("{{ role.dates }}    {{ role.employer }}")
    r.bold = True

    # Position
    p = doc.add_paragraph()
    r = p.add_run("Position: ")
    r.bold = True
    p.add_run("{{ role.position }}")

    # Bullets (inner loop)
    doc.add_paragraph("{% for b in role.bullets %}")
    doc.add_paragraph("- {{ b }}")
    doc.add_paragraph("{% endfor %}")

    doc.add_paragraph()
    doc.add_paragraph("{% endfor %}")

    # ----- Key Skills & Tools -----
    _section_heading(doc, "OTHER INFORMATION — Key Skills & Tools")
    doc.add_paragraph("{% for s in cv.key_skills_tools %}")
    doc.add_paragraph("- {{ s.label }}: {{ s.description }}")
    doc.add_paragraph("{% endfor %}")

    doc.add_paragraph()

    # ----- Achievements -----
    _section_heading(doc, "Achievements")
    doc.add_paragraph("{% for a in cv.achievements %}")
    doc.add_paragraph("- {{ a }}")
    doc.add_paragraph("{% endfor %}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    doc.save(OUTPUT_PATH)
    return OUTPUT_PATH


if __name__ == "__main__":
    path = build()
    print(f"Template written to {path}")
