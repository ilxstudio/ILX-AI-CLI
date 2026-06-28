"""Cluster 21 — Prompt caching (Anthropic) and enhanced tool schema.

Tests:
  - test_token_usage_has_cache_fields
  - test_anthropic_chat_use_cache_adds_cache_control_to_system
  - test_anthropic_chat_use_cache_adds_cache_control_to_last_user_message
  - test_anthropic_headers_include_beta_when_use_cache
  - test_anthropic_headers_no_beta_when_cache_off
  - test_openai_parallel_tool_calls_in_body
  - test_apply_patch_tool_def_schema
  - test_all_builtin_tool_defs_have_descriptions
  - test_token_usage_parses_cache_tokens_from_response
  - test_anthropic_chat_with_tools_use_cache
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


# ── TokenUsage cache fields ───────────────────────────────────────────────────

def test_token_usage_has_cache_fields():
    """TokenUsage dataclass must expose cache_creation_tokens and cache_read_tokens."""
    from codex.app.llm_client_base import TokenUsage
    usage = TokenUsage(
        prompt_tokens=100,
        completion_tokens=50,
        cache_creation_tokens=200,
        cache_read_tokens=150,
    )
    assert usage.cache_creation_tokens == 200
    assert usage.cache_read_tokens == 150
    assert usage.total_tokens == 150  # only prompt + completion
    save("token_usage_has_cache_fields", True, {
        "cache_creation_tokens": usage.cache_creation_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
    })


def test_token_usage_defaults_cache_fields_to_zero():
    """Cache token fields default to 0 for backward compatibility."""
    from codex.app.llm_client_base import TokenUsage
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
    assert usage.cache_creation_tokens == 0
    assert usage.cache_read_tokens == 0
    save("token_usage_defaults_cache_fields_to_zero", True, {})


# ── AnthropicClient cache_control on system ───────────────────────────────────

def test_anthropic_chat_use_cache_adds_cache_control_to_system():
    """When use_cache=True, system is wrapped as a list block with cache_control."""
    from codex.app.llm_client_providers import AnthropicClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body_response = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {
            "input_tokens": 80,
            "output_tokens": 10,
            "cache_creation_input_tokens": 60,
            "cache_read_input_tokens": 0,
        },
    }
    captured_body: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_body.update(json or {})
        return _make_mock_response(body_response)

    with patch.object(client._client, "post", side_effect=fake_post):
        client.chat(
            [{"role": "user", "content": "hi"}],
            system="You are a helpful assistant.",
            use_cache=True,
        )

    system_field = captured_body.get("system")
    assert isinstance(system_field, list), "system should be a list when use_cache=True"
    assert len(system_field) == 1
    block = system_field[0]
    assert block["type"] == "text"
    assert block["text"] == "You are a helpful assistant."
    assert block.get("cache_control") == {"type": "ephemeral"}
    save("anthropic_chat_use_cache_adds_cache_control_to_system", True, {"system_type": "list"})


def test_anthropic_chat_use_cache_adds_cache_control_to_last_user_message():
    """When use_cache=True, cache_control is added to the last user message content."""
    from codex.app.llm_client_providers import AnthropicClient

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body_response = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 5,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 20,
        },
    }
    captured_body: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_body.update(json or {})
        return _make_mock_response(body_response)

    messages = [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "got it"},
        {"role": "user", "content": "second message"},
    ]
    with patch.object(client._client, "post", side_effect=fake_post):
        client.chat(messages, use_cache=True)

    sent_msgs = captured_body.get("messages", [])
    # The last user message (index 2) should have cache_control
    last_user = sent_msgs[2]
    assert last_user["role"] == "user"
    content = last_user["content"]
    assert isinstance(content, list), "Content should be a list with cache_control block"
    assert content[0].get("cache_control") == {"type": "ephemeral"}
    # Earlier user messages must NOT be modified
    first_user = sent_msgs[0]
    assert isinstance(first_user["content"], str), "Earlier messages should remain as strings"
    save("anthropic_chat_use_cache_adds_cache_control_to_last_user_message", True, {})


# ── AnthropicClient headers ───────────────────────────────────────────────────

def test_anthropic_headers_include_beta_when_use_cache():
    """_headers(use_cache=True) must include the prompt-caching beta header."""
    from codex.app.llm_client_providers import AnthropicClient

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    headers = client._headers(use_cache=True)
    assert "anthropic-beta" in headers
    assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"
    save("anthropic_headers_include_beta_when_use_cache", True, {
        "beta_header": headers["anthropic-beta"]
    })


def test_anthropic_headers_no_beta_when_cache_off():
    """_headers() without use_cache must NOT include the beta header."""
    from codex.app.llm_client_providers import AnthropicClient

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    headers = client._headers()
    assert "anthropic-beta" not in headers
    headers_explicit_false = client._headers(use_cache=False)
    assert "anthropic-beta" not in headers_explicit_false
    save("anthropic_headers_no_beta_when_cache_off", True, {})


# ── AnthropicClient cache token parsing ──────────────────────────────────────

def test_token_usage_parses_cache_tokens_from_response():
    """After a cached chat() call, last_usage captures cache token counts."""
    from codex.app.llm_client_providers import AnthropicClient

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body_response = {
        "content": [{"type": "text", "text": "cached response"}],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 300,
        },
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body_response)):
        client.chat([{"role": "user", "content": "hello"}], use_cache=True)

    assert client.last_usage.prompt_tokens == 100
    assert client.last_usage.completion_tokens == 20
    assert client.last_usage.cache_creation_tokens == 500
    assert client.last_usage.cache_read_tokens == 300
    save("token_usage_parses_cache_tokens_from_response", True, {
        "cache_creation": client.last_usage.cache_creation_tokens,
        "cache_read": client.last_usage.cache_read_tokens,
    })


# ── AnthropicClient.chat_with_tools use_cache ────────────────────────────────

def test_anthropic_chat_with_tools_use_cache():
    """chat_with_tools(use_cache=True) sends beta header and cache_control."""
    from codex.app.llm_client_providers import AnthropicClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body_response = {
        "content": [{"type": "text", "text": "no tool needed"}],
        "usage": {
            "input_tokens": 30,
            "output_tokens": 8,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 30,
        },
    }
    captured_headers: dict = {}
    captured_body: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_headers.update(headers or {})
        captured_body.update(json or {})
        return _make_mock_response(body_response)

    with patch.object(client._client, "post", side_effect=fake_post):
        text, tool_calls = client.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            system="You are helpful.",
            tools=BUILTIN_TOOL_DEFS,
            use_cache=True,
        )

    assert "anthropic-beta" in captured_headers
    assert isinstance(captured_body.get("system"), list)
    assert text == "no tool needed"
    assert tool_calls == []
    save("anthropic_chat_with_tools_use_cache", True, {
        "beta_header_present": "anthropic-beta" in captured_headers,
    })


# ── OpenAIClient.chat_with_tools parallel_tool_calls ─────────────────────────

def test_openai_parallel_tool_calls_in_body():
    """OpenAIClient.chat_with_tools() sets parallel_tool_calls=True when tools are provided."""
    from codex.app.llm_client_providers import OpenAIClient
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    body_response = {
        "choices": [{"message": {"content": "Hello", "tool_calls": None}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5},
    }
    captured_body: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_body.update(json or {})
        return _make_mock_response(body_response)

    with patch.object(client._client, "post", side_effect=fake_post):
        client.chat_with_tools(
            [{"role": "user", "content": "hello"}],
            tools=BUILTIN_TOOL_DEFS,
        )

    assert captured_body.get("parallel_tool_calls") is True
    save("openai_parallel_tool_calls_in_body", True, {
        "parallel_tool_calls": captured_body.get("parallel_tool_calls"),
    })


def test_openai_no_parallel_tool_calls_without_tools():
    """OpenAIClient.chat_with_tools() does NOT set parallel_tool_calls when no tools."""
    from codex.app.llm_client_providers import OpenAIClient

    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    body_response = {
        "choices": [{"message": {"content": "Hi", "tool_calls": None}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }
    captured_body: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_body.update(json or {})
        return _make_mock_response(body_response)

    with patch.object(client._client, "post", side_effect=fake_post):
        client.chat_with_tools([{"role": "user", "content": "hello"}], tools=None)

    assert "parallel_tool_calls" not in captured_body
    save("openai_no_parallel_tool_calls_without_tools", True, {})


# ── apply_patch ToolDef ───────────────────────────────────────────────────────

def test_apply_patch_tool_def_schema():
    """apply_patch ToolDef must exist in BUILTIN_TOOL_DEFS with correct schema."""
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    names = [t.name for t in BUILTIN_TOOL_DEFS]
    assert "apply_patch" in names, f"apply_patch not found in BUILTIN_TOOL_DEFS: {names}"

    td = next(t for t in BUILTIN_TOOL_DEFS if t.name == "apply_patch")
    props = td.parameters.get("properties", {})
    assert "path" in props, "apply_patch must have 'path' parameter"
    assert "patch" in props, "apply_patch must have 'patch' parameter"
    assert props["path"]["type"] == "string"
    assert props["patch"]["type"] == "string"
    assert td.parameters.get("required") == ["path", "patch"]

    # Verify wire formats are correct
    anthropic_fmt = td.to_anthropic()
    assert anthropic_fmt["name"] == "apply_patch"
    assert "input_schema" in anthropic_fmt

    openai_fmt = td.to_openai()
    assert openai_fmt["type"] == "function"
    assert openai_fmt["function"]["name"] == "apply_patch"

    save("apply_patch_tool_def_schema", True, {"name": td.name})


# ── BUILTIN_TOOL_DEFS descriptions ───────────────────────────────────────────

def test_all_builtin_tool_defs_have_descriptions():
    """Every tool in BUILTIN_TOOL_DEFS must have a non-empty description."""
    from app.core.tool_schema import BUILTIN_TOOL_DEFS

    for td in BUILTIN_TOOL_DEFS:
        assert td.description, f"Tool '{td.name}' has an empty description"
        assert len(td.description.strip()) > 10, (
            f"Tool '{td.name}' description is too short: {td.description!r}"
        )

    tool_names = [t.name for t in BUILTIN_TOOL_DEFS]
    expected = {"read_file", "write_file", "list_dir", "run_command", "fetch_url", "apply_patch"}
    assert expected.issubset(set(tool_names)), (
        f"Missing tools: {expected - set(tool_names)}"
    )
    save("all_builtin_tool_defs_have_descriptions", True, {"tool_count": len(BUILTIN_TOOL_DEFS)})
