"""Anthropic and OpenAI client implementations.

Split from llm_client.py to keep that file under 700 lines.
Import these via ``codex.app.llm_client`` — do not import this module directly
unless you have a good reason.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from codex.app.llm_client_base import BaseLLMClient, TokenUsage, _handle_rate_limit, _call_with_retry

_log = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude via raw httpx — no SDK dependency."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = "", timeout: int = 120):
        super().__init__()
        self.model    = model or self.DEFAULT_MODEL
        self._api_key = api_key
        self.timeout  = timeout
        self._base    = "https://api.anthropic.com"
        self._client  = httpx.Client(
            base_url=self._base,
            timeout=httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return f"AnthropicClient(model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _headers(self, use_cache: bool = False) -> dict:
        headers = {
            "x-api-key":         self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        }
        if use_cache:
            headers["anthropic-beta"] = "prompt-caching-2024-07-31"
        return headers

    @staticmethod
    def _build_cached_system(system: str) -> list[dict]:
        """Wrap a system string in the cached-content array format."""
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _add_cache_to_last_user_message(messages: list[dict]) -> list[dict]:
        """Return a shallow copy of messages with cache_control on the last user message."""
        import copy
        msgs = list(messages)  # shallow copy of the list
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                msg = copy.deepcopy(msgs[i])
                content = msg.get("content")
                if isinstance(content, str):
                    msg["content"] = [
                        {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                    ]
                elif isinstance(content, list) and content:
                    content = list(content)
                    last_block = dict(content[-1])
                    last_block["cache_control"] = {"type": "ephemeral"}
                    content[-1] = last_block
                    msg["content"] = content
                msgs[i] = msg
                break
        return msgs

    def _parse_usage(self, usage: dict) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        )

    def generate(self, prompt: str) -> str:
        body = {
            "model":      self.model,
            "max_tokens": 8192,
            "messages":   [{"role": "user", "content": prompt}],
        }
        def _do():
            r = self._client.post("/v1/messages", headers=self._headers(), json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="Anthropic")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "Anthropic")
            raise RuntimeError(
                f"Anthropic HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Anthropic response shape: {data}") from exc
        self.last_usage = self._parse_usage(data.get("usage", {}))
        return text

    def chat(self, messages: list[dict], system: str = "", use_cache: bool = False) -> str:
        msgs = self._add_cache_to_last_user_message(messages) if use_cache else messages
        body: dict = {
            "model":      self.model,
            "max_tokens": 8192,
            "messages":   msgs,
        }
        if system:
            body["system"] = self._build_cached_system(system) if use_cache else system
        _hdrs = self._headers(use_cache=use_cache)
        def _do():
            r = self._client.post("/v1/messages", headers=_hdrs, json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="Anthropic")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "Anthropic")
            raise RuntimeError(
                f"Anthropic HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Anthropic response shape: {data}") from exc
        self.last_usage = self._parse_usage(data.get("usage", {}))
        return text

    def chat_stream(self, messages: list[dict], system: str = "", use_cache: bool = False):
        """Yield text chunks from Anthropic's SSE streaming API.

        Token usage arrives in the ``message_delta`` event (``usage`` field)
        just before ``message_stop``.  It is captured and stored in
        ``self.last_usage`` after the generator is fully consumed.
        """
        msgs = self._add_cache_to_last_user_message(messages) if use_cache else messages
        body: dict = {
            "model":      self.model,
            "max_tokens": 8192,
            "messages":   msgs,
            "stream":     True,
        }
        if system:
            body["system"] = self._build_cached_system(system) if use_cache else system
        stream_timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0)
        # Anthropic sends input_tokens in message_start, output_tokens in message_delta.
        input_tokens: int  = 0
        output_tokens: int = 0
        cache_creation_tokens: int = 0
        cache_read_tokens: int = 0
        with httpx.stream(
            "POST",
            f"{self._base}/v1/messages",
            headers=self._headers(use_cache=use_cache),
            json=body,
            timeout=stream_timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: "):].strip()
                if raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "message_start":
                    # usage.input_tokens is available here
                    usage = event.get("message", {}).get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
                    cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
                elif etype == "message_delta":
                    # usage.output_tokens is finalized here
                    usage = event.get("usage", {})
                    output_tokens = usage.get("output_tokens", 0)
                elif etype == "message_stop":
                    break
        self.last_usage = TokenUsage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
        use_cache: bool = False,
    ) -> tuple[str, list[dict]]:
        """Anthropic tool use — sends tools in request and parses tool_use blocks."""
        msgs = self._add_cache_to_last_user_message(messages) if use_cache else messages
        body: dict = {
            "model":      self.model,
            "max_tokens": 8192,
            "messages":   msgs,
        }
        if system:
            body["system"] = self._build_cached_system(system) if use_cache else system
        if tools:
            body["tools"] = [t.to_anthropic() for t in tools]
        _hdrs = self._headers(use_cache=use_cache)
        def _do():
            r = self._client.post("/v1/messages", headers=_hdrs, json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="Anthropic")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "Anthropic")
            raise RuntimeError(
                f"Anthropic HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Anthropic request failed: {exc}") from exc
        data = resp.json()
        self.last_usage = self._parse_usage(data.get("usage", {}))
        content_blocks = data.get("content", [])
        tool_calls = []
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "tool_use":
                raw_input = block.get("input", {})
                if isinstance(raw_input, str):
                    try:
                        raw_input = json.loads(raw_input or "{}")
                    except json.JSONDecodeError as exc:
                        _log.warning(
                            "Malformed Anthropic tool input (JSONDecodeError: %s). Raw: %.200s",
                            exc, raw_input,
                        )
                        raw_input = {}
                tool_calls.append({
                    "id":    block["id"],
                    "name":  block["name"],
                    "input": raw_input,
                })
            elif block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        if tool_calls:
            return "", tool_calls
        return "".join(text_parts), []


class OpenAIClient(BaseLLMClient):
    """OpenAI-compatible API via raw httpx — works with OpenAI and compatible endpoints."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str = "",
        timeout: int = 120,
        base_url: str = "https://api.openai.com",
    ):
        super().__init__()
        self.model    = model or self.DEFAULT_MODEL
        self._api_key = api_key
        self.timeout  = timeout
        self._base    = base_url.rstrip("/")
        self._client  = httpx.Client(
            base_url=self._base,
            timeout=httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    @property
    def api_key(self) -> str:
        return self._api_key

    def __repr__(self) -> str:
        return f"OpenAIClient(model={self.model!r}, base={self._base!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }

    def generate(self, prompt: str) -> str:
        body = {
            "model":    self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        def _do():
            r = self._client.post("/v1/chat/completions", headers=self._headers(), json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="OpenAI")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "OpenAI")
            raise RuntimeError(
                f"OpenAI HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenAI response shape: {data}") from exc
        usage = data.get("usage", {})
        self.last_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return text

    def chat(self, messages: list[dict], system: str = "") -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {"model": self.model, "messages": msgs}
        def _do():
            r = self._client.post("/v1/chat/completions", headers=self._headers(), json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="OpenAI")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "OpenAI")
            raise RuntimeError(
                f"OpenAI HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenAI response shape: {data}") from exc
        usage = data.get("usage", {})
        self.last_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return text

    def chat_stream(self, messages: list[dict], system: str = ""):
        """Yield text chunks from OpenAI's SSE streaming API.

        Usage data is requested via ``stream_options`` and arrives in the
        final ``[DONE]``-adjacent chunk.  It is stored in ``self.last_usage``
        after the generator is fully consumed.
        """
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        # stream_options.include_usage causes OpenAI to send a final chunk
        # with a non-null ``usage`` field just before the [DONE] sentinel.
        body = {
            "model":          self.model,
            "messages":       msgs,
            "stream":         True,
            "stream_options": {"include_usage": True},
        }
        stream_timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=5.0)
        with httpx.stream(
            "POST",
            f"{self._base}/v1/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=stream_timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: "):].strip()
                if raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # The final usage chunk has choices=[] and a usage object.
                usage = event.get("usage")
                if usage:
                    self.last_usage = TokenUsage(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )
                try:
                    text = event["choices"][0]["delta"].get("content", "")
                    if text:
                        yield text
                except (KeyError, IndexError, TypeError) as exc:
                    _log.debug("Skipped malformed OpenAI stream event: %s", exc)
                    continue

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        """OpenAI tool calling — sends tools in request and parses tool_calls."""
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body: dict = {"model": self.model, "messages": msgs}
        if tools:
            body["tools"] = [t.to_openai() for t in tools]
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        def _do():
            r = self._client.post("/v1/chat/completions", headers=self._headers(), json=body)
            r.raise_for_status()
            return r
        try:
            resp = _call_with_retry(_do, provider="OpenAI")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                _handle_rate_limit(exc, "OpenAI")
            raise RuntimeError(
                f"OpenAI HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        data = resp.json()
        usage = data.get("usage", {})
        self.last_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenAI response shape: {data}") from exc
        raw_tool_calls = msg.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                raw_args = fn.get("arguments", "{}")
                try:
                    parsed_args = json.loads(raw_args or "{}")
                except json.JSONDecodeError as exc:
                    _log.warning(
                        "Malformed tool arguments from LLM (JSONDecodeError: %s). Raw: %.200s",
                        exc, raw_args,
                    )
                    parsed_args = {}
                tool_calls.append({
                    "id":    tc["id"],
                    "name":  fn.get("name", ""),
                    "input": parsed_args,
                })
            return "", tool_calls
        return msg.get("content") or "", []
