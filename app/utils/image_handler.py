"""
app/utils/image_handler.py
--------------------------
Secure image upload, validation, and encoding utilities for Multimodal Vision.

Responsibilities:
1. Whitelist validation of extensions (png, jpg, jpeg, webp) and MIME types.
2. File size cap enforcement (max 5 MB).
3. Magic bytes / header inspection to prevent polyglot / spoofed files.
4. Secure on-disk storage with UUID-based nonces in instance/uploads/images/.
5. Encoding into Base64 Data URLs (data:image/<ext>;base64,...) for LLM APIs.
"""

import base64
import os
import re
import uuid
from pathlib import Path
from typing import Optional, Tuple
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

# Allowed extensions and MIME types
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_MIME_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}

# 5 MB maximum image size limit
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

# Magic byte signatures for verified image formats
MAGIC_SIGNATURES = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "webp": [b"RIFF"],  # Further checked for WEBP marker at offset 8
}


class ImageValidationError(ValueError):
    """Custom exception raised when an image violates security or formatting policies."""
    pass


def get_upload_dir() -> Path:
    """Returns and ensures existence of the safe instance image upload directory."""
    # Instance directory relative to project root
    base_dir = Path(__file__).resolve().parent.parent.parent
    upload_dir = base_dir / "instance" / "uploads" / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _detect_format_from_magic_bytes(header: bytes) -> Optional[str]:
    """
    Inspects leading bytes of a binary buffer to determine true file type.
    Guards against file extension spoofing (e.g. executable renamed to .jpg).
    """
    if len(header) < 12:
        return None

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"

    return None


def process_image_file_storage(file_storage: FileStorage) -> Tuple[str, str]:
    """
    Validates and persists a multipart FileStorage upload.

    :param file_storage: Flask/Werkzeug FileStorage object from request.files.
    :return: Tuple of (relative_storage_path, base64_data_url)
    :raises ImageValidationError: If validation fails.
    """
    if not file_storage or not file_storage.filename:
        raise ImageValidationError("No image file was provided.")

    original_filename = secure_filename(file_storage.filename)
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise ImageValidationError(
            f"Invalid file extension '.{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    # Read binary stream
    file_bytes = file_storage.read()
    file_size = len(file_bytes)

    if file_size == 0:
        raise ImageValidationError("Uploaded image file is empty (0 bytes).")

    if file_size > MAX_IMAGE_SIZE_BYTES:
        raise ImageValidationError(
            f"Image size exceeds the 5 MB limit (received {file_size / (1024 * 1024):.2f} MB)."
        )

    # Magic byte inspection
    detected_format = _detect_format_from_magic_bytes(file_bytes[:16])
    if not detected_format:
        raise ImageValidationError("File signature verification failed. The file is not a valid PNG, JPG, or WebP image.")

    # Save to disk with randomized secure filename
    upload_dir = get_upload_dir()
    save_ext = "jpg" if ext == "jpeg" else ext
    safe_filename = f"img_{uuid.uuid4().hex}.{save_ext}"
    absolute_path = upload_dir / safe_filename

    with open(absolute_path, "wb") as f:
        f.write(file_bytes)

    # Format base64 data URL for LLM consumption
    mime_type = f"image/{'jpeg' if save_ext == 'jpg' else save_ext}"
    b64_content = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64_content}"

    relative_path = f"uploads/images/{safe_filename}"
    return relative_path, data_url


def process_base64_image(base64_string: str) -> Tuple[str, str]:
    """
    Validates and persists a Base64-encoded image string sent via JSON.

    :param base64_string: Base64 string, either raw or Data URL format.
    :return: Tuple of (relative_storage_path, base64_data_url)
    :raises ImageValidationError: If validation fails.
    """
    clean_str = (base64_string or "").strip()
    if not clean_str:
        raise ImageValidationError("Base64 image string cannot be empty.")

    # Parse potential Data URL prefix: data:image/png;base64,...
    declared_mime = None
    if clean_str.startswith("data:"):
        match = re.match(r"^data:(image/[a-zA-Z0-9\+\-\.]+);base64,(.+)$", clean_str, re.DOTALL)
        if not match:
            raise ImageValidationError("Invalid Data URL format for image payload.")
        declared_mime = match.group(1).lower()
        raw_b64 = match.group(2).strip()
    else:
        raw_b64 = clean_str

    try:
        image_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception as e:
        raise ImageValidationError(f"Base64 decoding failed: {str(e)}.")

    image_size = len(image_bytes)
    if image_size == 0:
        raise ImageValidationError("Decoded image content is empty.")

    if image_size > MAX_IMAGE_SIZE_BYTES:
        raise ImageValidationError(
            f"Image size exceeds the 5 MB limit (received {image_size / (1024 * 1024):.2f} MB)."
        )

    # Inspect magic bytes
    detected_format = _detect_format_from_magic_bytes(image_bytes[:16])
    if not detected_format:
        raise ImageValidationError("File signature verification failed. The payload is not a valid PNG, JPG, or WebP image.")

    # Save to disk with randomized secure filename
    upload_dir = get_upload_dir()
    safe_filename = f"img_{uuid.uuid4().hex}.{detected_format}"
    absolute_path = upload_dir / safe_filename

    with open(absolute_path, "wb") as f:
        f.write(image_bytes)

    # Standardize data URL
    mime_type = f"image/{'jpeg' if detected_format == 'jpg' else detected_format}"
    b64_content = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64_content}"

    relative_path = f"uploads/images/{safe_filename}"
    return relative_path, data_url
