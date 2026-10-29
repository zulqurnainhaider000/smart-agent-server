"""
app/routes/health.py
--------------------
Health check and status route for connectivity and heartbeat verification.
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
@health_bp.route("/api/health", methods=["GET"])
def health_check():
    """
    Check server status and connectivity.
    Useful for health monitors, container orchestrators, and testing React Native connectivity.
    """
    return jsonify({
        "status": "ok",
        "service": "ai-agent-backend",
        "message": "AI Agent backend service is running smoothly."
    }), 200
