# Meraki Call Notes Automation - Technical Reference

## Project Overview

Automated extraction of structured candidate information from recruitment call transcripts, delivered to consultants via Microsoft Teams.

**Owner:** Joel @ Meraki Talent
**Status:** DEPLOYED AND WORKING on Railway
**Date:** January 2026
**Last Updated:** 23 Jan 2026 @ 12:00

---

## Quick Start

The system is deployed on Railway and runs automatically every 5 minutes.

**Railway Dashboard:** [https://railway.app](https://railway.app) (login as Joel)
**GitHub Repo:** [https://github.com/JimDogBass/call-notes-bot](https://github.com/JimDogBass/call-notes-bot)

### Local Development

```bash
# 1. Install dependencies
cd "C:\Projects\n8n Call Notes"
pip install -r requirements.txt

# 2. Set environment variables (or use .env file)
# See Environment Variables section below

# 3. Run the processor
python call_notes_processor.py
```

---

## What It Does

1. Polls Google Drive every 5 minutes for new PDF transcripts
2. Extracts text using pdfplumber (with PyPDF2 fallback)
3. Parses consultant name from filename
4. Looks up consultant info + desk-specific prompt from Google Sheets
5. Calls Azure OpenAI (GPT-4o-mini) to extract structured call notes
6. Sends Adaptive Card to consultant via Teams (1:1 chat from Joel)
7. Renames processed files with `[PROCESSED]` prefix
8. Logs skipped calls (short transcripts, unknown consultants) to Google Sheets

---

## Business Context

- **Company:** Meraki Talent - UK-based financial services recruitment agency (Edinburgh, Glasgow, London)
- **Staff:** 40 recruiters across multiple desks
- **Volume:** ~200 call transcripts/day from Fireflies
- **Problem:** Manual note-taking is inconsistent; consultants need structured candidate data delivered automatically
- **Solution:** Automated extraction pipeline with Teams delivery

---

## Architecture

```
Google Drive (PDF upload via Fireflies)
    |
    v
Poll for new PDFs (every 5 minutes)
    |
    v
Extract PDF text (pdfplumber + PyPDF2 fallback)
    |
    v
Word Count Gate (<300 = skip, log to Skipped_Calls)
    |
    v
Parse consultant name from filename
    |
    v
Lookup Consultant in Google Sheets --> Get Desk, TeamsUserId
    |
    v
Fetch Desk-Specific Prompt from Google Sheets
    |
    v
Azure OpenAI (GPT-4o-mini) --> Extract structured notes
    |
    v
Build Adaptive Card
    |
    v
Microsoft Graph API --> Create 1:1 chat --> Send message
    |
    v
Rename file to [PROCESSED] prefix
```

---

## Railway Deployment

### Environment Variables

Set these in Railway dashboard:

| Variable | Description | Notes |
|----------|-------------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Base64-encoded service account JSON | See encoding instructions below |
| `GOOGLE_DRIVE_FOLDER_ID` | `1SfFPHC1DRUzcR8FDcdQkzr5oJZhtNSzr` | Google Drive folder ID |
| `GOOGLE_SPREADSHEET_ID` | `1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g` | Google Sheets spreadsheet ID |
| `AZURE_OPENAI_ENDPOINT` | `https://meraki-call-notes-bot.openai.azure.com/` | Azure OpenAI endpoint |
| `AZURE_OPENAI_API_KEY` | (see CREDENTIALS.md) | Azure OpenAI API key |
| `MS_TENANT_ID` | `0591f50e-b7a3-41d0-a0b1-b26a2df48dfc` | Microsoft tenant ID |
| `MS_CLIENT_ID` | `7e1c4f4b-e80e-42ed-a1ac-fc1e0bb3af21` | Azure app registration ID |
| `MS_CLIENT_SECRET` | (see CREDENTIALS.md) | Azure app client secret |
| `MS_REFRESH_TOKEN` | (see CREDENTIALS.md) | Microsoft OAuth2 refresh token (1493 chars) |
| `JOEL_AAD_ID` | `5882d2ec-5fcc-48be-bea3-dbbd7020d6ea` | Joel's Azure AD user ID |
| `POLL_INTERVAL` | `300` | Seconds between polls (5 minutes) |

### Base64 Encoding for Google Service Account

The Google service account JSON must be base64-encoded for Railway:

```python
import base64
import json

# Read the JSON file
with open('meraki-n8n-automation-66a9d5aafc1e.json', 'r') as f:
    json_content = f.read()

# Encode to base64
encoded = base64.b64encode(json_content.encode()).decode()
print(encoded)  # Copy this value to Railway
```

### Procfile

```
worker: python call_notes_processor.py
```

### Deploying Updates

```bash
git add .
git commit -m "Your commit message"
git push origin main
```

Railway will automatically redeploy.

---

## Google Sheets Configuration

**Spreadsheet ID:** `1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g`

### 1. Consultants (sheet)

| Column | Notes |
|--------|-------|
| Name | Full name as appears in transcript filenames |
| Email | Company email |
| Desk | PE_VC, Compliance, Wealth_Trust, Product_Tech, Finance, Legal |
| TeamsUserId | Microsoft 365 user object ID |
| Active | TRUE or FALSE |

### 2. Prompts (sheet)

| Column | Notes |
|--------|-------|
| Desk | Must match Desk values above |
| PromptTemplate | Full extraction prompt |
| Description | Human-readable description |
| LastUpdated | Date of last modification |

### 3. Skipped_Calls (sheet)

| Column | Notes |
|--------|-------|
| Filename | Original transcript filename |
| Date | When processing attempted |
| WordCount | Transcript word count |
| Reason | Why skipped |
| ConsultantName | Extracted name if available |

### 4. Processing_Errors (sheet)

| Column | Notes |
|--------|-------|
| Filename | Original filename |
| Date | When error occurred |
| ErrorMessage | Full error details |
| NodeName | Which step failed |
| Resolved | TRUE or FALSE |

---

## Filename Parsing Logic

Fireflies generates filenames like:
```
Lisa Paton [+44 141 648 9417] - +44 7912 748851-transcript-2026-01-23T11-43-55.000Z.pdf
Scott Eccles [+44 141 846 0530] - +44 7940 704901-transcript-2026-01-23T11-40-38.000Z.pdf
```

**Extraction logic:**
1. Remove `[PROCESSED]` prefix if present
2. Split on ` [` or ` - ` to get first segment
3. Result: "Lisa Paton", "Scott Eccles"

---

## Word Count Gating

- **Threshold:** 300 words minimum
- **Purpose:** Filter voicemails, wrong numbers, very brief check-ins
- **Action when below threshold:** Log to "Skipped_Calls" sheet, rename with `[PROCESSED]` prefix

---

## Desk Types & Prompts

| Desk | Focus |
|------|-------|
| PE_VC | Private Equity, Venture Capital IR/Fundraising |
| Compliance | Regulatory, Risk |
| Wealth_Trust | Trust Administration, Private Client |
| Product_Tech | Product Management, Digital |
| Finance | Accounting, CFO roles |
| Legal | In-house counsel |

Prompts are managed in Google Sheets and can be updated anytime without redeploying.

---

## Error Handling

| Error Type | Action |
|------------|--------|
| PDF extraction fails | Try PyPDF2 fallback, then log to Processing_Errors |
| Consultant not found | Log to Skipped_Calls (reason: "Unknown consultant"), rename file |
| Consultant inactive | Log to Skipped_Calls (reason: "Inactive consultant"), rename file |
| Azure OpenAI fails | Log error, skip file |
| Teams delivery fails | Log error, do NOT rename (will retry next cycle) |

---

## Files

| File | Purpose |
|------|---------|
| `call_notes_processor.py` | Main processor script with polling loop |
| `auth_setup.py` | One-time OAuth2 setup for Microsoft Graph (local use) |
| `requirements.txt` | Python dependencies |
| `Procfile` | Railway deployment configuration |
| `.gitignore` | Excludes credentials and temp files |
| `README-claude-code-handoff.md` | This file |
| `CREDENTIALS.md` | Credential reference (not in git) |

---

## Refreshing Microsoft Token

The MS_REFRESH_TOKEN is long-lived but may need refreshing if:
- The Azure app client secret is rotated
- Joel's account password changes
- Permissions are revoked

To refresh:
1. Ensure `http://localhost:8765/callback` is a Redirect URI in Azure Portal
2. Set environment variables: `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`
3. Run `python auth_setup.py`
4. Sign in as Joel
5. Copy the token from `ms_refresh_token.txt` to Railway

---

## Progress Log

### 20 Jan 2026 - Session 1
- Created CSV templates for Google Sheets
- Drafted desk-specific extraction prompts
- Built initial n8n workflow structure

### 21 Jan 2026 - Session 2
- Migrated from SharePoint to Google Workspace
- Google Drive folder and Sheets created
- Service account configured
- Consultants sheet populated with 36 user IDs

### 22 Jan 2026 - Session 3
- Bot Framework API issues (encryption/permission problems)
- Switched to Graph API with delegated OAuth2
- n8n workflow working end-to-end

### 22 Jan 2026 - Session 4 (Evening)
- Adaptive Card rendering issues in n8n
- Decision to rebuild in Python for better debugging

### 23 Jan 2026 - Session 5 (DEPLOYMENT)

**Completed:**
- [x] Python script fully working with all integrations
- [x] Microsoft OAuth2 authentication working (auth_setup.py)
- [x] Deployed to Railway
- [x] Base64 encoding for Google service account JSON (Railway env var handling)
- [x] PyPDF2 fallback for PDF parsing (pdfplumber fails on some Fireflies PDFs)
- [x] Adaptive Card body fix (`<attachment id="ac1"></attachment>`)
- [x] Polling loop (5 minute interval)
- [x] File renaming to prevent reprocessing
- [x] Live testing with real consultants - messages delivered successfully

**Issues Resolved:**
1. **"Invalid control character" in Railway** - JSON parsing issue with newlines in private key. Fixed by base64-encoding the entire service account JSON.
2. **"list index out of range" in pdfplumber** - Some Fireflies PDFs cause pdfplumber to crash. Added PyPDF2 as fallback parser.
3. **Adaptive Card not rendering** - Teams requires `body.content` to contain `<attachment id="ac1"></attachment>`. Fixed in message payload.
4. **Token truncation** - MS_REFRESH_TOKEN was truncated when pasting. Full token is 1493 characters.

**Status: DEPLOYED AND WORKING**

---

## Monitoring

**Railway Logs:** View real-time logs in Railway dashboard

**Log Messages:**
- `Starting processing cycle...` - Poll started
- `Found X new files to process` - Files detected
- `Extracted X words from FILE` - PDF parsed successfully
- `Sending Teams message to NAME` - About to send
- `Message sent to chat` - Delivery confirmed
- `Renamed file to: [PROCESSED]` - File processed
- `Logged skipped call: FILE - REASON` - File skipped

**Common Issues:**
- If no files being processed, check Google Drive folder has new unprocessed PDFs
- If Teams messages not sending, check MS_REFRESH_TOKEN is valid (1493 chars)
- If PDF parsing fails, check Railway logs for specific error

---

## Contact

**Joel** - Meraki Talent
Building automation and AI agents for recruitment workflows.
