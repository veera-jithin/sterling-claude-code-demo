# CLAUDE.md

This file defines coding standards and behavioral expectations for Claude Code on this project.
Follow these guidelines in all code written or modified.

---

## Project Structure

```
project-root/
├── CLAUDE.md                  # project rules (this file) — stays at root
├── README.md                  # repo readme — stays at root
├── requirements.txt           # pinned dependencies (Python) — stays at root
├── pytest.ini                 # test framework config — stays at root
├── .env                       # secrets — never committed
├── .env.example               # secrets template — committed
├── .gitignore
│
├── src/                       # all application source code
│   ├── config.py              # configuration loader
│   ├── <module>.py            # application modules
│   └── tests/                 # all tests live inside src/
│       ├── conftest.py        # test configuration (adds src/ to sys.path)
│       ├── test_smoke.py      # smoke tests
│       └── test_<module>.py   # unit/integration tests
│
├── output/                    # runtime output and logs (gitignored)
│   ├── data/                  # generated data files
│   └── logs/                  # application logs
│
└── documentation/             # all project docs except CLAUDE.md and README.md
    ├── SRS.md                 # software requirements specification
    └── TESTING.md             # testing documentation
```

Rules:
* All source files go in `src/` — never in root
* All tests go in `src/tests/` — never alongside source files or in root
* All `.md` docs go in `documentation/` — except `CLAUDE.md` and `README.md` which stay at root
* All runtime output (results, logs, generated data) goes in a gitignored output directory
* Output directory is created at runtime if it doesn't exist — never committed

---

## General Principles

* Write code for the next developer, not just for the machine
* Prefer simple and explicit over clever and implicit
* If a function is doing two things, split it
* Delete code that isn't used — don't comment it out and leave it
* Don't over-engineer. Solve the problem in front of you, not the hypothetical future one

---

## Code Style

* Follow **PEP 8**
* Use **type hints** on all function signatures
* Max line length: **100 characters**
* Use `snake_case` for variables and functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
* Name functions as verbs: `fetch_data()`, `parse_response()`, `process_item()`
* Name booleans as predicates: `is_valid`, `has_children`, `was_processed`
* Avoid abbreviations unless they are universally understood (`url`, `id`, `csv` are fine; `proc`, `tmp`, `val` are not)

---

## Functions and Classes

* Functions should do one thing
* Keep functions under ~30 lines; if longer, consider breaking them up
* No more than 3–4 positional parameters — use a dataclass or dict beyond that
* Avoid deep nesting; use early returns to flatten logic
* **Prefer classes over loose functions** whenever a concept has state, multiple related behaviors, or is likely to grow — if in doubt, use a class
* Use abstraction (base classes, ABCs, interfaces) wherever a concept has multiple implementations or may need to be swapped out — don't wait until refactor time
* Classes should represent a clear concept, not just be a container for unrelated functions

---

## Error Handling

* Always handle exceptions at the right level — not too early, not too late
* Never silently swallow exceptions with a bare `except: pass`
* Use specific exception types, not bare `except Exception`
* Log errors with enough context to diagnose them without a debugger
* External calls (APIs, databases, file I/O) must always be wrapped in try/except

---

## Logging

* Use Python's built-in `logging` module — never use `print()` for runtime output
* Log levels: `DEBUG` for dev detail, `INFO` for normal operations, `WARNING` for recoverable issues, `ERROR` for failures
* Every log message should answer: what happened, where, and (if an error) why
* Never log secrets, credentials, or raw PII

---

## Configuration and Secrets

* **Two-layer config system:**
  * `config.py` — all configurable values (timeouts, intervals, model names, feature flags, defaults, etc.). This file is committed to git.
  * `.env` — secrets and environment-specific values only (API keys, credentials, connection strings). This file is never committed.
* `config.py` loads `.env` at runtime via `python-dotenv` and exposes a single clean interface for the rest of the codebase to import from
* No other file should read from `os.environ` or `os.getenv` directly — all config access goes through `config.py`
* Never hardcode credentials, API keys, URLs, or magic strings anywhere in code — if it's configurable, it lives in `config.py`
* `.env` must be in `.gitignore` — always
* Provide a `.env.example` with all required keys and placeholder values, committed to git
* Example pattern:
  ```python
  # config.py
  from dotenv import load_dotenv
  import os

  load_dotenv()

  # Secrets — loaded from .env
  API_KEY: str = os.getenv("API_KEY")
  DATABASE_URL: str = os.getenv("DATABASE_URL")
  SECRET_TOKEN: str = os.getenv("SECRET_TOKEN")

  # Configurable values — defaults defined here, overridable via .env
  POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", 60))
  MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", 3))
  LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
  ```

---

## Environment Setup

* **Always use a virtual environment** — never install packages into the global Python environment
* Create and activate venv before doing anything else:
  ```bash
  python -m venv venv
  source venv/bin/activate        # Mac/Linux
  venv\Scripts\activate           # Windows
  ```
* The `venv/` directory must be in `.gitignore` — never commit it

## Dependencies

* **Pin exact versions** for all dependencies in `requirements.txt` — use `==` not `>=`
* Every time a new package is installed, immediately update `requirements.txt`:
  ```bash
  pip install some-package
  pip freeze > requirements.txt   # always do this after every install
  ```
* `requirements.txt` is always committed to git and kept up to date — it is the source of truth for the environment
* To recreate the environment from scratch:
  ```bash
  python -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```
* Don't add a library for something that's easy to implement in stdlib
* If adding a new dependency, add a comment in `requirements.txt` above it explaining why it's needed:
  ```
  # HTTP client for external API calls
  requests==2.31.0
  ```

---

## Testing

* **Do not write tests speculatively.** Only write tests after the functionality has been verified working end-to-end
* Once verified, write tests at three levels in order:
  * **Smoke tests** — does the thing run without crashing? Minimal assertions, just confirms basic wiring
  * **Unit tests** — test individual functions/methods in isolation with mocked dependencies
  * **Integration tests** — test real interactions between components (e.g. API client + real service, database layer + real database)
* Test file naming: `test_<module>.py`; integration tests: `test_integration_<feature>.py`
* Each test should test one thing and have a descriptive name: `test_returns_null_when_field_missing`
* Mock all external calls (APIs, DB) in unit tests — unit tests must not make real network requests
* After writing tests, **update `TESTING.md`** to document what each test file covers, what type of test it is, any setup required, and how to run it

---

## Comments and Documentation

* Write comments to explain  **why** , not **what** — the code explains what
* Every module must have a **module-level docstring** describing its purpose, main classes/functions it exposes, and any important usage notes
* Every public function and method must have a **function-level docstring** covering: what it does, its parameters (`Args:`), return value (`Returns:`), and exceptions it may raise (`Raises:`)
* Use Google-style docstrings consistently:
  ```python
  def fetch_records(since: datetime) -> list[Record]:
      """Fetch records from the data source since a given datetime.

      Args:
          since: Only return records created after this timestamp.

      Returns:
          A list of Record objects ordered by creation time.

      Raises:
          APIError: If the API request fails or returns a non-2xx status.
      """
  ```
* Don't leave TODO comments without a name and date: `# TODO(name YYYY-MM-DD): description of what needs to be done`

---

## Git Hygiene

* Commit messages: imperative mood, present tense — `Add data validation logic` not `Added...`
* One logical change per commit
* Never commit `.env`, secrets, or local IDE config files
* Branch naming: `feature/`, `fix/`, `chore/` prefixes

## Git Workflow — Claude's Responsibilities

**Before starting new functionality:**
* Recommend the user switch to a feature branch before writing any code:
  `git checkout -b feature/<short-description>`
* Explain that this makes the work easier to track, review, and revert

**After a feature is complete:**
* Only propose a commit after the functionality has been tested and explicitly accepted by the user
* Ask the user: *"Should I commit this?"* — do not commit without their agreement
* If they agree, show the full proposed commit message and ask: *"Anything to add or change before I commit?"*
* After they confirm the message, ask: *"Local commit only, or push to remote as well?"*
* Act on whichever they choose — do not push unless explicitly told to

**Starting a new project:**
* If the working directory is not a git repo, ask the user: *"Should I initialise a git repository for this project?"*
* If they agree, ask for the repo name and whether it should be public or private
* Run `git init`, create the initial commit, create the remote repo via `gh repo create`, and push
* From that point on, use the remote repo to track all work on this project

**Never:**
* Commit speculatively or silently
* Push without being asked
* Amend a previous commit without explicit instruction

---

## What Claude Should NOT Do

* Do not refactor code that wasn't asked about
* Do not add dependencies without being asked
* Do not change `.env` structure without flagging it explicitly
* Do not generate placeholder or stub code and leave it — either implement it or leave a clearly marked TODO
* Do not suppress errors to make tests pass
* Do not write tests for functionality that hasn't been verified working yet

---

## TESTING.md

After writing any tests, Claude must update `TESTING.md` in the project root with the following structure:

```markdown
# TESTING.md

## Overview
Brief description of the testing strategy for this project.

## Test Types

### Smoke Tests
What they cover and how to run them.

### Unit Tests
What they cover, what is mocked, and how to run them.

### Integration Tests
What they cover, what real services they touch, any required setup (env vars, credentials),
and how to run them.

## Test Files

| File | Type | What it tests | Notes |
|---|---|---|---|
| test_parser.py | Unit | Data parsing logic | Mocks external dependencies |
| test_api_client.py | Unit | API client module | Mocks HTTP layer |
| test_integration_workflow.py | Integration | End-to-end workflow | Requires API_KEY in .env |

## Running Tests

\`\`\`bash
# All tests
pytest

# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration
\`\`\`

## Known Gaps / TODO
List any areas not yet covered by tests.
```
