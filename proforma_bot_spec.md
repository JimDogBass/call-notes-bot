# Build Spec — PwC Proforma Bot

A self-contained automation that turns a forwarded candidate email into a branded
PwC CV-submittal proforma (.docx) and delivers it to a consultant via Teams.

> This spec is written to be implemented directly. Items marked **`CONFIG`** are
> values/imports you must supply from the existing Meraki codebase or tenant.

---

## 1. Goal

Chris Paine forwards a candidate's email (body of details + CV attached) into the
`meraki1` inbox. The bot:

1. Parses the **email body** → header fields of the proforma.
2. Parses the **attached CV** (docx or pdf) → the candidate-profile body of the proforma.
3. Fills a **fixed PwC-branded Word template** with both.
4. Hands the finished `.docx` to **Christina** (existing delivery bot) to DM back to Chris.

The client is always PwC, so the template/logo is constant.

---

## 2. Environment & conventions

- **Language/host:** Python, deployed on Railway (match existing Meraki automation pattern).
- **Models:** Azure OpenAI for extraction. Use the `gpt-4o-mini` deployment (same as the
  call pipeline) — extraction is light and format-tolerance is the goal, not reasoning depth.
- **M365:** Microsoft Graph via the existing custom Entra ID app. Reuse the auth/token code
  already in the stack — do **not** stand up new auth.
- **Delivery:** Reuse **Christina**. She already delivers a **file to an individual** over
  Teams — point her at Chris and hand her the `.docx`. Do not rebuild Teams delivery.
- **Do not log candidate PII** (passport/right-to-work, salary, phone) beyond what's needed
  for debugging; keep all data in-tenant.

### `CONFIG` to supply
| Key | What |
|-----|------|
| `MERAKI1_MAILBOX` | the `meraki1` mailbox address |
| `CHRIS_PAINE_ADDRESS` | Chris's verified internal email (sender match + delivery target) |
| `AOAI_*` | Azure OpenAI endpoint, key, `gpt-4o-mini` deployment name |
| `christina.<send_fn>` | Christina's import path + function signature for "send file to person" |
| `templates/pwc_proforma_template.docx` | the branded template (see §6) |
| Fernando module path | CV text-extraction / prompt code to borrow from |

---

## 3. Flow

```
Candidate emails Chris  →  Chris forwards into meraki1
   → trigger fires ONLY if sender == Chris Paine AND a CV attachment is present
       ├─ forwarded body → gpt-4o-mini → header JSON
       └─ CV attachment  → text extract → gpt-4o-mini → cv JSON
   → docxtpl fills templates/pwc_proforma_template.docx
   → hand .docx to Christina → Teams DM to Chris
```

---

## 4. Trigger

- Source: `meraki1` inbox. Either a Graph change-subscription webhook or a short poll —
  match whatever the stack already uses for mailbox reads.
- **Fire only when both are true:**
  - sender matches `CHRIS_PAINE_ADDRESS` — match the **verified mailbox address**, never the
    display name (spoofable, and forwards mangle it).
  - the message has a usable CV attachment (see §5).
- The email is a **forward**: expect a forwarding preamble on top and quoted
  `From/Sent/To` headers in the middle. The extractor must ignore both (see §7).

---

## 5. Attachment selection

Forwards drag along inline signature images as "attachments." Pick the real CV:

1. Keep only `.docx` / `.pdf` (and `.doc` → convert).
2. Drop anything tiny / flagged `isInline` (signature logos).
3. If multiple survive: prefer a filename containing `cv`; else the largest.
4. Extract text: docx via the CV-text code borrowed from Fernando; pdf via `pdfplumber`
   (text layer) with an OCR fallback for scanned PDFs.

---

## 6. Template

Convert the existing SME submittal doc into a **docxtpl** template
(`templates/pwc_proforma_template.docx`), preserving the PwC logo, fonts and tabbed layout
exactly. Use placeholders for the header and a `{% for %}` loop for the variable-length
sections (a candidate may have 1 or 10 roles).

```jinja
Name: {{ header.name }}
Grade: {{ header.grade }}
Rate (Inc. Charge): {{ header.rate_inc_charge }}   (candidate asked: {{ header.desired_day_rate }})
LTD/PAYE/Umbrella: {{ header.ltd_paye_umbrella }}
Base Location: {{ header.base_location }}
Available from: {{ header.available_from }}
Holidays / Appointments booked: {{ header.holidays_appointments }}
{{ header.office_remote_line }}

Additional Comments:
{% for c in header.additional_comments %}- {{ c }}
{% endfor %}

CANDIDATE PROFILE
{% for p in cv.candidate_profile %}- {{ p }}
{% endfor %}

EDUCATION
{% for e in cv.education %}{{ e.year }}  {{ e.qualification }} — {{ e.institution }}
{% endfor %}

WORK EXPERIENCE
{% for role in cv.work_experience %}{{ role.dates }}  {{ role.employer }}
Position: {{ role.position }}
{% for b in role.bullets %}- {{ b }}
{% endfor %}
{% endfor %}

OTHER INFORMATION — Key Skills & Tools
{% for s in cv.key_skills_tools %}- {{ s.label }}: {{ s.description }}
{% endfor %}

Achievements
{% for a in cv.achievements %}- {{ a }}
{% endfor %}
```

---

## 7. Structured object (the contract between every stage)

```json
{
  "header": {
    "name": "",
    "grade": "",
    "rate_inc_charge": "[TBC]",
    "desired_day_rate": "",
    "ltd_paye_umbrella": "[TBC]",
    "base_location": "",
    "available_from": "",
    "holidays_appointments": "",
    "office_remote_line": "",
    "additional_comments": [],
    "_intel": {
      "current_salary": "",
      "right_to_work": "",
      "previous_pwc_experience": "",
      "other_interview_activity": "",
      "availability_to_interview": ""
    }
  },
  "cv": {
    "candidate_profile": [],
    "education": [ { "year": "", "qualification": "", "institution": "" } ],
    "work_experience": [ { "dates": "", "employer": "", "position": "", "bullets": [] } ],
    "key_skills_tools": [ { "label": "", "description": "" } ],
    "achievements": []
  }
}
```

### Manual fields — non-negotiable
`rate_inc_charge`, `ltd_paye_umbrella`, and `office_remote_line` are **never inferred**.
`rate_inc_charge` stays `[TBC]`; the candidate's stated `desired_day_rate` is rendered
beside it so Chris completes the real charge rate in one glance. The candidate's day rate
and the charge rate are structurally different numbers — the model must not derive one from
the other.

---

## 8. Prompts

### Email body → `header`

```
You are extracting a contractor's submission details from a FORWARDED email.
The text contains a forwarding preamble and quoted headers (From/Sent/To) — IGNORE those.
Extract ONLY the candidate's own stated answers.

Return ONLY valid JSON for the "header" object (omit rate_inc_charge and ltd_paye_umbrella —
those are set downstream).
Rules:
- Capture the candidate's requested rate into desired_day_rate. Never infer a charge rate.
- additional_comments = the candidate's "reasons suited" points, verbatim, as an array.
- Put right-to-work, current salary, previous PwC experience, other interview activity and
  interview availability into _intel.
- If a field is absent use "". Do not invent values.
- No prose, no markdown fences — JSON only.
```

### CV text → `cv`

```
Extract this CV into JSON for the "cv" object.
- Preserve employers, positions and date ranges exactly as written.
- key_skills_tools: split each "Label: description" line into {label, description}.
- Do not summarise, embellish, or add anything not present in the CV.
- No prose, no markdown fences — JSON only.
```

Parse defensively: strip any stray fences before `json.loads`; on a parse failure, retry once.

---

## 9. Suggested module layout

```
proforma_bot/
  main.py            # trigger handling, sender+attachment filter, orchestration
  graph_client.py    # reuse existing Graph auth; read message + fetch attachment
  email_extract.py   # forwarded body -> header JSON
  cv_extract.py      # attachment -> text (Fernando-borrowed) -> cv JSON
  assemble.py        # docxtpl render -> .docx in /tmp
  deliver.py         # call Christina's send-file-to-person
  templates/
    pwc_proforma_template.docx
  config.py          # env-driven CONFIG values
```

### Dependencies
`docxtpl`, `python-docx`, `pdfplumber` (+ OCR fallback if you want scanned-PDF support),
the existing Graph/MSAL code, the Azure OpenAI SDK, plus stdlib `email` / an HTML-to-text
step for the message body.

---

## 10. Build sequence

1. Build `templates/pwc_proforma_template.docx` from the SME doc (placeholders + loops).
2. `email_extract.py` — test against **real forwards**, not clean originals.
3. `cv_extract.py` — borrow Fernando's text extraction; output the `cv` schema.
4. `assemble.py` — render and validate the `.docx`.
5. `deliver.py` — wire to Christina.
6. `main.py` — sender+attachment filter and orchestration last (plumbing is the easy part).

---

## 11. Acceptance criteria

- [ ] Fires only on email from Chris Paine **with** a CV attachment; ignores everything else.
- [ ] Correctly extracts fields from a **forwarded** email (preamble + quoted headers present.
- [ ] Handles both **docx and pdf** CVs; ignores inline signature images.
- [ ] `rate_inc_charge` is always `[TBC]`; `desired_day_rate` shown beside it; never auto-derived.
- [ ] Variable-length work experience renders correctly (test a 1-role and a 9-role CV).
- [ ] Output is the exact PwC branding/layout of the template (logo, fonts, tabs intact).
- [ ] Finished `.docx` is DM'd to Chris via Christina.
- [ ] No candidate PII written to persistent logs.
