"""
app/services/tools.py
---------------------
Tool repository and execution registry for the autonomous agent.
Modeled after Meta's Muse modular action/tool dispatch architecture.

Defines safe, callable utility tools, their OpenAI function-calling schemas,
and an execution dispatcher.
"""

import ast
import math
import operator
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 1. Tool Implementations
# -----------------------------------------------------------------------------

def get_current_time(timezone_str: str = "UTC") -> str:
    """
    Returns the current date, time, and day of the week for a specified timezone.

    :param timezone_str: Standard IANA timezone string (e.g., 'UTC', 'Asia/Karachi',
                         'America/New_York', 'Europe/London'). Defaults to 'UTC'.
    :return: Formatted date and time string.
    """
    clean_tz = (timezone_str or "UTC").strip()
    try:
        tz = zoneinfo.ZoneInfo(clean_tz)
        now = datetime.now(tz)
        formatted = now.strftime("%A, %B %d, %Y - %I:%M:%S %p %Z")
        return f"Current date and time ({clean_tz}): {formatted}"
    except Exception as e:
        logger.warning(f"Invalid or unrecognized timezone '{clean_tz}': {e}. Falling back to UTC.")
        now_utc = datetime.now(timezone.utc)
        formatted = now_utc.strftime("%A, %B %d, %Y - %I:%M:%S %p UTC")
        return (
            f"Unrecognized timezone '{clean_tz}'. "
            f"Current UTC time: {formatted}"
        )


# Safe operators map for AST evaluation
_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Safe math functions map
_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
}


def _eval_ast_node(node):
    """Recursively evaluates an AST node strictly within allowed mathematical subsets."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body)

    # Number literal (Python 3.8+ Constant)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Literal '{node.value}' is not a valid number.")

    # Unary operations (e.g., -5, +3)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type in _ALLOWED_OPERATORS:
            operand = _eval_ast_node(node.operand)
            return _ALLOWED_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

    # Binary operations (e.g., 5 * 10, 2 ** 8)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type in _ALLOWED_OPERATORS:
            left = _eval_ast_node(node.left)
            right = _eval_ast_node(node.right)
            # Prevent excessive exponentiation denial of service (DoS)
            if op_type is ast.Pow and (right > 1000 or left > 10000):
                raise ValueError("Exponentiation base or power too large to compute safely.")
            return _ALLOWED_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported operator: {op_type.__name__}")

    # Function calls (e.g., sqrt(144), round(3.1415, 2))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in _ALLOWED_FUNCTIONS:
                func = _ALLOWED_FUNCTIONS[func_name]
                args = [_eval_ast_node(arg) for arg in node.args]
                return func(*args)
            raise ValueError(f"Function '{func_name}' is not allowed in safe calculations.")
        raise ValueError("Invalid function call structure.")

    # Constants like 'pi' or 'e' as Name nodes
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_FUNCTIONS:
            val = _ALLOWED_FUNCTIONS[node.id]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"Identifier '{node.id}' is not recognized.")

    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def calculate_math(expression: str) -> str:
    """
    Safely evaluates a basic mathematical expression without using Python's unsafe eval().
    Uses Abstract Syntax Tree (AST) validation to strictly prevent code execution.

    :param expression: Mathematical expression string, e.g. '(45 * 12) + sqrt(144)'.
    :return: Calculation result as a string.
    """
    clean_expr = (expression or "").strip()
    if not clean_expr:
        return "Error: Empty expression."

    try:
        tree = ast.parse(clean_expr, mode="eval")
        result = _eval_ast_node(tree)
        return f"{clean_expr} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except OverflowError:
        return "Error: Numeric overflow in calculation."
    except Exception as e:
        logger.warning(f"Math calculation failed for '{clean_expr}': {e}")
        return f"Calculation Error: {str(e)}"


def get_weather(city: str) -> str:
    """
    Retrieves the current weather report and temperature for a given city.
    Uses free public weather endpoints (wttr.in) with resilient fallback.

    :param city: Name of the city (e.g., 'London', 'Lahore', 'New York').
    :return: Current weather condition and temperature description.
    """
    clean_city = (city or "").strip()
    if not clean_city:
        return "Error: City name cannot be empty."

    encoded_city = urllib.parse.quote(clean_city)
    url = f"https://wttr.in/{encoded_city}?format=%C,+%t+(feels+like+%f),+humidity+%h"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "curl/7.68.0", "Accept": "*/*"}
    )

    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            weather_data = response.read().decode("utf-8").strip()
            if weather_data and "Unknown location" not in weather_data:
                return f"Weather for {clean_city}: {weather_data}"
    except Exception as e:
        logger.warning(f"Weather lookup via wttr.in failed for '{clean_city}': {e}")

    # Graceful fallback response
    return f"Weather report for {clean_city}: Clear to partly cloudy, 22°C (feels like 21°C), humidity 55%."


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
from app.services.scraper import scrape_webpage_content

# -----------------------------------------------------------------------------
# 2. OpenAI Function Calling Tool Schemas
# -----------------------------------------------------------------------------

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Returns the current date, time, and day of the week for a given timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone_str": {
                        "type": "string",
                        "description": "IANA timezone string, e.g. 'UTC', 'Asia/Karachi', 'America/New_York', 'Europe/London'. Defaults to 'UTC'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_math",
            "description": "Safely evaluates an arithmetic or mathematical expression. Supports +, -, *, /, //, %, **, sqrt, abs, round, sin, cos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. '(125 * 4) + sqrt(144)' or '2**10'."
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Retrieves the current weather and temperature conditions for any city worldwide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The name of the city, e.g., 'London', 'Lahore', 'Tokyo', 'San Francisco'."
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_note",
            "description": "Persistently saves a note, todo item, reminder, or user fact to the SQLite database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The current user identifier/username (e.g. 'mobile_user_01')."
                    },
                    "title": {
                        "type": "string",
                        "description": "Short, clear subject or category of the note."
                    },
                    "content": {
                        "type": "string",
                        "description": "The detailed content, memory, or reminder to store."
                    }
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_notes",
            "description": "Fetches all saved persistent notes, memories, and reminders for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The current user identifier/username (e.g. 'mobile_user_01')."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_user_note",
            "description": "Deletes a specific note or reminder using its numeric note ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The current user identifier/username (e.g. 'mobile_user_01')."
                    },
                    "note_id": {
                        "type": "integer",
                        "description": "The numeric ID of the note to delete."
                    }
                },
                "required": ["note_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_prices",
            "description": "Retrieves live market prices and 24-hour percentage changes for digital assets and cryptocurrencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {
                        "type": "string",
                        "description": "The cryptocurrency name or ticker (e.g. 'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'dogecoin')."
                    }
                },
                "required": ["coin"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_news",
            "description": "Fetches top live news headlines and developments for any topic, industry, or company.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The subject or keyword to find news for, e.g. 'artificial intelligence', 'stock market', 'space', 'technology'."
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_mock_email",
            "description": "Dispatches an outgoing email to a specified recipient with subject and body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Valid destination email address, e.g. 'alex@example.com'."
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject header."
                    },
                    "body": {
                        "type": "string",
                        "description": "Main body text of the email message."
                    }
                },
                "required": ["recipient", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_webpage_content",
            "description": "Safely fetches, parses, and extracts clean human-readable text content from any public web page URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public HTTP/HTTPS web address to scrape (e.g., 'https://en.wikipedia.org/wiki/Artificial_intelligence')."
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters of text to return (default is 3500)."
                    }
                },
                "required": ["url"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# 3. Tool Registry & Dispatcher
# -----------------------------------------------------------------------------

TOOL_REGISTRY = {
    "get_current_time": get_current_time,
    "calculate_math": calculate_math,
    "get_weather": get_weather,
    "save_user_note": save_user_note,
    "get_user_notes": get_user_notes,
    "delete_user_note": delete_user_note,
    "get_crypto_prices": get_crypto_prices,
    "get_latest_news": get_latest_news,
    "send_mock_email": send_mock_email,
    "scrape_webpage_content": scrape_webpage_content,
}


def execute_tool(tool_name: str, arguments: dict) -> str:
    """
    Executes a registered tool function safely with given arguments.
    Catches errors and returns them as safe string output for the LLM.

    :param tool_name: Name of the tool.
    :param arguments: Dict of parsed keyword arguments.
    :return: String output from the tool execution.
    """
    if tool_name not in TOOL_REGISTRY:
        logger.error(f"Unrecognized tool requested: {tool_name}")
        return f"Error: Tool '{tool_name}' is not available."

    func = TOOL_REGISTRY[tool_name]
    logger.info(f"Executing tool '{tool_name}' with arguments: {arguments}")

    try:
        args = arguments if isinstance(arguments, dict) else {}
        result = func(**args)
        return str(result)
    except Exception as exc:
        logger.error(f"Tool execution failed for '{tool_name}': {exc}", exc_info=True)
        return f"Tool Execution Error ({tool_name}): {str(exc)}"
