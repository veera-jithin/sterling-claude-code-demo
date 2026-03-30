"""
Agent orchestrator for the Email Job Extraction Agent.

Launches the MCP email server as a subprocess and runs an agentic Gemini session
per extraction cycle. Gemini autonomously calls MCP tools (list emails, fetch threads,
retrieve attachments, mark read) and calls extract_jobs to return structured job data.

Results are written incrementally to the output file after each extract_jobs call so
partial runs are not lost. A full prompt log (system prompt, user messages, model
responses, tool calls) is written to res/logs/ for each run.

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

You have access to email tools and an extract_jobs function. Your task is to:

1. Fetch emails using the tool specified in the user message.
2. For each email with a conversationId, call get_email_thread to retrieve the full
   thread — use only the most recent message, as older replies are quoted inline.
3. For emails where hasAttachments is true, call get_email_attachments to retrieve
   attachment content before extracting.
4. Call extract_jobs for each email that contains job order information.
5. Skip emails with no job information — do not call extract_jobs unnecessarily.

When extracting job orders from emails sent by construction/trade builders, extract
structured job order information. Each email may contain one or more job orders.

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
# MCP tool helpers
# ---------------------------------------------------------------------------

def _mcp_schema_to_gemini(schema: dict[str, Any]) -> types.Schema:
    """Recursively convert a JSON Schema dict (from MCP) to a Gemini Schema.

    Args:
        schema: JSON Schema dict as returned by the MCP tool listing.

    Returns:
        Equivalent Gemini types.Schema object.
    """
    type_map = {
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }
    gemini_type = type_map.get(schema.get("type", "object"), types.Type.OBJECT)

    properties = {
        name: _mcp_schema_to_gemini(prop)
        for name, prop in schema.get("properties", {}).items()
    }

    items = _mcp_schema_to_gemini(schema["items"]) if "items" in schema else None

    return types.Schema(
        type=gemini_type,
        description=schema.get("description", ""),
        properties=properties or None,
        required=schema.get("required") or None,
        items=items,
    )


async def _get_gemini_tools_from_mcp(
    session: ClientSession,
) -> list[types.FunctionDeclaration]:
    """Fetch available tools from the MCP server and convert to Gemini FunctionDeclarations.

    Args:
        session: Active MCP client session.

    Returns:
        List of FunctionDeclaration objects ready to pass to Gemini.
    """
    tools_result = await session.list_tools()
    declarations = []
    for tool in tools_result.tools:
        schema = _mcp_schema_to_gemini(tool.inputSchema or {})
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters=schema,
            )
        )
    logger.info("Loaded %d MCP tools as Gemini function declarations.", len(declarations))
    return declarations


def _extract_pdf_parts(items: list[Any]) -> tuple[list[Any], list[types.Part]]:
    """Separate PDF attachments from other items and convert them to Gemini inline Parts.

    PDFs cannot be passed through a FunctionResponse — they must be injected
    directly into the conversation as inline_data Parts alongside the tool result.

    Args:
        items: Parsed list of attachment dicts from get_email_attachments.

    Returns:
        Tuple of (items_without_pdfs, pdf_parts) where pdf_parts are Gemini
        Parts with inline_data ready to append to the conversation.
    """
    remaining: list[Any] = []
    pdf_parts: list[types.Part] = []

    for item in items:
        if isinstance(item, dict) and item.get("contentType") == "application/pdf":
            raw_base64 = item.get("content", "")
            if raw_base64:
                pdf_parts.append(
                    types.Part(
                        inline_data=types.Blob(
                            mime_type="application/pdf",
                            data=raw_base64,
                        )
                    )
                )
                logger.info("Injecting PDF attachment inline: %s", item.get("name", "unnamed"))
            # Replace content with a note so Gemini knows the PDF was passed separately
            remaining.append({**item, "content": "[PDF passed as inline data above]"})
        else:
            remaining.append(item)

    return remaining, pdf_parts


async def _call_mcp_tool(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    prompt_logger: PromptLogger,
) -> tuple[str, list[types.Part]]:
    """Call an MCP tool and return the result as a JSON string plus any PDF parts.

    Handles MCP content parsing including double-encoded list items that some
    MCP versions produce. For get_email_attachments calls, PDF attachments are
    extracted and returned as Gemini inline_data Parts to be injected directly
    into the conversation alongside the function response.

    Args:
        session: Active MCP client session.
        tool_name: Name of the MCP tool to call.
        arguments: Arguments to pass to the tool.
        prompt_logger: PromptLogger for this run.

    Returns:
        Tuple of (result_json_string, pdf_parts). pdf_parts is non-empty only
        when tool_name is "get_email_attachments" and PDFs were found.

    Raises:
        Exception: If the MCP call fails.
    """
    prompt_logger.write(f"TOOL_CALL {tool_name}", json.dumps(arguments, indent=2))
    result = await session.call_tool(tool_name, arguments=arguments)

    items: list[Any] = []
    for content in result.content:
        if not hasattr(content, "text"):
            continue
        try:
            parsed = json.loads(content.text)
        except json.JSONDecodeError:
            items.append(content.text)
            continue

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    items.append(item)
                elif isinstance(item, str):
                    # Some MCP versions double-encode list items as JSON strings
                    try:
                        decoded = json.loads(item)
                        if isinstance(decoded, dict):
                            items.append(decoded)
                    except json.JSONDecodeError:
                        items.append(item)
        else:
            items.append(parsed)

    pdf_parts: list[types.Part] = []
    if tool_name == "get_email_attachments":
        items, pdf_parts = _extract_pdf_parts(items)

    result_str = json.dumps(items[0] if len(items) == 1 else items)
    prompt_logger.write(f"TOOL_RESULT {tool_name}", result_str)
    return result_str, pdf_parts


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

async def _run_agentic_loop(
    session: ClientSession,
    gemini_client: genai.Client,
    fetch_all: bool,
    mark_read: bool,
    output_path: str,
    all_results: list[dict[str, Any]],
    prompt_logger: PromptLogger,
) -> int:
    """Run one agentic Gemini session: Gemini calls MCP tools and extract_jobs autonomously.

    Gemini receives all MCP email tools plus extract_jobs as function declarations.
    It decides when to fetch threads, when to retrieve attachments, and when to
    call extract_jobs — following rules in the system prompt. The loop continues
    until Gemini makes no further tool calls.

    Args:
        session: Active MCP client session.
        gemini_client: Configured Gemini API client.
        fetch_all: If True, instruct Gemini to fetch all emails; otherwise unread only.
        mark_read: If True, instruct Gemini to mark each email read after processing.
        output_path: Path to write extracted jobs JSON.
        all_results: Existing results list; new jobs are appended and saved here.
        prompt_logger: PromptLogger for this run.

    Returns:
        Number of jobs extracted in this session.
    """
    mcp_declarations = await _get_gemini_tools_from_mcp(session)
    gemini_tool = types.Tool(function_declarations=mcp_declarations + [EXTRACT_JOBS_FUNCTION])

    fetch_instruction = (
        "Call list_all_emails to retrieve every email in the inbox."
        if fetch_all else
        "Call list_unread_emails to retrieve unread emails only."
    )
    mark_read_instruction = (
        "After successfully calling extract_jobs for an email, call mark_email_read with its id."
        if mark_read else
        "Do NOT call mark_email_read — leave all emails in their current read state."
    )

    user_message = (
        f"{fetch_instruction} "
        "The list is already deduplicated — one email per conversation thread, always the most recent. "
        "For each email: "
        "(1) if hasAttachments is true, call get_email_attachments before extracting. "
        "(2) call extract_jobs with all job orders found in the email. "
        f"If an email has no job information, skip it. {mark_read_instruction}"
    )

    prompt_logger.write("SYSTEM", SYSTEM_PROMPT)
    prompt_logger.write("USER", user_message)

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]
    jobs_extracted = 0

    while True:
        try:
            response = gemini_client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[gemini_tool],
                ),
            )
        except Exception as error:
            logger.error("Gemini API call failed: %s", error)
            break

        prompt_logger.write("MODEL_RESPONSE", str(response))

        if not response.candidates:
            logger.warning("Gemini returned no candidates — stopping loop.")
            break

        model_content = response.candidates[0].content
        contents.append(model_content)

        function_calls = [
            part.function_call
            for part in (model_content.parts or [])
            if part.function_call
        ]

        if not function_calls:
            # No tool calls — Gemini is done
            break

        tool_result_parts: list[types.Part] = []
        for fc in function_calls:
            pdf_parts: list[types.Part] = []
            if fc.name == "extract_jobs":
                args = dict(fc.args)
                prompt_logger.write("TOOL_CALL extract_jobs", json.dumps(args, indent=2))
                jobs = args.get("jobs", [])
                all_results.extend(jobs)
                _save_results(output_path, all_results)
                jobs_extracted += len(jobs)
                logger.info("Extracted %d job(s) via extract_jobs.", len(jobs))
                result_payload: dict[str, Any] = {"status": "ok", "jobs_saved": len(jobs)}
            else:
                try:
                    result_str, pdf_parts = await _call_mcp_tool(
                        session, fc.name, dict(fc.args), prompt_logger
                    )
                    result_payload = {"result": result_str}
                except Exception as error:
                    logger.error("MCP tool %s failed: %s", fc.name, error)
                    result_payload = {"error": str(error)}

            tool_result_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response=result_payload,
                    )
                )
            )
            # PDFs must be injected as inline Parts — they can't go inside a FunctionResponse
            tool_result_parts.extend(pdf_parts)

        contents.append(types.Content(role="user", parts=tool_result_parts))

    return jobs_extracted


# ---------------------------------------------------------------------------
# Core extraction entry point
# ---------------------------------------------------------------------------

async def _run_extraction(
    output_path: str,
    fetch_all: bool,
    mark_read: bool,
    prompt_logger: PromptLogger,
    fresh_start: bool = False,
) -> int:
    """Run one extraction cycle.

    Opens the MCP server subprocess, initialises the Gemini client, then
    delegates entirely to _run_agentic_loop.

    Args:
        output_path: Path to write extracted jobs JSON.
        fetch_all: If True, fetch all emails; otherwise unread only.
        mark_read: If True, instruct Gemini to mark processed emails as read.
        prompt_logger: PromptLogger for this run.
        fresh_start: If True, ignore any existing output file and start from
            an empty list. Used for --all mode so re-runs don't accumulate
            duplicates from previous runs.

    Returns:
        Number of jobs extracted.
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
            return await _run_agentic_loop(
                session=session,
                gemini_client=gemini_client,
                fetch_all=fetch_all,
                mark_read=mark_read,
                output_path=output_path,
                all_results=all_results,
                prompt_logger=prompt_logger,
            )


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
    asyncio.run(_main())
