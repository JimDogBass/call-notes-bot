# Meraki Call Notes Automation - Technical Reference

## Project Overview

Automated extraction of structured candidate information from recruitment call transcripts, delivered to consultants via Microsoft Teams.

**Owner:** Joel @ Meraki Talent
**Status:** DEPLOYED AND WORKING on Railway
**Date:** January 2026
**Last Updated:** 26 Jan 2026 @ 14:00

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
5. Calls Gemini 2.5 Pro to extract structured call notes
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
Gemini 2.5 Pro --> Extract structured notes
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
| `GEMINI_API_KEY` | (see CREDENTIALS.md) | Google AI Studio API key |
| `MS_TENANT_ID` | `0591f50e-b7a3-41d0-a0b1-b26a2df48dfc` | Microsoft tenant ID |
| `MS_CLIENT_ID` | `7e1c4f4b-e80e-42ed-a1ac-fc1e0bb3af21` | Azure app registration ID |
| `MS_CLIENT_SECRET` | (see CREDENTIALS.md) | Azure app client secret |
| `MS_REFRESH_TOKEN` | (see CREDENTIALS.md) | Microsoft OAuth2 refresh token (1493 chars) |
| `JOEL_AAD_ID` | `5882d2ec-5fcc-48be-bea3-dbbd7020d6ea` | Joel's Azure AD user ID |
| `TEAM_ID` | (run setup_channels.py) | Teams team ID for private channels |
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
| ChannelId | Teams private channel ID (populated by setup_channels.py) |

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

Fireflies generates filenames in various formats:
```
Lisa Paton [+44 141 648 9417] - +44 7912 748851-transcript-2026-01-23T11-43-55.000Z.pdf
Scott Eccles [+44 141 846 0530] - +44 7940 704901-transcript-2026-01-23T11-40-38.000Z.pdf
+44 7742 546123 - Jonathan Kearsley [+44 20 4571 7401]-transcript-2026-01-26T13-41-48.000Z.pdf
```

**Consultant matching:**
- Uses "contains" lookup - searches for consultant name anywhere in filename
- Matches longer names first (e.g., "Jonathan Kearsley" before "Jon")
- Works regardless of filename format or order

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
| Gemini API fails | Log error, skip file |
| Teams delivery fails | Log error, do NOT rename (will retry next cycle) |

---

## Files

| File | Purpose |
|------|---------|
| `call_notes_processor.py` | Main processor script with polling loop |
| `auth_setup.py` | One-time OAuth2 setup for Microsoft Graph (local use) |
| `setup_channels.py` | One-time script to create Team and private channels |
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

### 23 Jan 2026 - Session 6 (Afternoon)

**Completed:**
- [x] Added 10-minute file age filter (only process new files, skip backlog)
- [x] Switched from Azure OpenAI (GPT-4o-mini) to Gemini 2.5 Pro
- [x] Better quality extraction at lower cost ($1.25/M input vs $2.50/M)
- [x] Removed unused Azure OpenAI and Bot Framework environment variables

**Railway Environment Variables (final):**
- GEMINI_API_KEY
- GOOGLE_DRIVE_FOLDER_ID
- GOOGLE_SERVICE_ACCOUNT_JSON
- GOOGLE_SPREADSHEET_ID
- JOEL_AAD_ID
- MS_CLIENT_ID
- MS_CLIENT_SECRET
- MS_REFRESH_TOKEN
- MS_TENANT_ID
- POLL_INTERVAL

### 26 Jan 2026 - Session 7 (Troubleshooting & Optimization)

**Issues Fixed:**
1. **Wrong Gemini model name** - Changed from `gemini-2.5-pro-preview-05-06` to `gemini-2.5-pro`
2. **Files slipping through time window** - Changed from rolling 10-15 min window to fixed cutoff date (26 Jan 2026)
3. **API failures not retried** - Added 3x retry logic with exponential backoff (5s, 10s, 15s)
4. **KeyError: 'parts'** - Added proper error handling for blocked content / safety filter responses
5. **MAX_TOKENS error** - Increased `maxOutputTokens` from 2000 to 8000 for long transcripts
6. **Reversed filename format** - Changed consultant lookup from exact match to "contains" match (finds name anywhere in filename, handles any format)

**Performance Improvements:**
- Poll interval reduced from 5 minutes to 1 minute (POLL_INTERVAL=60)
- Faster response to new files

**Current Configuration:**
- Model: Gemini 2.5 Pro
- Poll interval: 60 seconds
- Max output tokens: 8000
- File cutoff: 26 Jan 2026 00:00 UTC (ignores older backlog)
- Retries: 3 attempts with 5s/10s/15s backoff
- Consultant lookup: "contains" match (finds name anywhere in filename)

---

## Monitoring

**Railway Logs:** View real-time logs in Railway dashboard

**Log Messages:**
- `Starting processing cycle...` - Poll started
- `Poll interval: 60 seconds` - Confirms poll setting
- `Found X new files to process` - Files detected
- `Extracted X words from FILE` - PDF parsed successfully
- `Calling Gemini 2.5 Pro for FILE` - AI extraction starting
- `Gemini API attempt X failed... Retrying` - Transient failure, retrying
- `Sending Teams message to NAME` - About to send
- `Message sent to chat` - Delivery confirmed
- `Renamed file to: [PROCESSED]` - File processed
- `Logged skipped call: FILE - REASON` - File skipped

**Common Issues:**
- If no files being processed, check Google Drive folder has new unprocessed PDFs (created after 26 Jan 2026)
- If Teams messages not sending, check MS_REFRESH_TOKEN is valid (1493 chars)
- If Gemini fails repeatedly, check for safety filter blocks or quota limits
- If MAX_TOKENS error, transcript may be extremely long (current limit: 8000 tokens)

---

## Private Channels per Consultant

**Status:** IMPLEMENTED

**Current:** Messages posted to private Teams channels (with 1:1 chat fallback)

**Benefits:**
- Notes persist in searchable channel history
- Consultants get notifications
- Private to each consultant (they are channel owners)
- Consultants can add their manager/teammates to their channel
- Easier to reference past calls

### Setup Instructions

**1. Add ChannelId column to Google Sheet:**
- Open the Consultants sheet
- Add "ChannelId" as header in column F

**2. Re-authenticate with new permissions:**
```bash
cd "C:\Projects\n8n Call Notes"
python auth_setup.py
# Sign in as Joel - consent to new channel permissions
```

**3. Run channel setup script:**
```bash
python setup_channels.py
```
This will:
- Create "Call Notes" Team (or use existing)
- Create private channel for each active consultant
- Add consultant as channel owner
- Save channel IDs to Google Sheet
- Send welcome message to each channel

**4. Add TEAM_ID to Railway:**
- Copy the Team ID from `team_id.txt` (or script output)
- Add `TEAM_ID` environment variable in Railway dashboard

**5. Deploy:**
```bash
git add . && git commit -m "Add private channels support" && git push
```

### Fallback Behavior

If a consultant has no ChannelId or TEAM_ID is not set, the system falls back to 1:1 chat (original behavior).

### Adding New Consultants

When adding a new consultant:
1. Add them to Google Sheet with TeamsUserId
2. Run `setup_channels.py` again - it will only create channels for consultants without one

---

## Contact

**Joel** - Meraki Talent
Building automation and AI agents for recruitment workflows.
