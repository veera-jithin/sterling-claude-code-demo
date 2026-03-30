"""
Unit tests for GraphClient.

All HTTP calls are mocked — no real network requests are made.
Tests cover the fetch, filter, mark-read, and error-handling logic.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from graph import GraphClient, HardcodedTokenAuthProvider


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth() -> MagicMock:
    """Auth provider that returns a static fake token."""
    auth = MagicMock()
    auth.get_access_token.return_value = "fake-bearer-token"
    return auth


@pytest.fixture
def client(mock_auth) -> GraphClient:
    return GraphClient(auth_provider=mock_auth)


def _make_email(
    email_id: str = "id1",
    subject: str = "Test Email",
    is_read: bool = False,
    conversation_id: str = "conv1",
) -> dict:
    return {
        "id": email_id,
        "subject": subject,
        "from": {"emailAddress": {"address": "builder@example.com"}},
        "receivedDateTime": "2026-03-30T10:00:00Z",
        "isRead": is_read,
        "hasAttachments": False,
        "conversationId": conversation_id,
        "body": {"contentType": "text", "content": "Job order body"},
    }


def _mock_get_response(data: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = data
    response.raise_for_status.return_value = None
    return response


# ---------------------------------------------------------------------------
# fetch_all_emails
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fetch_all_emails_returns_list(client):
    emails = [_make_email("id1", is_read=False), _make_email("id2", is_read=True)]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_all_emails()
    assert len(result) == 2


@pytest.mark.unit
def test_fetch_all_emails_includes_read_and_unread(client):
    emails = [_make_email("id1", is_read=False), _make_email("id2", is_read=True)]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_all_emails()
    read_flags = [e["isRead"] for e in result]
    assert True in read_flags
    assert False in read_flags


@pytest.mark.unit
def test_fetch_all_emails_returns_empty_when_no_emails(client):
    with patch("requests.get", return_value=_mock_get_response({"value": []})):
        result = client.fetch_all_emails()
    assert result == []


@pytest.mark.unit
def test_fetch_all_emails_calls_correct_endpoint(client):
    with patch("requests.get", return_value=_mock_get_response({"value": []})) as mock_get:
        client.fetch_all_emails()
    called_url = mock_get.call_args[0][0]
    assert "/me/messages" in called_url


# ---------------------------------------------------------------------------
# fetch_unread_emails
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fetch_unread_emails_filters_out_read(client):
    emails = [
        _make_email("id1", is_read=False),
        _make_email("id2", is_read=True),
        _make_email("id3", is_read=False),
    ]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_unread_emails()
    assert len(result) == 2
    assert all(not e["isRead"] for e in result)


@pytest.mark.unit
def test_fetch_unread_emails_returns_empty_when_all_read(client):
    emails = [_make_email("id1", is_read=True), _make_email("id2", is_read=True)]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_unread_emails()
    assert result == []


# ---------------------------------------------------------------------------
# fetch_thread
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fetch_thread_returns_only_matching_conversation(client):
    emails = [
        _make_email("id1", conversation_id="conv-A"),
        _make_email("id2", conversation_id="conv-B"),
        _make_email("id3", conversation_id="conv-A"),
    ]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_thread("conv-A")
    assert len(result) == 2
    assert all(e["conversationId"] == "conv-A" for e in result)


@pytest.mark.unit
def test_fetch_thread_returns_oldest_first(client):
    emails = [
        _make_email("newest", conversation_id="conv-A"),
        _make_email("oldest", conversation_id="conv-A"),
    ]
    # Graph API returns newest first; fetch_thread should reverse to oldest first
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_thread("conv-A")
    assert result[0]["id"] == "oldest"
    assert result[1]["id"] == "newest"


@pytest.mark.unit
def test_fetch_thread_returns_empty_when_no_match(client):
    emails = [_make_email("id1", conversation_id="conv-X")]
    with patch("requests.get", return_value=_mock_get_response({"value": emails})):
        result = client.fetch_thread("conv-Z")
    assert result == []


# ---------------------------------------------------------------------------
# mark_email_read
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_mark_email_read_sends_patch_with_is_read_true(client):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    with patch("requests.patch", return_value=mock_response) as mock_patch:
        client.mark_email_read("email-123")
    assert mock_patch.called
    call_kwargs = mock_patch.call_args
    body = json.loads(call_kwargs[1]["data"])
    assert body["isRead"] is True


@pytest.mark.unit
def test_mark_email_read_targets_correct_message_id(client):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    with patch("requests.patch", return_value=mock_response) as mock_patch:
        client.mark_email_read("email-abc")
    url = mock_patch.call_args[0][0]
    assert "email-abc" in url


# ---------------------------------------------------------------------------
# fetch_attachments
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fetch_attachments_returns_list(client):
    attachments = [
        {"name": "file.pdf", "contentType": "application/pdf", "contentBytes": ""},
        {"name": "image.png", "contentType": "image/png", "contentBytes": "abc="},
    ]
    with patch("requests.get", return_value=_mock_get_response({"value": attachments})):
        result = client.fetch_attachments("email-123")
    assert len(result) == 2
    assert result[0]["name"] == "file.pdf"


@pytest.mark.unit
def test_fetch_attachments_returns_empty_when_none(client):
    with patch("requests.get", return_value=_mock_get_response({"value": []})):
        result = client.fetch_attachments("email-123")
    assert result == []


# ---------------------------------------------------------------------------
# Authentication header
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_auth_header_contains_bearer_token(client, mock_auth):
    with patch("requests.get", return_value=_mock_get_response({"value": []})) as mock_get:
        client.fetch_all_emails()
    headers = mock_get.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer fake-bearer-token"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fetch_raises_on_http_error(client):
    error_response = MagicMock()
    error_response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
    with patch("requests.get", return_value=error_response):
        with pytest.raises(requests.HTTPError):
            client.fetch_all_emails()


@pytest.mark.unit
def test_mark_read_raises_on_http_error(client):
    error_response = MagicMock()
    error_response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    with patch("requests.patch", return_value=error_response):
        with pytest.raises(requests.HTTPError):
            client.mark_email_read("email-123")


# ---------------------------------------------------------------------------
# HardcodedTokenAuthProvider
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_hardcoded_token_provider_returns_token():
    with patch("config.MICROSOFT_GRAPH_TOKEN", "my-static-token"):
        provider = HardcodedTokenAuthProvider()
        token = provider.get_access_token()
    assert token == "my-static-token"


@pytest.mark.unit
def test_hardcoded_token_provider_raises_when_not_configured():
    with patch("config.MICROSOFT_GRAPH_TOKEN", ""):
        provider = HardcodedTokenAuthProvider()
        with pytest.raises(RuntimeError, match="MICROSOFT_GRAPH_TOKEN is not set"):
            provider.get_access_token()
