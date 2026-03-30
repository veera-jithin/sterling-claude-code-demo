"""
Agent orchestrator for the Email Job Extraction Agent.

Launches the MCP email server as a subprocess, fetches emails via MCP tools,
deduplicates by conversation thread, and runs one Gemini API call per email
to extract structured job order data.

Results are written incrementally to the output file after each email so that
partial runs are not lost. A full prompt log (system prompt, user messages,
model responses, tool calls) is written to res/logs/ for each run.

Usage:
    python main.py --output res/results.json          # default polling mode
    python main.py --once --output res/results.json   # single run, unread only
    python main.py --all --output res/results.json    # single run, all emails
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a job extraction assistant for a land surveying company.

Your task is to read emails from construction/trade builders and extract structured
job order information. Each email may contain one or more job orders.

For each job order found, extract these fields exactly as they appear in the email:
- builder_name: the name of the builder or company sending the job
- community: the subdivision or community name
- type_of_job: the type of survey or work requested
- address: the full street address
- lot: the lot number
- block: the block number

Rules:
- Copy field values verbatim — preserve all codes, numbers, punctuation, and
  bracketed content. Do not summarise, truncate, or reword.
- If a field is marked N/A, not applicable, or is absent, set it to null.
- Return multiple job objects if the email contains multiple jobs.
- Return an empty list [] if the email contains no job information.
- Set confidence to "high" if all key fields are clearly present, "medium" if
  some fields required inference, or "low" if the data is ambiguous or incomplete.
- Always include confidence_reason: a one-sentence explanation of why you assigned
  that confidence level (e.g. which fields were missing, inferred, or ambiguous).
- Always include source_email_subject copied verbatim from the email subject.

Return your result as a JSON array of job objects. No commentary, just JSON.
"""

# Gemini function declaration for extract_jobs
EXTRACT_JOBS_FUNCTION = types.FunctionDeclaration(
    name="extract_jobs",
    description="Return structured job order records extracted from the email.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "jobs": types.Schema(
                type=types.Type.ARRAY,
                description="List of job objects extracted from the email. Empty if none found.",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "builder_name": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Builder or company name.",
                        ),
                        "community": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Subdivision or community name.",
                        ),
                        "type_of_job": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Type of survey or work requested.",
                        ),
                        "address": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Full street address.",
                        ),
                        "lot": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Lot number.",
                        ),
                        "block": types.Schema(
                            type=types.Type.STRING, nullable=True,
                            description="Block number.",
                        ),
                        "confidence": types.Schema(
                            type=types.Type.STRING,
                            description="Extraction confidence: high, medium, or low.",
                        ),
                        "confidence_reason": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "One-sentence explanation of the confidence rating — "
                                "e.g. which fields were missing, inferred, or ambiguous."
                            ),
                        ),
                        "source_email_subject": types.Schema(
                            type=types.Type.STRING,
                            description="Verbatim email subject line.",
                        ),
                    },
                    required=["confidence", "confidence_reason", "source_email_subject"],
                ),
            ),
        },
        required=["jobs"],
    ),
)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _ensure_output_dir(output_path: str) -> None:
    """Create the output file's parent directory if it doesn't exist.

    Args:
        output_path: Path to the output JSON file.
    """
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _load_existing_results(output_path: str) -> list[dict[str, Any]]:
    """Load any previously saved results from the output file.

    Args:
        output_path: Path to the output JSON file.

    Returns:
        List of previously extracted job dicts, or empty list if file missing.
    """
    if not os.path.exists(output_path):
        return []
    try:
        with open(output_path, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("Could not load existing results from %s: %s", output_path, error)
        return []


def _save_results(output_path: str, results: list[dict[str, Any]]) -> None:
    """Write results to the output JSON file, flushing immediately.

    Args:
        output_path: Path to write the JSON file.
        results: Full list of extracted job dicts to write.
    """
    with open(output_path, "w") as file:
        json.dump(results, file, indent=2)
        file.flush()
    logger.info("Saved %d total jobs to %s.", len(results), output_path)


# ---------------------------------------------------------------------------
# Prompt logging
# ---------------------------------------------------------------------------

class PromptLogger:
    """Writes a per-run prompt log to res/logs/ flushed after every entry.

    Each entry captures system prompts, user messages, model responses,
    tool calls, and tool results — everything sent and received by Gemini.

    Args:
        mode: Run mode label used in the log filename (e.g. 'polling', 'once', 'all').
    """

    def __init__(self, mode: str) -> None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = os.path.join(config.LOG_DIR, f"{timestamp}_{mode}.log")
        self._file = open(log_path, "w", buffering=1)  # line-buffered
        logger.info("Prompt log: %s", log_path)

    def write(self, label: str, content: str) -> None:
        """Write a labelled entry to the log, flushed immediately.

        Args:
            label: Entry label (e.g. 'SYSTEM', 'USER', 'MODEL', 'TOOL_CALL').
            content: The text content to log.
        """
        self._file.write(f"\n{'=' * 60}\n[{label}]\n{content}\n")
        self._file.flush()

    def close(self) -> None:
        """Close the log file."""
        self._file.close()


# ---------------------------------------------------------------------------
# Thread deduplication
# ---------------------------------------------------------------------------

def _deduplicate_by_thread(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the most recent email per conversation thread.

    Emails without a conversationId are treated as standalone and always kept.
    Older replies within a thread are skipped — their content is quoted inline
    in the latest reply.

    Args:
        emails: List of simplified email dicts (newest first from Graph API).

    Returns:
        Deduplicated list with at most one email per conversationId.
    """
    seen_conversations: set[str] = set()
    deduplicated: list[dict[str, Any]] = []

    for email in emails:
        conversation_id = email.get("conversationId", "")
        if not conversation_id:
            deduplicated.append(email)
            continue
        if conversation_id not in seen_conversations:
            seen_conversations.add(conversation_id)
            deduplicated.append(email)

    logger.info(
        "Deduplicated %d emails to %d unique threads.",
        len(emails), len(deduplicated),
    )
    return deduplicated


# ---------------------------------------------------------------------------
# Gemini extraction
# ---------------------------------------------------------------------------

def _extract_jobs_from_email(
    client: genai.Client,
    email: dict[str, Any],
    prompt_logger: PromptLogger,
) -> list[dict[str, Any]]:
    """Run one Gemini API call to extract job orders from a single email.

    Uses function calling so the model returns structured JSON via the
    extract_jobs function rather than free text.

    Args:
        client: Configured Gemini API client.
        email: Simplified email dict with subject and body.
        prompt_logger: PromptLogger instance for this run.

    Returns:
        List of extracted job dicts. Empty if no jobs found or call fails.
    """
    user_message = (
        f"Subject: {email.get('subject', '')}\n"
        f"From: {email.get('from', '')}\n"
        f"Received: {email.get('receivedDateTime', '')}\n\n"
        f"Body:\n{email.get('body', '')}"
    )

    prompt_logger.write("SYSTEM", SYSTEM_PROMPT)
    prompt_logger.write("USER", user_message)

    tool = types.Tool(function_declarations=[EXTRACT_JOBS_FUNCTION])

    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[tool],
            ),
        )
    except Exception as error:
        logger.error("Gemini API call failed for email '%s': %s", email.get("subject"), error)
        return []

    prompt_logger.write("MODEL_RESPONSE", str(response))

    # Extract the function call result from the response
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if part.function_call and part.function_call.name == "extract_jobs":
                args = dict(part.function_call.args)
                prompt_logger.write("TOOL_CALL", json.dumps(args, indent=2))
                jobs = args.get("jobs", [])
                logger.info(
                    "Extracted %d job(s) from email: %s",
                    len(jobs), email.get("subject"),
                )
                return jobs

    logger.warning("No function call in Gemini response for email: %s", email.get("subject"))
    return []


# ---------------------------------------------------------------------------
# MCP session helpers
# ---------------------------------------------------------------------------

async def _fetch_emails_via_mcp(
    session: ClientSession,
    fetch_all: bool,
) -> list[dict[str, Any]]:
    """Fetch emails from the MCP server and deduplicate by conversation.

    Args:
        session: Active MCP client session connected to the email server.
        fetch_all: If True, fetch all emails; otherwise fetch only unread.

    Returns:
        Deduplicated list of simplified email dicts.
    """
    tool_name = "list_all_emails" if fetch_all else "list_unread_emails"
    logger.info("Fetching emails via MCP tool: %s", tool_name)

    result = await session.call_tool(tool_name, arguments={})
    emails: list[dict[str, Any]] = []

    for content in result.content:
        if not hasattr(content, "text"):
            continue
        try:
            parsed = json.loads(content.text)
        except json.JSONDecodeError as error:
            logger.error("Failed to parse MCP tool response: %s", error)
            continue

        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict):
                emails.append(item)
            elif isinstance(item, str):
                # Some MCP versions double-encode list items as JSON strings
                try:
                    decoded = json.loads(item)
                    if isinstance(decoded, dict):
                        emails.append(decoded)
                except json.JSONDecodeError:
                    pass

    return _deduplicate_by_thread(emails)


async def _mark_emails_read_via_mcp(
    session: ClientSession,
    email_ids: list[str],
) -> None:
    """Mark a list of emails as read via the MCP server.

    Args:
        session: Active MCP client session.
        email_ids: List of Graph API message IDs to mark read.
    """
    for email_id in email_ids:
        await session.call_tool("mark_email_read", arguments={"email_id": email_id})
        logger.info("Marked email read: %s", email_id)


# ---------------------------------------------------------------------------
# Core extraction loop
# ---------------------------------------------------------------------------

async def _run_extraction(
    output_path: str,
    fetch_all: bool,
    mark_read: bool,
    prompt_logger: PromptLogger,
    fresh_start: bool = False,
) -> int:
    """Run one extraction cycle: fetch, deduplicate, extract, save.

    Args:
        output_path: Path to write extracted jobs JSON.
        fetch_all: If True, fetch all emails; otherwise unread only.
        mark_read: If True, mark processed emails as read after extraction.
        prompt_logger: PromptLogger for this run.
        fresh_start: If True, ignore any existing output file and start from
            an empty list. Used for --all mode so re-runs don't accumulate
            duplicates from previous runs.

    Returns:
        Number of emails processed.
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(os.path.dirname(__file__), "email_server.py")],
    )

    gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    all_results = [] if fresh_start else _load_existing_results(output_path)

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            emails = await _fetch_emails_via_mcp(session, fetch_all)
            if not emails:
                logger.info("No emails to process.")
                return 0

            processed_ids: list[str] = []

            for email in emails:
                email_id = email.get("id", "")
                subject = email.get("subject", "(no subject)")
                logger.info("Processing email: %s", subject)

                jobs = _extract_jobs_from_email(gemini_client, email, prompt_logger)
                all_results.extend(jobs)
                _save_results(output_path, all_results)

                if email_id:
                    processed_ids.append(email_id)

            if mark_read and processed_ids:
                await _mark_emails_read_via_mcp(session, processed_ids)

            return len(emails)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Parsed Namespace with output, all, and once flags.
    """
    parser = argparse.ArgumentParser(
        description="Extract job orders from Outlook emails using Gemini."
    )
    parser.add_argument(
        "--output", default=config.DEFAULT_OUTPUT_PATH,
        help=f"Path to write extracted jobs JSON (default: {config.DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_emails",
        help="Process all emails in the inbox, then exit.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Process unread emails once, then exit.",
    )
    return parser.parse_args()


async def _main() -> None:
    """Main async entry point."""
    args = _parse_args()
    _ensure_output_dir(args.output)

    if args.all_emails:
        mode = "all"
    elif args.once:
        mode = "once"
    else:
        mode = "polling"

    prompt_logger = PromptLogger(mode)

    try:
        if args.all_emails:
            # Bulk run: all emails, do not mark as read, always overwrite output
            await _run_extraction(
                output_path=args.output,
                fetch_all=True,
                mark_read=False,
                prompt_logger=prompt_logger,
                fresh_start=True,
            )

        elif args.once:
            # Single run: unread only, mark as read after processing
            await _run_extraction(
                output_path=args.output,
                fetch_all=False,
                mark_read=True,
                prompt_logger=prompt_logger,
            )

        else:
            # Polling mode: loop until interrupted
            logger.info(
                "Polling mode: checking every %d seconds. Ctrl+C to stop.",
                config.POLL_INTERVAL_SECONDS,
            )
            while True:
                try:
                    await _run_extraction(
                        output_path=args.output,
                        fetch_all=False,
                        mark_read=True,
                        prompt_logger=prompt_logger,
                    )
                except Exception as error:
                    # Log the error but keep polling — transient failures (503,
                    # network blip, MCP hiccup) should not kill the process
                    logger.error("Extraction cycle failed, will retry next poll: %s", error)
                logger.info("Sleeping %d seconds.", config.POLL_INTERVAL_SECONDS)
                await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        prompt_logger.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
