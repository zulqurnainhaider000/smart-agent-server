"""Services package."""
from app.services.agent_service import (
    generate_agent_response,
    orchestrate_agent_workflow,
    LLMServiceError,
    LLMConfigurationError,
    LLMTimeoutError,
    LLMRateLimitError,
)
from app.services.tools import (
    OPENAI_TOOLS,
    TOOL_REGISTRY,
    execute_tool,
    get_current_time,
    calculate_math,
    get_weather,
)
from app.services.note_tools import (
    save_user_note,
    get_user_notes,
    delete_user_note,
)
from app.services.connectors import (
    get_crypto_prices,
    get_latest_news,
    send_mock_email,
)
from app.services.scraper import (
    scrape_webpage_content,
)
from app.services.orchestrator import (
    plan_workflow,
    execute_orchestrated_workflow,
)
from app.services.scheduler import (
    init_scheduler,
    generate_daily_briefing,
    scheduler,
)
from app.services.voice_service import (
    transcribe_audio_bytes,
    process_audio_file_storage,
    AudioTranscriptionError,
    AudioValidationError,
    get_audio_upload_dir,
    generate_speech_audio,
    TextToSpeechError,
    strip_markdown_for_tts,
)


__all__ = [
    "generate_agent_response",
    "orchestrate_agent_workflow",
    "LLMServiceError",
    "LLMConfigurationError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "OPENAI_TOOLS",
    "TOOL_REGISTRY",
    "execute_tool",
    "get_current_time",
    "calculate_math",
    "get_weather",
    "save_user_note",
    "get_user_notes",
    "delete_user_note",
    "get_crypto_prices",
    "get_latest_news",
    "send_mock_email",
    "scrape_webpage_content",
    "plan_workflow",
    "execute_orchestrated_workflow",
    "init_scheduler",
    "generate_daily_briefing",
    "scheduler",
    "transcribe_audio_bytes",
    "process_audio_file_storage",
    "AudioTranscriptionError",
    "AudioValidationError",
    "get_audio_upload_dir",
]

