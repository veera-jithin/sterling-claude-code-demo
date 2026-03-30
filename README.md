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
```

---

## Output

- **`res/results.json`** — extracted job orders, written incrementally after each email (partial runs are never lost)
- **`res/logs/<timestamp>_<mode>.log`** — full prompt log for each run: system prompt, every Gemini response, all tool calls and their results

---

## Project Structure

```
src/
  main.py          # CLI entry point + agentic Gemini loop
  email_server.py  # FastMCP server exposing email tools over stdio
  graph.py         # Microsoft Graph API client (OAuth 2.0)
  extractor.py     # HTML email body cleaner (strips CSS, preserves tables)
  config.py        # All configuration and .env loading

documentation/
  SRS.md           # Software Requirements Specification
  TESTING.md       # Test documentation

res/               # Runtime output (gitignored)
  results.json
  logs/
```
