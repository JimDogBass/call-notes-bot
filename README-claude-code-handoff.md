# Meraki Call Notes Automation - Claude Code Handoff

## Project Overview

Automated extraction of structured candidate information from recruitment call transcripts, delivered to consultants via Microsoft Teams bot.

**Owner:** Joel @ Meraki Talent
**Status:** IN PROGRESS - Python version ready for testing
**Date:** January 2026
**Last Updated:** 22 Jan 2026 @ 18:45

---

## Quick Start (Python Version)

```bash
# 1. Install dependencies
cd "C:\Projects\n8n Call Notes"
pip install -r requirements.txt

# 2. Set up Microsoft auth (one-time)
# First: Add http://localhost:8765/callback as Redirect URI in Azure Portal
python auth_setup.py
# Sign in as Joel when browser opens

# 3. Run the processor
python call_notes_processor.py
```

**What it does:**
- Reads new PDFs from Google Drive
- Looks up consultant + desk prompt from Google Sheets (editable anytime)
- Calls Azure OpenAI to extract call notes
- Sends Adaptive Card to consultant via Teams (1:1 chat from Joel)
- Renames processed files

---

## Business Context

- **Company:** Meraki Talent - UK-based financial services recruitment agency (Edinburgh, Glasgow, London)
- **Staff:** 40 recruiters across multiple desks
- **Volume:** ~200 call transcripts/day from Fireflies
- **Problem:** Manual note-taking is inconsistent; consultants need structured candidate data delivered automatically
- **Solution:** Automated extraction pipeline → Teams bot delivery

---

## Architecture Summary

```
Google Drive (PDF upload)
    ↓
Word Count Gate (<300 = skip)
    ↓
Extract Consultant Name from Filename
    ↓
Lookup Consultant → Get Desk (Google Sheets)
    ↓
Fetch Desk-Specific Prompt (Google Sheets)
    ↓
Azure OpenAI (GPT-4o-mini) → Extract Fields
    ↓
Format as Adaptive Card
    ↓
Teams Bot → Consultant's Personal Chat
```

---

## Azure Resources

| Resource | Name | Type | Notes |
|----------|------|------|-------|
| Azure OpenAI | `meraki-call-notes-bot` | OpenAI Service | GPT-4o-mini deployed |
| App Registration | `meraki-call-notes-bot` | Entra ID App | OAuth2 for Graph API |

### Credentials (see CREDENTIALS.md)

- Azure OpenAI Endpoint + API Key
- App Registration ID: `7e1c4f4b-e80e-42ed-a1ac-fc1e0bb3af21`
- Delegated permissions: Chat.Create, ChatMessage.Send, User.Read
- Joel's AAD ID (sender): `5882d2ec-5fcc-48be-bea3-dbbd7020d6ea`

---

## Google Sheets to Create

Create a single Google Spreadsheet with the following sheets (tabs):

### 1. Consultants (sheet)

| Column       | Notes                                                    |
|--------------|----------------------------------------------------------|
| Name         | Full name as appears in transcript filenames             |
| Email        | Company email                                            |
| Desk         | PE_VC, Compliance, Wealth_Trust, Product_Tech, Finance, Legal |
| TeamsUserId  | Microsoft 365 user object ID                             |
| Active       | TRUE or FALSE                                            |

### 2. Prompts (sheet)

| Column         | Notes                              |
|----------------|------------------------------------|
| Desk           | Must match Desk values above       |
| PromptTemplate | Full extraction prompt             |
| Description    | Human-readable description         |
| LastUpdated    | Date of last modification          |

### 3. Skipped_Calls (sheet)

| Column         | Notes                          |
|----------------|--------------------------------|
| Filename       | Original transcript filename   |
| Date           | When processing attempted      |
| WordCount      | Transcript word count          |
| Reason         | Why skipped                    |
| ConsultantName | Extracted name if available    |

### 4. Processing_Errors (sheet)

| Column       | Notes                      |
|--------------|----------------------------|
| Filename     | Original filename          |
| Date         | When error occurred        |
| ErrorMessage | Full error details         |
| NodeName     | Which node failed          |
| Resolved     | TRUE or FALSE              |

---

## Filename Parsing Logic

Fireflies generates filenames like:
```
Killian_Dougal___1_929-229-1016__-__1_949-701-2278-transcript-2026-01-20T13-43-50_000Z.pdf
Sean_McDermott___44_131_381_5617__-__44_7933_158168-transcript-2026-01-20T13-43-55_000Z.pdf
```

**Extraction logic:**
1. Split on `___` (triple underscore) - take first segment
2. Replace remaining `_` with spaces
3. Trim whitespace
4. Result: "Killian Dougal", "Sean McDermott"

**Regex pattern (if needed):**
```regex
^([A-Za-z_]+)___
```
Then replace `_` with space in captured group.

---

## Word Count Gating

- **Threshold:** 300 words minimum
- **Purpose:** Filter voicemails, wrong numbers, very brief check-ins
- **Expected filter rate:** 25-30% of transcripts
- **Action when below threshold:** Log to "Skipped Calls" list, stop processing

---

## Azure OpenAI Configuration

```
Endpoint: https://meraki-call-notes-bot.openai.azure.com/
API Version: 2024-02-15-preview
Deployment: [GET FROM JOEL - likely gpt-4o-mini]
Temperature: 0.1
Max Tokens: 2000
```

**System Prompt:**
```
You are a recruitment call analyst for Meraki Talent, a UK-based financial services recruitment agency. Extract candidate information according to the provided template.

Rules:
- Only include information explicitly stated by the candidate about themselves
- Recruiter statements about roles, firms, or compensation ranges must be ignored
- If information is not explicitly stated, write "Not stated"
- Do not infer or guess
- Do not include any sensitive personal attributes (race, ethnicity, religion, nationality)
```

**User Message Format:**
```
{{PromptTemplate}}

---

Transcript:
{{TranscriptText}}
```

---

## Teams Message Delivery

**Architecture:** Microsoft Graph API with delegated OAuth2 permissions. Messages sent FROM Joel's account to consultants.

**Why this approach:**
- Bot Framework proactive messaging had encryption/permission issues
- Graph API with delegated auth is simpler and more reliable
- Messages appear as personal messages from Joel (more human)

**n8n OAuth2 Credential:**
| Field | Value |
|-------|-------|
| Grant Type | Authorization Code |
| Authorization URL | `https://login.microsoftonline.com/0591f50e-b7a3-41d0-a0b1-b26a2df48dfc/oauth2/v2.0/authorize` |
| Access Token URL | `https://login.microsoftonline.com/0591f50e-b7a3-41d0-a0b1-b26a2df48dfc/oauth2/v2.0/token` |
| Client ID | `7e1c4f4b-e80e-42ed-a1ac-fc1e0bb3af21` |
| Scope | `Chat.Create ChatMessage.Send User.Read offline_access` |

**Create Teams Conversation Node (HTTP Request):**
```
POST https://graph.microsoft.com/v1.0/chats

{
  "chatType": "oneOnOne",
  "members": [
    {
      "@odata.type": "#microsoft.graph.aadUserConversationMember",
      "roles": ["owner"],
      "user@odata.bind": "https://graph.microsoft.com/v1.0/users/5882d2ec-5fcc-48be-bea3-dbbd7020d6ea"
    },
    {
      "@odata.type": "#microsoft.graph.aadUserConversationMember",
      "roles": ["owner"],
      "user@odata.bind": "https://graph.microsoft.com/v1.0/users/{{ $json.teamsUserId }}"
    }
  ]
}
```

**Send Teams Message Node (HTTP Request):**
```
POST https://graph.microsoft.com/v1.0/chats/{{ $('Create Teams Conversation').item.json.id }}/messages

Body (set to Expression mode):
{{ $('Create Adaptive Card').item.json.teamsBody }}
```

The `teamsBody` object is built by the Code node and contains the proper attachment structure for Adaptive Cards.

---

## Adaptive Card Template

```json
{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "📞 Call Notes",
      "weight": "bolder",
      "size": "large"
    },
    {
      "type": "TextBlock",
      "text": "{{date}} | {{filename}}",
      "isSubtle": true,
      "spacing": "none"
    },
    {
      "type": "Container",
      "items": [
        {
          "type": "TextBlock",
          "text": "**Location:** {{location}}",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "**Compensation:** {{compensation}}",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "**Target Comp:** {{target_comp}}",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "**Title:** {{title}}",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "**Reason for leaving:** {{reason_for_leaving}}",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "**Aim for new role:** {{aim_for_new_role}}",
          "wrap": true
        }
      ]
    },
    {
      "type": "TextBlock",
      "text": "**Candidate Highlights:**",
      "weight": "bolder",
      "spacing": "medium"
    },
    {
      "type": "TextBlock",
      "text": "{{candidate_highlights}}",
      "wrap": true
    }
  ],
  "actions": [
    {
      "type": "Action.OpenUrl",
      "title": "View Transcript",
      "url": "{{sharepoint_link}}"
    }
  ]
}
```

---

## Desk Types & Prompt Mapping

| Desk | Focus | Prompt Differences |
|------|-------|-------------------|
| PE_VC | Private Equity, Venture Capital IR/Fundraising | AUM, LP relationships, fund experience |
| Compliance | Regulatory, Risk | Certifications, regulatory knowledge, jurisdictions |
| Wealth_Trust | Trust Administration, Private Client | STEP/TEP, jurisdictional (offshore), structures |
| Product_Tech | Product Management, Digital | Team size, methodologies, tech stack |
| Finance | Accounting, CFO roles | Qualifications (ACA, ACCA), audit experience |
| Legal | In-house counsel | PQE, practice areas, sectors |

**Joel to provide:** Full prompt templates for each desk type.

---

## Error Handling

| Error Type | Action |
|------------|--------|
| PDF extraction fails | Log to Processing_Errors sheet, skip file |
| Consultant not found | Log to Skipped_Calls sheet (reason: "Unknown consultant"), skip |
| Consultant inactive | Log to Skipped_Calls sheet (reason: "Inactive consultant"), skip |
| Azure OpenAI timeout | Retry 2x with 30s delay, then log error |
| Azure OpenAI rate limit | Retry with exponential backoff |
| Teams delivery fails | Log error, do NOT retry (avoid duplicates) |

---

## Workflow Settings

```yaml
execution_mode: production
retry_on_failure: true
retry_count: 2
retry_delay: 30 # seconds
timeout: 120 # seconds
concurrency: 5 # parallel executions max
```

---

## Cost Estimates

**Azure OpenAI (GPT-4o-mini):**
- ~140 transcripts/day (after gating)
- ~4,500 input tokens + 800 output tokens per transcript
- Monthly: ~£3-5

**Azure Bot Service:**
- F0 (Free tier)
- 10,000 messages/month included
- Expected usage: ~4,400 messages/month
- Cost: £0

**Total estimated monthly cost: ~£5**

---

## Testing Checklist

- [ ] Short transcript (<300 words) → Should skip, log to Skipped_Calls sheet
- [ ] Known consultant name → Should match, process, deliver
- [ ] Unknown consultant name → Should skip, log reason
- [ ] Inactive consultant → Should skip, log reason
- [ ] Each desk type → Verify correct prompt selected
- [ ] Teams delivery → Message appears in consultant's bot chat
- [ ] Error handling → Disconnect Google Drive, verify logging works
- [ ] Duplicate handling → Same file twice, should not double-process

---

## Files in This Project

| File | Purpose |
|------|---------|
| `README-claude-code-handoff.md` | This file - technical reference |
| `CREDENTIALS.md` | All credentials and API endpoints |
| **Python (NEW)** | |
| `call_notes_processor.py` | Main Python script - full workflow |
| `auth_setup.py` | One-time OAuth2 setup for Microsoft Graph |
| `requirements.txt` | Python dependencies |
| `ms_refresh_token.txt` | Microsoft refresh token (created by auth_setup.py) |
| **Google Sheets** | |
| `Consultants_Final.csv` | Staff data for import |
| `Prompts_Final.csv` | Desk prompts for import |
| **Legacy (n8n)** | |
| `google-templates/` | CSV templates for Google Sheets import |
| `teams-app/` | Teams app manifest (not used - using Graph API instead) |

---

## Progress Log

### 20 Jan 2026 - Session 1

#### Completed
- [x] Created CSV templates for all 4 sheets (Consultants, Prompts, Skipped_Calls, Processing_Errors)
- [x] Drafted desk-specific extraction prompts for all 6 desks (PE_VC, Compliance, Wealth_Trust, Product_Tech, Finance, Legal)
- [x] Built n8n workflow structure with all nodes laid out

#### n8n Workflow Nodes (Structure Complete)
```
Schedule Trigger → Calculate Time Window → Get New Transcript Files → Check If Files Found
    → Parse PDF → Word Count and Metadata Extraction → Word Count Gate
        → (true) Log Skipped Call (Short Transcript)
        → (false) Lookup Consultant → Validate Consultant Found and Active
            → (true) Log Skipped Call (Unknown/Inactive)
            → (false) Fetch Desk Prompt → Prepare Prompt with Fallback
                → Azure OpenAI Extraction → Format Teams Adaptive Card
                → Get Bot Access Token → Prepare Bot API Request
                → Send Message via Bot Framework → Success Marker
```

### 21 Jan 2026 - Session 2

#### Change: Migrated from SharePoint to Google Workspace
- SharePoint authority/permissions issues → switched to Google Drive + Sheets

#### Completed
- [x] Google Drive folder created
- [x] Google Sheets created with all tabs
- [x] Google Service Account configured
- [x] Consultants sheet populated with 36 user IDs

### 22 Jan 2026 - Session 3

#### Problem: Bot Framework API Issues
- Direct Bot Framework API calls failed with "Failed to decrypt pairwise id"
- Microsoft Graph API blocked app-only chat messaging (401 - "only for import purposes")
- Teams app upload failed due to bot registration issues
- Multi-tenant bots not an option for the organization

#### Solution: Graph API with Delegated OAuth2
- Use Microsoft Graph API with **delegated permissions** (not application)
- Messages sent FROM Joel's account to consultants
- OAuth2 flow - Joel authenticated once in n8n
- No bot infrastructure needed

#### Completed
- [x] Azure app registration configured with delegated permissions (Chat.Create, ChatMessage.Send, User.Read)
- [x] OAuth2 redirect URI added for n8n
- [x] n8n OAuth2 credential connected as Joel
- [x] Create Teams Conversation node configured with Graph API
- [x] Send Teams Message node configured
- [x] End-to-end workflow tested and working
- [x] Documentation updated

#### Final Architecture
```
Google Drive (PDF) → Parse → Lookup Consultant → Get Prompt → Azure OpenAI
    → Create Adaptive Card → Graph API Create Chat → Graph API Send Message
    → Rename Processed File
```

**STATUS: ~~COMPLETE AND WORKING~~ - See Session 4 below**

### 22 Jan 2026 - Session 4 (Evening)

#### Problem: Adaptive Card Not Rendering
- Teams messages showed literal expression text `{{ $('Create Adaptive Card').item.json.cardContent }}` instead of actual content
- Root cause: n8n expression syntax issues with JSON.stringify() inside JSON body fields

#### Solution: Replace "Create Adaptive Card" with Code Node
- Changed from Set node to Code node for proper JavaScript execution
- Code node builds both the Adaptive Card AND the complete Teams message body
- Send Teams Message node now references `teamsBody` directly

#### Create Adaptive Card - Code Node

**Mode:** Run Once for Each Item
**Language:** JavaScript

```javascript
// Get data from input (data flows through the pipeline)
const input = $input.item.json;

const notes = input.message?.content || "No notes";
const filename = input.fileName || "Unknown file";
const consultantName = input.consultantName || "Unknown";
const candidateName = input.candidateName || "Unknown";
const callDate = input.callDate || new Date().toISOString().split('T')[0];
const teamsUserId = input.TeamsUserId || input.teamsUserId;

// Build the adaptive card
const card = {
  type: "AdaptiveCard",
  version: "1.4",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  body: [
    {
      type: "TextBlock",
      text: "📞 Call Notes: " + candidateName,
      weight: "Bolder",
      size: "Large"
    },
    {
      type: "TextBlock",
      text: "Date: " + callDate,
      size: "Medium",
      spacing: "Small"
    },
    {
      type: "TextBlock",
      text: notes,
      wrap: true,
      spacing: "Medium"
    },
    {
      type: "TextBlock",
      text: "Source: " + filename,
      size: "Small",
      isSubtle: true,
      spacing: "Large"
    }
  ]
};

// Build Teams message body
const teamsBody = {
  body: {
    contentType: "html",
    content: ""
  },
  attachments: [
    {
      id: "ac1",
      contentType: "application/vnd.microsoft.card.adaptive",
      contentUrl: null,
      content: JSON.stringify(card)
    }
  ]
};

return {
  teamsBody: teamsBody,
  teamsUserId: teamsUserId
};
```

#### Input Data Structure (for reference)
Data flows through pipeline. Key fields available in `$input.item.json`:
- `message.content` - Azure OpenAI extracted notes
- `fileName` - from Parse Filename
- `consultantName` - from Parse Filename
- `candidateName` - from Parse Filename
- `callDate` - from Parse Filename
- `teamsUserId` or `TeamsUserId` - from Lookup Consultant

#### Status
- [x] Code node created and tested
- [x] Expression `input.message?.content` working
- [ ] Full end-to-end test with Teams delivery
- [ ] Verify Adaptive Card renders correctly in Teams

#### Decision: Rebuild in Python
n8n expression issues with JSON/newlines making debugging too slow. Rebuilding as Python script.

---

## Python Rebuild Plan (23 Jan 2026)

### Why Python?
- n8n expressions don't handle newlines in JSON well
- Difficult to debug without seeing full code
- Python allows direct debugging and testing

### Architecture (Python)
```
Google Drive (watch for PDFs)
    ↓
Parse PDF → Extract text
    ↓
Parse filename → Get consultant name, date
    ↓
Google Sheets lookup → Consultant (Desk, TeamsUserId, Active)
    ↓
Google Sheets lookup → Prompt template (by Desk)
    ↓
Azure OpenAI → Extract call notes
    ↓
Microsoft Graph API → Send Teams message
    ↓
Rename/move processed file
```

### Keep Using Google Sheets
| Sheet | Purpose | Update Locally |
|-------|---------|----------------|
| Consultants | Name, Email, Desk, TeamsUserId, Active | Yes - add/remove staff anytime |
| Prompts | Desk-specific extraction prompts | Yes - refine prompts anytime |
| Skipped_Calls | Logging | Written by Python |
| Processing_Errors | Error tracking | Written by Python |

**Spreadsheet ID:** `1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g`

### Credentials Needed (from CREDENTIALS.md)
- Google Service Account JSON key
- Azure OpenAI API key
- Microsoft Graph OAuth2 (Client ID, Secret, Tenant ID, Joel's refresh token)

### Deployment Options
1. **Railway** - same platform as current n8n, easy deploy
2. **Local** - run on Joel's machine with scheduler
3. **Azure Functions** - serverless, trigger on Drive changes

### Python Dependencies
```
google-api-python-client
google-auth
pypdf2 or pdfplumber
openai
msal (Microsoft auth)
requests
```

### Python Files Created
| File | Purpose |
|------|---------|
| `call_notes_processor.py` | Main processor script |
| `requirements.txt` | Python dependencies |
| `auth_setup.py` | One-time OAuth2 setup for Microsoft Graph |

### Setup Instructions

**1. Install dependencies:**
```bash
cd "C:\Projects\n8n Call Notes"
pip install -r requirements.txt
```

**2. Get Microsoft refresh token (one of these options):**

**Option A: Run auth_setup.py**
- First add `http://localhost:8765/callback` as a Redirect URI in Azure App Registration
- Run: `python auth_setup.py`
- Sign in as Joel
- Token saved to `ms_refresh_token.txt`

**Option B: Extract from n8n**
- In n8n, go to Credentials → your OAuth2 credential
- Look for the refresh token in the credential data
- Save to `ms_refresh_token.txt`

**3. Test the processor:**
```bash
python call_notes_processor.py
```

### Next Steps
1. [x] Create Python script with full workflow
2. [ ] Install dependencies
3. [ ] Set up Microsoft refresh token
4. [ ] Test locally with sample PDF
5. [ ] Verify Teams message sends
6. [ ] Set up scheduler (Task Scheduler on Windows or cron)

---

## Google Workspace Structure

### Google Drive
```
Call Transcripts/               ← Fireflies drops PDFs here (n8n trigger)
├── [transcript files].pdf
└── Processed/                  ← Optional: move files after processing
```

### Google Sheets
**Spreadsheet:** `Call Notes Data`
```
Sheets (tabs):
├── Consultants                 ← Staff lookup (Name, Email, Desk, TeamsUserId, Active)
├── Prompts                     ← Desk prompts (Desk, PromptTemplate, Description, LastUpdated)
├── Skipped_Calls               ← Logging (Filename, Date, WordCount, Reason, ConsultantName)
└── Processing_Errors           ← Error tracking (Filename, Date, ErrorMessage, NodeName, Resolved)
```

### IDs Needed for n8n
| Item | How to Get |
|------|------------|
| Google Drive Folder ID | Open folder in Drive, copy ID from URL: `drive.google.com/drive/folders/{FOLDER_ID}` |
| Google Spreadsheet ID | Open spreadsheet, copy ID from URL: `docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit` |

---

## Open Items / Questions for Joel

1. ~~**Azure OpenAI deployment name**~~ - Confirm exact name of GPT-4o-mini deployment
2. ~~**Desk-specific prompts**~~ - ✅ Drafted in Prompts.csv (review and refine)
3. **Google Drive folder** - Create folder for Fireflies transcript uploads
4. **Google Sheets** - Create spreadsheet with 4 tabs (can import CSVs)
5. **Consultant list** - Need to populate with all 40 staff + TeamsUserIds
6. **Teams app icons** - Need color.png (192x192) and outline.png (32x32)
7. **Google Service Account** - Create in Google Cloud Console for n8n access

---

## Contact

**Joel** - Meraki Talent
Building automation and AI agents for recruitment workflows.
Primary tools: n8n, Azure OpenAI, Supabase, Microsoft ecosystem.
