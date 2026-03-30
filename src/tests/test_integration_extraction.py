"""
Integration tests for the Gemini extraction pipeline.

Makes real Gemini API calls using GEMINI_API_KEY from .env.
Uses a fixed sample email so results are deterministic regardless of mailbox state.

Requirements:
    - GEMINI_API_KEY must be set in .env

Run:
    pytest -m integration
    pytest src/tests/test_integration_extraction.py -v
"""

import pytest
from google import genai

import config
from main import EXTRACT_JOBS_FUNCTION, SYSTEM_PROMPT, _extract_jobs_from_email, PromptLogger


# ---------------------------------------------------------------------------
# Sample emails — fixed inputs so tests are deterministic
# ---------------------------------------------------------------------------

SAMPLE_JOB_EMAIL = {
    "id": "test-001",
    "subject": "FW: Hulen Trails - 4500 Blue Mist Drive, Slab Survey",
    "from": "builder@lenna.com",
    "receivedDateTime": "2026-03-30T10:00:00Z",
    "isRead": False,
    "hasAttachments": False,
    "conversationId": "conv-test-001",
    "body": (
        "Please arrange a slab survey for the following job:\n\n"
        "Builder: Lennar\n"
        "Community: Hulen Trails\n"
        "Address: 4500 Blue Mist Drive, Fort Worth TX 76123\n"
        "Lot: 29\n"
        "Block: 28\n"
        "Type of Work: Slab Survey\n"
    ),
}

SAMPLE_NO_JOB_EMAIL = {
    "id": "test-002",
    "subject": "Office closed Monday",
    "from": "admin@company.com",
    "receivedDateTime": "2026-03-30T09:00:00Z",
    "isRead": False,
    "hasAttachments": False,
    "conversationId": "conv-test-002",
    "body": "Just a reminder that the office will be closed on Monday for the public holiday.",
}

SAMPLE_MULTI_JOB_EMAIL = {
    "id": "test-003",
    "subject": "Two new jobs - Patriot Estates",
    "from": "dispatch@brightland.com",
    "receivedDateTime": "2026-03-30T11:00:00Z",
    "isRead": False,
    "hasAttachments": False,
    "conversationId": "conv-test-003",
    "body": (
        "Please schedule the following two surveys:\n\n"
        "Job 1:\n"
        "Builder: Brightland Homes\n"
        "Community: Patriot Estates\n"
        "Address: 130 Patrick Henry Drive, Venus TX 76084\n"
        "Lot: 35\n"
        "Block: 45\n"
        "Type: Grade Inspection\n\n"
        "Job 2:\n"
        "Builder: Brightland Homes\n"
        "Community: Patriot Estates\n"
        "Address: 145 Liberty Bell Lane, Venus TX 76084\n"
        "Lot: 36\n"
        "Block: 45\n"
        "Type: Form Survey\n"
    ),
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gemini_client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=config.GEMINI_API_KEY)


@pytest.fixture(scope="module")
def prompt_logger(tmp_path_factory) -> PromptLogger:
    """Writes integration test prompt logs to a temp directory."""
    import os
    log_dir = tmp_path_factory.mktemp("logs")
    original = config.LOG_DIR
    config.LOG_DIR = str(log_dir)
    logger = PromptLogger("integration_test")
    config.LOG_DIR = original
    yield logger
    logger.close()


# ---------------------------------------------------------------------------
# Extraction schema validation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_extracts_jobs_from_clear_email(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert isinstance(jobs, list)
    assert len(jobs) >= 1


@pytest.mark.integration
def test_extracted_job_has_required_fields(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs, "No jobs extracted from sample email"
    job = jobs[0]
    assert "confidence" in job
    assert "confidence_reason" in job
    assert "source_email_subject" in job


@pytest.mark.integration
def test_extracted_job_confidence_is_valid_value(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs
    assert jobs[0]["confidence"] in ("high", "medium", "low")


@pytest.mark.integration
def test_extracted_job_source_subject_matches_email(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs
    assert jobs[0]["source_email_subject"] == SAMPLE_JOB_EMAIL["subject"]


@pytest.mark.integration
def test_extracts_correct_builder_name(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs
    assert jobs[0].get("builder_name") == "Lennar"


@pytest.mark.integration
def test_extracts_correct_address(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs
    assert "Blue Mist" in (jobs[0].get("address") or "")


@pytest.mark.integration
def test_extracts_correct_lot_and_block(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_JOB_EMAIL, prompt_logger)
    assert jobs
    assert jobs[0].get("lot") == "29"
    assert jobs[0].get("block") == "28"


# ---------------------------------------------------------------------------
# Empty result for non-job emails
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_returns_empty_list_for_non_job_email(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_NO_JOB_EMAIL, prompt_logger)
    assert jobs == [], f"Expected [] for non-job email, got: {jobs}"


# ---------------------------------------------------------------------------
# Multi-job email
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_extracts_multiple_jobs_from_single_email(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_MULTI_JOB_EMAIL, prompt_logger)
    assert len(jobs) >= 2, f"Expected at least 2 jobs, got {len(jobs)}"


@pytest.mark.integration
def test_multi_job_all_have_same_source_subject(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_MULTI_JOB_EMAIL, prompt_logger)
    assert jobs
    for job in jobs:
        assert job["source_email_subject"] == SAMPLE_MULTI_JOB_EMAIL["subject"]


@pytest.mark.integration
def test_multi_job_different_addresses(gemini_client, prompt_logger):
    jobs = _extract_jobs_from_email(gemini_client, SAMPLE_MULTI_JOB_EMAIL, prompt_logger)
    assert len(jobs) >= 2
    addresses = [j.get("address") for j in jobs]
    assert len(set(addresses)) > 1, "Expected different addresses for each job"
