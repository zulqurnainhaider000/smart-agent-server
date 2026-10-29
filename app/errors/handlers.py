"""
app/errors/handlers.py
----------------------
Centralized error handling middleware.
Ensures uniform JSON error responses across the API and prevents
internal stack traces, file paths, or sensitive exceptions from leaking to clients.
"""

from flask import jsonify, current_app
from werkzeug.exceptions import HTTPException


def register_error_handlers(app):
    """Registers standard HTTP and catch-all JSON error handlers on the Flask application."""

    @app.errorhandler(400)
    def handle_bad_request(error):
        """Handle 400 Bad Request error."""
        message = getattr(error, "description", "The browser or client sent a request that this server could not understand.")
        return jsonify({
            "status": "error",
            "error": {
                "code": 400,
                "type": "BadRequest",
                "message": message
            }
        }), 400

    @app.errorhandler(404)
    def handle_not_found(error):
        """Handle 404 Not Found error."""
        return jsonify({
            "status": "error",
            "error": {
                "code": 404,
                "type": "NotFound",
                "message": "The requested endpoint or resource was not found on this server."
            }
        }), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """Handle 405 Method Not Allowed error."""
        return jsonify({
            "status": "error",
            "error": {
                "code": 405,
                "type": "MethodNotAllowed",
                "message": "The HTTP method used is not allowed for this endpoint."
            }
        }), 405

    @app.errorhandler(500)
    def handle_internal_server_error(error):
        """
        Handle 500 Internal Server Error.
        Logs the actual error and traceback internally, but returns a sanitized,
        safe message to the client to prevent sensitive data leakage.
        """
        current_app.logger.error(f"Internal Server Error (500): {error}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "type": "InternalServerError",
                "message": "An internal server error occurred. Please try again later."
            }
        }), 500

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        """Handle any other standard Werkzeug HTTP exceptions as uniform JSON."""
        return jsonify({
            "status": "error",
            "error": {
                "code": error.code,
                "type": error.__class__.__name__,
                "message": error.description
            }
        }), error.code

    @app.errorhandler(Exception)
    def handle_unhandled_exception(error):
        """
        Catch-all handler for unhandled exceptions.
        Guarantees that unhandled Python runtime exceptions are logged safely
        and that a generic 500 JSON response is returned without crashing the process
        or exposing traceback details.
        """
        current_app.logger.critical(f"Unhandled Server Exception: {error}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "type": "InternalServerError",
                "message": "An unexpected error occurred. Please try again later."
            }
        }), 500
