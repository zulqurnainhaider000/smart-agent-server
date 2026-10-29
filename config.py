"""
config.py
---------
Configuration management for the AI Agent Flask application.
Securely loads environment variables using python-dotenv and provides
environment-specific settings (Development, Production, Testing).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Explicitly load .env from the project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Ensure instance directory exists for SQLite storage
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    """Base configuration shared across environments."""

    # Server network settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))

    # Secret key for cryptographic signing & session security
    SECRET_KEY = os.getenv("SECRET_KEY")

    # CORS configuration: trusted client origins (e.g. React Native Metro, Expo, or Web)
    _raw_cors = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8081,http://127.0.0.1:8081,http://localhost:8082,http://127.0.0.1:8082,http://localhost:8083,http://127.0.0.1:8083,http://localhost:19006,http://localhost:3000"
    )
    CORS_ALLOWED_ORIGINS = [
        origin.strip() for origin in _raw_cors.split(",") if origin.strip()
    ]

    # Database Configuration (Flask-SQLAlchemy + SQLite)
    _default_sqlite_path = (INSTANCE_DIR / "agent.db").as_posix()
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{_default_sqlite_path}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    # Consistent JSON formatting
    JSON_SORT_KEYS = False

    # Uploads, Multimodal Vision & Audio configuration
    MAX_CONTENT_LENGTH = 30 * 1024 * 1024  # 30 MB maximum request payload
    UPLOAD_FOLDER = str(INSTANCE_DIR / "uploads" / "images")
    UPLOAD_AUDIO_FOLDER = str(INSTANCE_DIR / "uploads" / "audio")




class DevelopmentConfig(Config):
    """Development environment configuration."""
    DEBUG = True
    TESTING = False

    # Development-only fallback secret key with a clear warning
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-key-change-in-production")


class ProductionConfig(Config):
    """Production environment configuration with strict security assertions."""
    DEBUG = False
    TESTING = False

    def __init__(self):
        # Strict validation: Fail fast if SECRET_KEY is missing or using the placeholder
        secret = os.getenv("SECRET_KEY")
        if not secret or secret == "dev-insecure-secret-key-change-in-production":
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR:\n"
                "The SECRET_KEY environment variable must be set to a cryptographically strong value in production."
            )


class TestingConfig(Config):
    """Testing environment configuration using in-memory SQLite."""
    DEBUG = True
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    CORS_ALLOWED_ORIGINS = ["*"]


# Environment name to Config class mapping
CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    """Factory function to resolve and instantiate configuration from FLASK_ENV."""
    env = os.getenv("FLASK_ENV", "development").lower()
    config_class = CONFIG_MAP.get(env, DevelopmentConfig)

    # Instantiate ProductionConfig to trigger validation checks
    if config_class is ProductionConfig:
        return ProductionConfig()
    return config_class
