"""
Database module for storing approved job orders.

Provides SQLite persistence for job orders after they have been reviewed and approved
through the web UI. Maintains an audit trail of all edits made during the review process.

Schema:
    pending_jobs: Jobs awaiting review and approval
    approved_jobs: Final approved job records
    edit_history: Audit trail of all edits made before approval
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class JobDatabase:
    """SQLite database for approved job orders and edit history.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "res/jobs.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    builder_name TEXT,
                    community TEXT,
                    type_of_job TEXT,
                    address TEXT,
                    lot TEXT,
                    block TEXT,
                    confidence TEXT NOT NULL,
                    confidence_reason TEXT NOT NULL,
                    source_email_subject TEXT NOT NULL,
                    email_data TEXT NOT NULL,
                    job_data TEXT NOT NULL,
                    extracted_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approved_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    builder_name TEXT,
                    community TEXT,
                    type_of_job TEXT,
                    address TEXT,
                    lot TEXT,
                    block TEXT,
                    confidence TEXT NOT NULL,
                    confidence_reason TEXT NOT NULL,
                    source_email_subject TEXT NOT NULL,
                    original_extraction TEXT NOT NULL,
                    editor_notes TEXT,
                    approved_at TEXT NOT NULL,
                    approved_by TEXT DEFAULT 'system'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edit_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    edited_at TEXT NOT NULL,
                    edited_by TEXT DEFAULT 'system',
                    FOREIGN KEY (job_id) REFERENCES approved_jobs(id)
                )
            """)
            conn.commit()

    def save_pending_job(
        self, job_data: dict[str, Any], email_data: dict[str, Any]
    ) -> int:
        """Save a pending job to the database.

        Args:
            job_data: Extracted job dictionary with all fields.
            email_data: Source email metadata (subject, from, date, body, etc.).

        Returns:
            The database ID of the newly inserted pending job.
        """
        extracted_at = datetime.now(timezone.utc).isoformat()
        job_json = json.dumps(job_data)
        email_json = json.dumps(email_data)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_jobs (
                    builder_name, community, type_of_job, address, lot, block,
                    confidence, confidence_reason, source_email_subject,
                    email_data, job_data, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_data.get("builder_name"),
                    job_data.get("community"),
                    job_data.get("type_of_job"),
                    job_data.get("address"),
                    job_data.get("lot"),
                    job_data.get("block"),
                    job_data.get("confidence", "unknown"),
                    job_data.get("confidence_reason", ""),
                    job_data.get("source_email_subject", ""),
                    email_json,
                    job_json,
                    extracted_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_all_pending_jobs(self) -> list[dict[str, Any]]:
        """Fetch all pending jobs from the database.

        Returns:
            List of pending job dictionaries with job data and email data parsed.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM pending_jobs ORDER BY extracted_at ASC
                """
            )
            results = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                # Parse JSON fields
                row_dict["job_data"] = json.loads(row_dict["job_data"])
                row_dict["email_data"] = json.loads(row_dict["email_data"])
                results.append(row_dict)
            return results

    def delete_pending_job(self, pending_job_id: int) -> None:
        """Delete a pending job from the database.

        Args:
            pending_job_id: Database ID of the pending job to delete.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_jobs WHERE id = ?", (pending_job_id,))
            conn.commit()

    def approve_job(
        self,
        job_data: dict[str, Any],
        editor_notes: Optional[str] = None,
        approved_by: str = "system",
    ) -> int:
        """Save an approved job to the database.

        Args:
            job_data: Extracted job dictionary with all fields.
            editor_notes: Optional notes from the reviewer explaining any changes.
            approved_by: Username or identifier of the person approving.

        Returns:
            The database ID of the newly inserted job.
        """
        original_extraction = json.dumps(job_data)
        approved_at = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO approved_jobs (
                    builder_name, community, type_of_job, address, lot, block,
                    confidence, confidence_reason, source_email_subject,
                    original_extraction, editor_notes, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_data.get("builder_name"),
                    job_data.get("community"),
                    job_data.get("type_of_job"),
                    job_data.get("address"),
                    job_data.get("lot"),
                    job_data.get("block"),
                    job_data.get("confidence", "unknown"),
                    job_data.get("confidence_reason", ""),
                    job_data.get("source_email_subject", ""),
                    original_extraction,
                    editor_notes,
                    approved_at,
                    approved_by,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def save_edit(
        self,
        job_id: int,
        field_name: str,
        old_value: Any,
        new_value: Any,
        edited_by: str = "system",
    ) -> None:
        """Record an edit made to a job before approval.

        Args:
            job_id: Database ID of the approved job.
            field_name: Name of the field that was edited.
            old_value: Original value before edit.
            new_value: New value after edit.
            edited_by: Username or identifier of the person making the edit.
        """
        edited_at = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO edit_history (
                    job_id, field_name, old_value, new_value, edited_at, edited_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, field_name, str(old_value), str(new_value), edited_at, edited_by),
            )
            conn.commit()

    def get_all_approved_jobs(self) -> list[dict[str, Any]]:
        """Fetch all approved jobs from the database.

        Returns:
            List of job dictionaries with all fields plus approval metadata.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM approved_jobs ORDER BY approved_at DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_job_edit_history(self, job_id: int) -> list[dict[str, Any]]:
        """Fetch the edit history for a specific job.

        Args:
            job_id: Database ID of the approved job.

        Returns:
            List of edit records for the job.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM edit_history WHERE job_id = ? ORDER BY edited_at ASC
                """,
                (job_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def search_jobs(
        self,
        builder: Optional[str] = None,
        community: Optional[str] = None,
        address: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search approved jobs by builder, community, or address.

        Args:
            builder: Filter by builder name (partial match, case-insensitive).
            community: Filter by community name (partial match, case-insensitive).
            address: Filter by address (partial match, case-insensitive).

        Returns:
            List of matching job dictionaries.
        """
        query = "SELECT * FROM approved_jobs WHERE 1=1"
        params: list[str] = []

        if builder:
            query += " AND builder_name LIKE ?"
            params.append(f"%{builder}%")
        if community:
            query += " AND community LIKE ?"
            params.append(f"%{community}%")
        if address:
            query += " AND address LIKE ?"
            params.append(f"%{address}%")

        query += " ORDER BY approved_at DESC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
