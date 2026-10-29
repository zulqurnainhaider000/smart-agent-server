"""
app/services/orchestrator.py
----------------------------
Workflow Orchestrator and Multi-Step Task Decomposition Engine.
Modeled after Meta's Muse hierarchical planning and sub-agent coordination layer.

When a user submits a multi-part or complex goal:
1. Decomposes the goal into an ordered execution plan.
2. Coordinates sequential tool dispatches, carrying intermediate context between steps.
3. Synthesizes a unified final result with an execution audit trail.
"""

import json
import logging
from typing import Dict, List, Tuple

from app.services.tools import OPENAI_TOOLS, execute_tool

logger = logging.getLogger(__name__)

# Prompt for decomposing goals into structured plans
PLANNER_SYSTEM_PROMPT = (
    "You are an expert Autonomous Task Orchestrator modeled after Meta's Muse architecture. "
    "Your objective is to decompose a complex user request into an ordered, minimal set of sequential tool steps. "
    "Output ONLY a valid JSON object matching this schema:\n"
    "{\n"
    "  \"goal\": \"summary of user goal\",\n"
    "  \"requires_multi_step\": true,\n"
    "  \"steps\": [\n"
    "    {\n"
    "      \"step_id\": 1,\n"
    "      \"description\": \"What to do in this step\",\n"
    "      \"tool_name\": \"name of the tool from available tools\",\n"
    "      \"arguments\": { \"arg_name\": \"value\" }\n"
    "    }\n"
    "  ]\n"
    "}\n"
    "Available Tools:\n"
    "- get_current_time(timezone_str)\n"
    "- calculate_math(expression)\n"
    "- get_weather(city)\n"
    "- save_user_note(user_id, title, content)\n"
    "- get_user_notes(user_id)\n"
    "- delete_user_note(user_id, note_id)\n"
    "- get_crypto_prices(coin)\n"
    "- get_latest_news(topic)\n"
    "- send_mock_email(recipient, subject, body)\n"
    "- scrape_webpage_content(url)\n"
    "Do not include any conversational markdown or text outside the JSON object."
)


def plan_workflow(goal: str, user_id: str = "mobile_user_01", image_data: str = None) -> Dict:
    """
    Decomposes a complex goal into an actionable multi-step execution plan using the LLM.
    Supports multimodal inputs (e.g. diagrams, receipts, screenshots).

    :param goal: High-level instruction from the user.
    :param user_id: Identifier of the interacting user.
    :param image_data: Optional base64 data URL of attached image.
    :return: Parsed plan dictionary containing ordered execution steps.
    """
    from app.services.agent_service import _resolve_llm_provider, _call_llm_api

    is_multimodal = bool(image_data and image_data.strip())
    endpoint, api_key, model = _resolve_llm_provider(is_multimodal=is_multimodal)

    if is_multimodal:
        user_content = [
            {"type": "text", "text": f"User ID: '{user_id}'\nGoal: {goal}"},
            {"type": "image_url", "image_url": {"url": image_data.strip()}}
        ]
    else:
        user_content = f"User ID: '{user_id}'\nGoal: {goal}"

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1024,
    }

    try:
        response = _call_llm_api(endpoint, api_key, payload, timeout_seconds=25)
        raw_content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        # Clean potential markdown fences (```json ... ```)
        if raw_content.startswith("```"):
            lines = raw_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_content = "\n".join(lines).strip()

        plan = json.loads(raw_content)
        logger.info(f"[ORCHESTRATOR]: Generated plan with {len(plan.get('steps', []))} step(s) for goal: '{goal}'")
        return plan

    except Exception as e:
        logger.warning(f"[ORCHESTRATOR]: Automated planning parsing failed: {e}. Falling back to default plan.")
        return {
            "goal": goal,
            "requires_multi_step": False,
            "steps": []
        }


def execute_orchestrated_workflow(
    goal: str,
    user_id: str = "mobile_user_01",
    history_messages: List[Dict] = None,
    image_data: str = None,
) -> Tuple[str, List[Dict], int]:
    """
    Full Orchestration Pipeline:
    1. Plans the workflow into steps (with multimodal image analysis if attached).
    2. Sequentially executes tools, capturing intermediate state into task memory.
    3. Synthesizes a unified, polished response explaining all actions taken.

    :param goal: User's complex request.
    :param user_id: Current user's identifier.
    :param history_messages: Prior conversation history.
    :param image_data: Optional base64 data URL for multimodal tasks.
    :return: Tuple of (synthesized_response_text, execution_audit_log, total_tokens)
    """
    from app.services.agent_service import _resolve_llm_provider, _call_llm_api

    logger.info(f"[ORCHESTRATOR]: Initiating workflow orchestration for: '{goal}' (has_image={bool(image_data)})")
    plan = plan_workflow(goal, user_id=user_id, image_data=image_data)
    steps = plan.get("steps", [])


    execution_log = []
    task_memory = []
    total_tokens = 0

    # Execute each planned step sequentially
    for step in steps:
        step_id = step.get("step_id")
        desc = step.get("description")
        tool_name = step.get("tool_name")
        args = step.get("arguments", {})

        # Ensure user_id is injected for user-bound tools
        if tool_name in ("save_user_note", "get_user_notes", "delete_user_note"):
            if not args.get("user_id"):
                args["user_id"] = user_id

        # Substitute prior step results if referenced
        for k, v in args.items():
            if isinstance(v, str) and "{step_1_result}" in v and len(execution_log) >= 1:
                args[k] = v.replace("{step_1_result}", execution_log[0]["output"][:500])

        logger.info(f"[ORCHESTRATOR STEP {step_id}]: {desc} -> Calling '{tool_name}'({args})")
        output = execute_tool(tool_name, args)

        log_entry = {
            "step_id": step_id,
            "description": desc,
            "tool_name": tool_name,
            "arguments": args,
            "output": output
        }
        execution_log.append(log_entry)
        task_memory.append(f"Step {step_id} ({desc}):\nResult: {output}\n")

    # Synthesis Step: Have the model generate the final comprehensive report
    endpoint, api_key, model = _resolve_llm_provider()
    memory_context = "\n---\n".join(task_memory)

    synthesis_messages = [
        {
            "role": "system",
            "content": (
                "You are an executive personal AI agent modeled after Meta's Muse architecture. "
                "You have just completed a multi-step autonomous workflow on behalf of the user. "
                "Synthesize the steps taken, the data gathered, and any actions dispatched into a clear, "
                "professional, and beautifully formatted final briefing for the user.\n\n"
                "CRITICAL FORMATTING GUIDELINE: Do NOT generate raw markdown tables (| --- | --- |). "
                "Instead, present data and comparisons using bold section headers (###), clean bullet points, "
                "and bold key terms for maximum readability."
            )
        },
        {
            "role": "user",
            "content": (
                f"User Goal: {goal}\n\n"
                f"Completed Workflow Execution Log:\n{memory_context}\n\n"
                "Please provide the final comprehensive response to the user."
            )
        }
    ]

    payload = {
        "model": model,
        "messages": synthesis_messages,
        "temperature": 0.5,
        "max_tokens": 1500,
    }

    try:
        final_resp = _call_llm_api(endpoint, api_key, payload, timeout_seconds=30)
        final_text = final_resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        total_tokens += final_resp.get("usage", {}).get("total_tokens", 0)
        return final_text, execution_log, total_tokens

    except Exception as e:
        logger.error(f"[ORCHESTRATOR SYNTHESIS ERROR]: {e}", exc_info=True)
        # Fallback synthesis directly from execution log
        fallback_lines = [f"Completed workflow for goal: '{goal}'\n"]
        for item in execution_log:
            fallback_lines.append(f"• **{item['description']}** (Tool: `{item['tool_name']}`): {item['output']}")
        return "\n".join(fallback_lines), execution_log, total_tokens
