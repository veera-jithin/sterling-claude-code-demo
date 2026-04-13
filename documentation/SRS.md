# Software Requirements Specification

## Email Job Extraction Agent

**Version:** 1.4
**Date:** 2026-04-12
**Project:** EAI Internship Demo — Sterling Demo

---

## 1. Introduction

### 1.1 Purpose

This document describes the requirements for an automated email job extraction agent. The system monitors a Microsoft Outlook mailbox, reads incoming emails from construction/trade clients, and uses an AI model to extract structured job order information from each email. Extracted jobs are surfaced through a web UI where operators can review, edit, and approve them before they are saved to a database.

### 1.2 Scope

The system connects to a Microsoft 365 mailbox via the Microsoft Graph API, runs an AI agent session to extract job data, and provides a real-time browser-based UI for human review. The AI agent autonomously decides how to read and interpret emails (including threads and attachments) before producing structured output.

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
   Email fetching + auth layer
        │
        ▼
   MCP email tools (list emails, get threads, get attachments, mark read)
        │  exposed to AI agent
        ▼
   AI Agent (Gemini 2.5 Pro)
   — calls email tools autonomously
   — extracts structured job records
        │
        ├──▶ results.json (file output)
        │
        └──▶ SQLite database (pending + approved jobs)
                │
                ▼
         Web Server (Flask + SocketIO)
          — real-time WebSocket updates
          — REST API for job approval
          — serves browser UI
                │
                ▼
         Browser UI (http://localhost:5000)
          — left panel: current email
          — right panel: extracted job cards
          — bottom: approved jobs table
```

---

## 3. Functional Requirements

### 3.1 Email Fetching

| ID    | Requirement                                                                                |
| ----- | ------------------------------------------------------------------------------------------ |
| FR-01 | System shall fetch unread emails from the configured mailbox inbox                         |
| FR-02 | System shall fetch all emails (read and unread) when running in bulk mode                  |
| FR-03 | System shall retrieve the full conversation thread for any email with a `conversationId`   |
| FR-04 | System shall retrieve attachment content for emails where `hasAttachments` is true         |
| FR-05 | System shall mark emails as read after processing in polling mode                          |
| FR-06 | System shall NOT mark emails as read during bulk (`--all`) extraction runs                 |

### 3.2 Thread Deduplication

| ID    | Requirement                                                                                                                             |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------- |
| FR-07 | Email lists shall deduplicate by `conversationId`, keeping only the most recent email per thread                                        |
| FR-08 | Emails without a `conversationId` shall be treated as standalone and always included                                                   |

### 3.3 Job Extraction

| ID     | Requirement                                                                                                                          |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| FR-09  | The AI agent shall autonomously call email tools to fetch, thread, and inspect emails before extracting jobs                         |
| FR-10  | System shall extract the following fields from each job order email: `builder_name`, `community`, `type_of_job`, `address`, `lot`, `block` |
| FR-11  | System shall return multiple job objects if a single email contains multiple jobs                                                    |
| FR-12  | System shall skip emails that contain no job information                                                                             |
| FR-13  | Each extracted job shall include a `confidence` rating: `high`, `medium`, or `low`                                                  |
| FR-14  | Each extracted job shall include the `source_email_subject` field                                                                   |
| FR-15  | Field values shall be copied verbatim from the source without summarising, truncating, or dropping any portion                       |
| FR-16  | Fields marked N/A or absent shall be set to null                                                                                     |

### 3.4 HTML Processing

| ID    | Requirement                                                                                                  |
| ----- | ------------------------------------------------------------------------------------------------------------ |
| FR-17 | System shall strip style, script, and head tags from HTML email bodies                                       |
| FR-18 | System shall strip inline CSS attributes from all HTML tags                                                  |
| FR-19 | System shall preserve table HTML structure so the AI model can parse key-value layouts                       |
| FR-20 | System shall convert block-level elements to newlines for readable plain text                                |
| FR-21 | System shall normalize whitespace (collapse multiple spaces, limit consecutive newlines)                     |
| FR-22 | System shall pass the full email body without truncation                                                     |

### 3.5 Output

| ID    | Requirement                                                                                  |
| ----- | -------------------------------------------------------------------------------------------- |
| FR-23 | System shall support an optional output file path for saving extracted jobs as JSON          |
| FR-24 | Output file shall be updated incrementally after each email is processed — not only at end   |
| FR-25 | If a run fails mid-way, all jobs extracted before the failure shall already be saved         |

### 3.6 Operating Modes

| ID    | Requirement                                                                                  |
| ----- | -------------------------------------------------------------------------------------------- |
| FR-26 | `--all` mode: single run on all emails in inbox, exits when done                             |
| FR-27 | `--once` mode: single run on unread emails only, exits when done                             |
| FR-28 | Default (polling) mode: continuously polls for unread emails at a configurable interval      |
| FR-29 | `POLL_INTERVAL_SECONDS` environment variable shall control polling interval (default: 60s)   |

### 3.7 Logging

| ID    | Requirement                                                                                                                      |
| ----- | -------------------------------------------------------------------------------------------------------------------------------- |
| FR-30 | System shall write a per-run prompt log with timestamp and mode identifier                                                       |
| FR-31 | Prompt logs shall include the full system prompt, every user message, every model response, and all tool calls                   |
| FR-32 | Each log entry shall be flushed to disk immediately to ensure no data is lost if process terminates                             |

### 3.8 Web UI — Functional Requirements

| ID    | Requirement                                                                                                                              |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| FR-33 | System shall provide a CLI flag that launches the web server alongside the extraction agent                                              |
| FR-34 | The web UI shall be accessible via localhost in a browser when the server is running                                                     |
| FR-35 | The UI shall display the email currently being processed, including subject, sender, date, read status, and body preview                  |
| FR-36 | The UI shall display clickable attachment links; PDFs and images shall open inline, other file types shall download                       |
| FR-37 | The UI shall display each extracted job as a card as soon as it is extracted — without requiring a page refresh                           |
| FR-38 | Each job card shall show all extracted fields: builder name, community, address, lot, block, job type, confidence, and source email       |
| FR-39 | Each job card shall have an **Edit** button that opens a modal for field-by-field editing                                                 |
| FR-40 | The edit modal shall require a non-empty "Editor's Notes" field before allowing save when any field has been changed                       |
| FR-41 | Each job card shall have an **Approve** button that saves the job to the database and removes it from the pending panel                   |
| FR-42 | Approving without prior edits shall not require editor notes                                                                              |
| FR-43 | The UI shall display a table of all approved jobs at the bottom, populated on page load and updated live on each approval                 |
| FR-44 | The approved jobs table shall support search/filter by builder name, community, and address                                               |
| FR-45 | The UI shall display a WebSocket connection status indicator (connected / connecting / disconnected)                                       |
| FR-46 | The UI shall display session statistics: total emails processed and total jobs approved                                                    |
| FR-47 | When a job is edited before approval, every changed field (old value, new value, editor) shall be recorded in an edit history table       |
| FR-48 | Approved jobs shall persist to a database across sessions                                                                                 |

### 3.9 Web UI — Design Requirements

| ID    | Requirement                                                                                                                         |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------- |
| DR-01 | The UI shall use a three-panel layout: current email (left), extracted jobs (right), approved jobs table (bottom, full-width)       |
| DR-02 | The header bar shall display the application title, WebSocket connection status, and session statistics                             |
| DR-03 | Connection status shall be colour-coded: green = connected, grey = connecting, red = disconnected                                   |
| DR-04 | Job cards shall use badge colour coding: yellow = Pending Review, blue = Edit Mode, green = Approved                                |
| DR-05 | Confidence levels shall be colour-coded on job cards: green = high, orange = medium, red = low                                     |
| DR-06 | The edit modal shall display all editable fields as labelled text inputs and include a required "Editor's Notes" textarea           |
| DR-07 | Empty extracted fields shall display as "—" rather than null or blank                                                               |
| DR-08 | The approved jobs section shall include search inputs for builder, community, and address                                           |
| DR-09 | The UI shall be usable on a standard 1280×800 desktop viewport without horizontal scrolling                                        |
| DR-10 | Real-time events (new email, new job, approval) shall update the UI immediately without requiring a manual refresh                  |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| ID     | Requirement                                                                 |
| ------ | --------------------------------------------------------------------------- |
| NFR-01 | HTML stripping shall reduce token count by at least 3x compared to raw HTML |
| NFR-02 | The system shall handle at least 25 emails per extraction cycle             |
| NFR-03 | Graph API calls shall use a 30-second timeout                               |

### 4.2 Security

| ID     | Requirement                                                                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------------------ |
| NFR-04 | All credentials (API keys, Azure client secret, tokens) shall be stored in `.env` and never committed to version control      |
| NFR-05 | All secret files (`.env`, token caches) shall be excluded from version control                                                |
| NFR-06 | Microsoft Graph token cache shall be stored locally and persist across sessions                                               |

### 4.3 Authentication

| ID     | Requirement                                                                                                                                     |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR-07 | System shall use OAuth 2.0 Authorization Code Flow for Microsoft Graph authentication                                                           |
| NFR-08 | Refresh tokens shall be cached locally and reused automatically (~90 day validity)                                                              |
| NFR-09 | System shall provide a mechanism to trigger one-time browser-based login                                                                        |
| NFR-10 | Gemini shall be accessed via Google AI API using a static API key                                                                               |
| NFR-11 | OAuth implementation must use confidential client pattern (with client secret)                                                                  |
| NFR-12 | System shall capture the OAuth redirect on a local HTTP server                                                                                  |
| NFR-13 | The localhost redirect URI used by the system must be registered in the Azure app's Web platform configuration                                  |

---

## 5. Microsoft Account Authentication Setup

### 5.1 Azure App Registration

Before running the system for the first time, an Azure App Registration must be created to define the identity the system uses to access the Microsoft Graph API.

**Required outcomes:**

- App must support **personal Microsoft accounts only** (not work/school accounts)
  - The monitored mailbox is a personal Outlook/Hotmail account
  - Work/school accounts use different authentication authority and cannot access personal mailboxes
- App must be configured as a **web application** with a redirect URI to localhost
  - System will capture OAuth redirect on a local HTTP server during authentication
- App must have a **client secret** generated and stored securely in `.env`
  - Presence of client secret makes this a confidential client (required for Authorization Code Flow)
- App must be granted **`Mail.ReadWrite` delegated permission**
  - `Mail.Read` is insufficient because system marks emails as read after processing
  - Permission requires user consent during first login

### 5.2 Authentication Flow

The system uses **OAuth 2.0 Authorization Code Flow** (not Device Code Flow) because the app has a client secret, making it a confidential client.

**First-time authentication requirements:**
- System must open browser to Microsoft login page
- User signs in with their personal Microsoft account
- Azure redirects to localhost with authorization code
- System must run a local HTTP server to capture the OAuth redirect
- Authorization code is exchanged for access and refresh tokens
- Tokens must be cached locally for reuse

**Subsequent runs:**
- System must use cached refresh token silently without browser interaction
- Refresh tokens remain valid for approximately 90 days of inactivity
- If token expires or cache is deleted, first-time authentication flow must be repeated

### 5.3 Required Environment Variables for Authentication

The following values must be present in `.env`:

- `AZURE_CLIENT_ID` — Application (client) ID from Azure app registration
- `AZURE_CLIENT_SECRET` — Client secret value generated during app registration
- `MAILBOX` — Email address of the monitored mailbox (used as login hint)

---

## 6. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google AI API key for Gemini access |
| `AZURE_CLIENT_ID` | Yes | Azure app registration client ID |
| `AZURE_CLIENT_SECRET` | Yes | Azure app registration secret |
| `MAILBOX` | Yes | Outlook email address (used as login hint) |
| `POLL_INTERVAL_SECONDS` | No | Polling interval in seconds (default: 60) |
| `AZURE_TENANT_ID` | No | Not used for personal MSA accounts |
| `MICROSOFT_GRAPH_TOKEN` | No | Legacy dev-only fallback token |

---

## 7. Data Model

### 7.1 Extracted Job Object

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

### 7.2 Database Schema Requirements

The system must persist data across three conceptual tables:

**Pending jobs** — jobs awaiting human review:
- Must store all extracted job fields (builder name, community, address, lot, block, job type)
- Must store extraction metadata (confidence level, confidence reason, source email subject, extraction timestamp)
- Must store complete email context for UI display (email subject, sender, body, attachment metadata)
- Must support querying all pending jobs for initial UI page load
- Must support deletion when a job is approved (moved to approved table)

**Approved jobs** — final approved records:
- Must store all job fields in their final state (after any human edits)
- Must store original extracted values for audit purposes
- Must store approval metadata (timestamp, approver identity if applicable)
- Must store editor notes if job was edited before approval
- Must persist indefinitely across sessions
- Must support search/filter by builder name, community, and address

**Edit history** — per-field audit trail:
- Must record every field modification made during review
- Each edit record must capture: field name, old value, new value, editor identity, timestamp
- Must be linked to the corresponding approved job
- Multiple edit records may exist for a single approved job if multiple fields were changed

### 7.3 Web UI API Requirements

The web UI must communicate with the backend through a combination of request/response and real-time updates:

**Initial data loading:**
- UI must be able to request all pending jobs when page first loads
- UI must be able to request all approved jobs when page first loads
- Response must include all job fields plus metadata needed for display

**Job review actions:**
- UI must be able to submit field edits for a pending job
  - If any field is changed, editor notes must be required and included
  - Backend must validate that notes are non-empty when fields have been modified
- UI must be able to approve a job (moving it from pending to approved)
  - If job was previously edited, approval must include the editor notes
  - If job was not edited, approval must not require notes

**Real-time updates:**
- Backend must broadcast updates to all connected clients when:
  - A new email begins processing (show current email in UI)
  - A new job is extracted (add job card to pending panel immediately)
  - A job is approved (remove from pending, add to approved table)
- UI must display connection status (connected / connecting / disconnected)
- Updates must not require manual page refresh

**Search and filtering:**
- UI must support filtering approved jobs by:
  - Builder name (partial text match)
  - Community (partial text match)
  - Address (partial text match)

---

## 8. Initial Setup Requirements

Before the system can run, the following setup must be completed:

**Python environment:**
- System must run in an isolated Python virtual environment
- All dependencies must be installable from a requirements file
- Virtual environment must not be committed to version control

**Authentication:**
- User must authenticate with Microsoft once before first extraction run
- Authentication must open a browser for user login
- Successful authentication must cache tokens locally for automatic reuse
- Token cache must persist across sessions until expiration (~90 days)
- Re-authentication must be possible by running authentication flow again

**Configuration:**
- All secrets and credentials must be stored in `.env` file
- `.env` file must never be committed to version control
- A template `.env.example` must be provided showing all required variables
- System must validate that all required environment variables are present before starting

**Runtime directories:**
- System must create output directories if they don't exist
- All runtime output (results, logs, database) must be stored outside version control

---

## 9. Limitations and Known Constraints

- Microsoft refresh tokens expire after approximately 90 days of inactivity; requires re-authentication
- Personal Microsoft accounts do not support combining filter and sort operations in a single Graph API request — sorting must be done client-side
- Graph API has a maximum email return limit per request
- Authorization Code Flow requires the OAuth redirect port to be available during authentication
- Device Code Flow cannot be used because the app has a client secret (confidential client)
