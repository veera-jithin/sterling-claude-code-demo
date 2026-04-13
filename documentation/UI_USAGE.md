# Web UI Usage Guide

## Overview

The Email Job Extraction Agent now includes a real-time web interface for monitoring email processing, reviewing extracted jobs, and approving them to a database.

## Starting the UI

Launch the agent with the `--ui` flag:

```bash
python src/main.py --ui
```

This will:
1. Start the extraction agent (in default polling mode)
2. Launch the web server on http://localhost:5000
3. Begin processing emails automatically

You can combine `--ui` with other modes:

```bash
# UI + process all emails once
python src/main.py --ui --all

# UI + process unread emails once
python src/main.py --ui --once

# UI + continuous polling (default)
python src/main.py --ui
```

## Accessing the UI

Open your browser and navigate to:

```
http://localhost:5000
```

## UI Layout

### Three Main Sections:

1. **Left Panel - Current Email**
   - Displays the email currently being processed
   - Shows subject, sender, date, read status
   - Email body preview (first 500 characters)
   - Clickable attachment links

2. **Right Panel - Extracted Jobs**
   - Shows jobs extracted from emails in real-time
   - Each job appears as a card with all extracted fields
   - Jobs start in "Pending Review" state with yellow badge
   - Two action buttons per job: **Edit** and **Approve**

3. **Bottom Section - Approved Jobs Database**
   - Table view of all approved jobs
   - Search functionality (by builder, community, address)
   - Shows approval timestamp and editor notes
   - Refresh button to reload data

## Workflow

### 1. Real-Time Extraction
As the agent processes emails:
- New emails appear in the left panel automatically
- Extracted jobs appear in the right panel
- No manual refresh needed - updates are live via WebSocket

### 2. Review & Edit Jobs

**To Edit a Job:**
1. Click the **Edit** button on any job card
2. Modal opens with all editable fields:
   - Builder Name
   - Community
   - Address
   - Lot
   - Block
   - Job Type
3. Make your changes
4. **Required:** Enter "Editor's Notes" explaining what was changed and why
5. Click **Save Changes**

**Example Editor's Notes:**
```
Corrected lot number from 29/1 to 29 based on PDF attachment
Fixed address: added missing street suffix "Ln"
```

### 3. Approve Jobs

**Direct Approval (No Edits):**
1. Click **Approve** button on job card
2. Job is immediately saved to database
3. Job card disappears from right panel
4. Job appears in database table at bottom

**Approval After Edit:**
1. Edit the job (follow edit workflow above)
2. After saving edits, job returns to pending state
3. Click **Approve** to save to database
4. Edit history is automatically tracked

## Database Features

### Search & Filter
Use the search inputs at the top of the database section:
- **Builder**: Search by builder name (partial match)
- **Community**: Search by community name (partial match)
- **Address**: Search by address (partial match)

Click **Search** to filter results, **Refresh** to clear filters.

### Database Schema
Each approved job includes:
- All extracted fields (builder, community, address, lot, block, job type)
- Confidence rating and reason
- Source email subject
- Editor notes (if edited before approval)
- Approval timestamp
- Approved by (defaults to "user")
- Original extraction (stored for audit trail)

### Edit History Tracking
When a job is edited before approval:
- Each changed field is logged in `edit_history` table
- Records: field name, old value, new value, timestamp, editor
- Can be queried via API: `GET /api/jobs/{job_id}/history`

## Status Indicators

**Connection Status (top right):**
- Green dot + "Connected" = WebSocket active, receiving updates
- Gray dot + "Connecting..." = Attempting connection
- Red dot + "Disconnected" = No connection, no real-time updates

**Statistics (top right):**
- **Processed**: Total emails processed in this session
- **Approved**: Total jobs approved to database (persists across sessions)

**Job Status Badges:**
- Yellow "Pending Review" = Awaiting approval
- Blue "Edit Mode" = Currently being edited (only visible to editor)
- Green "Approved" = Saved to database (only shown in database table)

## API Endpoints

The UI communicates with these backend endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs` | GET | Get all approved jobs |
| `/api/jobs/search?builder=X&community=Y&address=Z` | GET | Search approved jobs |
| `/api/jobs/{id}/history` | GET | Get edit history for a job |
| `/api/jobs/approve` | POST | Approve a job and save to database |

## Database Location

SQLite database is stored at:
```
res/jobs.db
```

This file is created automatically on first approval and persists across sessions.

## Troubleshooting

**UI won't load:**
- Check that the server started successfully (look for "Starting web UI on http://0.0.0.0:5000" in logs)
- Verify no other service is using port 5000

**No real-time updates:**
- Check connection status indicator (top right)
- Ensure WebSocket connection succeeded (check browser console for errors)
- Try refreshing the page

**Jobs not appearing:**
- Verify the agent is running and processing emails
- Check main.py logs for extraction messages
- Ensure emails contain job order data

**Can't approve without editor notes:**
- Editor notes are required after editing a job
- Notes should explain what was changed and why
- Direct approval (no edits) does not require notes

## Architecture

```
main.py (--ui flag)
    ↓
Launches Flask + SocketIO in background thread
    ↓
Extraction loop broadcasts events:
    - email_processing (left panel)
    - job_extracted (right panel)
    - job_approved (database table)
    ↓
UI receives WebSocket events
    ↓
User reviews, edits, approves
    ↓
database.py saves to SQLite
```

## Next Steps

- Add user authentication (currently defaults to "user")
- Export approved jobs to CSV/Excel
- Bulk approval workflow
- Job templates for common extraction patterns
- Email attachment viewer (inline PDFs)
