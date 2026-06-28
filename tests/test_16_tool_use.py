"""Cluster 16 — Function calling / tool-use protocol.

Tests (all mock-based — no live API keys required):
  - test_tool_def_to_anthropic_format
  - test_tool_def_to_openai_format
  - test_tool_def_to_gemini_format
  - test_anthropic_chat_with_tools_returns_tool_call
  - test_anthropic_chat_with_tools_returns_text
  - test_openai_chat_with_tools_returns_tool_call
  - test_openai_chat_with_tools_returns_text
  - test_ollama_chat_with_tools
  - test_gemini_chat_with_tools_returns_tool_call
  - test_groq_chat_with_tools_delegates
  - test_format_tool_result_anthropic
  - test_format_tool_result_openai
  - test_format_assistant_tool_use_anthropic
  - test_format_assistant_tool_calls_openai
  - test_tools_cmd_on
  - test_tools_cmd_off
  - test_tools_cmd_list
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_response(json_body: dict, status: int = 200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = json_body
    mock.raise_for_status = MagicMock()
    return mock


# ── ToolDef wire-format conversions ──────────────────────────────────────────

def test_tool_def_to_anthropic_format():
    from app.core.tool_schema import BUILTIN_TOOL_DEFS
    td = BUILTIN_TOOL_DEFS[0]  # read_file
    result = td.to_anthropic()
    assert result["name"] == "read_file"
    assert "input_schema" in result
    assert result["input_schema"]["type"] == "object"
    assert "description" in result
    save("tool_def_to_anthropic_format", True, {"name": result["name"]})


def test_tool_def_to_openai_format():
    from app.core.tool_schema import BUILTIN_TOOL_DEFS
    td = BUILTIN_TOOL_DEFS[0]  # read_file
    result = td.to_openai()
    assert result["type"] == "function"
    assert result["function"]["name"] == "read_file"
    assert "parameters" in result["function"]
    save("tool_def_to_openai_format", True, {"type": result["type"]})


def test_tool_def_to_gemini_format():
    from app.core.tool_schema import BUILTIN_TOOL_DEFS
    td = BUILTIN_TOOL_DEFS[0]  # read_file
    result = td.to_gemini()
    assert result["name"] == "read_file"
    assert "parameters" in result
    assert "description" in result
    save("tool_def_to_gemini_format", True, {"name": result["name"]})


# ── AnthropicClient.chat_with_tools ──────────────────────────────────────────

def test_anthropic_chat_with_tools_returns_tool_call():
    from codex.app.llm_client import AnthropicClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body = {
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01ABC",
                "name": "read_file",
                "input": {"path": "README.md"},
            }
        ],
        "usage": {"input_tokens": 50, "output_tokens": 20},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "read the README"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["id"] == "toolu_01ABC"
    assert tool_calls[0]["input"] == {"path": "README.md"}
    save("anthropic_chat_with_tools_returns_tool_call", True, {"tool": tool_calls[0]["name"]})


def test_anthropic_chat_with_tools_returns_text():
    from codex.app.llm_client import AnthropicClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body = {
        "content": [{"type": "text", "text": "Hello from Claude"}],
        "usage": {"input_tokens": 40, "output_tokens": 15},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == "Hello from Claude"
    assert tool_calls == []
    save("anthropic_chat_with_tools_returns_text", True, {"text_len": len(text)})


# ── OpenAIClient.chat_with_tools ──────────────────────────────────────────────

def test_openai_chat_with_tools_returns_tool_call():
    from codex.app.llm_client import OpenAIClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    body = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_XYZ",
                    "type": "function",
                    "function": {
                        "name": "list_dir",
                        "arguments": json.dumps({"path": "."}),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 60, "completion_tokens": 25},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "list the workspace"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "list_dir"
    assert tool_calls[0]["id"] == "call_XYZ"
    assert tool_calls[0]["input"] == {"path": "."}
    save("openai_chat_with_tools_returns_tool_call", True, {"tool": tool_calls[0]["name"]})


def test_openai_chat_with_tools_returns_text():
    from codex.app.llm_client import OpenAIClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    body = {
        "choices": [{"message": {"content": "Hello from GPT", "tool_calls": None}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 10},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == "Hello from GPT"
    assert tool_calls == []
    save("openai_chat_with_tools_returns_text", True, {"text_len": len(text)})


# ── OllamaClient.chat_with_tools ─────────────────────────────────────────────

def test_ollama_chat_with_tools():
    from codex.app.llm_client import OllamaClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = OllamaClient(model="llama3.2")
    body = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_ollama_1",
                "function": {
                    "name": "run_command",
                    "arguments": {"command": "ls"},
                },
            }],
        },
        "prompt_eval_count": 20,
        "eval_count": 8,
    }
    with patch("httpx.post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "list files"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "run_command"
    assert tool_calls[0]["input"] == {"command": "ls"}
    save("ollama_chat_with_tools", True, {"tool": tool_calls[0]["name"]})


# ── GeminiClient.chat_with_tools ─────────────────────────────────────────────

def test_gemini_chat_with_tools_returns_tool_call():
    from codex.app.llm_client import GeminiClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = GeminiClient(model="gemini-1.5-flash-latest", api_key="AIza-test")
    body = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "fetch_url",
                        "args": {"url": "https://example.com"},
                    }
                }]
            }
        }],
        "usageMetadata": {"promptTokenCount": 45, "candidatesTokenCount": 18},
    }
    with patch("httpx.post", return_value=_make_mock_response(body)):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "fetch the example page"}],
            tools=BUILTIN_TOOL_DEFS,
        )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "fetch_url"
    assert tool_calls[0]["input"] == {"url": "https://example.com"}
    assert "id" in tool_calls[0]
    save("gemini_chat_with_tools_returns_tool_call", True, {"tool": tool_calls[0]["name"]})


# ── GroqClient.chat_with_tools ───────────────────────────────────────────────

def test_groq_chat_with_tools_delegates():
    """GroqClient.chat_with_tools() delegates to inner OpenAIClient."""
    from codex.app.llm_client import GroqClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = GroqClient(model="llama-3.3-70b-versatile", api_key="gsk_test")

    expected_text = "Hello from Groq"
    expected_calls: list[dict] = []

    mock_inner = MagicMock()
    mock_inner.chat_with_tools.return_value = (expected_text, expected_calls)
    mock_inner.last_usage.prompt_tokens = 55
    mock_inner.last_usage.completion_tokens = 22

    client._inner = mock_inner

    text, tool_calls = client.chat_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=BUILTIN_TOOL_DEFS,
    )
    mock_inner.chat_with_tools.assert_called_once()
    assert text == expected_text
    assert tool_calls == expected_calls
    assert client.last_usage == mock_inner.last_usage
    save("groq_chat_with_tools_delegates", True, {"delegated": True})


# ── tool_result_formatter ────────────────────────────────────────────────────

def test_format_tool_result_anthropic():
    from app.core.tool_result_formatter import format_tool_result_anthropic
    result = format_tool_result_anthropic("toolu_01", "file contents here")
    assert result["role"] == "user"
    content = result["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "tool_result"
    assert content[0]["tool_use_id"] == "toolu_01"
    assert content[0]["content"] == "file contents here"
    save("format_tool_result_anthropic", True, {})


def test_format_tool_result_openai():
    from app.core.tool_result_formatter import format_tool_result_openai
    result = format_tool_result_openai("call_XYZ", "read_file", "file contents")
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_XYZ"
    assert result["name"] == "read_file"
    assert result["content"] == "file contents"
    save("format_tool_result_openai", True, {})


def test_format_assistant_tool_use_anthropic():
    from app.core.tool_result_formatter import format_assistant_tool_use_anthropic
    tool_calls = [{"id": "toolu_01", "name": "read_file", "input": {"path": "foo.py"}}]
    result = format_assistant_tool_use_anthropic(tool_calls)
    assert result["role"] == "assistant"
    blocks = result["content"]
    assert len(blocks) == 1
    assert blocks[0]["type"] == "tool_use"
    assert blocks[0]["id"] == "toolu_01"
    assert blocks[0]["name"] == "read_file"
    assert blocks[0]["input"] == {"path": "foo.py"}
    save("format_assistant_tool_use_anthropic", True, {})


def test_format_assistant_tool_calls_openai():
    from app.core.tool_result_formatter import format_assistant_tool_calls_openai
    tool_calls = [{"id": "call_1", "name": "list_dir", "input": {"path": "."}}]
    result = format_assistant_tool_calls_openai(tool_calls)
    assert result["role"] == "assistant"
    assert result["content"] is None
    tcs = result["tool_calls"]
    assert len(tcs) == 1
    assert tcs[0]["id"] == "call_1"
    assert tcs[0]["type"] == "function"
    assert tcs[0]["function"]["name"] == "list_dir"
    parsed_args = json.loads(tcs[0]["function"]["arguments"])
    assert parsed_args == {"path": "."}
    save("format_assistant_tool_calls_openai", True, {})


# ── /tools command ────────────────────────────────────────────────────────────

def _make_settings():
    from cli.commands.settings import SettingsCommands
    from app.core.config import AppConfig
    cfg = AppConfig()
    cfg.tool_use_enabled = False
    mgr = MagicMock()
    return SettingsCommands(cfg, mgr), cfg, mgr


def test_tools_cmd_on(capsys):
    cmd, cfg, mgr = _make_settings()
    cmd.cmd_tools(["on"])
    assert cfg.tool_use_enabled is True
    mgr.save.assert_called_once_with(cfg)
    out = capsys.readouterr().out
    assert "enabled" in out.lower()
    save("tools_cmd_on", True, {})


def test_tools_cmd_off(capsys):
    cmd, cfg, mgr = _make_settings()
    cfg.tool_use_enabled = True
    cmd.cmd_tools(["off"])
    assert cfg.tool_use_enabled is False
    mgr.save.assert_called_once_with(cfg)
    out = capsys.readouterr().out
    assert "disabled" in out.lower()
    save("tools_cmd_off", True, {})


def test_tools_cmd_list(capsys):
    cmd, cfg, mgr = _make_settings()
    cmd.cmd_tools(["list"])
    out = capsys.readouterr().out
    # All 5 built-in tool names must appear
    for name in ("read_file", "write_file", "list_dir", "run_command", "fetch_url"):
        assert name in out, f"Tool '{name}' not found in /tools list output"
    save("tools_cmd_list", True, {"tools_listed": 5})
