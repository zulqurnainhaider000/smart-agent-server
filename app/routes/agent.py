"""
app/routes/agent.py
-------------------
AI Agent API routes with Multimodal Vision, Voice Input (Whisper STT), and Workflow Orchestration.
Handles message reception, audio transcription, image validation, conversation session resolution,
LLM orchestration, and interaction persistence in SQLite database.
"""

import base64
import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, send_from_directory, abort
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import User, ChatHistory
from app.utils.validators import (
    sanitize_text,
    validate_username,
    validate_session_id,
)
from app.utils.image_handler import (
    ImageValidationError,
    process_image_file_storage,
    process_base64_image,
    get_upload_dir,
)
from app.services.voice_service import (
    transcribe_audio_bytes,
    process_audio_file_storage,
    AudioTranscriptionError,
    AudioValidationError,
    get_audio_upload_dir,
    generate_speech_audio,
    TextToSpeechError,
)
from app.services.agent_service import (
    generate_agent_response,
    orchestrate_agent_workflow,
    LLMServiceError,
)

# Blueprint initialization with /api prefix
agent_bp = Blueprint("agent", __name__, url_prefix="/api")


@agent_bp.route("/agent", methods=["POST"])
def chat_with_agent():
    """
    POST /api/agent
    Main multimodal & voice interaction endpoint for the personal AI agent.

    Accepts:
    1. application/json:
       {
           "user_id": "string",            # Required: public UUID or username
           "message": "string",            # Optional if image or audio is attached
           "image_base64": "string",       # Optional: Base64 data URL
           "audio_base64": "string",       # Optional: Base64 audio content
           "session_id": "string",         # Optional: conversation thread ID
           "orchestrate": false            # Optional: boolean
       }

    2. multipart/form-data:
       - user_id: text field
       - message: text field (optional if audio is uploaded)
       - session_id: text field
       - orchestrate: text field ("true"/"false")
       - image or file: binary file upload (png, jpg, jpeg, webp up to 5MB)
       - audio or voice: binary file upload (m4a, mp3, wav, webm up to 25MB)
    """
    # -------------------------------------------------------------------------
    # 1. Payload & Content-Type Ingestion (JSON or Multipart Form)
    # -------------------------------------------------------------------------
    image_rel_path = None
    image_data_url = None
    audio_rel_path = None
    transcribed_text = None

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        raw_user_id = payload.get("user_id") or payload.get("public_id")
        raw_message = payload.get("message")
        raw_session_id = payload.get("session_id")
        is_orchestrate = bool(payload.get("orchestrate", False))

        # Check for Base64 image payload
        b64_candidate = (
            payload.get("image_base64")
            or payload.get("image")
            or payload.get("image_url")
        )
        if b64_candidate and isinstance(b64_candidate, str) and b64_candidate.strip():
            try:
                image_rel_path, image_data_url = process_base64_image(b64_candidate)
                current_app.logger.info(f"Processed JSON base64 image -> {image_rel_path}")
            except ImageValidationError as img_err:
                return jsonify({
                    "status": "error",
                    "error": {
                        "code": 400,
                        "type": "ImageValidationError",
                        "message": str(img_err)
                    }
                }), 400

        # Check for Base64 audio payload
        b64_audio = payload.get("audio_base64") or payload.get("voice_base64")
        if b64_audio and isinstance(b64_audio, str) and b64_audio.strip():
            try:
                clean_audio = b64_audio.split(",")[-1] if "," in b64_audio else b64_audio
                audio_bytes = base64.b64decode(clean_audio)
                transcribed_text, audio_rel_path = transcribe_audio_bytes(audio_bytes, filename="voice.m4a")
                current_app.logger.info(f"Transcribed JSON base64 audio -> '{transcribed_text}'")
            except (AudioTranscriptionError, AudioValidationError) as audio_err:
                return jsonify({
                    "status": "error",
                    "error": {
                        "code": getattr(audio_err, "status_code", 400),
                        "type": audio_err.__class__.__name__,
                        "message": str(audio_err)
                    }
                }), getattr(audio_err, "status_code", 400)
            except Exception as b64_err:
                return jsonify({
                    "status": "error",
                    "error": {
                        "code": 400,
                        "type": "AudioValidationError",
                        "message": f"Failed to decode base64 audio: {b64_err}"
                    }
                }), 400

    elif request.content_type and "multipart/form-data" in request.content_type:
        raw_user_id = request.form.get("user_id") or request.form.get("public_id")
        raw_message = request.form.get("message")
        raw_session_id = request.form.get("session_id")
        is_orchestrate = request.form.get("orchestrate", "").lower() in ("true", "1", "yes")

        # Check for audio file upload (Whisper STT)
        uploaded_audio = (
            request.files.get("audio")
            or request.files.get("voice")
            or request.files.get("recording")
        )
        if uploaded_audio and uploaded_audio.filename:
            try:
                transcribed_text, audio_rel_path = process_audio_file_storage(uploaded_audio)
                current_app.logger.info(f"Transcribed multipart voice upload -> '{transcribed_text}'")
            except (AudioTranscriptionError, AudioValidationError) as audio_err:
                return jsonify({
                    "status": "error",
                    "error": {
                        "code": getattr(audio_err, "status_code", 400),
                        "type": audio_err.__class__.__name__,
                        "message": str(audio_err)
                    }
                }), getattr(audio_err, "status_code", 400)

        # Check for image file upload
        uploaded_file = request.files.get("image") or request.files.get("file")
        if uploaded_file and uploaded_file.filename:
            try:
                image_rel_path, image_data_url = process_image_file_storage(uploaded_file)
                current_app.logger.info(f"Processed multipart image upload -> {image_rel_path}")
            except ImageValidationError as img_err:
                return jsonify({
                    "status": "error",
                    "error": {
                        "code": 400,
                        "type": "ImageValidationError",
                        "message": str(img_err)
                    }
                }), 400
        else:
            # Check form-field base64
            b64_form = request.form.get("image_base64") or request.form.get("image")
            if b64_form and isinstance(b64_form, str) and b64_form.strip():
                try:
                    image_rel_path, image_data_url = process_base64_image(b64_form)
                    current_app.logger.info(f"Processed form base64 image -> {image_rel_path}")
                except ImageValidationError as img_err:
                    return jsonify({
                        "status": "error",
                        "error": {
                            "code": 400,
                            "type": "ImageValidationError",
                            "message": str(img_err)
                        }
                    }), 400
    else:
        return jsonify({
            "status": "error",
            "error": {
                "code": 400,
                "type": "BadRequest",
                "message": "Content-Type must be 'application/json' or 'multipart/form-data'."
            }
        }), 400

    # -------------------------------------------------------------------------
    # 2. Extract and Validate Required Fields
    # -------------------------------------------------------------------------
    if not raw_user_id or not isinstance(raw_user_id, str) or not raw_user_id.strip():
        return jsonify({
            "status": "error",
            "error": {
                "code": 400,
                "type": "ValidationError",
                "message": "Field 'user_id' (or 'public_id') is required and cannot be empty."
            }
        }), 400

    user_identifier = raw_user_id.strip()

    # If audio was transcribed, use it as the user message
    if transcribed_text:
        if raw_message and raw_message.strip():
            raw_message = f"{raw_message.strip()} (Audio: {transcribed_text})"
        else:
            raw_message = transcribed_text

    # If user provided an image but left prompt empty, assign a sensible vision default
    if not raw_message or not isinstance(raw_message, str) or not raw_message.strip():
        if image_data_url:
            raw_message = "Please analyze this image and explain what you see in detail."
        else:
            return jsonify({
                "status": "error",
                "error": {
                    "code": 400,
                    "type": "ValidationError",
                    "message": "Field 'message' (or an audio voice recording) is required."
                }
            }), 400

    # Sanitize message payload
    try:
        sanitized_message = sanitize_text(raw_message)
    except ValueError as val_err:
        return jsonify({
            "status": "error",
            "error": {
                "code": 400,
                "type": "ValidationError",
                "message": str(val_err)
            }
        }), 400

    # -------------------------------------------------------------------------
    # 3. Resolve Conversation Session ID
    # -------------------------------------------------------------------------
    if raw_session_id:
        try:
            session_id = validate_session_id(str(raw_session_id))
        except ValueError as val_err:
            return jsonify({
                "status": "error",
                "error": {
                    "code": 400,
                    "type": "ValidationError",
                    "message": str(val_err)
                }
            }), 400
    else:
        session_id = str(uuid.uuid4())

    # -------------------------------------------------------------------------
    # 4. Secure User Resolution (Query or Auto-Create)
    # -------------------------------------------------------------------------
    try:
        user = User.query.filter(
            (User.public_id == user_identifier) | (User.username == user_identifier)
        ).first()

        if not user:
            try:
                candidate_username = validate_username(user_identifier)
            except ValueError:
                candidate_username = f"user_{uuid.uuid4().hex[:8]}"

            if User.query.filter_by(username=candidate_username).first():
                candidate_username = f"user_{uuid.uuid4().hex[:8]}"

            try:
                public_id_val = str(uuid.UUID(user_identifier))
            except (ValueError, AttributeError):
                public_id_val = str(uuid.uuid4())

            user = User(
                username=candidate_username,
                public_id=public_id_val,
                is_active=True
            )
            db.session.add(user)
            db.session.commit()
            current_app.logger.info(f"Created new user: {user.username} ({user.public_id})")

    except Exception as db_err:
        db.session.rollback()
        current_app.logger.error(f"User resolution database error: {db_err}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "type": "DatabaseError",
                "message": "Database error while resolving user record."
            }
        }), 500

    # -------------------------------------------------------------------------
    # 5. Fetch Past Conversation History for Multi-Turn Context (Capped at 3 Turns)
    # -------------------------------------------------------------------------
    try:
        # Retrieve the most recent 3 turns to prevent LLM TPM token-overflow
        recent_turns = (
            ChatHistory.query.filter_by(user_id=user.id, session_id=session_id)
            .order_by(ChatHistory.created_at.desc())
            .limit(3)
            .all()
        )
        # Reverse to maintain correct chronological order (oldest to newest) for LLM context
        past_turns = list(reversed(recent_turns))

        history_messages = []
        for turn in past_turns:
            history_messages.extend(turn.to_llm_messages())

    except Exception as fetch_err:
        current_app.logger.warning(f"Could not load conversation history: {fetch_err}")
        history_messages = []

    # -------------------------------------------------------------------------
    # 6. Execute LLM Query via Agent Service (Multimodal / Orchestration)
    # -------------------------------------------------------------------------
    execution_plan = None

    try:
        if is_orchestrate:
            current_app.logger.info(f"Triggering workflow orchestrator for user: {user.username}")
            agent_reply, execution_plan, tokens_used = orchestrate_agent_workflow(
                goal=sanitized_message,
                user_id=user.username,
                history_messages=history_messages,
                image_data=image_data_url,
            )
        else:
            agent_reply, tokens_used = generate_agent_response(
                user_message=sanitized_message,
                history_messages=history_messages,
                current_user_id=user.username,
                image_data=image_data_url,
            )
    except LLMServiceError as llm_err:
        return jsonify({
            "status": "error",
            "error": {
                "code": llm_err.status_code,
                "type": llm_err.__class__.__name__,
                "message": str(llm_err)
            }
        }), llm_err.status_code

    # -------------------------------------------------------------------------
    # 7. Persist Interaction to Database
    # -------------------------------------------------------------------------
    try:
        chat_turn = ChatHistory(
            user_id=user.id,
            session_id=session_id,
            user_message=sanitized_message,
            agent_response=agent_reply,
            image_path=image_rel_path,
            audio_path=audio_rel_path,
            tokens_used=tokens_used
        )
        db.session.add(chat_turn)
        db.session.commit()

        created_iso = (
            chat_turn.created_at.isoformat()
            if chat_turn.created_at
            else datetime.now(timezone.utc).isoformat()
        )

    except Exception as persist_err:
        db.session.rollback()
        current_app.logger.error(f"Failed to save chat interaction: {persist_err}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "type": "DatabaseError",
                "message": "Failed to persist chat record to database."
            }
        }), 500

    # -------------------------------------------------------------------------
    # 8. Optional Speech Synthesis (TTS Voice Mode)
    # -------------------------------------------------------------------------
    response_audio_url = None
    wants_voice = (
        request.endpoint == "agent.voice_chat"
        or (request.is_json and (request.get_json(silent=True) or {}).get("return_audio"))
        or (request.form and request.form.get("return_audio", "").lower() in ("true", "1", "yes"))
    )

    if wants_voice and agent_reply:
        try:
            tts_filename, _ = generate_speech_audio(agent_reply)
            response_audio_url = f"/api/audio/{tts_filename}"
            current_app.logger.info(f"Generated Live Voice response audio -> {response_audio_url}")
        except Exception as tts_err:
            current_app.logger.warning(f"Failed to generate voice mode audio: {tts_err}")

    # -------------------------------------------------------------------------
    # 9. Return Standardized Success Response
    # -------------------------------------------------------------------------
    response_payload = {
        "session_id": chat_turn.session_id,
        "user_message": chat_turn.user_message,
        "agent_response": chat_turn.agent_response,
        "image_path": chat_turn.image_path,
        "audio_path": chat_turn.audio_path,
        "response_audio_url": response_audio_url,
        "transcription": transcribed_text,
        "created_at": created_iso
    }
    if execution_plan is not None:
        response_payload["execution_plan"] = execution_plan

    return jsonify({
        "status": "success",
        "data": response_payload
    }), 200


@agent_bp.route("/voice-chat", methods=["POST"])
def voice_chat():
    """
    POST /api/voice-chat
    Dedicated Speech-to-Speech endpoint for Real-Time Live Voice Conversations.
    Ingests voice audio, transcribes via Whisper, processes tools, synthesizes speech audio,
    and returns both text and speech stream URLs.
    """
    return chat_with_agent()


@agent_bp.route("/images/<path:filename>", methods=["GET"])
def serve_uploaded_image(filename: str):
    """
    GET /api/images/<filename>
    Safely serves uploaded user images from instance/uploads/images/.
    Enforces safe basename validation to prevent directory traversal attacks.
    """
    safe_name = secure_filename(os.path.basename(filename))
    if not safe_name:
        abort(400, description="Invalid image filename requested.")

    upload_dir = get_upload_dir()
    image_file = upload_dir / safe_name

    if not image_file.exists() or not image_file.is_file():
        return jsonify({
            "status": "error",
            "error": {
                "code": 404,
                "type": "NotFound",
                "message": f"Image '{safe_name}' not found."
            }
        }), 404

    return send_from_directory(str(upload_dir), safe_name)


@agent_bp.route("/audio/<path:filename>", methods=["GET"])
def serve_uploaded_audio(filename: str):
    """
    GET /api/audio/<filename>
    Safely serves uploaded user audio recordings from instance/uploads/audio/.
    """
    safe_name = secure_filename(os.path.basename(filename))
    if not safe_name:
        abort(400, description="Invalid audio filename requested.")

    upload_dir = get_audio_upload_dir()
    audio_file = upload_dir / safe_name

    if not audio_file.exists() or not audio_file.is_file():
        return jsonify({
            "status": "error",
            "error": {
                "code": 404,
                "type": "NotFound",
                "message": f"Audio file '{safe_name}' not found."
            }
        }), 404

    return send_from_directory(str(upload_dir), safe_name)


@agent_bp.route("/tts", methods=["POST"])
def text_to_speech():
    """
    POST /api/tts
    Synthesizes speech audio from text using OpenAI TTS with resilient zero-quota fallback.

    Accepts:
    {
        "text": "Text to synthesize",
        "voice": "alloy"  # Optional: alloy, echo, fable, onyx, nova, shimmer
    }
    """
    if not request.is_json:
        return jsonify({
            "status": "error",
            "error": {
                "code": 415,
                "type": "UnsupportedMediaType",
                "message": "Content-Type must be application/json."
            }
        }), 415

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    voice = (body.get("voice") or "alloy").strip()

    if not text:
        return jsonify({
            "status": "error",
            "error": {
                "code": 400,
                "type": "ValidationError",
                "message": "Field 'text' is required and cannot be empty."
            }
        }), 400

    try:
        filename, rel_path = generate_speech_audio(text=text, voice=voice)
        return jsonify({
            "status": "success",
            "data": {
                "filename": filename,
                "audio_url": f"/api/audio/{filename}",
                "relative_path": rel_path
            }
        }), 200

    except TextToSpeechError as tts_err:
        return jsonify({
            "status": "error",
            "error": {
                "code": tts_err.status_code,
                "type": "TextToSpeechError",
                "message": str(tts_err)
            }
        }), tts_err.status_code
    except Exception as exc:
        current_app.logger.error(f"TTS endpoint error: {exc}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "type": "InternalServerError",
                "message": f"Unexpected TTS error: {str(exc)}"
            }
        }), 500
