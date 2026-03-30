"""
FastMCP server exposing Microsoft 365 email access as MCP tools.

Launched as a subprocess by main.py and communicates over stdio using the
MCP protocol. The server wraps graph.py calls and simplifies email payloads
before returning them to the MCP client.

Tools exposed:
    list_unread_emails      — fetch unread emails from the inbox
    list_all_emails         — fetch all emails (read + unread)
    get_latest_email_tool   — fetch the single most recent email
    get_email_thread        — fetch all emails in a conversation thread
    get_email_attachments   — fetch attachment content for an email
    mark_email_read         — mark an email as read
"""

import base64
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

import config
from extractor import HtmlExtractor
from graph import GraphClient

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

mcp = FastMCP("email-server")
_graph = GraphClient()
_extractor = HtmlExtractor()


# ---------------------------------------------------------------------------
# Email payload helpers
# ---------------------------------------------------------------------------

def _simplify_email(email: dict[str, Any]) -> dict[str, Any]:
    """Strip Graph API noise and clean the body for LLM consumption.

    Preserves the full body — never truncates. HTML bodies are cleaned via
    HtmlExtractor to reduce token count while keeping table structure intact.

    Args:
        email: Raw email dict from the Graph API.

    Returns:
        Simplified dict with only the fields needed for extraction.
    """
    body_content: str = ""
    body_obj = email.get("body", {})
    content_type = body_obj.get("contentType", "text").lower()
    raw_content = body_obj.get("content", "")

    if content_type == "html":
        body_content = _extractor.extract(raw_content)
    else:
        body_content = raw_content

    sender = email.get("from", {}).get("emailAddress", {})

    return {
        "id": email.get("id", ""),
        "subject": email.get("subject", ""),
        "from": sender.get("address", ""),
        "receivedDateTime": email.get("receivedDateTime", ""),
        "isRead": email.get("isRead", False),
        "hasAttachments": email.get("hasAttachments", False),
        "conversationId": email.get("conversationId", ""),
        "body": body_content,
    }


def _decode_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    """Decode attachment content based on its type.

    Images are kept as base64. PDFs are noted but not decoded. All other
    types are decoded as UTF-8 text where possible.

    Args:
        attachment: Raw attachment dict from the Graph API.

    Returns:
        Attachment dict with a decoded 'content' field added.
    """
    content_type: str = attachment.get("contentType", "").lower()
    raw_bytes: str = attachment.get("contentBytes", "")

    if content_type.startswith("image/"):
        content = f"[image/base64] {raw_bytes}"
    elif content_type == "application/pdf":
        content = "[PDF attachment — content not decoded]"
    else:
        try:
            content = base64.b64decode(raw_bytes).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            content = f"[binary attachment — could not decode as text]"

    return {
        "name": attachment.get("name", ""),
        "contentType": content_type,
        "content": content,
    }


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_unread_emails() -> list[dict[str, Any]]:
    """Fetch all unread emails from the inbox.

    Returns:
        List of simplified email dicts, ordered newest first.
    """
    logger.info("Tool called: list_unread_emails")
    emails = _graph.fetch_unread_emails()
    return [_simplify_email(e) for e in emails]


@mcp.tool()
def list_all_emails() -> list[dict[str, Any]]:
    """Fetch all emails (read and unread) from the inbox.

    Returns:
        List of simplified email dicts, ordered newest first.
    """
    logger.info("Tool called: list_all_emails")
    emails = _graph.fetch_all_emails()
    return [_simplify_email(e) for e in emails]


@mcp.tool()
def get_latest_email_tool() -> dict[str, Any] | None:
    """Fetch the single most recent email from the inbox.

    Returns:
        Simplified email dict, or None if the inbox is empty.
    """
    logger.info("Tool called: get_latest_email_tool")
    emails = _graph.fetch_all_emails()
    if not emails:
        return None
    return _simplify_email(emails[0])


@mcp.tool()
def get_email_thread(conversation_id: str) -> list[dict[str, Any]]:
    """Fetch all emails in a conversation thread.

    Args:
        conversation_id: The conversationId shared by emails in the thread.

    Returns:
        List of simplified email dicts ordered oldest-first.
    """
    logger.info("Tool called: get_email_thread conversation_id=%s", conversation_id)
    emails = _graph.fetch_thread(conversation_id)
    return [_simplify_email(e) for e in emails]


@mcp.tool()
def get_email_attachments(email_id: str) -> list[dict[str, Any]]:
    """Fetch all attachments for a given email.

    Args:
        email_id: The Graph API message ID.

    Returns:
        List of attachment dicts with name, contentType, and decoded content.
    """
    logger.info("Tool called: get_email_attachments email_id=%s", email_id)
    attachments = _graph.fetch_attachments(email_id)
    return [_decode_attachment(a) for a in attachments]


@mcp.tool()
def mark_email_read(email_id: str) -> dict[str, str]:
    """Mark an email as read in the mailbox.

    Args:
        email_id: The Graph API message ID.

    Returns:
        Dict with a 'status' key confirming the operation.
    """
    logger.info("Tool called: mark_email_read email_id=%s", email_id)
    _graph.mark_email_read(email_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point — launched as subprocess by main.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
