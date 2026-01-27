# Meraki Call Notes Automation - Technical Reference

## Project Overview

Automated extraction of structured candidate information from recruitment call transcripts, delivered to consultants via Microsoft Teams bot.

**Owner:** Joel @ Meraki Talent
**Status:** DEPLOYED AND WORKING on Railway
**Date:** January 2026
**Last Updated:** 27 Jan 2026 @ 16:30

---

## Quick Start

The system is deployed on Railway and runs automatically.

**Railway Dashboard:** [https://railway.app](https://railway.app) (login as Joel)
**GitHub Repo:** [https://github.com/JimDogBass/call-notes-bot](https://github.com/JimDogBass/call-notes-bot)
**Railway URL:** `https://call-notes-bot-production.up.railway.app`

### Local Development

```bash
# 1. Install dependencies
cd "C:\Projects\n8n Call Notes"
pip install -r requirements.txt

# 2. Set environment variables (or use .env file)
# See Environment Variables section below

# 3. Run the combined server
python main.py
```

---

## What It Does

1. Polls Google Drive every 60 seconds for new PDF transcripts
2. Extracts text using pdfplumber (with PyPDF2 fallback)
3. Parses consultant name from filename
4. Looks up consultant info + desk-specific prompt from Google Sheets
5. Calls Gemini 2.5 Pro to extract structured call notes
6. Sends Adaptive Card via **Christina bot** (messages appear in Chat from "Christina")
7. Renames processed files with `[PROCESSED]` prefix
8. Logs skipped calls (short transcripts, unknown consultants, unregistered users) to Google Sheets

**Note:** Consultants must message Christina once to register before receiving notes.

---

## Business Context

- **Company:** Meraki Talent - UK-based financial services recruitment agency (Edinburgh, Glasgow, London)
- **Staff:** 40 recruiters across multiple desks
- **Volume:** ~200 call transcripts/day from Fireflies
- **Problem:** Manual note-taking is inconsistent; consultants need structured candidate data delivered automatically
- **Solution:** Automated extraction pipeline with Teams bot delivery

---

## Architecture

```
Google Drive (PDF upload via Fireflies)
    |
    v
Poll for new PDFs (every 60 seconds)
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
Christina Bot --> Proactive message to consultant's Chat
    |                (user must be registered)
    v
Rename file to [PROCESSED] prefix
```

---

## Christina Bot (Teams Delivery)

**Primary delivery method** - Messages appear in consultants' Chat from "Christina"

### How It Works

1. Consultant installs Christina app in Teams
2. Consultant sends any message to bot (e.g., "hi") to register
3. Bot stores conversation reference for that user
4. When call notes are ready, bot sends proactive message
5. Message appears in Chat from "Christina"

### Bot Details

| Item | Value |
|------|-------|
| Bot Name | Christina-Call-Notes |
| App ID | `5e5ed2ce-14d5-46b8-93d5-0a473f3cd88c` |
| Messaging Endpoint | `https://call-notes-bot-production.up.railway.app/api/messages` |
| Teams App Package | `christina-bot.zip` |

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/messages` | POST | Bot Framework webhook |
| `/api/send-note` | POST | Send proactive call note |
| `/api/users` | GET | List registered users |
| `/health` | GET | Health check |

### Registering Users (Required)

**All consultants must register with Christina to receive call notes.**

1. Install Christina app in Teams (from "Built for your org" section)
2. Open chat with Christina
3. Send "hi" or any message
4. User is now registered and will receive all future call notes

**Note:** Registration is stored in Google Sheets (ConversationReferences sheet) - users only need to register once and will survive redeployments.

### Onboarding Message Template

Send this to your team:

> Hi team! We've set up automated call notes. To receive your call summaries:
> 1. Open Teams and go to Apps
> 2. Find "Christina" under "Built for your org"
> 3. Click Open and send "hi"
>
> That's it! You'll now receive call notes automatically in your Chat from Christina.

---

## Railway Deployment

### Environment Variables

| Variable | Description | Notes |
|----------|-------------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Base64-encoded service account JSON | See encoding instructions below |
| `GOOGLE_DRIVE_FOLDER_ID` | `1SfFPHC1DRUzcR8FDcdQkzr5oJZhtNSzr` | Google Drive folder ID |
| `GOOGLE_SPREADSHEET_ID` | `1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g` | Google Sheets ID |
| `GEMINI_API_KEY` | (see CREDENTIALS.md) | Google AI Studio API key |
| `BOT_APP_ID` | `5e5ed2ce-14d5-46b8-93d5-0a473f3cd88c` | Christina bot app ID |
| `BOT_APP_PASSWORD` | (see CREDENTIALS.md) | Christina bot secret |
| `BOT_TENANT_ID` | `0591f50e-b7a3-41d0-a0b1-b26a2df48dfc` | Microsoft tenant ID |
| `POLL_INTERVAL` | `60` | Seconds between polls |

### Procfile

```
web: python main.py
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
| ChannelId | Teams private channel ID (optional) |

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

### 5. ConversationReferences (sheet)

| Column | Notes |
|--------|-------|
| UserAADId | Microsoft 365 user object ID |
| ConversationReferenceJSON | Bot Framework conversation reference (JSON) |
| UpdatedAt | When last updated |

**Note:** This sheet is created automatically when the first user registers with Christina.

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Combined bot server + processor (main entry point) |
| `call_notes_processor.py` | PDF processing logic (imported by main.py) |
| `bot_server.py` | Standalone bot server (not used in production) |
| `auth_setup.py` | OAuth2 setup for Microsoft Graph (local use) |
| `setup_channels.py` | Create private channels (optional feature) |
| `requirements.txt` | Python dependencies |
| `Procfile` | Railway deployment configuration |
| `teams-manifest/` | Teams app manifest and icons |
| `christina-bot.zip` | Packaged Teams app for installation |

---

## Filename Parsing Logic

Fireflies generates filenames in various formats:
```
Lisa Paton [+44 141 648 9417] - +44 7912 748851-transcript-2026-01-23T11-43-55.000Z.pdf
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

## Error Handling

| Error Type | Action |
|------------|--------|
| PDF extraction fails | Try PyPDF2 fallback, then log to Processing_Errors |
| Consultant not found | Log to Skipped_Calls (reason: "Unknown consultant"), rename file |
| Consultant inactive | Log to Skipped_Calls (reason: "Inactive consultant"), rename file |
| Gemini API fails | Retry 3x with backoff, then log error |
| Bot delivery fails | Log error in Railway logs |

---

## Monitoring

**Railway Logs:** View real-time logs in Railway dashboard

**Health Check:** `https://call-notes-bot-production.up.railway.app/health`

**Registered Users:** `https://call-notes-bot-production.up.railway.app/api/users`

**Log Messages:**
- `Starting processing cycle...` - Poll started
- `Found X new files to process` - Files detected
- `Extracted X words from FILE` - PDF parsed successfully
- `Calling Gemini 2.5 Pro for FILE` - AI extraction starting
- `Sent proactive card to user: XXX` - Bot message delivered
- `Renamed file to: [PROCESSED]` - File processed

---

## Progress Log

### 20-23 Jan 2026 - Initial Development
- Created CSV templates, prompts, Google Sheets integration
- Built Python processor with Gemini 2.5 Pro
- Deployed to Railway with Graph API (1:1 chats from Joel)

### 26 Jan 2026 - Optimization
- Fixed Gemini model name, retry logic, filename parsing
- Reduced poll interval to 60 seconds
- Contains-based consultant matching

### 27 Jan 2026 - Christina Bot Implementation

**Completed:**
- [x] Created Christina-Call-Notes Azure Bot (Single Tenant)
- [x] Built bot server with proactive messaging support
- [x] Combined bot server + processor in main.py
- [x] Created Teams app manifest and icons
- [x] Deployed and tested proactive messaging
- [x] Messages now appear in Chat from "Christina" bot
- [x] Persistent conversation storage in Google Sheets
- [x] First successful test with Ayman Waren

**Configuration:**
- Bot App ID: `5e5ed2ce-14d5-46b8-93d5-0a473f3cd88c`
- Messaging Endpoint: `https://call-notes-bot-production.up.railway.app/api/messages`
- Teams App: `christina-bot.zip`

**Persistent Storage:**
- Conversation references stored in Google Sheets (ConversationReferences sheet)
- Sheet created automatically on first user registration
- Users only need to register once - survives all redeployments
- Tested: Ayman Waren registered and received test messages successfully

**Christina-Only Delivery:**
- All messages now sent via Christina bot (not Graph API)
- Messages appear in Chat from "Christina" (not from Joel)
- Consultants must register by messaging Christina once
- Unregistered users logged to Skipped_Calls

---

## Troubleshooting Skipped Calls

Check the `Skipped_Calls` sheet for logged issues:

| Reason | Cause | Action |
|--------|-------|--------|
| Too short | < 300 words | Expected - voicemails, brief calls |
| Unknown consultant | Name not found in Consultants sheet | Add consultant to sheet, or check spelling |
| Inactive consultant | Consultant marked FALSE in Active column | Set Active to TRUE |
| No TeamsUserId | Consultant has no Teams ID | Add their AAD Object ID |
| Christina delivery failed | User hasn't registered with Christina | User must message Christina to register |

**To reprocess a skipped file:**
1. Go to Google Drive folder
2. Find the file (has `[PROCESSED]` prefix)
3. Remove the `[PROCESSED]` prefix from filename
4. Processor will pick it up on next cycle

---

## Future Improvements

1. **Org-wide app deployment** - Have IT deploy Christina to all users automatically
2. **Bot commands** - Allow users to ask Christina questions (search past notes, etc.)
3. **Delivery confirmation** - Track which notes were delivered successfully

---

## Contact

**Joel** - Meraki Talent
Building automation and AI agents for recruitment workflows.
