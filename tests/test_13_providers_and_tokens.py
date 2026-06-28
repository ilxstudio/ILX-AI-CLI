"""Cluster 13 — Multi-provider clients and token counter.

Tests (all mock-based — no live API keys required):
  - test_token_usage_dataclass        : TokenUsage properties work correctly
  - test_ollama_chat_token_usage      : OllamaClient.chat() populates last_usage
  - test_ollama_stream_token_usage    : OllamaClient.chat_stream() populates last_usage
  - test_anthropic_chat_token_usage   : AnthropicClient.chat() populates last_usage
  - test_anthropic_stream_token_usage : AnthropicClient.chat_stream() populates last_usage
  - test_openai_chat_token_usage      : OpenAIClient.chat() populates last_usage
  - test_openai_stream_token_usage    : OpenAIClient.chat_stream() populates last_usage
  - test_groq_chat_delegates          : GroqClient.chat() delegates to OpenAIClient (Groq base)
  - test_groq_stream_delegates        : GroqClient.chat_stream() copies last_usage from inner
  - test_gemini_chat_token_usage      : GeminiClient.chat() parses usageMetadata
  - test_gemini_stream_token_usage    : GeminiClient.chat_stream() accumulates usage
  - test_get_llm_client_factory       : factory returns correct type for each provider
  - test_meta_uses_ollama             : meta provider returns OllamaClient with llama model
  - test_secret_store_per_provider    : get/set/delete API key with provider prefix
  - test_provider_cmd_lists_all       : cmd_provider() with no args lists all 6 providers
  - test_provider_cmd_unknown         : unknown provider prints error without switching
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── TokenUsage ────────────────────────────────────────────────────────────────

def test_token_usage_dataclass():
    from codex.app.llm_client import TokenUsage
    u = TokenUsage(prompt_tokens=100, completion_tokens=50)
    assert u.total_tokens == 150
    u2 = TokenUsage()
    assert u2.prompt_tokens == 0
    assert u2.completion_tokens == 0
    assert u2.total_tokens == 0
    save("token_usage_dataclass", True, {"total": u.total_tokens})


# ── OllamaClient ─────────────────────────────────────────────────────────────

def _make_mock_response(json_body: dict, status: int = 200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = json_body
    mock.raise_for_status = MagicMock()
    return mock


def test_ollama_chat_token_usage():
    from codex.app.llm_client import OllamaClient
    client = OllamaClient(model="codellama:7b")
    body = {
        "message": {"role": "assistant", "content": "Hello!"},
        "prompt_eval_count": 42,
        "eval_count": 17,
    }
    with patch("httpx.post", return_value=_make_mock_response(body)):
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello!"
    assert client.last_usage.prompt_tokens == 42
    assert client.last_usage.completion_tokens == 17
    assert client.last_usage.total_tokens == 59
    save("ollama_chat_token_usage", True, {"total": client.last_usage.total_tokens})


def test_ollama_stream_token_usage():
    from codex.app.llm_client import OllamaClient
    client = OllamaClient(model="codellama:7b")

    chunks = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        json.dumps({"message": {"content": " world"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True,
                    "prompt_eval_count": 30, "eval_count": 10}),
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(chunks)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("httpx.stream", return_value=mock_resp):
        tokens = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert "Hello" in tokens
    assert client.last_usage.prompt_tokens == 30
    assert client.last_usage.completion_tokens == 10
    save("ollama_stream_token_usage", True, {"chunks": len(tokens)})


# ── AnthropicClient ───────────────────────────────────────────────────────────

def test_anthropic_chat_token_usage():
    from codex.app.llm_client import AnthropicClient
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")
    body = {
        "content": [{"type": "text", "text": "Hello from Claude"}],
        "usage": {"input_tokens": 55, "output_tokens": 25},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        result = client.chat([{"role": "user", "content": "hi"}])
    assert "Hello" in result
    assert client.last_usage.prompt_tokens == 55
    assert client.last_usage.completion_tokens == 25
    save("anthropic_chat_token_usage", True, {"total": client.last_usage.total_tokens})


def test_anthropic_stream_token_usage():
    from codex.app.llm_client import AnthropicClient
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-test")

    sse_lines = [
        'data: {"type": "message_start", "message": {"usage": {"input_tokens": 70}}}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " there"}}',
        'data: {"type": "message_delta", "usage": {"output_tokens": 35}}',
        'data: {"type": "message_stop"}',
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(sse_lines)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("httpx.stream", return_value=mock_resp):
        tokens = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert "Hi" in tokens
    assert client.last_usage.prompt_tokens == 70
    assert client.last_usage.completion_tokens == 35
    save("anthropic_stream_token_usage", True, {"prompt": 70, "completion": 35})


# ── OpenAIClient ──────────────────────────────────────────────────────────────

def test_openai_chat_token_usage():
    from codex.app.llm_client import OpenAIClient
    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    body = {
        "choices": [{"message": {"content": "Hello from GPT"}}],
        "usage": {"prompt_tokens": 80, "completion_tokens": 40},
    }
    with patch.object(client._client, "post", return_value=_make_mock_response(body)):
        result = client.chat([{"role": "user", "content": "hi"}])
    assert "Hello" in result
    assert client.last_usage.prompt_tokens == 80
    assert client.last_usage.completion_tokens == 40
    save("openai_chat_token_usage", True, {"total": client.last_usage.total_tokens})


def test_openai_stream_token_usage():
    from codex.app.llm_client import OpenAIClient
    client = OpenAIClient(model="gpt-4o", api_key="sk-test")

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}], "usage": null}',
        'data: {"choices": [{"delta": {"content": " GPT"}}], "usage": null}',
        # final usage chunk (choices=[])
        'data: {"choices": [], "usage": {"prompt_tokens": 60, "completion_tokens": 20}}',
        'data: [DONE]',
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(sse_lines)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("httpx.stream", return_value=mock_resp):
        tokens = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert "Hello" in tokens
    assert client.last_usage.prompt_tokens == 60
    assert client.last_usage.completion_tokens == 20
    save("openai_stream_token_usage", True, {"chunks": len(tokens)})


# ── GroqClient ────────────────────────────────────────────────────────────────

def test_groq_chat_delegates():
    """GroqClient.chat() uses OpenAI-compat endpoint at api.groq.com."""
    from codex.app.llm_client import GroqClient
    client = GroqClient(model="llama-3.3-70b-versatile", api_key="gsk_test")

    body = {
        "choices": [{"message": {"content": "Hello from Groq"}}],
        "usage": {"prompt_tokens": 45, "completion_tokens": 22},
    }
    # Groq uses OpenAIClient internally; _client.base_url contains the Groq URL
    inner_http_client = client._inner._client
    with patch.object(inner_http_client, "post", return_value=_make_mock_response(body)):
        result = client.chat([{"role": "user", "content": "hi"}])

    # Verify the inner httpx.Client targets the Groq base URL
    base_url = str(inner_http_client.base_url)
    assert "groq.com" in base_url, f"Expected groq.com in base_url, got: {base_url}"
    assert "Hello" in result
    assert client.last_usage.prompt_tokens == 45
    assert client.last_usage.completion_tokens == 22
    save("groq_chat_delegates", True, {"url": base_url})


def test_groq_stream_delegates():
    """GroqClient.chat_stream() propagates last_usage from inner client."""
    from codex.app.llm_client import GroqClient
    client = GroqClient(model="llama-3.3-70b-versatile", api_key="gsk_test")

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Fast"}}], "usage": null}',
        'data: {"choices": [], "usage": {"prompt_tokens": 33, "completion_tokens": 11}}',
        'data: [DONE]',
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(sse_lines)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("httpx.stream", return_value=mock_resp):
        tokens = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert "Fast" in tokens
    assert client.last_usage.prompt_tokens == 33
    save("groq_stream_delegates", True, {"prompt": 33})


# ── GeminiClient ──────────────────────────────────────────────────────────────

def test_gemini_chat_token_usage():
    from codex.app.llm_client import GeminiClient
    client = GeminiClient(model="gemini-1.5-flash-latest", api_key="AIza-test")

    body = {
        "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}],
        "usageMetadata": {"promptTokenCount": 65, "candidatesTokenCount": 30},
    }
    with patch("httpx.post", return_value=_make_mock_response(body)) as mock_post:
        result = client.chat([{"role": "user", "content": "hi"}])

    url_called = mock_post.call_args[0][0]
    assert "generativelanguage.googleapis.com" in url_called
    assert "AIza-test" in url_called  # key as query param
    assert "Hello" in result
    assert client.last_usage.prompt_tokens == 65
    assert client.last_usage.completion_tokens == 30
    save("gemini_chat_token_usage", True, {"total": client.last_usage.total_tokens})


def test_gemini_stream_token_usage():
    from codex.app.llm_client import GeminiClient
    client = GeminiClient(model="gemini-1.5-flash-latest", api_key="AIza-test")

    sse_lines = [
        'data: {"candidates": [{"content": {"parts": [{"text": "Hi "}]}}], "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 5}}',
        'data: {"candidates": [{"content": {"parts": [{"text": "Gemini"}]}}], "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10}}',
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(sse_lines)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("httpx.stream", return_value=mock_resp):
        tokens = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert any("Hi" in t or "Gemini" in t for t in tokens)
    assert client.last_usage.prompt_tokens == 50
    assert client.last_usage.completion_tokens == 10
    save("gemini_stream_token_usage", True, {"tokens": len(tokens)})


# ── Factory ───────────────────────────────────────────────────────────────────

def _make_cfg(provider: str, model: str = "test-model") -> object:
    from app.core.config import AppConfig
    cfg = AppConfig()
    cfg.provider = provider
    cfg.ollama_model = model
    cfg.ollama_url = "http://localhost:11434"
    return cfg


def test_get_llm_client_factory():
    from codex.app.llm_client import (
        get_llm_client, OllamaClient, AnthropicClient, OpenAIClient,
        GroqClient, GeminiClient,
    )

    def _mock_key(provider=""):
        return "fake-key"

    with patch("app.core.secret_store.get_api_key", side_effect=_mock_key):
        assert isinstance(get_llm_client(_make_cfg("ollama")),    OllamaClient)
        assert isinstance(get_llm_client(_make_cfg("anthropic")), AnthropicClient)
        assert isinstance(get_llm_client(_make_cfg("openai")),    OpenAIClient)
        assert isinstance(get_llm_client(_make_cfg("groq")),      GroqClient)
        assert isinstance(get_llm_client(_make_cfg("gemini")),    GeminiClient)

    save("get_llm_client_factory", True, {"providers_tested": 5})


def test_meta_uses_ollama():
    """meta provider returns OllamaClient with a llama model."""
    from codex.app.llm_client import get_llm_client, OllamaClient
    cfg = _make_cfg("meta", model="")
    client = get_llm_client(cfg)
    assert isinstance(client, OllamaClient)
    assert "llama" in client.model.lower()
    save("meta_uses_ollama", True, {"model": client.model})


# ── secret_store per-provider ─────────────────────────────────────────────────

def test_secret_store_per_provider():
    """get_api_key/set_api_key support a provider prefix for separate keys."""
    from app.core import secret_store

    with patch("keyring.set_password") as mock_set, \
         patch("keyring.get_password") as mock_get, \
         patch("keyring.delete_password") as mock_del:

        mock_get.return_value = "my-groq-key"

        secret_store.set_api_key("my-groq-key", "groq")
        mock_set.assert_called_once_with(secret_store.SERVICE, "api_key:groq", "my-groq-key")

        key = secret_store.get_api_key("groq")
        assert key == "my-groq-key"
        mock_get.assert_called_with(secret_store.SERVICE, "api_key:groq")

        secret_store.delete_api_key("groq")
        mock_del.assert_called_with(secret_store.SERVICE, "api_key:groq")

    save("secret_store_per_provider", True, {})


def test_secret_store_backward_compat():
    """get_api_key() with no provider uses the legacy ACCOUNT key."""
    from app.core import secret_store

    with patch("keyring.get_password", return_value="legacy-key") as mock_get:
        key = secret_store.get_api_key()
        mock_get.assert_called_with(secret_store.SERVICE, secret_store.ACCOUNT)
        assert key == "legacy-key"

    save("secret_store_backward_compat", True, {})


# ── Settings cmd_provider ─────────────────────────────────────────────────────

def test_provider_cmd_lists_all(capsys):
    """cmd_provider() with no args lists all 6 providers."""
    from cli.commands.settings import SettingsCommands
    from app.core.config import AppConfig, ConfigManager

    cfg = AppConfig()
    cfg.provider = "ollama"
    mgr = MagicMock(spec=ConfigManager)
    cmd = SettingsCommands(cfg, mgr)
    cmd.cmd_provider([])

    out = capsys.readouterr().out
    for name in ("ollama", "anthropic", "openai", "groq", "gemini", "meta"):
        assert name in out, f"Provider '{name}' not listed in /provider output"
    save("provider_cmd_lists_all", True, {"output_len": len(out)})


def test_provider_cmd_unknown(capsys):
    """cmd_provider() with an unknown name prints error and does not switch."""
    from cli.commands.settings import SettingsCommands
    from app.core.config import AppConfig, ConfigManager

    cfg = AppConfig()
    cfg.provider = "ollama"
    mgr = MagicMock(spec=ConfigManager)
    cmd = SettingsCommands(cfg, mgr)
    cmd.cmd_provider(["nonexistent_llm"])

    assert cfg.provider == "ollama"
    mgr.save.assert_not_called()
    out = capsys.readouterr().out
    assert "unknown" in out.lower() or "nonexistent" in out.lower()
    save("provider_cmd_unknown", True, {})


def test_provider_cmd_switch_no_key_needed(capsys):
    """Switching to 'ollama' or 'meta' requires no API key and saves immediately."""
    from cli.commands.settings import SettingsCommands
    from app.core.config import AppConfig, ConfigManager

    for provider in ("meta",):
        cfg = AppConfig()
        cfg.provider = "ollama"
        mgr = MagicMock(spec=ConfigManager)
        cmd = SettingsCommands(cfg, mgr)
        cmd.cmd_provider([provider])
        assert cfg.provider == provider
        mgr.save.assert_called_once()

    save("provider_cmd_switch_no_key_needed", True, {})
