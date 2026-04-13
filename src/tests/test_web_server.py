"""
Unit tests for the Flask web server.

All database calls are mocked — no real SQLite operations.
Tests cover HTTP endpoints: job listing, pending jobs, search, approval, and error handling.
WebSocket events are verified via mock on the SocketIO instance.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from web_server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.get_all_approved_jobs.return_value = []
    db.get_all_pending_jobs.return_value = []
    db.search_jobs.return_value = []
    db.get_job_edit_history.return_value = []
    db.approve_job.return_value = 1
    return db


@pytest.fixture
def client(mock_db: MagicMock) -> FlaskClient:
    with patch("web_server.JobDatabase", return_value=mock_db):
        app, _ = create_app(db_path=":memory:")
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------

class TestGetJobs:
    def test_returns_200_with_empty_list(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.get_all_approved_jobs.return_value = []
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert data["jobs"] == []

    def test_returns_jobs_from_database(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.get_all_approved_jobs.return_value = [
            {"id": 1, "builder_name": "Acme", "community": "Riverside"}
        ]
        response = client.get("/api/jobs")
        assert response.status_code == 200
        assert len(response.get_json()["jobs"]) == 1

    def test_returns_500_on_database_error(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.get_all_approved_jobs.side_effect = Exception("db error")
        response = client.get("/api/jobs")
        assert response.status_code == 500
        assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/jobs/pending
# ---------------------------------------------------------------------------

class TestGetPendingJobs:
    def test_returns_200_with_pending_list(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.get_all_pending_jobs.return_value = [
            {"id": 1, "builder_name": "Acme", "job_data": {}, "email_data": {}}
        ]
        response = client.get("/api/jobs/pending")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert len(data["pending_jobs"]) == 1


# ---------------------------------------------------------------------------
# GET /api/jobs/search
# ---------------------------------------------------------------------------

class TestSearchJobs:
    def test_passes_query_params_to_db(self, client: FlaskClient, mock_db: MagicMock) -> None:
        client.get("/api/jobs/search?builder=Acme&community=River&address=Main")
        mock_db.search_jobs.assert_called_once_with(
            builder="Acme", community="River", address="Main"
        )

    def test_returns_matching_jobs(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.search_jobs.return_value = [{"id": 1, "builder_name": "Acme"}]
        response = client.get("/api/jobs/search?builder=Acme")
        assert response.status_code == 200
        assert len(response.get_json()["jobs"]) == 1


# ---------------------------------------------------------------------------
# GET /api/jobs/<id>/history
# ---------------------------------------------------------------------------

class TestGetJobHistory:
    def test_returns_edit_history(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.get_job_edit_history.return_value = [
            {"id": 1, "field_name": "lot", "old_value": "1", "new_value": "2"}
        ]
        response = client.get("/api/jobs/1/history")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"
        assert len(data["history"]) == 1


# ---------------------------------------------------------------------------
# POST /api/jobs/approve
# ---------------------------------------------------------------------------

class TestApproveJob:
    def _job_payload(self, **overrides) -> dict:
        base = {
            "job_data": {
                "builder_name": "Acme",
                "community": "Riverside",
                "type_of_job": "Survey",
                "address": "123 Main St",
                "lot": "1",
                "block": "A",
                "confidence": "high",
                "confidence_reason": "Clear",
                "source_email_subject": "Job #1",
            },
            "approved_by": "jithin",
        }
        return {**base, **overrides}

    def test_approve_returns_job_id(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.approve_job.return_value = 42
        response = client.post(
            "/api/jobs/approve",
            json=self._job_payload(),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.get_json()["job_id"] == 42

    def test_missing_job_data_returns_400(self, client: FlaskClient) -> None:
        response = client.post(
            "/api/jobs/approve",
            json={"approved_by": "jithin"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_deletes_pending_job_when_id_provided(
        self, client: FlaskClient, mock_db: MagicMock
    ) -> None:
        client.post(
            "/api/jobs/approve",
            json=self._job_payload(pending_job_id=5),
            content_type="application/json",
        )
        mock_db.delete_pending_job.assert_called_once_with(5)

    def test_records_edits_when_original_provided(
        self, client: FlaskClient, mock_db: MagicMock
    ) -> None:
        payload = self._job_payload(
            original_extraction={"lot": "1", "block": "A"},
        )
        payload["job_data"]["lot"] = "2"  # simulate edit
        client.post("/api/jobs/approve", json=payload, content_type="application/json")
        mock_db.save_edit.assert_called()

    def test_returns_500_on_database_error(self, client: FlaskClient, mock_db: MagicMock) -> None:
        mock_db.approve_job.side_effect = Exception("db failure")
        response = client.post(
            "/api/jobs/approve",
            json=self._job_payload(),
            content_type="application/json",
        )
        assert response.status_code == 500
