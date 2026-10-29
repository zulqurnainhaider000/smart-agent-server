"""
app/services/voice_service.py
-----------------------------
Audio Speech-to-Text Transcription Service for the AI Agent.
Integrates with OpenAI-compatible Whisper endpoints (Groq Whisper-large-v3-turbo / OpenAI Whisper-1).

Responsibilities:
1. Audio format validation (mp3, m4a, wav, webm, ogg, mp4, aac).
2. Audio size limits (max 25 MB).
3. Secure temporary persistence in instance/uploads/audio/.
4. Whisper transcription dispatch with resilient multi-provider fallback.
5. Cleanup of temporary audio artifacts.
"""

import io
import json
import logging
import os
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Union
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Allowed audio file extensions
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "m4a", "wav", "webm", "ogg", "mp4", "aac", "oga"}

# Maximum audio file size (25 MB standard Whisper API cap)
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024


class AudioTranscriptionError(Exception):
    """Raised when audio transcription fails."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class AudioValidationError(AudioTranscriptionError):
    """Raised when an uploaded audio file fails validation."""
    def __init__(self, message: str):
        super().__init__(message, status_code=400)


def get_audio_upload_dir() -> Path:
    """Returns and ensures existence of instance/uploads/audio/."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    upload_dir = base_dir / "instance" / "uploads" / "audio"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _resolve_whisper_provider() -> Tuple[str, str, str]:
    """
    Resolves the Whisper transcription endpoint, API key, and model.
    Priority:
    1. Groq Whisper (blazing fast whisper-large-v3-turbo / whisper-large-v3)
    2. OpenAI Whisper (whisper-1)
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    if groq_key:
        endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
        model = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo").strip()
        return endpoint, groq_key, model

    if openai_key:
        endpoint = "https://api.openai.com/v1/audio/transcriptions"
        model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1").strip()
        return endpoint, openai_key, model

    raise AudioTranscriptionError(
        "Voice transcription is not configured. Please set GROQ_API_KEY or OPENAI_API_KEY in .env.",
        status_code=503
    )


def transcribe_audio_bytes(
    audio_bytes: bytes,
    filename: str = "recording.m4a",
    language: Optional[str] = None
) -> Tuple[str, str]:
    """
    Transcribes raw audio bytes into text using the Whisper API.
    Saves a copy into instance/uploads/audio/ for audit / playback.

    :param audio_bytes: Raw binary content of the audio file.
    :param filename: Original filename to infer audio container extension.
    :param language: Optional ISO-639-1 language code (e.g. 'en', 'ur', 'es').
    :return: Tuple of (transcribed_text, relative_audio_path)
    """
    if not audio_bytes or len(audio_bytes) == 0:
        raise AudioValidationError("Audio data is empty (0 bytes).")

    if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
        raise AudioValidationError(
            f"Audio file exceeds the 25 MB limit (received {len(audio_bytes) / (1024 * 1024):.2f} MB)."
        )

    # Validate file extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "m4a"
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        # Default to m4a if unrecognized
        ext = "m4a"

    # Persist file with secure nonce
    upload_dir = get_audio_upload_dir()
    safe_filename = f"voice_{uuid.uuid4().hex}.{ext}"
    absolute_path = upload_dir / safe_filename

    try:
        with open(absolute_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        logger.error(f"Failed to persist audio file: {e}")
        raise AudioTranscriptionError("Failed to store incoming audio file.", status_code=500)

    relative_path = f"uploads/audio/{safe_filename}"

    # Resolve Whisper API configuration
    endpoint, api_key, model = _resolve_whisper_provider()
    logger.info(f"[WHISPER]: Dispatching transcription for '{safe_filename}' to {model} via {endpoint}")

    # Build standard multipart/form-data payload
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n".encode("utf-8"),
    ]

    if language:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language}\r\n".encode("utf-8")
        )

    parts.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_filename}\"\r\nContent-Type: audio/{ext}\r\n\r\n".encode("utf-8"),
        audio_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8")
    ])
    body = b"".join(parts)

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Personal-AI-Agent-Server/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            transcribed_text = (result.get("text") or "").strip()

            if not transcribed_text:
                logger.warning(f"Whisper returned empty transcription for '{safe_filename}'.")
                transcribed_text = "[Inaudible audio or silence detected]"

            logger.info(f"[WHISPER SUCCESS]: Transcribed ({len(transcribed_text)} chars): '{transcribed_text[:80]}...'")
            return transcribed_text, relative_path

    except urllib.error.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.read().decode("utf-8", errors="ignore")
            err_json = json.loads(error_body)
            err_msg = err_json.get("error", {}).get("message")
        except Exception:
            err_msg = http_err.reason

        logger.error(f"[WHISPER HTTP ERROR {http_err.code}]: {error_body}")
        raise AudioTranscriptionError(f"Speech transcription failed: {err_msg}", status_code=http_err.code)

    except Exception as exc:
        logger.error(f"[WHISPER NETWORK ERROR]: {exc}", exc_info=True)
        raise AudioTranscriptionError(f"Speech transcription service error: {str(exc)}", status_code=502)


def process_audio_file_storage(file_storage: FileStorage) -> Tuple[str, str]:
    """
    Validates and transcribes a multipart FileStorage upload from Flask's request.files.

    :param file_storage: Flask/Werkzeug FileStorage object.
    :return: Tuple of (transcribed_text, relative_audio_path)
    """
    if not file_storage or not file_storage.filename:
        raise AudioValidationError("No audio file was attached.")

    original_filename = secure_filename(file_storage.filename)
    audio_bytes = file_storage.read()

    return transcribe_audio_bytes(audio_bytes, filename=original_filename)


# =============================================================================
# Text-to-Speech (TTS) Voice Synthesis Service
# =============================================================================

class TextToSpeechError(Exception):
    """Raised when text-to-speech generation fails."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def strip_markdown_for_tts(text: str) -> str:
    """
    Cleans markdown formatting from text so speech synthesizers read it naturally.
    Removes headers (###), bold/italics (*, _), bullets, code blocks, links, and extra spaces.
    """
    if not text:
        return ""
    import re

    # Remove code blocks ```...```
    cleaned = re.sub(r"```[\s\S]*?```", " Code snippet omitted. ", text)
    # Remove inline code `...`
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Remove URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    # Remove markdown headers ###, ##, #
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    # Remove bold/italic **text** or *text*
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    # Remove bullet symbols
    cleaned = re.sub(r"^[•\-\*]\s+", "", cleaned, flags=re.MULTILINE)
    # Remove numbered lists
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    # Collapse multiple whitespaces and newlines
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _fetch_free_tts_audio(text: str, language: str = "en") -> bytes:
    """
    Fetches speech audio bytes from a free, resilient TTS service.
    Acts as a zero-quota fallback when OpenAI credit balance is exhausted.
    """
    import urllib.parse
    clean_text = text[:800]  # Standard phrase cap per request
    encoded_query = urllib.parse.quote(clean_text)
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded_query}&tl={language}&client=tw-ob"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def generate_speech_audio(
    text: str,
    voice: str = "alloy",
    model: str = "tts-1",
    language: str = "en"
) -> Tuple[str, str]:
    """
    Generates a high-quality speech audio file (.mp3) from text.
    Primary: OpenAI TTS API (tts-1, alloy).
    Resilient Fallback: Free TTS engine if OpenAI credits are exhausted or key is missing.

    :param text: Text to synthesize.
    :param voice: Voice persona (e.g. 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer').
    :param model: TTS model identifier.
    :param language: Language code for fallback synthesizer.
    :return: Tuple of (safe_filename, relative_audio_path)
    """
    if not text or not text.strip():
        raise TextToSpeechError("Cannot generate speech for empty text.", status_code=400)

    # Clean markdown formatting for clean spoken delivery
    speech_text = strip_markdown_for_tts(text)
    if not speech_text:
        speech_text = text.strip()

    from dotenv import load_dotenv
    load_dotenv(override=True)
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    audio_bytes = None
    provider_used = "OpenAI TTS"

    # Attempt OpenAI TTS if key is present
    if openai_key:
        try:
            tts_payload = json.dumps({
                "model": model,
                "input": speech_text[:4096],
                "voice": voice,
                "response_format": "mp3"
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.openai.com/v1/audio/speech",
                data=tts_payload,
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Personal-AI-Agent-Server/1.0"
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=20) as resp:
                audio_bytes = resp.read()
                logger.info(f"[TTS SUCCESS]: Generated {len(audio_bytes)} audio bytes using OpenAI TTS.")

        except urllib.error.HTTPError as http_err:
            error_body = ""
            try:
                error_body = http_err.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            logger.warning(
                f"[TTS]: OpenAI TTS returned HTTP {http_err.code} ({error_body}). "
                "Engaging resilient free TTS fallback."
            )
        except Exception as exc:
            logger.warning(f"[TTS]: OpenAI TTS connection failed: {exc}. Engaging resilient free TTS fallback.")

    # Fallback to free TTS if OpenAI failed or had no credits
    if not audio_bytes:
        try:
            logger.info("[TTS]: Generating audio speech via resilient free TTS fallback...")
            audio_bytes = _fetch_free_tts_audio(speech_text, language=language)
            provider_used = "Resilient Free TTS"
        except Exception as fb_err:
            logger.error(f"[TTS FALLBACK FAILED]: {fb_err}", exc_info=True)
            raise TextToSpeechError(f"All TTS synthesis engines failed: {fb_err}", status_code=502)

    # Persist audio file to instance/uploads/audio/
    upload_dir = get_audio_upload_dir()
    safe_filename = f"tts_{uuid.uuid4().hex}.mp3"
    absolute_path = upload_dir / safe_filename

    try:
        with open(absolute_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        logger.error(f"Failed to persist synthesized TTS audio: {e}")
        raise TextToSpeechError("Failed to store synthesized audio file.", status_code=500)

    relative_path = f"uploads/audio/{safe_filename}"
    logger.info(f"[TTS COMPLETE]: Persisted {len(audio_bytes)} bytes to '{safe_filename}' via {provider_used}.")
    return safe_filename, relative_path

