"""
Integration tests for GraphClient against the real Microsoft Graph API.

These tests make real HTTP requests using the cached token in .token_cache.json.
They do NOT modify mailbox state (no mark-as-read, no deletes).

Requirements:
    - .token_cache.json must exist (run `python src/graph.py --login` first)
    - AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, MAILBOX must be set in .env

Run:
    pytest -m integration
    pytest src/tests/test_integration_graph.py -v
"""

import pytest
from graph import GraphClient


@pytest.fixture(scope="module")
def client() -> GraphClient:
    """Real GraphClient using the cached delegated token."""
    return GraphClient()


@pytest.mark.integration
def test_fetch_all_emails_returns_list(client):
    emails = client.fetch_all_emails()
    assert isinstance(emails, list)


@pytest.mark.integration
def test_fetch_all_emails_have_expected_fields(client):
    emails = client.fetch_all_emails()
    if not emails:
        pytest.skip("Mailbox is empty — cannot verify email shape")
    email = emails[0]
    for field in ("id", "subject", "isRead", "hasAttachments", "conversationId", "body"):
        assert field in email, f"Expected field '{field}' missing from email"


@pytest.mark.integration
def test_fetch_all_emails_body_has_content_type(client):
    emails = client.fetch_all_emails()
    if not emails:
        pytest.skip("Mailbox is empty")
    body = emails[0].get("body", {})
    assert "contentType" in body
    assert body["contentType"] in ("html", "text")


@pytest.mark.integration
def test_fetch_unread_emails_are_all_unread(client):
    emails = client.fetch_unread_emails()
    assert all(not e["isRead"] for e in emails), "fetch_unread_emails returned a read email"


@pytest.mark.integration
def test_fetch_thread_returns_emails_for_conversation(client):
    all_emails = client.fetch_all_emails()
    # Find an email that has a conversationId to test with
    threaded = [e for e in all_emails if e.get("conversationId")]
    if not threaded:
        pytest.skip("No emails with conversationId found in mailbox")

    conversation_id = threaded[0]["conversationId"]
    thread = client.fetch_thread(conversation_id)

    assert isinstance(thread, list)
    assert len(thread) >= 1
    assert all(e["conversationId"] == conversation_id for e in thread)


@pytest.mark.integration
def test_fetch_thread_ordered_oldest_first(client):
    all_emails = client.fetch_all_emails()
    threaded = [e for e in all_emails if e.get("conversationId")]
    if not threaded:
        pytest.skip("No emails with conversationId found in mailbox")

    conversation_id = threaded[0]["conversationId"]
    thread = client.fetch_thread(conversation_id)

    if len(thread) < 2:
        pytest.skip("Thread has only one email — cannot verify ordering")

    timestamps = [e["receivedDateTime"] for e in thread]
    assert timestamps == sorted(timestamps), "Thread emails are not ordered oldest-first"


@pytest.mark.integration
def test_fetch_attachments_returns_list_for_email_with_attachments(client):
    all_emails = client.fetch_all_emails()
    emails_with_attachments = [e for e in all_emails if e.get("hasAttachments")]
    if not emails_with_attachments:
        pytest.skip("No emails with attachments found in mailbox")

    email_id = emails_with_attachments[0]["id"]
    attachments = client.fetch_attachments(email_id)

    assert isinstance(attachments, list)
    assert len(attachments) >= 1
    assert "name" in attachments[0]
    assert "contentType" in attachments[0]


@pytest.mark.integration
def test_fetch_attachments_returns_empty_for_email_without_attachments(client):
    all_emails = client.fetch_all_emails()
    emails_without = [e for e in all_emails if not e.get("hasAttachments")]
    if not emails_without:
        pytest.skip("All emails have attachments — cannot test empty case")

    email_id = emails_without[0]["id"]
    attachments = client.fetch_attachments(email_id)
    assert attachments == []
