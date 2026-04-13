"""
Unit tests for the MCP email server tools.

All GraphClient calls are mocked — no real network requests.
Tests cover email simplification, deduplication, and the MCP tool handlers.
"""

from unittest.mock import MagicMock, patch

import pytest

import email_server
from email_server import _simplify_email, _deduplicate_by_thread


# ---------------------------------------------------------------------------
# _simplify_email
# ---------------------------------------------------------------------------

class TestSimplifyEmail:
    def _raw_email(self, **overrides) -> dict:
        base = {
            "id": "msg-001",
            "subject": "Job Order",
            "from": {"emailAddress": {"address": "builder@example.com"}},
            "receivedDateTime": "2026-04-01T10:00:00Z",
            "isRead": False,
            "hasAttachments": True,
            "conversationId": "conv-001",
            "body": {"content": "<p>Job details here</p>", "contentType": "html"},
        }
        return {**base, **overrides}

    def test_extracts_from_address(self) -> None:
        simplified = _simplify_email(self._raw_email())
        assert simplified["from"] == "builder@example.com"

    def test_preserves_core_fields(self) -> None:
        simplified = _simplify_email(self._raw_email())
        assert simplified["id"] == "msg-001"
        assert simplified["subject"] == "Job Order"
        assert simplified["isRead"] is False
        assert simplified["hasAttachments"] is True
        assert simplified["conversationId"] == "conv-001"

    def test_strips_html_from_body(self) -> None:
        raw = self._raw_email()
        raw["body"]["content"] = "<p>Hello <b>world</b></p>"
        simplified = _simplify_email(raw)
        assert "<p>" not in simplified["body"]
        assert "Hello" in simplified["body"]

    def test_handles_plain_text_body(self) -> None:
        raw = self._raw_email()
        raw["body"] = {"content": "Plain text body", "contentType": "text"}
        simplified = _simplify_email(raw)
        assert "Plain text body" in simplified["body"]


# ---------------------------------------------------------------------------
# _deduplicate_by_thread
# ---------------------------------------------------------------------------

class TestDeduplicateByConversation:
    def _email(self, email_id: str, conv_id: str, received: str) -> dict:
        return {
            "id": email_id,
            "conversationId": conv_id,
            "receivedDateTime": received,
        }

    def test_keeps_most_recent_per_thread(self) -> None:
        # Input is newest-first (as returned by Graph API) — first occurrence is kept
        emails = [
            self._email("e2", "conv-A", "2026-04-01T10:00:00Z"),
            self._email("e1", "conv-A", "2026-04-01T08:00:00Z"),
        ]
        result = _deduplicate_by_thread(emails)
        assert len(result) == 1
        assert result[0]["id"] == "e2"

    def test_keeps_emails_without_conversation_id(self) -> None:
        emails = [
            {"id": "e1", "conversationId": None, "receivedDateTime": "2026-04-01T08:00:00Z"},
            {"id": "e2", "conversationId": None, "receivedDateTime": "2026-04-01T09:00:00Z"},
        ]
        result = _deduplicate_by_thread(emails)
        assert len(result) == 2

    def test_multiple_threads_deduplicated_independently(self) -> None:
        # Input is newest-first per thread; first occurrence of each conv is kept
        emails = [
            self._email("e2", "conv-A", "2026-04-01T10:00:00Z"),
            self._email("e4", "conv-B", "2026-04-01T11:00:00Z"),
            self._email("e1", "conv-A", "2026-04-01T08:00:00Z"),
            self._email("e3", "conv-B", "2026-04-01T09:00:00Z"),
        ]
        result = _deduplicate_by_thread(emails)
        ids = {e["id"] for e in result}
        assert ids == {"e2", "e4"}

    def test_single_email_per_thread_unchanged(self) -> None:
        emails = [self._email("e1", "conv-A", "2026-04-01T08:00:00Z")]
        result = _deduplicate_by_thread(emails)
        assert len(result) == 1
        assert result[0]["id"] == "e1"
