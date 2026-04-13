"""
Web server module for the Email Job Extraction Agent UI.

Provides a Flask web server with SocketIO for real-time updates. Serves the web UI
and exposes API endpoints for job approval, editing, and database queries.

The server runs alongside the extraction agent and broadcasts extraction events
to connected clients via WebSocket.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from database import JobDatabase

logger = logging.getLogger(__name__)

# Global SocketIO instance for broadcasting from main.py
socketio: Optional[SocketIO] = None


def create_app(db_path: str = "res/jobs.db") -> tuple[Flask, SocketIO]:
    """Create and configure the Flask application with SocketIO.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Tuple of (Flask app, SocketIO instance).
    """
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config["SECRET_KEY"] = "email-extraction-secret-key"
    CORS(app)

    sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    db = JobDatabase(db_path)

    # Ensure static directory exists
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)

    # ---------------------------------------------------------------------------
    # HTTP Routes
    # ---------------------------------------------------------------------------

    @app.route("/")
    def index() -> Any:
        """Serve the main UI page."""
        return send_from_directory("static", "index.html")

    @app.route("/api/jobs", methods=["GET"])
    def get_jobs() -> Any:
        """Get all approved jobs from the database."""
        try:
            jobs = db.get_all_approved_jobs()
            return jsonify({"status": "ok", "jobs": jobs})
        except Exception as error:
            logger.error("Failed to fetch jobs: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    @app.route("/api/jobs/pending", methods=["GET"])
    def get_pending_jobs() -> Any:
        """Get all pending jobs from the database."""
        try:
            pending_jobs = db.get_all_pending_jobs()
            return jsonify({"status": "ok", "pending_jobs": pending_jobs})
        except Exception as error:
            logger.error("Failed to fetch pending jobs: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    @app.route("/api/jobs/search", methods=["GET"])
    def search_jobs() -> Any:
        """Search approved jobs by builder, community, or address."""
        builder = request.args.get("builder")
        community = request.args.get("community")
        address = request.args.get("address")

        try:
            jobs = db.search_jobs(builder=builder, community=community, address=address)
            return jsonify({"status": "ok", "jobs": jobs})
        except Exception as error:
            logger.error("Failed to search jobs: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    @app.route("/api/jobs/<int:job_id>/history", methods=["GET"])
    def get_job_history(job_id: int) -> Any:
        """Get the edit history for a specific job."""
        try:
            history = db.get_job_edit_history(job_id)
            return jsonify({"status": "ok", "history": history})
        except Exception as error:
            logger.error("Failed to fetch job history: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    @app.route("/api/attachments/<email_id>/<attachment_name>", methods=["GET"])
    def get_attachment(email_id: str, attachment_name: str) -> Any:
        """Download or view an email attachment.

        Args:
            email_id: Graph API message ID
            attachment_name: Name of the attachment file

        Returns:
            File content with appropriate headers for download/viewing
        """
        try:
            # Import graph client
            from graph import GraphClient
            import base64

            graph = GraphClient()
            attachments = graph.fetch_attachments(email_id)

            # Find matching attachment
            attachment = None
            for att in attachments:
                if att.get("name") == attachment_name:
                    attachment = att
                    break

            if not attachment:
                return jsonify({"status": "error", "message": "Attachment not found"}), 404

            content_type = attachment.get("contentType", "application/octet-stream")
            content_bytes = base64.b64decode(attachment.get("contentBytes", ""))

            # Log for debugging
            logger.info("Serving attachment: %s, Content-Type: %s", attachment_name, content_type)

            # Create response with file content
            from flask import Response
            response = Response(content_bytes, mimetype=content_type)

            # Display PDFs and images inline; download others
            if content_type == "application/pdf" or content_type.startswith("image/"):
                response.headers["Content-Disposition"] = f"inline; filename={attachment_name}"
                logger.info("Set Content-Disposition to inline for %s", attachment_name)
            else:
                response.headers["Content-Disposition"] = f"attachment; filename={attachment_name}"
                logger.info("Set Content-Disposition to attachment for %s", attachment_name)

            return response

        except Exception as error:
            logger.error("Failed to fetch attachment: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    @app.route("/api/jobs/approve", methods=["POST"])
    def approve_job() -> Any:
        """Approve a job and save it to the database.

        Expected JSON body:
        {
            "job_data": {...},
            "editor_notes": "optional notes",
            "approved_by": "username",
            "pending_job_id": integer (optional - if provided, deletes from pending_jobs)
        }
        """
        try:
            data = request.get_json()
            if not data or "job_data" not in data:
                return jsonify({"status": "error", "message": "Missing job_data"}), 400

            job_data = data["job_data"]
            editor_notes = data.get("editor_notes")
            approved_by = data.get("approved_by", "system")
            pending_job_id = data.get("pending_job_id")

            # Track edits if original_extraction is provided
            original = data.get("original_extraction")
            job_id = db.approve_job(job_data, editor_notes, approved_by)

            if original:
                for field in ["builder_name", "community", "type_of_job", "address", "lot", "block"]:
                    old_val = original.get(field)
                    new_val = job_data.get(field)
                    if old_val != new_val:
                        db.save_edit(job_id, field, old_val, new_val, approved_by)

            # Delete from pending_jobs if pending_job_id was provided
            if pending_job_id:
                db.delete_pending_job(pending_job_id)
                logger.info("Deleted pending job %d after approval", pending_job_id)

            # Broadcast approval to all connected clients
            sio.emit("job_approved", {"job_id": job_id, "job_data": job_data, "pending_job_id": pending_job_id})

            return jsonify({"status": "ok", "job_id": job_id})

        except Exception as error:
            logger.error("Failed to approve job: %s", error)
            return jsonify({"status": "error", "message": str(error)}), 500

    # ---------------------------------------------------------------------------
    # WebSocket Events
    # ---------------------------------------------------------------------------

    @sio.on("connect")
    def handle_connect() -> None:
        """Handle client connection."""
        logger.info("Client connected: %s", request.sid)
        emit("connected", {"message": "Connected to extraction agent"})

    @sio.on("disconnect")
    def handle_disconnect() -> None:
        """Handle client disconnection."""
        logger.info("Client disconnected: %s", request.sid)

    return app, sio


def broadcast_extraction_event(event_type: str, data: dict[str, Any]) -> None:
    """Broadcast an extraction event to all connected WebSocket clients.

    Args:
        event_type: Event name (e.g., 'email_processing', 'job_extracted').
        data: Event payload to send to clients.
    """
    global socketio
    if socketio:
        try:
            socketio.emit(event_type, data)
            logger.info("Broadcasted event: %s with data: %s", event_type, str(data)[:100])
        except Exception as error:
            logger.error("Failed to broadcast event %s: %s", event_type, error)


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    """Run the Flask web server.

    Args:
        host: Host address to bind to.
        port: Port number to listen on.
        debug: Enable Flask debug mode.
    """
    global socketio
    app, socketio = create_app()
    logger.info("Starting web server on http://%s:%d", host, port)
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()
