# Sterling Email Job Extraction Agent

Automated agent that monitors a Microsoft 365 mailbox and uses Gemini 2.5 Pro to extract structured job order data from construction/trade client emails.

---

## How It Works

The system runs a single agentic Gemini session per extraction cycle. Rather than fetching emails in Python and feeding them to the model, the model drives the process itself using MCP (Model Context Protocol) tools:

```
CLI arg (--all / --once / polling)
         │
         ▼
Gemini receives instruction + 7 available tools
         │
         ▼
Gemini calls list_unread_emails or list_all_emails
         │  (server-side deduplicated — 1 email per thread, newest only)
         ▼
For each email, Gemini decides:
   ├── hasAttachments = true  →  call get_email_attachments
   │        └── PDFs passed as inline binary directly to Gemini
   └── job info present       →  call extract_jobs
            └── no job info   →  skip
         │
         ▼
extract_jobs returns structured JSON → written to results.json immediately
         │
         ▼
Gemini calls mark_email_read (polling / --once mode only)
         │
         ▼
Repeat for next email until no more tool calls
```

### Tools available to Gemini

| Tool | Purpose |
|---|---|
| `list_unread_emails` | Fetch unread emails (deduplicated by thread) |
| `list_all_emails` | Fetch all emails (deduplicated by thread) |
| `get_latest_email_tool` | Fetch the single most recent email |
| `get_email_thread` | Fetch all messages in a conversation thread |
| `get_email_attachments` | Fetch attachment content for an email |
| `mark_email_read` | Mark an email as read |
| `extract_jobs` | Return structured job order JSON from email content |

### Extracted fields

Each job order produces:

```json
{
  "builder_name": "string | null",
  "community": "string | null",
  "type_of_job": "string | null",
  "address": "string | null",
  "lot": "string | null",
  "block": "string | null",
  "confidence": "high | medium | low",
  "confidence_reason": "string",
  "source_email_subject": "string"
}
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your credentials
```

### Required environment variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google AI API key |
| `AZURE_CLIENT_ID` | Azure app registration client ID |
| `AZURE_CLIENT_SECRET` | Azure app registration secret |
| `MAILBOX` | Outlook email address to monitor |
| `POLL_INTERVAL_SECONDS` | Polling interval in seconds (default: 60) |

---

## Authentication

One-time browser login to authorise Microsoft Graph access:

```bash
python src/graph.py --login
```

This caches a refresh token locally (~90 day validity). Re-run if authentication expires.

---

## Usage

```bash
# Poll continuously for new unread emails (default)
python src/main.py

# Single run on unread emails, then exit
python src/main.py --once

# Bulk run on all emails in inbox, then exit
python src/main.py --all

# Custom output path (default: res/results.json)
python src/main.py --all --output res/results.json

# Launch with web UI for real-time review and approval
python src/main.py --ui

# Combine UI with other modes
python src/main.py --ui --all
python src/main.py --ui --once
```

---

## Output

- **`res/results.json`** — extracted job orders, written incrementally after each email (partial runs are never lost)
- **`res/logs/<timestamp>_<mode>.log`** — full prompt log for each run: system prompt, every Gemini response, all tool calls and their results
- **`res/jobs.db`** — SQLite database for approved jobs (created when using `--ui` flag)

---

## Web UI

Launch the web interface for real-time job review and approval:

```bash
python src/main.py --ui
```

Access at: **http://localhost:5000**

### Features:
- **Real-time email monitoring** — see emails as they're processed
- **Live job extraction** — extracted jobs appear immediately without page refresh
- **Edit & approve workflow** — review, edit fields, add notes, and approve to database
- **Search & filter** — find approved jobs by builder, community, or address
- **Audit trail** — tracks all field edits with timestamp and editor notes
- **WebSocket updates** — all changes broadcast instantly to connected clients

See [UI_USAGE.md](documentation/UI_USAGE.md) for detailed usage guide.

---

## Project Structure

```
src/
  main.py          # CLI entry point + agentic Gemini loop + web UI launcher
  email_server.py  # FastMCP server exposing email tools over stdio
  graph.py         # Microsoft Graph API client (OAuth 2.0)
  extractor.py     # HTML email body cleaner (strips CSS, preserves tables)
  config.py        # All configuration and .env loading
  web_server.py    # Flask + SocketIO server for web UI
  database.py      # SQLite persistence layer for jobs and edit history

  static/          # Web UI frontend
    index.html     # Main UI layout
    app.js         # JavaScript for WebSocket and DOM updates
    style.css      # UI styling

  tests/           # Test suite
    test_smoke.py              # Smoke tests
    test_extractor.py          # Unit tests for HTML extractor
    test_graph.py              # Unit tests for Graph API client
    test_database.py           # Unit tests for database operations
    test_email_server.py       # Unit tests for MCP email tools
    test_web_server.py         # Unit tests for web server endpoints
    test_integration_graph.py  # Integration tests for Graph API
    test_integration_extraction.py  # Integration tests for Gemini extraction

documentation/
  SRS.md           # Software Requirements Specification
  TESTING.md       # Test documentation
  UI_USAGE.md      # Web UI usage guide

res/               # Runtime output (gitignored)
  results.json
  jobs.db
  logs/
```
