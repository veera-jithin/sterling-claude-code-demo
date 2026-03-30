# Software Requirements Specification

## Email Job Extraction Agent

**Version:** 1.1
**Date:** 2026-03-30
**Project:** EAI Internship Demo — Sterling Demo

---

## 1. Introduction

### 1.1 Purpose

This document describes the software requirements for an automated email job extraction agent. The system monitors a Microsoft Outlook mailbox, reads incoming emails from construction/trade clients, and uses Gemini AI to extract structured job order information from each email.

### 1.2 Scope

The system connects to a Microsoft 365 mailbox via the Microsoft Graph API, exposes email access as MCP (Model Context Protocol) tools, and runs one Gemini API call per email to extract structured JSON job records.

### 1.3 Intended Users

- Land surveying / construction trade businesses receiving job order emails from builders
- Operations staff who need job data extracted into a structured format for downstream processing

---

## 2. System Overview

```
Microsoft 365 Mailbox
        │
        │  Microsoft Graph API (OAuth 2.0)
        ▼
   graph.py
        │
        ▼
  email_server.py (FastMCP server)
   ├── list_unread_emails
   ├── list_all_emails
   ├── get_latest_email_tool
   ├── get_email_thread
   ├── get_email_attachments
   └── mark_email_read
        │  stdio (MCP protocol)
        ▼
     main.py (MCP client + per-email loop)
        │  one Gemini call per email
        │  Google AI API
        ▼
  Gemini 2.5 Pro (`gemini-2.5-pro`)
        │
        ▼
  results.json (updated after each email)
```

---

## 3. Functional Requirements

### 3.1 Email Fetching

| ID    | Requirement                                                                                |
| ----- | ------------------------------------------------------------------------------------------ |
| FR-01 | System shall fetch unread emails from the configured mailbox inbox                         |
| FR-02 | System shall fetch all emails (read and unread) when running in bulk mode                  |
| FR-03 | System shall retrieve the full conversation thread for any email with a `conversationId` |
| FR-04 | System shall retrieve attachment content for emails where `hasAttachments` is true       |
| FR-05 | System shall mark emails as read after processing in unread/polling mode                   |
| FR-06 | System shall NOT mark emails as read during bulk (`--all`) extraction runs               |

### 3.2 Thread Deduplication

| ID    | Requirement                                                                                                |
| ----- | ---------------------------------------------------------------------------------------------------------- |
| FR-07 | System shall group emails by `conversationId` before processing                                          |
| FR-08 | For each conversation thread, system shall process only the most recent email                              |
| FR-09 | Older emails within the same thread shall be skipped — their content is quoted inline in the latest reply |

### 3.3 Job Extraction

| ID     | Requirement                                                                                                                                                                             |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-10  | System shall process emails sequentially — one Gemini API call per email, not batched or parallelised                                                                                  |
| FR-11  | System shall extract the following fields from each job order email:`builder_name`, `community`, `type_of_job`, `address`, `lot`, `block`                                   |
| FR-12  | System shall return multiple job objects if a single email contains multiple jobs                                                                                                       |
| FR-13  | System shall skip emails that contain no job information (return `[]`)                                                                                                                |
| FR-14  | Each extracted job shall include a `confidence` rating: `high`, `medium`, or `low`                                                                                              |
| FR-15  | Each extracted job shall include the `source_email_subject` field                                                                                                                     |
| FR-16  | System shall copy field values verbatim from the source — including all codes, numbers, punctuation, and bracketed content — without summarising, truncating, or dropping any portion |
| FR-16b | Fields marked N/A, not applicable, or absent shall be set to null                                                                                                                       |

### 3.4 HTML Processing

| ID    | Requirement                                                                                                  |
| ----- | ------------------------------------------------------------------------------------------------------------ |
| FR-17 | System shall strip `<style>`, `<script>`, and `<head>` tags from HTML email bodies                     |
| FR-18 | System shall strip inline CSS attributes (style, class, id, width, height, bgcolor, etc.) from all HTML tags |
| FR-19 | System shall preserve `<table>` HTML structure intact so Gemini can parse key-value layouts                |
| FR-20 | System shall insert newlines for block-level elements (`<p>`, `<div>`, `<br>`, `<h1>`–`<h6>`)     |
| FR-21 | System shall format list items (`<li>`, `<dt>`, `<dd>`) with a `\n- ` prefix                         |
| FR-22 | System shall normalize whitespace (collapse multiple spaces, limit to 2 consecutive newlines)                |
| FR-23 | System shall pass the full email body without truncation                                                     |

### 3.5 Output

| ID    | Requirement                                                                          |
| ----- | ------------------------------------------------------------------------------------ |
| FR-24 | `--output FILE` option: saves extracted jobs as JSON to the specified file path    |
| FR-25 | Output file shall be updated after each email is processed — not only at end of run |
| FR-26 | If a run fails mid-way, all jobs extracted before the failure shall already be saved |

### 3.6 Operating Modes

| ID    | Requirement                                                                                  |
| ----- | -------------------------------------------------------------------------------------------- |
| FR-27 | `--all` mode: single run on all emails in inbox, exits when done                           |
| FR-28 | `--once` mode: single run on unread emails only, exits when done                           |
| FR-29 | Default (polling) mode: continuously polls for unread emails at a configurable interval      |
| FR-30 | `POLL_INTERVAL_SECONDS` environment variable shall control polling interval (default: 60s) |

### 3.7 Logging

| ID    | Requirement                                                                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------- |
| FR-31 | System shall write a per-run prompt log to `logs/<timestamp>_<mode>.log`                                                   |
| FR-32 | Prompt logs shall include the full system prompt, every user message, every model response, all tool calls and their results |
| FR-33 | Each log entry shall be flushed to disk immediately (not buffered until end of run)                                          |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| ID     | Requirement                                                                 |
| ------ | --------------------------------------------------------------------------- |
| NFR-01 | HTML stripping shall reduce token count by at least 3x compared to raw HTML |
| NFR-02 | The system shall handle at least 25 emails per extraction cycle             |
| NFR-03 | Graph API calls shall use a 30-second timeout                               |

### 4.2 Security

| ID     | Requirement                                                                                                                |
| ------ | -------------------------------------------------------------------------------------------------------------------------- |
| NFR-04 | All credentials (API keys, Azure client secret, tokens) shall be stored in `.env` and never committed to version control |
| NFR-05 | `.env` and `.token_cache.json` shall be listed in `.gitignore`                                                       |
| NFR-06 | Microsoft Graph token cache shall be stored locally in `.token_cache.json`                                               |

### 4.3 Authentication

| ID     | Requirement                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------ |
| NFR-07 | System shall use OAuth 2.0 Authorization Code Flow for Microsoft Graph authentication                        |
| NFR-08 | Refresh tokens shall be cached locally and reused automatically (~90 day validity)                           |
| NFR-09 | One-time browser login shall be triggered via `python graph.py --login`                                    |
| NFR-10 | Gemini shall be accessed via Google AI API using a static API key                                            |
| NFR-11 | System shall use `ConfidentialClientApplication` (MSAL) — not `PublicClientApplication` — because the Azure app has a client secret registered |
| NFR-12 | System shall use Authorization Code Flow with a local redirect server on `http://localhost:8400` to capture the OAuth callback |
| NFR-13 | `http://localhost:8400` must be registered as a redirect URI in the Azure app registration (Authentication → Web platform) |

### 4.4 Azure App Registration Setup

The Azure app must be configured as follows for authentication to work:

**App type:** Confidential client (Web application) — do **not** enable "Allow public client flows"

**Required redirect URI:**
- Platform: **Web**
- URI: `http://localhost:8400`

**Required API permissions (Delegated):**
- `Mail.ReadWrite` — read and mark emails as read

**Why this matters:**
- The app has a client secret, making it a confidential client. Confidential clients use Authorization Code Flow, not Device Code Flow.
- Device Code Flow (`initiate_device_flow`) only works with `PublicClientApplication` and requires "Allow public client flows" to be enabled — loosening the security model unnecessarily.
- Auth Code Flow with a local redirect server is the correct, secure pattern: it opens the browser, the user logs in, Azure redirects to `http://localhost:8400` with the auth code, and the local server captures it to exchange for tokens.

---

## 5. Data Model

### 5.1 Extracted Job Object

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

### 5.2 Simplified Email Object (passed to Gemini)

```json
{
  "id": "string",
  "subject": "string",
  "from": "email@address.com",
  "receivedDateTime": "ISO 8601 string",
  "isRead": "boolean",
  "hasAttachments": "boolean",
  "conversationId": "string",
  "body": "plain text with table HTML preserved (no truncation)"
}
```

---

## 6. System Components

### 6.1 `graph.py` — Microsoft Graph API Client

- Wraps all Microsoft Graph REST API calls
- Manages MSAL token acquisition and caching
- Supports three auth modes: delegated (default), client credentials, hardcoded token
- Uses `/me/` endpoints (required for delegated personal account access)

### 6.2 `email_server.py` — MCP Server

- FastMCP server exposing 6 email tools over stdio
- Simplifies email payloads via `_simplify_email()` — passes full body without truncation
- Handles attachment content decoding (images as base64, PDFs noted, others UTF-8)
- Runs as a subprocess launched by `main.py`

### 6.3 `extractor.py` — HTML Processor

- Strips CSS/script noise from Outlook HTML email bodies
- Preserves table HTML structure for Gemini to parse
- Converts block elements to newlines for readable plain text

### 6.4 `main.py` — Agent Orchestrator

- Fetches emails via MCP, deduplicates by conversation thread
- Runs one Gemini API call per email with function-calling loop
- Saves results incrementally to output file after each email
- Manages prompt logging

---

## 7. External Dependencies

| Dependency          | Purpose                                         |
| ------------------- | ----------------------------------------------- |
| `google-genai`    | Gemini API client with function calling support |
| `mcp` (FastMCP)   | MCP server and client libraries                 |
| `msal`            | Microsoft Authentication Library for OAuth 2.0  |
| `requests`        | HTTP client for Graph API calls                 |
| `beautifulsoup4`  | HTML parsing and stripping                      |
| `python-dotenv`   | `.env` file loading                           |
| Google AI API       | Gemini 2.5 Pro model hosting (`gemini-2.5-pro`) |
| Microsoft Graph API | Email access (`Mail.ReadWrite` permission)    |

---

## 8. Environment Variables

| Variable                  | Required | Description                                  |
| ------------------------- | -------- | -------------------------------------------- |
| `GEMINI_API_KEY`        | Yes      | Google AI API key for Gemini access          |
| `AZURE_CLIENT_ID`       | Yes      | Azure app registration client ID             |
| `AZURE_CLIENT_SECRET`   | Yes      | Azure app registration secret                |
| `AZURE_TENANT_ID`       | No       | Azure tenant ID (not used in delegated flow) |
| `MAILBOX`               | Yes      | Outlook email address (login hint)           |
| `POLL_INTERVAL_SECONDS` | No       | Polling interval in seconds (default: 60)    |
| `MICROSOFT_GRAPH_TOKEN` | No       | Legacy hardcoded token fallback              |

---

## 9. Limitations and Known Constraints

- **Microsoft refresh tokens** expire after ~90 days of inactivity; requires re-running `python graph.py --login`
- **Personal MSA accounts** require `consumers` authority and do not support `$filter` + `$orderby` combined on Graph API
- **Graph API returns max 25 emails** per call in current configuration
- **Attachment handling**: images passed as base64, PDFs are noted but not decoded/parsed
- **Thread deduplication** is based on `conversationId` — emails without a conversationId are treated as standalone
- **Auth Code Flow requires port 8400 to be free** during login — if another process occupies the port, `python graph.py --login` will fail
- **Device Code Flow is not used** — the app is registered as a confidential client (has a secret), so `PublicClientApplication` and device code flow are not appropriate; Auth Code Flow with `ConfidentialClientApplication` is used instead
