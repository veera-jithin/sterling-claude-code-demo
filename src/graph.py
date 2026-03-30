"""
Microsoft Graph API client for the Email Job Extraction Agent.

Handles OAuth 2.0 authentication via MSAL and all REST calls to the
Microsoft Graph /me/messages endpoint. Supports three auth modes:
  - delegated (default): browser-based login with cached refresh token
  - client credentials: app-only, no user login required
  - hardcoded token: legacy fallback for development

Run `python graph.py --login` once to complete the browser login and cache
the refresh token locally (~90 day validity).

Main class:
    GraphClient: wraps all Graph API calls with auth and error handling.
"""

import argparse
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import msal
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth providers (abstract base + concrete implementations)
# ---------------------------------------------------------------------------

class AuthProvider(ABC):
    """Abstract base for Microsoft Graph authentication providers."""

    @abstractmethod
    def get_access_token(self) -> str:
        """Return a valid access token for Microsoft Graph.

        Returns:
            A Bearer token string.

        Raises:
            RuntimeError: If a token cannot be obtained.
        """


class DelegatedAuthProvider(AuthProvider):
    """Authorization Code Flow using ConfidentialClientApplication with local token cache.

    Uses a local HTTP server on port 8400 to capture the OAuth redirect from
    Azure AD after the user authenticates in a browser. This is the correct flow
    for confidential client app registrations (those with a client secret).

    Auth flow on first run:
      1. initiate_auth_code_flow() → generates the login URL
      2. Browser is opened to that URL (user signs in)
      3. Azure redirects to http://localhost:8400 with the auth code
      4. Local server captures the code; acquire_token_by_auth_code_flow() exchanges it
      5. Tokens cached to TOKEN_CACHE_PATH; subsequent runs are silent (~90 day validity)

    Azure app registration requirement:
      - Add http://localhost:8400 as a redirect URI under Authentication → Web platform
    """

    _REDIRECT_PORT: int = 8400
    _REDIRECT_URI: str = f"http://localhost:{_REDIRECT_PORT}"

    def __init__(self) -> None:
        self._cache = self._load_cache()
        self._app = msal.ConfidentialClientApplication(
            client_id=config.AZURE_CLIENT_ID,
            client_credential=config.AZURE_CLIENT_SECRET,
            authority=config.MSAL_AUTHORITY,
            token_cache=self._cache,
        )

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing silently if possible.

        If no cached token exists, opens the browser for login and starts a
        local HTTP server on port 8400 to capture the OAuth redirect.

        Returns:
            Bearer token string.

        Raises:
            RuntimeError: If the auth code flow fails or the user denies access.
        """
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(config.MSAL_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]

        # No cached token — run auth code flow with local redirect server
        logger.info("No cached token found. Starting browser login.")
        return self._run_auth_code_flow()

    def _run_auth_code_flow(self) -> str:
        """Open the browser and capture the OAuth redirect on localhost:8400.

        Returns:
            Bearer token string.

        Raises:
            RuntimeError: If the flow fails or returns an error.
        """
        import webbrowser

        flow = self._app.initiate_auth_code_flow(
            scopes=config.MSAL_SCOPES,
            redirect_uri=self._REDIRECT_URI,
            login_hint=config.MAILBOX,
        )

        auth_url = flow["auth_uri"]
        print(f"\nOpening browser for login...\n{auth_url}\n", flush=True)
        webbrowser.open(auth_url)

        # Capture the redirect with a one-shot local HTTP server
        redirect_params = self._capture_redirect()

        result = self._app.acquire_token_by_auth_code_flow(flow, redirect_params)
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "unknown"))
            raise RuntimeError(f"Auth code flow failed: {error}")

        self._save_cache()
        return result["access_token"]

    def _capture_redirect(self) -> dict[str, str]:
        """Start a one-shot HTTP server that captures a single OAuth redirect.

        Listens on localhost:8400, parses the query string from the first
        incoming request, returns a success page to the browser, then shuts down.

        Returns:
            Dict of query parameters from the redirect (code, state, etc.).

        Raises:
            RuntimeError: If the server fails to start.
        """
        captured: dict[str, list[str]] = {}  # parse_qs produces lists; flattened on return

        class _RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                captured.update(parse_qs(parsed.query))
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Login successful. You can close this tab.</h2></body></html>"
                )

            def log_message(self, format: str, *args: object) -> None:
                # Suppress default HTTP server access logs
                pass

        server = HTTPServer(("localhost", self._REDIRECT_PORT), _RedirectHandler)
        logger.info("Waiting for OAuth redirect on http://localhost:%d ...", self._REDIRECT_PORT)
        server.handle_request()  # handles exactly one request then returns
        server.server_close()
        # parse_qs returns {'key': ['value']} — MSAL expects {'key': 'value'}
        return {k: v[0] for k, v in captured.items()}

    def _load_cache(self) -> msal.SerializableTokenCache:
        """Load the token cache from disk if it exists.

        Returns:
            A populated or empty SerializableTokenCache.
        """
        cache = msal.SerializableTokenCache()
        if os.path.exists(config.TOKEN_CACHE_PATH):
            with open(config.TOKEN_CACHE_PATH, "r") as file:
                cache.deserialize(file.read())
        return cache

    def _save_cache(self) -> None:
        """Persist the token cache to disk if it has changed."""
        if self._cache.has_state_changed:
            with open(config.TOKEN_CACHE_PATH, "w") as file:
                file.write(self._cache.serialize())


class HardcodedTokenAuthProvider(AuthProvider):
    """Legacy fallback auth using a static token from config.

    Only used for development when MICROSOFT_GRAPH_TOKEN is set.
    Tokens expire quickly — not suitable for production use.
    """

    def get_access_token(self) -> str:
        """Return the static token from config.

        Returns:
            Bearer token string.

        Raises:
            RuntimeError: If the token is not configured.
        """
        if not config.MICROSOFT_GRAPH_TOKEN:
            raise RuntimeError("MICROSOFT_GRAPH_TOKEN is not set in .env")
        return config.MICROSOFT_GRAPH_TOKEN


# ---------------------------------------------------------------------------
# Graph API client
# ---------------------------------------------------------------------------

class GraphClient:
    """Wraps Microsoft Graph /me/messages REST calls with auth and retries.

    Uses the /me/ endpoint which requires delegated (user) permissions.
    Personal MSA accounts do not support combining $filter and $orderby in
    a single request, so sorting is done client-side where needed.

    Args:
        auth_provider: The authentication provider to use. Defaults to
            DelegatedAuthProvider if not supplied.
    """

    def __init__(self, auth_provider: AuthProvider | None = None) -> None:
        if auth_provider is not None:
            self._auth = auth_provider
        elif config.MICROSOFT_GRAPH_TOKEN:
            # Dev convenience: use the hardcoded token if set
            self._auth = HardcodedTokenAuthProvider()
        else:
            self._auth = DelegatedAuthProvider()

    def fetch_unread_emails(self) -> list[dict[str, Any]]:
        """Fetch all unread emails from the inbox.

        Returns:
            List of email dicts ordered by receivedDateTime descending.

        Raises:
            requests.HTTPError: If the Graph API returns a non-2xx status.
        """
        # Personal MSA accounts don't support $filter + $orderby combined,
        # so we filter client-side after fetching by receivedDateTime.
        params = {
            "$orderby": "receivedDateTime desc",
            "$top": 25,
            "$select": (
                "id,subject,from,receivedDateTime,isRead,"
                "hasAttachments,conversationId,body"
            ),
        }
        emails = self._get_messages(params)
        return [e for e in emails if not e.get("isRead", True)]

    def fetch_all_emails(self) -> list[dict[str, Any]]:
        """Fetch all emails (read and unread) from the inbox.

        Returns:
            List of email dicts ordered by receivedDateTime descending.

        Raises:
            requests.HTTPError: If the Graph API returns a non-2xx status.
        """
        params = {
            "$orderby": "receivedDateTime desc",
            "$top": 25,
            "$select": (
                "id,subject,from,receivedDateTime,isRead,"
                "hasAttachments,conversationId,body"
            ),
        }
        return self._get_messages(params)

    def fetch_thread(self, conversation_id: str) -> list[dict[str, Any]]:
        """Fetch all emails in a conversation thread.

        Personal MSA accounts don't support $filter on conversationId, so
        we fetch recent messages and filter client-side.

        Args:
            conversation_id: The conversationId to match.

        Returns:
            List of email dicts in the thread, ordered oldest-first.

        Raises:
            requests.HTTPError: If the Graph API returns a non-2xx status.
        """
        params = {
            "$orderby": "receivedDateTime desc",
            "$top": 25,
            "$select": (
                "id,subject,from,receivedDateTime,isRead,"
                "hasAttachments,conversationId,body"
            ),
        }
        all_emails = self._get_messages(params)
        thread = [e for e in all_emails if e.get("conversationId") == conversation_id]
        return list(reversed(thread))  # oldest first

    def fetch_attachments(self, email_id: str) -> list[dict[str, Any]]:
        """Fetch all attachments for a given email.

        Args:
            email_id: The Graph API message ID.

        Returns:
            List of attachment dicts with name, contentType, and contentBytes
            (base64-encoded for binary types).

        Raises:
            requests.HTTPError: If the Graph API returns a non-2xx status.
        """
        url = f"{config.GRAPH_API_BASE_URL}/me/messages/{email_id}/attachments"
        response = self._get(url)
        return response.get("value", [])

    def mark_email_read(self, email_id: str) -> None:
        """Mark a single email as read.

        Args:
            email_id: The Graph API message ID.

        Raises:
            requests.HTTPError: If the Graph API returns a non-2xx status.
        """
        url = f"{config.GRAPH_API_BASE_URL}/me/messages/{email_id}"
        self._patch(url, {"isRead": True})
        logger.info("Marked email %s as read.", email_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_messages(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch messages from /me/messages with the given query params.

        Args:
            params: OData query parameters.

        Returns:
            List of message dicts from the 'value' field of the response.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        url = f"{config.GRAPH_API_BASE_URL}/me/messages"
        response = self._get(url, params=params)
        return response.get("value", [])

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform an authenticated GET request to the Graph API.

        Args:
            url: Full Graph API URL.
            params: Optional OData query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        headers = self._auth_headers()
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=config.GRAPH_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            logger.error("Graph API GET failed: %s — %s", url, error)
            raise

    def _patch(self, url: str, body: dict[str, Any]) -> None:
        """Perform an authenticated PATCH request to the Graph API.

        Args:
            url: Full Graph API URL.
            body: JSON body to send.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        try:
            response = requests.patch(
                url,
                headers=headers,
                data=json.dumps(body),
                timeout=config.GRAPH_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.HTTPError as error:
            logger.error("Graph API PATCH failed: %s — %s", url, error)
            raise

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization headers using the current access token.

        Returns:
            Dict with a Bearer Authorization header.

        Raises:
            RuntimeError: If the auth provider cannot obtain a token.
        """
        token = self._auth.get_access_token()
        return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# CLI entry point — `python graph.py --login`
# ---------------------------------------------------------------------------

def _login() -> None:
    """Trigger an interactive browser login and cache the refresh token."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Microsoft Graph login for mailbox: %s", config.MAILBOX)
    provider = DelegatedAuthProvider()
    token = provider.get_access_token()
    if token:
        logger.info("Login successful. Token cached to %s.", config.TOKEN_CACHE_PATH)
    else:
        logger.error("Login failed — no token returned.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Microsoft Graph API client utilities.")
    parser.add_argument("--login", action="store_true",
                        help="Perform interactive browser login and cache the refresh token.")
    args = parser.parse_args()

    if args.login:
        _login()
    else:
        parser.print_help()
