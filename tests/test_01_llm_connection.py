"""Cluster 01 — LLM connection and basic chat.

Tests (all live against Ollama):
  - test_ollama_reachable       : GET /api/tags returns 200
  - test_model_listed           : configured model appears in /api/tags
  - test_chat_returns_text      : single chat() call returns non-empty string
  - test_chat_stream_yields     : chat_stream() yields at least one token
  - test_chat_context_retained  : two-turn conversation references first message
"""
from __future__ import annotations

import httpx
import pytest
from tests.result_store import save


# ── helpers ──────────────────────────────────────────────────────────────────

def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.ollama_live
def test_ollama_reachable(ollama_url):
    try:
        r = httpx.get(f"{ollama_url}/api/tags", timeout=6.0)
        ok = r.status_code == 200
        models = [m["name"] for m in r.json().get("models", [])] if ok else []
    except Exception as exc:
        ok = False
        models = []
        save("ollama_reachable", False, {"error": str(exc), "url": ollama_url})
        pytest.skip(f"Ollama not reachable at {ollama_url}: {exc}")

    save("ollama_reachable", ok, {"url": ollama_url, "model_count": len(models), "models": models})
    assert ok, f"GET /api/tags returned {r.status_code}"


@pytest.mark.ollama_live
def test_model_listed(ollama_url, model):
    try:
        r = httpx.get(f"{ollama_url}/api/tags", timeout=6.0)
        models = [m["name"] for m in r.json().get("models", [])]
    except Exception as exc:
        save("model_listed", False, {"error": str(exc)})
        pytest.skip(f"Ollama not reachable: {exc}")

    listed = model in models
    save("model_listed", listed, {"model": model, "available_models": models})
    if not listed:
        pytest.skip(f"Model '{model}' not in server list — pull it first. Available: {models}")


@pytest.mark.ollama_live
def test_chat_returns_text(llm):
    prompt = "Say exactly: HELLO_ILX"
    try:
        response = llm.chat([_msg("user", prompt)])
    except Exception as exc:
        save("chat_returns_text", False, {"error": str(exc), "prompt": prompt})
        pytest.fail(f"llm.chat() raised: {exc}")

    ok = isinstance(response, str) and len(response.strip()) > 0
    save("chat_returns_text", ok, {
        "prompt":   prompt,
        "response": response[:500],
        "length":   len(response),
    })
    assert ok, f"Expected non-empty string, got: {response!r}"


@pytest.mark.ollama_live
def test_chat_stream_yields(llm):
    prompt = "Count from 1 to 5, one number per line."
    tokens: list[str] = []
    error = None
    try:
        for chunk in llm.chat_stream([_msg("user", prompt)]):
            tokens.append(chunk)
            if len(tokens) > 200:
                break
    except Exception as exc:
        error = str(exc)

    ok = len(tokens) > 0 and error is None
    full = "".join(tokens)
    save("chat_stream_yields", ok, {
        "prompt":      prompt,
        "token_count": len(tokens),
        "response":    full[:500],
        "error":       error,
    })
    assert ok, f"chat_stream() yielded no tokens. error={error}"


@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_chat_context_retained(llm):
    history = [
        _msg("user",      "Remember this codeword: BANANA_SPLIT_42"),
        _msg("assistant", "I will remember: BANANA_SPLIT_42"),
        _msg("user",      "What codeword did I ask you to remember? Reply with just the codeword."),
    ]
    try:
        response = llm.chat(history)
    except Exception as exc:
        save("chat_context_retained", False, {"error": str(exc)})
        pytest.fail(f"llm.chat() raised: {exc}")

    found = "BANANA_SPLIT_42" in response
    save("chat_context_retained", found, {
        "expected_in_response": "BANANA_SPLIT_42",
        "response":             response[:500],
    })
    assert found, f"Model did not recall codeword. Response: {response[:200]}"
