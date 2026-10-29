"""
app/services/agent_service.py
-----------------------------
Core Agent & LLM service layer modeled after Meta's Muse architecture.
Implements an autonomous ReAct loop:
1. Reason: Analyzes the user's intent.
2. Act: Decides whether to invoke external tools (Function Calling).
3. Observe: Feeds tool outputs back into the conversation context.
4. Synthesize: Produces the final context-aware answer for the user.
"""

import os
import json
import socket
import logging
import urllib.request
import urllib.error
from typing import Tuple, List, Dict

from app.services.tools import OPENAI_TOOLS, execute_tool

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are Muse, an elite, highly intelligent, and professional personal AI assistant. "
    "You possess advanced multimodal vision, voice perception, tool calling, and workflow orchestration capabilities.\n\n"

    "### LANGUAGE & COMMUNICATION STYLE (CRITICAL)\n"
    "• **Language Matching**: Strict rule—always reply in the exact same language/script the user is using. "
    "If the user writes in Roman Urdu (e.g., 'sab se low cost kitna budget ma bana sakta ha'), you MUST reply back in smooth, natural, and friendly Roman Urdu. "
    "If the user writes in English, reply in English.\n"
    "• **Tone**: Be articulate, direct, and conversational. Avoid robotic preambles like 'As an AI...' or 'Here is the data'. Jump straight into the point.\n\n"

    "### STRICT FORMATTING RULES (NO RAW TABLES)\n"
    "• **ABSOLUTE PROHIBITION**: NEVER generate raw markdown grid tables (e.g. `| Col 1 | Col 2 |` or `| --- | --- |`). Tables look messy and break chat layouts.\n"
    "• **HOW TO SHOW DATA/COMPARISONS**: Always convert tabular data, comparisons, or financial breakdowns into clean bullet lists with bold sub-headings.\n"
    "  Example format:\n"
    "  - **Compute Cost**: $2,000 to $3,000 for fine-tuning\n"
    "  - **Storage & Data**: $200 to $400 for datasets and checkpoints\n"
    "• **READABILITY**: Use clean section headers (`###`), bold text for key points, and proper spacing between paragraphs.\n\n"

    "### AVAILABLE CAPABILITIES & TOOLS\n"
    "• You can use tools for time (`get_current_time`), math (`calculate_math`), weather (`get_weather`), persistent memory (`save_user_note`, `get_user_notes`, `delete_user_note`), crypto (`get_crypto_prices`), news (`get_latest_news`), web scraping (`scrape_webpage_content`), and email dispatch (`send_mock_email`).\n"
    "• When tools return data, synthesize the results into a smooth, executive conversational summary rather than raw JSON or data dumps."
)


class LLMServiceError(Exception):
    """Base exception for LLM service issues."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class LLMConfigurationError(LLMServiceError):
    """Raised when required API credentials are not set."""
    def __init__(self, message: str = "LLM provider is not configured. Please set GROQ_API_KEY or OPENAI_API_KEY in .env."):
        super().__init__(message, status_code=503)


class LLMTimeoutError(LLMServiceError):
    """Raised when the LLM provider fails to respond in time."""
    def __init__(self, message: str = "The AI service timed out waiting for a response. Please try again."):
        super().__init__(message, status_code=504)


class LLMRateLimitError(LLMServiceError):
    """Raised when hitting LLM rate limits."""
    def __init__(self, message: str = "The AI service rate limit was exceeded. Please try again in a few moments."):
        super().__init__(message, status_code=429)


def _resolve_llm_provider(is_multimodal: bool = False) -> Tuple[str, str, str]:
    """
    Resolves the LLM API provider based on available environment variables and modality.
    When is_multimodal=True, resolves to a vision-capable model:
    - Groq: GROQ_VISION_MODEL (defaults to 'qwen/qwen3.8-27b')
    - OpenAI: OPENAI_MODEL (defaults to 'gpt-4o-mini')
    - Custom: LLM_VISION_MODEL or LLM_MODEL

    Returns:
        Tuple of (endpoint_url, api_key, model_name)
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    custom_url = os.getenv("LLM_API_BASE_URL", "").strip()
    custom_key = os.getenv("LLM_API_KEY", "").strip()

    if groq_key:
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
        if is_multimodal:
            model = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
        else:
            model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        return endpoint, groq_key, model

    if openai_key:
        endpoint = "https://api.openai.com/v1/chat/completions"
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        return endpoint, openai_key, model

    if custom_url and custom_key:
        endpoint = f"{custom_url.rstrip('/')}/chat/completions"
        if is_multimodal:
            model = os.getenv("LLM_VISION_MODEL", os.getenv("LLM_MODEL", "default")).strip()
        else:
            model = os.getenv("LLM_MODEL", "default").strip()
        return endpoint, custom_key, model

    raise LLMConfigurationError()



def _call_llm_api(
    endpoint: str,
    api_key: str,
    payload: dict,
    timeout_seconds: int = 35
) -> dict:
    """
    Executes a single HTTP request to the OpenAI-compatible LLM endpoint.
    Handles network errors, extracts response JSON, and parses provider errors.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Personal-AI-Agent-Server/1.0"
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body)

    except urllib.error.HTTPError as http_err:
        error_code = http_err.code
        error_body = ""
        detail_msg = None
        try:
            error_body = http_err.read().decode("utf-8", errors="ignore")
            error_json = json.loads(error_body)
            detail_msg = error_json.get("error", {}).get("message")
        except Exception:
            pass

        logger.error(f"LLM Provider HTTP Error {error_code}: {error_body}")

        if error_code in (401, 403):
            raise LLMServiceError(
                detail_msg or "LLM API authentication failed. Please verify your API key.",
                status_code=502
            )
        elif error_code == 429:
            raise LLMRateLimitError(
                detail_msg or "The AI service rate limit was exceeded. Please try again in a few moments."
            )
        elif error_code >= 500:
            raise LLMServiceError(
                detail_msg or "The upstream AI service encountered an internal error. Please try again later.",
                status_code=502
            )
        else:
            msg = detail_msg or f"AI Provider error: {http_err.reason}"
            raise LLMServiceError(msg, status_code=error_code)

    except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
        logger.error(f"LLM Provider Network/Timeout Error: {net_err}")
        if isinstance(net_err, (socket.timeout, TimeoutError)) or "timed out" in str(net_err).lower():
            raise LLMTimeoutError()
        raise LLMServiceError("Unable to establish connection to the AI provider. Check network connectivity.", status_code=504)

    except json.JSONDecodeError as json_err:
        logger.error(f"Failed to parse LLM JSON response: {json_err}")
        raise LLMServiceError("Received an invalid response payload from the AI service.", status_code=502)

    except LLMServiceError:
        raise

    except Exception as e:
        logger.critical(f"Unexpected failure during LLM request: {e}", exc_info=True)
        raise LLMServiceError("An unexpected error occurred while communicating with the AI service.", status_code=500)


def generate_agent_response(
    user_message: str,
    history_messages: List[Dict[str, str]] = None,
    current_user_id: str = None,
    image_data: str = None,
    timeout_seconds: int = 35,
    max_tool_iterations: int = 5,
) -> Tuple[str, int]:
    """
    Executes an autonomous ReAct loop with Function Calling and Multimodal Vision support.
    
    1. Sends message history + tool schemas (+ multimodal image payload if provided) to LLM.
    2. If LLM returns tool_calls, safely executes the tools from tools.py.
    3. Feeds tool results back into the conversation context.
    4. Repeats until the agent produces its final answer or reaches max_tool_iterations.

    :param user_message: Sanitized message from the user.
    :param history_messages: Previous conversation turns.
    :param current_user_id: Active user's identifier for user-specific tools.
    :param image_data: Optional base64 data URL (e.g. 'data:image/png;base64,...') or remote image URL.
    :param timeout_seconds: Timeout per network call.
    :param max_tool_iterations: Max tool loop cycles to prevent infinite looping.
    :return: Tuple of (final_agent_response_text, cumulative_tokens_used)
    """
    is_multimodal = bool(image_data and image_data.strip())
    endpoint, api_key, model = _resolve_llm_provider(is_multimodal=is_multimodal)
    system_prompt = os.getenv("AGENT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

    if current_user_id:
        system_prompt += (
            f"\n[Active User Context]: The current interacting user's identifier is '{current_user_id}'. "
            f"When invoking note/memory management tools (save_user_note, get_user_notes, delete_user_note), "
            f"always provide user_id='{current_user_id}'."
        )

    # Construct conversation history
    messages: List[Dict] = [{"role": "system", "content": system_prompt}]

    if history_messages:
        messages.extend(history_messages)

    if is_multimodal:
        text_prompt = (user_message or "").strip() or "Please inspect this image and provide a detailed analysis."
        user_content = [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": image_data.strip()}}
        ]
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_message})

    cumulative_tokens = 0
    iteration = 0


    while iteration < max_tool_iterations:
        iteration += 1
        logger.info(f"ReAct Loop Iteration {iteration}/{max_tool_iterations} for model '{model}'")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "2048")),
            "tools": OPENAI_TOOLS,
            "tool_choice": "auto",
        }

        result = _call_llm_api(endpoint, api_key, payload, timeout_seconds=timeout_seconds)

        choices = result.get("choices", [])
        if not choices:
            raise LLMServiceError("No response choices returned by the AI provider.", status_code=502)

        assistant_message = choices[0].get("message", {})
        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        cumulative_tokens += tokens_used

        tool_calls = assistant_message.get("tool_calls")

        # Case A: Model responded with text directly (No tools needed)
        if not tool_calls:
            agent_text = (assistant_message.get("content") or "").strip()
            logger.info(f"Agent finished reasoning at iteration {iteration}.")
            return agent_text, cumulative_tokens

        # Case B: Model requested one or more tool executions
        logger.info(f"Agent requested {len(tool_calls)} tool call(s) at iteration {iteration}")

        # Append assistant's decision to call tools
        messages.append(assistant_message)

        for tool_call in tool_calls:
            tool_id = tool_call.get("id")
            func_data = tool_call.get("function", {})
            tool_name = func_data.get("name")
            raw_arguments = func_data.get("arguments", "{}")

            try:
                args = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if not isinstance(args, dict):
                    args = {}
            except Exception as parse_err:
                logger.warning(f"Failed to parse tool arguments for {tool_name}: {parse_err}")
                args = {}

            # Fallback auto-inject user_id if omitted for user-specific tools
            if current_user_id and tool_name in ("save_user_note", "get_user_notes", "delete_user_note"):
                if not args.get("user_id"):
                    args["user_id"] = current_user_id

            # Execute the tool safely
            logger.info(f"--> [DISPATCH TOOL]: {tool_name}({args})")
            tool_output = execute_tool(tool_name, args)
            logger.info(f"<-- [TOOL OUTPUT]: {tool_output}")

            # Feed tool observation back to context
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "name": tool_name,
                "content": str(tool_output)
            })

    # If loop limit reached, make one final call to summarize
    logger.warning("Reached maximum tool iterations. Generating final synthesis.")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 1024,
    }
    final_result = _call_llm_api(endpoint, api_key, payload, timeout_seconds=timeout_seconds)
    cumulative_tokens += final_result.get("usage", {}).get("total_tokens", 0)
    final_text = (final_result.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    return final_text, cumulative_tokens


def orchestrate_agent_workflow(
    goal: str,
    user_id: str = "mobile_user_01",
    history_messages: List[Dict] = None,
    image_data: str = None,
) -> Tuple[str, List[Dict], int]:
    """
    Directly invokes the Multi-Step Workflow Orchestrator for complex, multi-tool instructions.
    
    1. Decomposes the goal into ordered sub-steps.
    2. Sequentially invokes tools with task memory chaining.
    3. Synthesizes a unified executive report with an audit trail.

    :param goal: High-level complex user goal.
    :param user_id: User identifier.
    :param history_messages: Optional conversation history.
    :param image_data: Optional base64 data URL for multimodal tasks.
    :return: Tuple of (synthesized_report, execution_log, total_tokens)
    """
    from app.services.orchestrator import execute_orchestrated_workflow
    return execute_orchestrated_workflow(
        goal=goal,
        user_id=user_id,
        history_messages=history_messages,
        image_data=image_data,
    )


