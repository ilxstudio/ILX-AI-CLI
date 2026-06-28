"""FallbackLLMClient — tries providers in order, moves to the next on any error.

Created as a separate module so that llm_client_base.py stays under 700 lines.
Import via ``codex.app.llm_client`` for the unified surface.

MIT License 2026 ILX Studio
"""
from __future__ import annotations

import logging

from codex.app.llm_client_base import BaseLLMClient

_log = logging.getLogger("ilx_cli.llm_fallback")


class FallbackLLMClient(BaseLLMClient):
    """Composite client that tries a list of providers in order.

    On any exception from a provider the error is logged at WARNING level and
    the next provider in the list is attempted.  If every provider fails a
    ``RuntimeError`` is raised containing the last exception.

    Usage::

        from codex.app.llm_client_fallback import FallbackLLMClient
        client = FallbackLLMClient([primary_client, backup_client])
    """

    def __init__(self, clients: list[BaseLLMClient]) -> None:
        super().__init__()
        if not clients:
            raise ValueError("FallbackLLMClient requires at least one client")
        self._clients = clients

    # ── Required abstract method ───────────────────────────────────────────────

    def generate(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for client in self._clients:
            try:
                result = client.generate(prompt)
                self.last_usage = client.last_usage
                return result
            except Exception as exc:
                _log.warning(
                    "Provider %s generate() failed, trying next: %s",
                    type(client).__name__, exc,
                )
                last_exc = exc
        raise RuntimeError(f"All providers failed. Last error: {last_exc}") from last_exc

    # ── Chat ──────────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list | None = None,
    ) -> str:
        last_exc: Exception | None = None
        for client in self._clients:
            try:
                result = client.chat(messages, system=system)
                self.last_usage = client.last_usage
                return result
            except Exception as exc:
                _log.warning(
                    "Provider %s chat() failed, trying next: %s",
                    type(client).__name__, exc,
                )
                last_exc = exc
        raise RuntimeError(f"All providers failed. Last error: {last_exc}") from last_exc

    # ── Streaming chat ────────────────────────────────────────────────────────

    def stream_chat(
        self,
        messages: list[dict],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = -1,
    ):
        """Try streaming from each provider in order; fall back to the next on error."""
        last_exc: Exception | None = None
        for client in self._clients:
            try:
                # OllamaClient exposes chat_stream; other clients may use stream_chat
                stream_fn = getattr(client, "chat_stream", None) or getattr(
                    client, "stream_chat", None
                )
                if stream_fn is None:
                    raise AttributeError(
                        f"{type(client).__name__} has no streaming method"
                    )
                yield from stream_fn(messages, system=system)
                self.last_usage = client.last_usage
                return
            except Exception as exc:
                _log.warning(
                    "Provider %s stream failed, trying next: %s",
                    type(client).__name__, exc,
                )
                last_exc = exc
        raise RuntimeError(f"All providers failed. Last error: {last_exc}") from last_exc

    # ── Tool calling ──────────────────────────────────────────────────────────

    def chat_with_tools(
        self,
        messages: list[dict],
        system: str = "",
        tools: list | None = None,
    ) -> tuple[str, list[dict]]:
        last_exc: Exception | None = None
        for client in self._clients:
            try:
                text, tool_calls = client.chat_with_tools(
                    messages, system=system, tools=tools
                )
                self.last_usage = client.last_usage
                return text, tool_calls
            except Exception as exc:
                _log.warning(
                    "Provider %s chat_with_tools() failed, trying next: %s",
                    type(client).__name__, exc,
                )
                last_exc = exc
        raise RuntimeError(f"All providers failed. Last error: {last_exc}") from last_exc
