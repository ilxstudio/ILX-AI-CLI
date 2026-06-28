"""Extended LLM clients — GroqClient, GeminiClient, and the provider factory.

Kept in a separate file so that llm_client.py stays under 700 lines.
Import everything from codex.app.llm_client for a unified surface.
"""
from __future__ import annotations

import json
import uuid

import httpx

from codex.app.llm_client_base import BaseLLMClient, TokenUsage, _handle_rate_limit
from codex.app.llm_client_providers import OpenAIClient


class GroqClient(BaseLLMClient):
    """Groq cloud inference — OpenAI-compatible API at api.groq.com.

    Groq supports the same /v1/chat/completions endpoint as OpenAI but with
    much faster token-per-second rates via their LPU hardware.  The API key is
    stored in the OS keychain under the "groq" service name.

    Popular models: llama-3.3-70b-versatile, llama-3.1-8b-instant,
    mixtral-8x7b-32768, gemma2-9b-it.
    """

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    _BASE = "https://api.groq.com"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = "", timeout: int = 60):
        super().__init__()
        self.model   = model or self.DEFAULT_MODEL
        self.api_key = api_key
        self.timeout = timeout
        # Groq is OpenAI-compatible — delegate to an OpenAIClient pointed at Groq
        self._inner = OpenAIClient(model=self.model, api_key=api_key,
                                   timeout=timeout, base_url=self._BASE)

    def generate(self, prompt: str) -> str:
        result = self._inner.generate(prompt)
        self.last_usage = self._inner.last_usage
        return result

    def chat(self, messages: list[dict], system: str = "") -> str:
        result = self._inner.chat(messages, system=system)
        self.last_usage = self._inner.last_usage
        return result

    def chat_stream(self, messages: list[dict], system: str = ""):
        for chunk in self._inner.chat_stream(messages, system=system):
            yield chunk
        self.last_usage = self._inner.last_usage

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        """Delegate to inner OpenAIClient pointed at Groq, copy last_usage."""
        text, tool_calls = self._inner.chat_with_tools(messages, system=system, tools=tools)
        self.last_usage = self._inner.last_usage
        return text, tool_calls


class GeminiClient(BaseLLMClient):
    """Google Gemini via the REST generateContent / streamGenerateContent API.

    No SDK dependency — uses raw httpx against generativelanguage.googleapis.com.
    API key is passed as a query parameter (standard for Google AI Studio keys).

    Supported models: gemini-1.5-pro-latest, gemini-1.5-flash-latest,
    gemini-2.0-flash-exp.
    """

    DEFAULT_MODEL = "gemini-1.5-flash-latest"
    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = "", timeout: int = 120):
        super().__init__()
        self.model   = model or self.DEFAULT_MODEL
        self.api_key = api_key
        self.timeout = timeout

    def _build_body(self, messages: list[dict], system: str = "") -> dict:
        """Convert OpenAI-style messages to Gemini's contents format."""
        contents = []
        for m in messages:
            role = "user" if m.get("role") != "assistant" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
        body: dict = {"contents": contents}
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        return body

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])

    def chat(self, messages: list[dict], system: str = "") -> str:
        url = f"{self._BASE}/{self.model}:generateContent?key={self.api_key}"
        body = self._build_body(messages, system)
        try:
            resp = httpx.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "Gemini")
            raise RuntimeError(
                f"Gemini HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Gemini request failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Gemini response shape: {data}") from exc
        usage = data.get("usageMetadata", {})
        self.last_usage = TokenUsage(
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
        )
        return text

    def chat_stream(self, messages: list[dict], system: str = ""):
        """Stream from Gemini's streamGenerateContent endpoint (SSE)."""
        url = (
            f"{self._BASE}/{self.model}:streamGenerateContent"
            f"?key={self.api_key}&alt=sse"
        )
        body = self._build_body(messages, system)
        stream_timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0)
        prompt_tokens = 0
        completion_tokens = 0
        with httpx.stream("POST", url, json=body, timeout=stream_timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: "):].strip()
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                try:
                    text = event["candidates"][0]["content"]["parts"][0]["text"]
                    if text:
                        yield text
                except (KeyError, IndexError, TypeError):
                    pass
                usage = event.get("usageMetadata", {})
                if usage:
                    prompt_tokens = usage.get("promptTokenCount", prompt_tokens)
                    completion_tokens = usage.get("candidatesTokenCount", completion_tokens)
        self.last_usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        """Gemini function calling — sends function_declarations and parses functionCall."""
        body = self._build_body(messages, system)
        if tools:
            body["tools"] = [{"function_declarations": [t.to_gemini() for t in tools]}]
        url = f"{self._BASE}/{self.model}:generateContent?key={self.api_key}"
        try:
            resp = httpx.post(url, json=body, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "Gemini")
            raise RuntimeError(
                f"Gemini HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Gemini request failed: {exc}") from exc
        data = resp.json()
        usage_meta = data.get("usageMetadata", {})
        self.last_usage = TokenUsage(
            prompt_tokens=usage_meta.get("promptTokenCount", 0),
            completion_tokens=usage_meta.get("candidatesTokenCount", 0),
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Gemini response shape: {data}") from exc
        tool_calls: list[dict] = []
        text_parts: list[str] = []
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id":    str(uuid.uuid4()),
                    "name":  fc.get("name", ""),
                    "input": fc.get("args", {}),
                })
            elif "text" in part:
                text_parts.append(part["text"])
        if tool_calls:
            return "", tool_calls
        return "".join(text_parts), []


def get_client(ollama_url: str, ollama_model: str):
    """Return an OllamaClient (legacy helper)."""
    from codex.app.llm_client_base import OllamaClient
    return OllamaClient(model=ollama_model, base_url=ollama_url)


def _build_single_client(provider: str, model: str, cfg) -> BaseLLMClient:
    """Build one LLM client for *provider* using *model* and cfg for URL/key lookup."""
    from app.core import secret_store
    from codex.app.llm_client_base import OllamaClient
    from codex.app.llm_client_providers import AnthropicClient, OpenAIClient

    if provider == "anthropic":
        key = secret_store.get_api_key("anthropic") or secret_store.get_api_key() or ""
        return AnthropicClient(model=model or AnthropicClient.DEFAULT_MODEL, api_key=key)
    elif provider == "openai":
        key = secret_store.get_api_key("openai") or secret_store.get_api_key() or ""
        return OpenAIClient(model=model or OpenAIClient.DEFAULT_MODEL, api_key=key)
    elif provider == "groq":
        key = secret_store.get_api_key("groq") or secret_store.get_api_key() or ""
        return GroqClient(model=model or GroqClient.DEFAULT_MODEL, api_key=key)
    elif provider == "gemini":
        key = secret_store.get_api_key("gemini") or secret_store.get_api_key() or ""
        return GeminiClient(model=model or GeminiClient.DEFAULT_MODEL, api_key=key)
    elif provider == "meta":
        meta_model = model if model else "llama3.2"
        return OllamaClient(model=meta_model, base_url=cfg.ollama_url)
    else:  # ollama (default)
        return OllamaClient(model=model, base_url=cfg.ollama_url)


def get_llm_client(cfg) -> BaseLLMClient:
    """Factory: return the right LLM client based on cfg.provider.

    Supported providers:
      ollama     — local Ollama server (default)
      anthropic  — Anthropic (cloud)
      openai     — OpenAI (cloud)
      groq       — Groq LPU cloud
      gemini     — Google Gemini (cloud)
      meta       — Meta LLaMA via local Ollama

    When ``cfg.fallback_providers`` is non-empty, returns a ``FallbackLLMClient``
    that tries the primary provider first, then each fallback in order.
    """
    provider = getattr(cfg, "provider", "ollama")
    model = cfg.ollama_model
    primary = _build_single_client(provider, model, cfg)

    fallback_providers: list[str] = getattr(cfg, "fallback_providers", []) or []
    if not fallback_providers:
        return primary

    from codex.app.llm_client_fallback import FallbackLLMClient
    clients: list[BaseLLMClient] = [primary]
    for fp in fallback_providers:
        try:
            clients.append(_build_single_client(fp, "", cfg))
        except Exception:
            pass  # skip badly-configured fallback providers silently
    if len(clients) == 1:
        return primary
    return FallbackLLMClient(clients)


def get_chat_llm_client(cfg) -> BaseLLMClient:
    """Like get_llm_client but honours cfg.chat_model for chat mode.

    If ``cfg.chat_model`` is set, it overrides ``cfg.ollama_model`` so that
    the user can run a lighter/faster model for interactive chat while keeping
    a more capable model for code-agent tasks.  Falls back to
    ``get_llm_client`` when chat_model is empty.
    """
    chat_model = getattr(cfg, "chat_model", "").strip()
    if not chat_model:
        return get_llm_client(cfg)

    # Build a lightweight shim so we can swap just the model name
    from dataclasses import replace as _dc_replace
    try:
        shim = _dc_replace(cfg, ollama_model=chat_model)
    except TypeError:
        # Not a dataclass — fall back to attribute copy
        import copy
        shim = copy.copy(cfg)
        shim.ollama_model = chat_model
    return get_llm_client(shim)
