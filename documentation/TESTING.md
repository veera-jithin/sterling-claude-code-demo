# TESTING.md

## Overview

Tests are written at three levels — smoke, unit, and integration — and only
after functionality has been verified working end-to-end. All tests live in
`src/tests/`. Unit tests mock all external calls; no real network requests are
made unless running integration tests.

**Current test coverage:** 65 tests across smoke, unit, and integration levels.

---

## Test Types

### Smoke Tests (`test_smoke.py`)
Confirm that all modules import cleanly and core objects can be instantiated.
No assertions on logic — just validates basic wiring. Runs in under 1 second.

### Unit Tests (`test_extractor.py`, `test_graph.py`, `test_database.py`, `test_email_server.py`, `test_web_server.py`)
Test individual classes and methods in isolation. All external calls (HTTP,
MSAL, file I/O) are mocked using `pytest-mock` and `unittest.mock`.

- **`test_extractor.py`**: Tests every behaviour of `HtmlExtractor` — noise
  removal, table HTML preservation, block-to-newline conversion, list item
  formatting, whitespace normalisation, and edge cases.
- **`test_graph.py`**: Tests `GraphClient` fetch/filter/mark-read logic, auth
  header construction, error propagation on non-2xx responses, and both auth
  providers (`HardcodedTokenAuthProvider`, mock of `DelegatedAuthProvider`).
- **`test_database.py`**: Tests database CRUD operations for pending and approved
  jobs, edit history tracking, search/filter functionality, and constraint validation.
- **`test_email_server.py`**: Tests MCP email tool implementations including
  list emails, get thread, get attachments, mark as read, and thread deduplication.
- **`test_web_server.py`**: Tests Flask REST endpoints, WebSocket event broadcasting,
  job approval workflow, and request validation.

### Integration Tests (`test_integration_graph.py`, `test_integration_extraction.py`)
Test real interactions with external services using live credentials.

- **`test_integration_graph.py`**: Real Graph API calls — fetch all/unread emails,
  thread ordering, attachment retrieval. Read-only; does not modify mailbox state.
  Requires `.token_cache.json` (run `python src/graph.py --login` first).
- **`test_integration_extraction.py`**: Real Gemini API calls using fixed sample
  emails. Verifies extraction schema, field accuracy, empty-list for non-job emails,
  and multi-job extraction. Requires `GEMINI_API_KEY` in `.env`.

---

## Test Files

| File | Type | What it tests | Notes |
|---|---|---|---|
| `test_smoke.py` | Smoke | All module imports, basic instantiation | No external calls |
| `test_extractor.py` | Unit | `HtmlExtractor` — HTML stripping, table preservation, whitespace | No dependencies |
| `test_graph.py` | Unit | `GraphClient` — fetch, filter, mark-read, auth, error handling | Mocks `requests.get/patch` |
| `test_database.py` | Unit | Database CRUD, edit history, search/filter, constraints | Uses in-memory SQLite |
| `test_email_server.py` | Unit | MCP email tools, thread deduplication, attachments | Mocks Graph API client |
| `test_web_server.py` | Unit | Flask endpoints, WebSocket events, approval workflow | Mocks database layer |
| `test_integration_graph.py` | Integration | Real Graph API — fetch, thread ordering, attachments | Requires `.token_cache.json` |
| `test_integration_extraction.py` | Integration | Real Gemini API — schema, field accuracy, multi-job, empty result | Requires `GEMINI_API_KEY` |

---

## Running Tests

```bash
# Activate venv first
source venv/bin/activate

# All tests
pytest

# By marker
pytest -m smoke
pytest -m unit
pytest -m integration

# Verbose output
pytest -v

# Specific file
pytest src/tests/test_extractor.py -v
```

---

## Known Gaps / TODO

- **`main.py` unit tests** — Extraction loop orchestration, CLI argument parsing,
  and mode switching logic not yet covered
- **Web UI frontend tests** — JavaScript WebSocket handling and DOM manipulation
  not yet tested (currently manual testing only)
- **Gemini 503 retry logic** — The extractor currently returns `[]` on 503;
  a retry with exponential backoff should be added and tested
- **Integration test for full workflow** — End-to-end test covering email fetch →
  extraction → web UI broadcast → database save not yet implemented
