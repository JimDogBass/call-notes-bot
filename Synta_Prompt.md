# n8n Workflow Configuration Request

## Overview
I need help configuring an n8n workflow that processes recruitment call transcripts from Google Drive, extracts candidate information using Azure OpenAI, and sends formatted results to consultants via Microsoft Teams Bot.

## Google Resources

- **Google Drive Folder ID:** `1SfFPHC1DRUzcR8FDcdQkzr5oJZhtNSzr`
- **Google Spreadsheet ID:** `1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g`

### Google Sheets Structure

**Sheet 1: Consultants**
| Column | Description |
|--------|-------------|
| Name | Consultant full name |
| Email | Email address (used for lookup) |
| Desk | Department/desk assignment |
| TeamsUserId | Microsoft Teams user ID for messaging |
| Active | TRUE/FALSE |

**Sheet 2: Prompts**
| Column | Description |
|--------|-------------|
| Desk | Department name (used for lookup) |
| PromptTemplate | The AI extraction prompt for that desk |
| Description | What the prompt is for |
| LastUpdated | Date last modified |

**Sheet 3: Skipped_Calls**
| Column | Description |
|--------|-------------|
| FileName | Name of the transcript file |
| Consultant | Email of the consultant |
| Reason | Why it was skipped |
| Timestamp | When it was skipped |

**Sheet 4: Processing_Errors**
| Column | Description |
|--------|-------------|
| FileName | Name of the transcript file |
| ErrorMessage | What went wrong |
| Stage | Which workflow stage failed |
| Timestamp | When the error occurred |

---

## Workflow Logic

### 1. Schedule Trigger
- Run every 15 minutes (or configurable interval)

### 2. Calculate Time Window
- Calculate the start time for filtering (e.g., last 15 minutes or last run time)
- Output: `startTime` in ISO format

### 3. Get New Transcript Files (Google Drive)
- **Operation:** List files from Google Drive folder
- **Folder ID:** `1SfFPHC1DRUzcR8FDcdQkzr5oJZhtNSzr`
- **Filter:** PDF files only (`mimeType='application/pdf'`)
- **Filter:** Modified after the calculated start time
- Files are named like: `firstname.lastname@merakitalent.com - Candidate Name - Date.pdf`

### 4. Check If Files Found
- IF node: Check if any files were returned
- If no files, end workflow gracefully

### 5. Loop Through Each File
For each PDF file:

#### 5a. Parse PDF
- Download the file from Google Drive
- Extract text content from PDF

#### 5b. Extract Metadata from Filename
- Parse the filename to extract:
  - `consultantEmail` (the part before the first " - ")
  - `candidateName` (the part between first and second " - ")
  - `callDate` (the part after the second " - ", before .pdf)

#### 5c. Word Count Check
- Count words in the transcript
- **Minimum threshold:** 100 words (configurable)

#### 5d. Word Count Gate (IF Node)
- If word count < threshold:
  - Log to Skipped_Calls sheet with reason "Transcript too short (X words)"
  - Skip to next file
- If word count >= threshold:
  - Continue processing

#### 5e. Lookup Consultant (Google Sheets)
- **Sheet:** Consultants
- **Lookup Column:** Email
- **Lookup Value:** The extracted `consultantEmail`
- Returns: Name, Desk, TeamsUserId, Active

#### 5f. Validate Consultant (IF Node)
- Check if consultant was found AND Active = TRUE
- If not found or not active:
  - Log to Skipped_Calls sheet with reason "Consultant not found or inactive"
  - Skip to next file
- If valid:
  - Continue processing

#### 5g. Fetch Desk Prompt (Google Sheets)
- **Sheet:** Prompts
- **Lookup Column:** Desk
- **Lookup Value:** The consultant's Desk from previous lookup
- Returns: PromptTemplate

#### 5h. Prepare Prompt with Fallback
- If no prompt found for desk, use a generic fallback prompt
- Combine the PromptTemplate with the transcript text

#### 5i. Azure OpenAI Extraction (HTTP Request)
- **Method:** POST
- **URL:** `https://[RESOURCE-NAME].openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-02-15-preview`
- **Headers:**
  - `Content-Type: application/json`
  - `api-key: [AZURE_OPENAI_KEY]`
- **Body:**
```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a recruitment assistant extracting candidate information from call transcripts. Only include information explicitly stated in the transcript."
    },
    {
      "role": "user",
      "content": "[PromptTemplate]\n\nTRANSCRIPT:\n[transcriptText]"
    }
  ],
  "temperature": 0.3,
  "max_tokens": 1500
}
```

#### 5j. Format Teams Adaptive Card
- Create an Adaptive Card JSON with:
  - Header showing candidate name and call date
  - The extracted information from Azure OpenAI
  - File name for reference

Example Adaptive Card structure:
```json
{
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "Call Notes: [Candidate Name]",
      "weight": "Bolder",
      "size": "Large"
    },
    {
      "type": "TextBlock",
      "text": "[Extracted Information]",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "Source: [FileName]",
      "size": "Small",
      "isSubtle": true
    }
  ]
}
```

#### 5k. Get Bot Access Token (HTTP Request)
- **Method:** POST
- **URL:** `https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token`
- **Body (Form URL Encoded):**
  - `grant_type=client_credentials`
  - `client_id=[BOT_APP_ID]`
  - `client_secret=[BOT_APP_SECRET]`
  - `scope=https://api.botframework.com/.default`
- **Output:** Access token for bot API

#### 5l. Create Conversation with User (HTTP Request)
- **Method:** POST
- **URL:** `https://smba.trafficmanager.net/uk/v3/conversations`
- **Headers:**
  - `Authorization: Bearer [accessToken]`
  - `Content-Type: application/json`
- **Body:**
```json
{
  "bot": {
    "id": "[BOT_APP_ID]",
    "name": "Call Notes Bot"
  },
  "members": [
    {
      "id": "[TeamsUserId]"
    }
  ],
  "channelData": {
    "tenant": {
      "id": "[TENANT_ID]"
    }
  }
}
```
- **Output:** Conversation ID

#### 5m. Send Message via Bot Framework (HTTP Request)
- **Method:** POST
- **URL:** `https://smba.trafficmanager.net/uk/v3/conversations/[conversationId]/activities`
- **Headers:**
  - `Authorization: Bearer [accessToken]`
  - `Content-Type: application/json`
- **Body:**
```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": [AdaptiveCardJSON]
    }
  ]
}
```

#### 5n. Success Marker / Move Processed File
- Optionally move the processed file to a "Processed" subfolder in Google Drive
- Or rename with a prefix like "DONE_"

---

## Error Handling

- Wrap the main processing loop in try-catch
- On any error, log to Processing_Errors sheet with:
  - FileName
  - ErrorMessage
  - Stage (which step failed)
  - Timestamp
- Continue to next file (don't stop the whole workflow)

---

## Credentials Needed

1. **Google Service Account** - with access to the Drive folder and Spreadsheet
2. **Azure OpenAI** - API key and endpoint
3. **Microsoft Bot Framework** - App ID and Secret for the Teams bot

---

## Notes

- The Google Spreadsheet already has data in Consultants and Prompts sheets
- Consultant emails in filenames match the Email column in the Consultants sheet
- Each desk has a specific prompt template for extracting relevant information
- The workflow should be resilient - one failed file shouldn't stop processing of others
