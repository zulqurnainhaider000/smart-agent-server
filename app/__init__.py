"""
app/__init__.py
---------------
Application Factory for the personal AI agent Flask backend.
Initializes the Flask application, database ORM, logging, CORS security policies,
registers error handlers, blueprints, and database CLI commands.
"""

import logging
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import get_config
from app.extensions import db, cors
from app.errors.handlers import register_error_handlers
from app.routes.health import health_bp
from app.routes.agent import agent_bp
from app.services.scheduler import init_scheduler


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    """
    Ensures SQLite enforces foreign key constraints and runs with WAL mode.
    By default in SQLite, foreign keys are DISABLED unless PRAGMA foreign_keys=ON is executed.
    """
    if "sqlite3" in type(dbapi_connection).__module__:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_app(config_object=None) -> Flask:
    """
    Application Factory function.

    :param config_object: Optional configuration class or instance. If None,
                          the appropriate configuration is inferred from FLASK_ENV.
    :return: An initialized Flask application instance.
    """
    app = Flask(__name__)

    # 1. Load configuration
    if config_object is None:
        config_object = get_config()
    app.config.from_object(config_object)

    # 2. Configure structured logging
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] in %(module)s: %(message)s"
    )

    # 3. Initialize Extensions
    db.init_app(app)

    # Configure CORS - Restrict communication to designated origins (e.g. React Native / Metro / Expo)
    allowed_origins = list(app.config.get("CORS_ALLOWED_ORIGINS", []))
    if app.config.get("DEBUG", True):
        allowed_origins.extend([r"^http://localhost(:\d+)?$", r"^http://127\.0\.0\.1(:\d+)?$"])

    cors.init_app(
        app,
        resources={
            r"/api/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept"],
                "supports_credentials": True,
                "max_age": 600,
            }
        }
    )
    app.logger.info(f"Initialized CORS with allowed origins: {allowed_origins}")

    # 4. Import models to register them with SQLAlchemy metadata
    with app.app_context():
        from app import models  # noqa: F401

    # 5. Register error handling middleware
    register_error_handlers(app)

    # 6. Register application blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(agent_bp)

    # 7. Initialize background automation scheduler
    init_scheduler(app)

    # 7. Register database management CLI commands
    @app.cli.command("init-db")
    def init_db_command():
        """CLI command: flask --app app.py init-db"""
        with app.app_context():
            db.create_all()
        app.logger.info("Database schema initialized successfully.")
        print("Database schema initialized successfully.")

    return app
