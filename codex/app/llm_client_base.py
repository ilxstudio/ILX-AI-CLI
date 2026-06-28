"""Base LLM abstractions — BaseLLMClient, TokenUsage, OllamaClient, and helpers.

Split from llm_client.py to keep individual files under 700 lines.
Import everything from ``codex.app.llm_client`` for a unified surface.
"""
from __future__ import annotations

import json
import logging
import time
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

_log = logging.getLogger(__name__)


# ── Rate-limit helper ─────────────────────────────────────────────────────────

def _handle_rate_limit(exc: httpx.HTTPStatusError, provider: str) -> None:
    """Parse a 429 response, wait retry-after seconds (capped at 60), then raise.

    Never silently retries — one wait, then a user-friendly error is raised.

    Backward-compatible shim: internally delegates to classify_error().
    """
    from app.core.error_classifier import classify_error
    classified = classify_error(exc, provider=provider)
    retry_after = classified.retry_after
    if retry_after > 0:
        print(f"  Rate limited by {provider}. Retry after {retry_after}s...")
        time.sleep(retry_after)
    raise RuntimeError(classified.message) from exc


# ── Retry helper with error classification ────────────────────────────────────

#: Exception types that indicate a transient connectivity problem.
_OLLAMA_RETRYABLE = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


def _retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    provider: str = "ollama",
):
    """Call *fn* with exponential backoff, using error classification to decide
    whether to retry.

    - Uses ``classify_error()`` to determine if the error is retriable.
    - Respects the ``retry_after`` field from ``ClassifiedError`` when set.
    - On non-retriable errors, raises ``RuntimeError`` with the user-friendly
      message and suggestion appended.
    - Backward-compatible: existing callers that omit *provider* continue to
      work unchanged.

    Prints a dim console message on each retry attempt.
    """
    delay = base_delay
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            classified = None
            should_retry = True
            wait = 0
            try:
                from app.core.error_classifier import classify_error, ErrorClass
                classified = classify_error(exc, provider=provider)
                should_retry = classified.should_retry
                # cap retry_after at 60s here; absolute cap applied below
                wait = min(classified.retry_after or 0, 60)
            except Exception:
                # If error classifier itself fails, use conservative defaults
                pass

            # Absolute cap to prevent accidental very long waits
            wait = min(max(0, wait), 120)  # never wait more than 2 minutes

            if not should_retry:
                # Non-retriable: surface a helpful error immediately.
                if classified is not None:
                    detail = f" {classified.suggestion}" if classified.suggestion else ""
                    raise RuntimeError(f"{classified.message}{detail}") from exc
                raise RuntimeError(str(exc)) from exc

            # Retriable error — record and maybe sleep.
            last_exc = exc
            if attempt < max_retries:
                if wait == 0:
                    wait = min(delay, max_delay)
                print(
                    f"\033[2mRetrying {provider}… (attempt {attempt}/{max_retries},"
                    f" wait {wait:.0f}s)\033[0m"
                )
                time.sleep(wait)
                if classified is None or classified.retry_after == 0:
                    delay = min(delay * 2, max_delay)
            # else: exhausted retries, fall through

    raise last_exc


def _call_with_retry(fn, *, provider: str = "", max_retries: int = 3):
    """Call fn(), retrying on transient/rate-limit errors with exponential backoff."""
    from app.core.error_classifier import classify_error, ErrorClass
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            classified = classify_error(exc, provider)
            if not classified.should_retry or attempt == max_retries:
                raise
            wait = classified.retry_after if classified.retry_after > 0 else (2 ** attempt)
            _log.warning(
                "%s: %s — retrying in %ds (attempt %d/%d)",
                provider or "LLM", classified.message, wait, attempt + 1, max_retries,
            )
            _time.sleep(wait)
            last_exc = exc
    raise last_exc  # unreachable but satisfies type checkers


_CODEX_SYSTEM = (
    "You are a code generator.  Read the user message and write the file(s) "
    "it asks for.  Your entire response is a single JSON object — nothing "
    "else.  No markdown fences.  No prose before or after the JSON.  No "
    "tool calls.  Always include real file content (never ellipsis or "
    "'rest unchanged').  If the user gives a task, do it; never reply that "
    "there is no task.  The JSON must parse with json.loads()."
)


@dataclass
class TokenUsage:
    """Token counts from the last LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class BaseLLMClient(ABC):
    """Abstract base for all LLM clients.

    After every ``chat()``, ``chat_stream()``, or ``generate()`` call the
    client updates ``self.last_usage`` with the token counts returned by the
    provider.  Callers that don't need usage data can ignore the attribute
    entirely — the return types of all methods are unchanged.
    """

    def __init__(self) -> None:
        self.last_usage = TokenUsage()

    @abstractmethod
    def generate(self, prompt: str) -> str:
        ...

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        """Chat with optional tool use. Returns (text, tool_calls).

        Returns (text, []) for plain text response.
        Returns ("", [{"name": str, "input": dict, "id": str}]) when model
        calls a tool.
        Default implementation falls back to chat() with no tool support.
        """
        text = self.chat(messages, system=system)
        return text, []


class OllamaClient(BaseLLMClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: int = 120):
        super().__init__()
        self.model    = model
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    def generate(self, prompt: str) -> str:
        url  = f"{self.base_url}/api/generate"
        body = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            response = _retry_with_backoff(
                lambda: httpx.post(url, json=body, timeout=self.timeout)
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama HTTP error {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Ollama returned non-JSON body: {response.text[:300]}") from exc
        if "response" not in data:
            raise RuntimeError(f"Ollama response missing 'response' field. Keys: {list(data.keys())}")
        self.last_usage = TokenUsage(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )
        return data["response"]

    def chat(self, messages: list[dict], system: str = "") -> str:
        """Multi-turn chat via /api/chat endpoint (streaming disabled)."""
        url  = f"{self.base_url}/api/chat"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {"model": self.model, "messages": msgs, "stream": False}
        try:
            response = _retry_with_backoff(
                lambda: httpx.post(url, json=body, timeout=self.timeout)
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ollama HTTP error {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Ollama returned non-JSON: {response.text[:300]}") from exc
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Ollama chat response missing content. Keys: {list(data.keys())}") from exc
        self.last_usage = TokenUsage(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )
        return content

    def chat_stream(self, messages: list[dict], system: str = ""):
        """Yield text chunks as they arrive from Ollama's streaming /api/chat.

        Token usage is captured from the final ``done`` chunk and stored in
        ``self.last_usage`` after the generator is fully consumed.
        """
        url  = f"{self.base_url}/api/chat"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {"model": self.model, "messages": msgs, "stream": True}
        stream_timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0)
        with httpx.stream("POST", url, json=body, timeout=stream_timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    self.last_usage = TokenUsage(
                        prompt_tokens=chunk.get("prompt_eval_count", 0),
                        completion_tokens=chunk.get("eval_count", 0),
                    )
                    break

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        """OpenAI-compatible tool calling for Ollama (supported models only).

        Falls back to plain text if the model doesn't support tool calling or
        returns malformed JSON.
        """
        if not tools:
            text = self.chat(messages, system=system)
            return text, []

        url  = f"{self.base_url}/api/chat"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {
            "model":   self.model,
            "messages": msgs,
            "stream":  False,
            "tools":   [t.to_openai() for t in tools],
        }
        try:
            response = _retry_with_backoff(
                lambda: httpx.post(url, json=body, timeout=self.timeout)
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            _log.warning(
                "Ollama tool-call attempt failed (%s: %s), falling back to plain chat",
                type(exc).__name__, exc,
            )
            # Fall back to plain text on any tool-call error
            text = self.chat(messages, system=system)
            return text, []

        try:
            msg = data["message"]
            tool_calls_raw = msg.get("tool_calls") or []
            if tool_calls_raw:
                tool_calls = []
                for tc in tool_calls_raw:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            raw_args = {}
                    tool_calls.append({
                        "id":    tc.get("id", f"call_{fn.get('name', 'tool')}"),
                        "name":  fn.get("name", ""),
                        "input": raw_args,
                    })
                self.last_usage = TokenUsage(
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                )
                return "", tool_calls
            # Plain text response
            content = msg.get("content", "")
            self.last_usage = TokenUsage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
            )
            return content, []
        except (KeyError, TypeError):
            text = self.chat(messages, system=system)
            return text, []
