"""
Unit tests for JobDatabase.

Uses a temporary SQLite database for each test — no shared state between tests.
Tests cover pending job creation, approval, edit history, search, and deletion.
"""

import json
import tempfile
from pathlib import Path

import pytest

from database import JobDatabase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> JobDatabase:
    """Fresh database in a temp directory for each test."""
    return JobDatabase(db_path=str(tmp_path / "test_jobs.db"))


def _make_job(**overrides) -> dict:
    base = {
        "builder_name": "Acme Builders",
        "community": "Riverside",
        "type_of_job": "Survey",
        "address": "123 Main St",
        "lot": "1",
        "block": "A",
        "confidence": "high",
        "confidence_reason": "All fields clearly stated",
        "source_email_subject": "Job Order #001",
    }
    return {**base, **overrides}


def _make_email_data() -> dict:
    return {
        "id": "email-abc",
        "subject": "Job Order #001",
        "from": "builder@example.com",
        "receivedDateTime": "2026-04-01T10:00:00Z",
        "body": "Please survey lot 1 block A.",
    }


# ---------------------------------------------------------------------------
# pending_jobs
# ---------------------------------------------------------------------------

class TestSavePendingJob:
    def test_returns_integer_id(self, db: JobDatabase) -> None:
        job_id = db.save_pending_job(_make_job(), _make_email_data())
        assert isinstance(job_id, int)
        assert job_id > 0

    def test_stores_all_fields(self, db: JobDatabase) -> None:
        job = _make_job()
        db.save_pending_job(job, _make_email_data())
        pending = db.get_all_pending_jobs()
        assert len(pending) == 1
        assert pending[0]["builder_name"] == "Acme Builders"
        assert pending[0]["confidence"] == "high"

    def test_job_data_stored_as_parsed_dict(self, db: JobDatabase) -> None:
        db.save_pending_job(_make_job(), _make_email_data())
        pending = db.get_all_pending_jobs()
        assert isinstance(pending[0]["job_data"], dict)
        assert isinstance(pending[0]["email_data"], dict)

    def test_null_fields_stored_correctly(self, db: JobDatabase) -> None:
        job = _make_job(builder_name=None, lot=None)
        db.save_pending_job(job, _make_email_data())
        pending = db.get_all_pending_jobs()
        assert pending[0]["builder_name"] is None
        assert pending[0]["lot"] is None


class TestGetAllPendingJobs:
    def test_returns_empty_list_when_no_jobs(self, db: JobDatabase) -> None:
        assert db.get_all_pending_jobs() == []

    def test_returns_multiple_jobs_ordered_asc(self, db: JobDatabase) -> None:
        db.save_pending_job(_make_job(source_email_subject="First"), _make_email_data())
        db.save_pending_job(_make_job(source_email_subject="Second"), _make_email_data())
        pending = db.get_all_pending_jobs()
        assert len(pending) == 2
        assert pending[0]["source_email_subject"] == "First"


class TestDeletePendingJob:
    def test_removes_job_from_pending(self, db: JobDatabase) -> None:
        job_id = db.save_pending_job(_make_job(), _make_email_data())
        db.delete_pending_job(job_id)
        assert db.get_all_pending_jobs() == []

    def test_delete_nonexistent_id_does_not_raise(self, db: JobDatabase) -> None:
        db.delete_pending_job(9999)  # should not raise


# ---------------------------------------------------------------------------
# approved_jobs
# ---------------------------------------------------------------------------

class TestApproveJob:
    def test_returns_integer_id(self, db: JobDatabase) -> None:
        job_id = db.approve_job(_make_job())
        assert isinstance(job_id, int)
        assert job_id > 0

    def test_approved_job_appears_in_get_all(self, db: JobDatabase) -> None:
        db.approve_job(_make_job())
        approved = db.get_all_approved_jobs()
        assert len(approved) == 1
        assert approved[0]["builder_name"] == "Acme Builders"

    def test_editor_notes_stored(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(), editor_notes="Fixed lot number", approved_by="jithin")
        approved = db.get_all_approved_jobs()
        assert approved[0]["editor_notes"] == "Fixed lot number"
        assert approved[0]["approved_by"] == "jithin"

    def test_approved_jobs_ordered_desc(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(source_email_subject="First"))
        db.approve_job(_make_job(source_email_subject="Second"))
        approved = db.get_all_approved_jobs()
        assert approved[0]["source_email_subject"] == "Second"


# ---------------------------------------------------------------------------
# edit_history
# ---------------------------------------------------------------------------

class TestSaveEdit:
    def test_edit_recorded_for_approved_job(self, db: JobDatabase) -> None:
        job_id = db.approve_job(_make_job())
        db.save_edit(job_id, "lot", "1", "2", edited_by="jithin")
        history = db.get_job_edit_history(job_id)
        assert len(history) == 1
        assert history[0]["field_name"] == "lot"
        assert history[0]["old_value"] == "1"
        assert history[0]["new_value"] == "2"

    def test_multiple_edits_ordered_asc(self, db: JobDatabase) -> None:
        job_id = db.approve_job(_make_job())
        db.save_edit(job_id, "lot", "1", "2")
        db.save_edit(job_id, "address", "123 Main St", "456 Oak Ave")
        history = db.get_job_edit_history(job_id)
        assert len(history) == 2
        assert history[0]["field_name"] == "lot"
        assert history[1]["field_name"] == "address"

    def test_returns_empty_history_for_uneditied_job(self, db: JobDatabase) -> None:
        job_id = db.approve_job(_make_job())
        assert db.get_job_edit_history(job_id) == []


# ---------------------------------------------------------------------------
# search_jobs
# ---------------------------------------------------------------------------

class TestSearchJobs:
    def test_search_by_builder(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(builder_name="Acme Builders"))
        db.approve_job(_make_job(builder_name="Other Corp"))
        results = db.search_jobs(builder="acme")
        assert len(results) == 1
        assert results[0]["builder_name"] == "Acme Builders"

    def test_search_by_community(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(community="Riverside"))
        db.approve_job(_make_job(community="Lakeside"))
        results = db.search_jobs(community="river")
        assert len(results) == 1

    def test_search_by_address(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(address="123 Main St"))
        db.approve_job(_make_job(address="456 Oak Ave"))
        results = db.search_jobs(address="main")
        assert len(results) == 1

    def test_search_with_no_filters_returns_all(self, db: JobDatabase) -> None:
        db.approve_job(_make_job())
        db.approve_job(_make_job())
        assert len(db.search_jobs()) == 2

    def test_search_returns_empty_when_no_match(self, db: JobDatabase) -> None:
        db.approve_job(_make_job(builder_name="Acme"))
        assert db.search_jobs(builder="xyz") == []
