"""
Configuration module for the Email Job Extraction Agent.

Loads secrets from .env and exposes all configurable values as module-level
constants. All other modules must import config values from here — no direct
os.getenv() calls elsewhere in the codebase.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Secrets (loaded from .env, never committed) ---

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
AZURE_CLIENT_ID: str = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET: str = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID: str = os.getenv("AZURE_TENANT_ID", "")
MAILBOX: str = os.getenv("MAILBOX", "")

# Legacy fallback: hardcoded Graph API token (optional, for dev use only)
MICROSOFT_GRAPH_TOKEN: str = os.getenv("MICROSOFT_GRAPH_TOKEN", "")

# --- Configurable values (overridable via .env) ---

POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
MAX_THREAD_LENGTH: int = int(os.getenv("MAX_THREAD_LENGTH", "10"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Microsoft Graph API ---

GRAPH_API_BASE_URL: str = "https://graph.microsoft.com/v1.0"
GRAPH_API_TIMEOUT_SECONDS: int = 30
# App is MSA-only (personal accounts) — must use the /consumers endpoint
MSAL_AUTHORITY: str = "https://login.microsoftonline.com/consumers"
# offline_access is reserved — MSAL adds it automatically, must not be passed explicitly
# Full URL scope required for personal MSA (outlook.com) accounts
MSAL_SCOPES: list[str] = ["https://graph.microsoft.com/Mail.ReadWrite"]
TOKEN_CACHE_PATH: str = ".token_cache.json"
# Redirect URI for auth code flow — must be registered in the Azure app under Authentication → Web
OAUTH_REDIRECT_URI: str = "http://localhost:8400"

# --- Gemini ---

GEMINI_MODEL: str = "gemini-2.5-pro"

# --- Output ---

DEFAULT_OUTPUT_PATH: str = "res/results.json"
LOG_DIR: str = "res/logs"
