# Google Workspace Setup Instructions

## Step 1: Create Google Drive Folder for Transcripts

1. Go to [Google Drive](https://drive.google.com)
2. Click **+ New** → **New folder**
3. Name: `Call Transcripts`
4. This is where Fireflies will upload PDFs

**Optional:** Create a `Processed` subfolder to move files after processing.

**Get Folder ID:**
- Open the folder
- Copy the ID from the URL: `drive.google.com/drive/folders/{FOLDER_ID}`
- Save this ID for n8n configuration

---

## Step 2: Create Google Sheets Spreadsheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Click **+ Blank** to create a new spreadsheet
3. Name it: `Call Notes Data`

### Option A: Import from CSV (Recommended)

For each CSV file (Consultants.csv, Prompts.csv):

1. Go to **File** → **Import**
2. Click **Upload** tab
3. Select the CSV file
4. Import location: **Insert new sheet(s)**
5. Click **Import data**
6. Rename the sheet tab to match (Consultants, Prompts)

For Skipped_Calls.csv and Processing_Errors.csv:
- Import the same way (these just have headers, n8n will append rows)

### Option B: Create Sheets Manually

Create 4 sheets (tabs) with these columns:

#### Consultants
| A | B | C | D | E |
|---|---|---|---|---|
| Name | Email | Desk | TeamsUserId | Active |

#### Prompts
| A | B | C | D |
|---|---|---|---|
| Desk | PromptTemplate | Description | LastUpdated |

#### Skipped_Calls
| A | B | C | D | E |
|---|---|---|---|---|
| Filename | Date | WordCount | Reason | ConsultantName |

#### Processing_Errors
| A | B | C | D | E |
|---|---|---|---|---|
| Filename | Date | ErrorMessage | NodeName | Resolved |

**Get Spreadsheet ID:**
- Open the spreadsheet
- Copy the ID from the URL: `docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
- Save this ID for n8n configuration

---

## Step 3: Populate Consultants Sheet

Add all 40 consultants with:
| Name | Email | Desk | TeamsUserId | Active |
|------|-------|------|-------------|--------|
| Killian Dougal | killian.dougal@merakitalent.com | PE_VC | [Object ID] | TRUE |
| ... | ... | ... | ... | TRUE |

**To get TeamsUserId (Microsoft 365 Object ID):**
- Azure Portal → Azure Active Directory → Users → Select user → Copy **Object ID**
- Or via PowerShell: `Get-AzureADUser -ObjectId "email@domain.com" | Select ObjectId`

**Valid Desk values:**
- PE_VC
- Compliance
- Wealth_Trust
- Product_Tech
- Finance
- Legal

---

## Step 4: Create Google Service Account for n8n

### 4.1 Create Google Cloud Project (if needed)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown → **New Project**
3. Name: `n8n-call-notes` (or similar)
4. Click **Create**

### 4.2 Enable APIs

1. Go to **APIs & Services** → **Library**
2. Search and enable:
   - **Google Drive API**
   - **Google Sheets API**

### 4.3 Create Service Account

1. Go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **Service account**
3. Name: `n8n-integration`
4. Click **Create and Continue**
5. Skip the optional steps, click **Done**

### 4.4 Create Key File

1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **Add Key** → **Create new key**
4. Select **JSON**
5. Click **Create** (downloads the key file)
6. **Keep this file secure** - you'll need it for n8n

### 4.5 Share Resources with Service Account

The service account has an email like: `n8n-integration@your-project.iam.gserviceaccount.com`

**Share Google Drive folder:**
1. Right-click the `Call Transcripts` folder
2. Click **Share**
3. Add the service account email
4. Set permission to **Editor**

**Share Google Sheets:**
1. Open `Call Notes Data` spreadsheet
2. Click **Share**
3. Add the service account email
4. Set permission to **Editor**

---

## Step 5: Configure n8n Credentials

### Google Sheets Credential

1. In n8n, go to **Credentials** → **Add Credential**
2. Search for **Google Sheets API**
3. Select **Service Account**
4. Paste the contents of your JSON key file
5. Save

### Google Drive Credential

1. In n8n, go to **Credentials** → **Add Credential**
2. Search for **Google Drive API**
3. Select **Service Account**
4. Paste the contents of your JSON key file (same file)
5. Save

---

## Step 6: Configure Fireflies Integration

Set up Fireflies to upload transcripts to the Google Drive folder:
- Fireflies → Settings → Integrations → Google Drive
- Select the `Call Transcripts` folder
- Or use Fireflies API + n8n to push files

---

## IDs to Collect for n8n

| Item | ID |
|------|-----|
| Google Drive Folder ID | _________________________________ |
| Google Spreadsheet ID | _________________________________ |
| Service Account Email | _________________________________ |

---

## Troubleshooting

### "The caller does not have permission"
- Ensure the Google Drive folder and Sheets are shared with the service account email
- Check that APIs are enabled in Google Cloud Console

### "Quota exceeded"
- Google Sheets API has limits (100 requests per 100 seconds per user)
- Add delays between requests if processing many files

### Sheet not found
- Verify sheet names match exactly (case-sensitive)
- Use sheet names: `Consultants`, `Prompts`, `Skipped_Calls`, `Processing_Errors`
