"""
app/utils/validators.py
-----------------------
Input validation and sanitization utilities.
Ensures incoming data is clean, bounded, and free of dangerous null bytes or control characters
before being persisted to the database.
"""

import re
import unicodedata

# Regex patterns for validation
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Maximum string lengths to prevent Denial of Service (DoS) and database bloating
MAX_MESSAGE_LENGTH = 16384  # 16 KB per message turn
MAX_USERNAME_LENGTH = 32
MAX_EMAIL_LENGTH = 120


def sanitize_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """
    Sanitizes raw text input:
    1. Rejects non-string types.
    2. Strips harmful NULL bytes (C-string termination vulnerabilities).
    3. Normalizes Unicode characters (NFC form).
    4. Strips dangerous ASCII control characters while preserving valid newlines/tabs.
    5. Enforces strict length boundaries.

    :param text: The raw text string.
    :param max_length: Maximum allowed character length.
    :return: Sanitized string.
    :raises ValueError: If validation fails.
    """
    if not isinstance(text, str):
        raise ValueError("Payload content must be a valid string.")

    # 1. Remove dangerous null bytes (\x00)
    cleaned = text.replace("\x00", "")

    # 2. Normalize Unicode to prevent homoglyph and canonical decomposition bypasses
    cleaned = unicodedata.normalize("NFC", cleaned)

    # 3. Remove non-printable control characters (ASCII 0-31 except \t, \n, \r)
    cleaned = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)

    # 4. Strip surrounding whitespace
    cleaned = cleaned.strip()

    if not cleaned:
        raise ValueError("Text content cannot be empty or purely whitespace.")

    # 5. Enforce length limits
    if len(cleaned) > max_length:
        raise ValueError(f"Text content exceeds maximum allowed length of {max_length} characters.")

    return cleaned


def validate_username(username: str) -> str:
    """
    Validates and cleans a username.
    Allows 3-32 alphanumeric characters, dashes, and underscores.
    """
    if not isinstance(username, str):
        raise ValueError("Username must be a string.")

    cleaned = username.strip()
    if not USERNAME_REGEX.match(cleaned):
        raise ValueError(
            "Username must be 3-32 characters and contain only letters, numbers, hyphens, and underscores."
        )
    return cleaned


def validate_email(email: str) -> str:
    """
    Validates and cleans an email address.
    """
    if not isinstance(email, str):
        raise ValueError("Email must be a string.")

    cleaned = email.strip().lower()
    if len(cleaned) > MAX_EMAIL_LENGTH:
        raise ValueError(f"Email exceeds maximum length of {MAX_EMAIL_LENGTH} characters.")

    if not EMAIL_REGEX.match(cleaned):
        raise ValueError("Invalid email address format.")
    return cleaned


def validate_session_id(session_id: str) -> str:
    """
    Validates session/conversation ID format.
    """
    if not isinstance(session_id, str):
        raise ValueError("Session ID must be a string.")

    cleaned = session_id.strip()
    if not SESSION_ID_REGEX.match(cleaned):
        raise ValueError("Session ID must be 1-64 alphanumeric characters, dashes, or underscores.")
    return cleaned
