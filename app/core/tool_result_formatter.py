"""Tool result formatters — feed tool results back to each provider's wire format."""
from __future__ import annotations

import json


def format_tool_result_anthropic(tool_use_id: str, result: str) -> dict:
    """User message containing a tool_result block."""
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
    }


def format_assistant_tool_use_anthropic(tool_calls: list[dict]) -> dict:
    """Assistant message containing tool_use content blocks."""
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            }
            for tc in tool_calls
        ],
    }


def format_tool_result_openai(tool_call_id: str, name: str, result: str) -> dict:
    """Tool role message for OpenAI/Groq/Ollama."""
    return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": result}


def format_assistant_tool_calls_openai(tool_calls: list[dict]) -> dict:
    """Assistant message with tool_calls array for OpenAI/Groq/Ollama."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
            }
            for tc in tool_calls
        ],
    }


def format_tool_result_gemini(name: str, result: str) -> dict:
    """User message with functionResponse part for Gemini."""
    return {
        "role": "user",
        "parts": [{"functionResponse": {"name": name, "response": {"result": result}}}],
    }


def format_assistant_function_call_gemini(tool_calls: list[dict]) -> dict:
    """Model message with functionCall parts for Gemini."""
    return {
        "role": "model",
        "parts": [{"functionCall": {"name": tc["name"], "args": tc["input"]}} for tc in tool_calls],
    }
