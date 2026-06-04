"""CV attachment -> text -> cv JSON via gpt-4o-mini.

Text extraction ported from meraki-teams-bot/app.py (Fernando) with two fixes:
  1. docx: nested-table content was silently dropped — cell.text doesn't include
     <w:tbl> inside cells. Now recurses into cell.tables properly.
  2. Same PDF fallback chain (pdfplumber -> PyMuPDF -> OCR) with the ligature/
     corruption heuristic. Heavier deps (pymupdf/pdf2image/pytesseract) are
     optional — graceful skip if unavailable so Railway boots without them.

The proforma extraction prompt differs from Fernando's: PwC submittal forms
render one block per role, so multi-role-same-company is SPLIT into separate
entries (Fernando merges). Role-specific parenthesised dates still win over
employer total span (Fernando's rule, copied verbatim because it's correct).
"""
from __future__ import annotations

import io
import logging
from typing import Any

import pdfplumber
from docx import Document
from docx.table import _Cell

from . import aoai

log = logging.getLogger("proforma_bot.cv")

# Attachment selection moved into gmail_client._pick_cv_attachment — Gmail
# MIME-walks need a different shape than Graph's attachment listing.


# ---------------------------------------------------------------------------
# PDF extraction — ported from meraki-teams-bot/app.py:175-314
# ---------------------------------------------------------------------------


def _detect_text_corruption(text: str) -> bool:
    """Ligature-decoding heuristic from Fernando. PDFs from Google Docs (custom
    glyph maps for 'ti'/'fi'/'fl'/'ff'/'ft') produce 'MarkeUng', 'creaGve',
    'plaBorms' etc. when pdfplumber can't resolve them."""
    if not text or len(text) < 100:
        return False
    words = text.split()
    if len(words) < 20:
        return False
    suspicious = checked = 0
    for word in words:
        if len(word) < 4 or word.isupper() or word.isdigit():
            continue
        if "@" in word or "/" in word or "." in word:
            continue
        checked += 1
        for j in range(2, len(word)):
            if word[j].isupper() and word[j - 1].islower():
                suspicious += 1
                break
    return checked > 0 and (suspicious / checked) > 0.03


def _extract_pdf_pymupdf(file_bytes: bytes) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        log.warning("pymupdf not installed; skipping fallback")
        return ""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc if page.get_text()]
        doc.close()
        return "\n".join(parts).strip()
    except Exception as e:
        log.error("pymupdf extraction failed: %s", e)
        return ""


def _extract_pdf_ocr(file_bytes: bytes) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        log.warning("pdf2image/pytesseract not installed; skipping OCR fallback")
        return ""
    try:
        images = convert_from_bytes(file_bytes)
        parts = []
        for image in images:
            page_text = pytesseract.image_to_string(image)
            if page_text.strip():
                parts.append(page_text.strip())
        return "\n".join(parts)
    except Exception as e:
        log.error("OCR fallback failed: %s", e)
        return ""


def _extract_pdf(file_bytes: bytes) -> str:
    """3-tier fallback: pdfplumber -> PyMuPDF -> OCR. Includes table rows."""
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
            for table in page.extract_tables():
                for row in table:
                    cells = [c.strip() for c in row if c]
                    if cells:
                        text_parts.append(" | ".join(cells))
    text = "\n".join(text_parts).strip()

    if text and _detect_text_corruption(text):
        log.warning("PDF text corruption detected (ligature decoding)")
        pm = _extract_pdf_pymupdf(file_bytes)
        if pm and not _detect_text_corruption(pm):
            return pm
        ocr = _extract_pdf_ocr(file_bytes)
        if ocr and not _detect_text_corruption(ocr):
            return ocr
        return pm or ocr or text

    if not text:
        return _extract_pdf_pymupdf(file_bytes) or _extract_pdf_ocr(file_bytes) or ""
    return text


# ---------------------------------------------------------------------------
# DOCX extraction — fixes Fernando's silent nested-table drop
# ---------------------------------------------------------------------------


def _walk_cell(cell: _Cell, out: list[str]) -> None:
    """Recurse into a cell so nested tables aren't lost. python-docx's
    cell.text only concatenates <w:p> children, not nested <w:tbl>."""
    for para in cell.paragraphs:
        if para.text.strip():
            out.append(para.text)
    for nested in cell.tables:
        for row in nested.rows:
            row_parts: list[str] = []
            for inner in row.cells:
                bucket: list[str] = []
                _walk_cell(inner, bucket)
                joined = " ".join(bucket).strip()
                if joined:
                    row_parts.append(joined)
            if row_parts:
                out.append(" | ".join(row_parts))


def _extract_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    out: list[str] = [p.text for p in doc.paragraphs]

    for table in doc.tables:
        for row in table.rows:
            row_parts: list[str] = []
            for cell in row.cells:
                bucket: list[str] = []
                _walk_cell(cell, bucket)
                joined = " ".join(bucket).strip()
                if joined:
                    row_parts.append(joined)
            if row_parts:
                out.append(" | ".join(row_parts))

    standard = "\n".join(out).strip()

    # Deep-XML safety net: walk every w:t. Kept from Fernando — if recursion
    # missed something obscure (textboxes, SDT content controls), this catches it.
    if len(standard) < 500:
        try:
            body = doc._body._body
            texts = [c.text for c in body.iter() if c.tag.endswith("}t") and c.text]
            deep = "".join(texts)
            if len(deep) > len(standard):
                return deep
        except Exception:
            pass
    return standard


def _extract_doc(file_bytes: bytes) -> str:
    """.doc via antiword. Heavy dep; ask Joel to convert to .docx upstream if
    this is hit often."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        try:
            r = subprocess.run(
                ["antiword", tmp.name], capture_output=True, text=True, timeout=30
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except FileNotFoundError:
            log.error("antiword not installed; cannot read .doc")
            return ""


def extract_text(filename: str, blob: bytes) -> str:
    name = filename.lower()
    if name.endswith(".docx"):
        return _extract_docx(blob)
    if name.endswith(".pdf"):
        return _extract_pdf(blob)
    if name.endswith(".doc"):
        return _extract_doc(blob)
    raise ValueError(f"unsupported attachment: {filename}")


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

# Schema-aligned with spec §7 work_experience: one flat entry per role.
# Multi-role-same-company is SPLIT (Fernando merges; the PwC template renders
# one block per role so splitting is the right call here).
SYSTEM_PROMPT = """Extract this CV into JSON for the "cv" object. Return ONLY valid JSON — no prose, no markdown fences.

REQUIRED SHAPE:
{
  "candidate_profile": ["bullet 1", "bullet 2", ...],
  "education": [{"year": "", "qualification": "", "institution": ""}],
  "work_experience": [{"dates": "", "employer": "", "position": "", "bullets": ["..."]}],
  "key_skills_tools": [{"label": "", "description": ""}],
  "achievements": ["..."]
}

CRITICAL — MULTI-ROLE SAME COMPANY:
PwC submittal forms render one block per role. When a candidate held multiple titles at the same employer, emit ONE work_experience entry PER ROLE — repeat the employer name on each. Do NOT merge titles into a single entry.

Example input:
    M&G Plc (Treasury & Investment Office)              April 2016 – July 2022
      Senior Compliance Manager, Advisory                (July 2021 – July 2022)
      ...bullets for senior role...
      Manager, Investment Mandate Monitoring             (April 2016 – July 2021)
      ...bullets for manager role...

Correct output — TWO entries:
  {"dates": "Jul 21 - Jul 22", "employer": "M&G Plc (Treasury & Investment Office)",
   "position": "Senior Compliance Manager, Advisory", "bullets": [...]}
  {"dates": "Apr 16 - Jul 21", "employer": "M&G Plc (Treasury & Investment Office)",
   "position": "Manager, Investment Mandate Monitoring", "bullets": [...]}

CRITICAL — ROLE-SPECIFIC DATES VS EMPLOYER TOTAL SPAN:
If a role has its OWN date range (usually in parentheses next to the title), that range ALWAYS wins over the employer's total span on the company line. NEVER reuse the employer total span as the dates for any single role.

CRITICAL — DIFFERENT EMPLOYERS STAY SEPARATE:
UBS, Credit Suisse, Goldman Sachs etc. are DIFFERENT employers even when the candidate moved between them. Never merge across employers.

CRITICAL — BULLET INTEGRITY:
A bullet like "Strategic Leadership: define and implement..." is ONE bullet. Do NOT split the "Label: text" pattern into two bullets.

OTHER RULES:
- Preserve employers, positions, and date ranges EXACTLY as written. Short-date format like "Jan 23" is preferred but only if the source uses it — otherwise keep what's written.
- key_skills_tools: split each "Label: description" line into {"label": ..., "description": ...}. If a skills section is just a comma list with no labels, use the skill name as label and leave description "".
- Do NOT summarise, embellish, paraphrase, or add anything not present in the CV.
- candidate_profile = the candidate's personal statement / profile / summary section, split into bullet points. If no profile section, use [].
- achievements = a standalone "Achievements" or "Key Achievements" section. NOT bullets from inside roles. If absent, use [].
- If a field is absent use "" or []. Never invent values."""


def extract_cv(cv_text: str) -> dict[str, Any]:
    return aoai.extract_json(SYSTEM_PROMPT, cv_text, max_tokens=8000)
