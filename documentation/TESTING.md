# TESTING.md

## Overview

Tests are written at three levels — smoke, unit, and integration — and only
after functionality has been verified working end-to-end. All tests live in
`src/tests/`. Unit tests mock all external calls; no real network requests are
made unless running integration tests.

---

## Test Types

### Smoke Tests (`test_smoke.py`)
Confirm that all modules import cleanly and core objects can be instantiated.
No assertions on logic — just validates basic wiring. Runs in under 1 second.

### Unit Tests (`test_extractor.py`, `test_graph.py`)
Test individual classes and methods in isolation. All external calls (HTTP,
MSAL) are mocked using `pytest-mock` and `unittest.mock`.

- **`test_extractor.py`**: Tests every behaviour of `HtmlExtractor` — noise
  removal, table HTML preservation, block-to-newline conversion, list item
  formatting, whitespace normalisation, and edge cases.
- **`test_graph.py`**: Tests `GraphClient` fetch/filter/mark-read logic, auth
  header construction, error propagation on non-2xx responses, and both auth
  providers (`HardcodedTokenAuthProvider`, mock of `DelegatedAuthProvider`).

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

- **`email_server.py` unit tests** — MCP tool wiring not yet tested in isolation
- **`main.py` unit tests** — extraction loop, thread deduplication logic, and
  incremental save behaviour not yet covered
- **Gemini 503 retry logic** — the extractor currently returns `[]` on 503;
  a retry with backoff should be added and tested
