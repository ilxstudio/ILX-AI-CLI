"""ChatSession — manages a single interactive chat conversation."""
from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from app.core.error_classifier import ErrorClass, classify_error

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from cli.context import ContextManager

_log = logging.getLogger("ilx_cli.chat")

# Error classes that warrant switching to the next fallback provider rather
# than retrying the same one (transient / rate-limit errors are excluded so
# the existing retry logic handles them).
_FALLBACK_TRIGGER = {
    ErrorClass.AUTH,
    ErrorClass.QUOTA,
    ErrorClass.PERMANENT,
    ErrorClass.MODEL_NOT_FOUND,
}


class ChatSession:
    """Holds state and handles one round-trip in chat mode."""

    def __init__(self, cfg: AppConfig, ctx: ContextManager) -> None:
        self.cfg            = cfg
        self.ctx            = ctx
        self.history:  list[dict] = []
        self.pinned:   list[dict] = []
        self.pending_paste: str | None = None

    def clear(self) -> None:
        self.history.clear()
        self.pinned.clear()
        self.pending_paste = None

    def undo(self) -> bool:
        """Remove the last user+assistant exchange from history.
        Returns True if something was removed, False if history was too short.
        """
        if len(self.history) < 2:
            return False
        # Pop pairs from the end: assistant first, then user
        last = self.history[-1]
        if last.get("role") == "assistant":
            self.history.pop()
        if self.history and self.history[-1].get("role") == "user":
            self.history.pop()
        return True

    def compact(self) -> tuple[str | None, int, int]:
        """Summarize the conversation history with the LLM and replace it.

        Returns (summary, old_token_estimate, savings_tokens), or
        (None, 0, 0) if history is too short to compact.
        """
        from cli.context import estimate_tokens
        if len(self.history) < 4:
            return None, 0, 0
        from codex.app.llm_client import get_chat_llm_client as get_llm_client
        summarize_msgs = list(self.history) + [{
            "role": "user",
            "content": (
                "Please summarize our conversation so far in 2-3 sentences, "
                "capturing the key context, decisions made, and current goal. "
                "Be concise — this will replace the full history."
            )
        }]
        # Estimate tokens before compacting
        old_tokens = estimate_tokens(
            " ".join(m.get("content", "") for m in self.history)
        )
        try:
            client = get_llm_client(self.cfg)
            summary = client.chat(summarize_msgs)
        except Exception as exc:
            _log.warning("Compact failed: %s", exc)
            return None, 0, 0
        old_count = len(self.history)
        self.history.clear()
        summary_entry = {
            "role": "system",
            "content": f"[Conversation summary — {old_count} messages compacted]\n{summary}"
        }
        self.history.append(summary_entry)
        new_tokens = estimate_tokens(summary_entry["content"])
        savings = max(0, old_tokens - new_tokens)
        return summary, old_count, savings

    def _warn_context_usage(self, system: str, all_msgs: list[dict]) -> None:
        """Print a dim warning when the estimated context usage is high."""
        from cli.context import estimate_tokens
        from cli.display import DIM, RESET, YELLOW

        num_ctx = getattr(self.cfg, "num_ctx", 4096)
        if not num_ctx:
            return

        all_text = system + " ".join(m.get("content", "") for m in all_msgs)
        estimated = estimate_tokens(all_text)
        pct = estimated / num_ctx

        if pct >= 0.95:
            print(
                f"  {YELLOW}Warning: Context near limit"
                f" ({estimated}t / {num_ctx}t) — run /compact now{RESET}"
            )
        elif pct >= 0.80:
            print(
                f"  {DIM}Context ~{estimated}t / {num_ctx}t"
                f" — consider /compact to free space{RESET}"
            )

    def send(self, raw: str) -> bool:
        """Send raw to the LLM in chat mode. Returns True on success."""
        import time

        from app.core import audit
        from app.core.spinner import Spinner
        from cli.display import DIM, GREEN, RED, RESET
        from codex.app.llm_client import get_chat_llm_client as get_llm_client

        if self.pending_paste:
            raw = f"[Pasted content]\n{self.pending_paste}\n\n{raw}"
            self.pending_paste = None

        expanded, at_paths = self.ctx.expand_at_paths(raw)
        if at_paths:
            print(f"  {DIM}Attached: {', '.join(at_paths)}{RESET}")

        # ── Vision / multimodal image injection ───────────────────────────────
        provider = getattr(self.cfg, "provider", "ollama")
        from app.core.vision import (
            build_multimodal_message,
            extract_image_paths,
            ollama_model_has_vision,
        )
        image_paths = extract_image_paths(raw)

        if image_paths:
            import os
            names = ", ".join(os.path.basename(p) for p in image_paths)
            if provider in ("ollama", "meta"):
                # Derive model name from cfg — avoids instantiating the client twice.
                _model_name: str = (
                    getattr(self.cfg, "chat_model", "")
                    or getattr(self.cfg, "ollama_model", "")
                )
                if ollama_model_has_vision(_model_name):
                    print(f"  {DIM}Attached images: {names}{RESET}")
                    user_message: dict = build_multimodal_message(
                        expanded, image_paths, provider, model_name=_model_name
                    )
                else:
                    print(
                        f"  {DIM}[Vision not supported with this Ollama model"
                        f" — use a vision-capable model such as llava,"
                        f" or attach images when using a cloud provider]{RESET}"
                    )
                    user_message = {"role": "user", "content": expanded}
            else:
                print(f"  {DIM}Attached images: {names}{RESET}")
                user_message = build_multimodal_message(expanded, image_paths, provider)
        else:
            user_message = {"role": "user", "content": expanded}

        self.history.append(user_message)
        client = get_llm_client(self.cfg)
        system = self.ctx.build_system_prompt()
        all_msgs = self.pinned + self.history

        # ── Context window usage warning ──────────────────────────────────────
        self._warn_context_usage(system, all_msgs)

        t_start = time.monotonic()

        # ── Tool-use path (non-streaming) ─────────────────────────────────────
        if getattr(self.cfg, "tool_use_enabled", False):
            return self._send_with_tools(client, all_msgs, system, t_start, audit)

        # ── Streaming path (default) ──────────────────────────────────────────
        spinner = Spinner("ILX AI thinking")
        spinner.start()
        first_token = True
        collected: list[str] = []

        try:
            for chunk in client.chat_stream(all_msgs, system=system):
                if first_token:
                    spinner.stop(clear=True)
                    print(f"\n{GREEN}ILX AI:{RESET} ", end="", flush=True)
                    first_token = False
                print(chunk, end="", flush=True)
                collected.append(chunk)

            if first_token:
                spinner.stop(clear=True)
                print(f"\n{GREEN}ILX AI:{RESET} (no response)")

            latency_ms = (time.monotonic() - t_start) * 1000
            full_response = "".join(collected)

            # Re-render as Rich markdown when rich is available, the terminal
            # is a real tty, and the response actually looks like markdown.
            if sys.stdout.isatty():
                try:
                    from cli.rich_display import _looks_like_markdown, is_rich_available
                    if is_rich_available() and _looks_like_markdown(full_response):
                        # Move cursor up past the streamed lines so we can
                        # replace them with the nicely-formatted version.
                        line_count = full_response.count("\n") + 2
                        sys.stdout.write(f"\033[{line_count}F")
                        sys.stdout.write("\033[J")  # erase from cursor to end
                        sys.stdout.flush()
                        from cli.rich_display import print_ai_response
                        provider = getattr(self.cfg, "provider", "ollama")
                        print_ai_response(full_response, provider, client.model)
                except Exception:
                    pass  # Never break streaming on rich errors

            # Show token usage from the last call.
            usage = client.last_usage
            provider = getattr(self.cfg, "provider", "ollama")
            if usage.prompt_tokens or usage.completion_tokens:
                from app.core.cost_tracker import tracker as _cost_tracker
                from cli.display import estimate_cost, format_cost
                cost = estimate_cost(provider, client.model,
                                     usage.prompt_tokens, usage.completion_tokens)
                # Accumulate into session tracker regardless of display path
                _cost_tracker.add(provider, client.model,
                                   usage.prompt_tokens, usage.completion_tokens)
                cost_str = format_cost(cost, provider)
                cost_part = f"  ({cost_str})" if cost_str else ""
                try:
                    print(
                        f"\n  {DIM}"
                        f"↳ {usage.prompt_tokens} prompt"
                        f" + {usage.completion_tokens} completion"
                        f" = {usage.total_tokens} tokens"
                        f"{cost_part}"
                        f"{RESET}"
                    )
                except UnicodeEncodeError:
                    print(
                        f"\n  {DIM}"
                        f"-> {usage.prompt_tokens} prompt"
                        f" + {usage.completion_tokens} completion"
                        f" = {usage.total_tokens} tokens"
                        f"{cost_part}"
                        f"{RESET}"
                    )
            else:
                print()

            print()
            self.history.append({"role": "assistant", "content": full_response})

            # Audit log.
            audit.log_llm_call(
                model=client.model,
                prompt_tokens=usage.prompt_tokens,
                response_tokens=usage.completion_tokens,
                latency_ms=latency_ms,
                provider=provider,
            )

            return True

        except Exception as exc:
            spinner.stop(clear=True)
            classified = classify_error(exc, provider)
            fallback_providers = list(
                getattr(self.cfg, "fallback_providers", None) or []
            )
            has_fallback = bool(fallback_providers)
            if classified.error_class in _FALLBACK_TRIGGER and has_fallback:
                # Primary provider failed permanently — attempt non-streaming
                # fallback through the configured fallback chain.
                try:
                    _log.debug("Streaming failed; attempting fallback chain", exc_info=True)
                    full_response = self._send_with_fallback(all_msgs, system=system)
                    latency_ms = (time.monotonic() - t_start) * 1000
                    print(f"\n{GREEN}ILX AI:{RESET} {full_response}\n")
                    self.history.append({"role": "assistant", "content": full_response})
                    audit.log_llm_call(
                        model="fallback",
                        prompt_tokens=0,
                        response_tokens=0,
                        latency_ms=latency_ms,
                        provider=provider,
                    )
                    return True
                except Exception as fallback_exc:
                    print(f"\n{RED}Error: {fallback_exc}{RESET}\n")
                    _log.debug("fallback chain also failed", exc_info=True)
                    if self.history and self.history[-1].get("role") == "user":
                        self.history.pop()
                    return False
            print(f"\n{RED}Error: {exc}{RESET}\n")
            _log.debug("chat error", exc_info=True)
            if self.history and self.history[-1].get("role") == "user":
                self.history.pop()
            return False

    def _send_with_fallback(self, messages: list[dict], **kwargs) -> str:
        """Call ``client.chat()`` with provider fallback on permanent failures.

        Iterates through the primary provider followed by any configured
        ``fallback_providers``.  Transient errors (network, rate-limit) are
        re-raised immediately so the existing retry logic can handle them.
        Only permanent, non-retryable errors trigger a provider switch.

        Returns the response string from the first provider that succeeds.
        Raises the last exception if every provider fails.
        """
        from codex.app.llm_client import get_client

        fallback_providers = list(
            getattr(self.cfg, "fallback_providers", None) or []
        )
        primary = getattr(self.cfg, "provider", "ollama")
        providers_to_try = [primary] + [
            p for p in fallback_providers if p != primary
        ]

        last_exc: Exception | None = None
        for provider in providers_to_try:
            try:
                if provider != primary:
                    client = get_client(provider, self.cfg)
                    print(f"[fallback] Switching to provider: {provider}")
                else:
                    from codex.app.llm_client import get_chat_llm_client as _get
                    client = _get(self.cfg)
                return client.chat(messages, **kwargs)
            except Exception as exc:
                last_exc = exc
                classified = classify_error(exc, provider)
                if classified.error_class not in _FALLBACK_TRIGGER:
                    raise  # transient — let retry logic handle
                print(
                    f"[fallback] Provider {provider} failed"
                    f" ({classified.error_class.name}), trying next..."
                )

        raise last_exc or RuntimeError("All providers in fallback chain failed")

    def _make_permission_cb(self):
        """Return a permission callback that gates tool execution via PermissionEngine.

        The callback signature is (kind: str, name: str, detail: str) -> bool,
        which matches the interface expected by MCPClient.call(permission_cb=...).
        Tool names are mapped to permission kinds understood by PermissionEngine.
        """
        from app.core.permissions import FileOperation, PermissionEngine

        _TOOL_KIND_MAP = {
            "read_file":   "read",
            "write_file":  "write",
            "apply_patch": "write",
            "run_command": "execute",
            "fetch_url":   "read",
        }

        engine = PermissionEngine(self.cfg)

        def _cb(kind: str, name: str, detail: str) -> bool:
            op_kind = _TOOL_KIND_MAP.get(name, "read")
            op = FileOperation(
                op_type=op_kind,
                path=detail,
                command=(detail.split() if op_kind == "execute" else None),
            )
            return engine.request_permission(op)

        return _cb

    def _execute_single_tool(self, tc: dict, mcp, permission_cb) -> dict:
        """Execute one tool call and return a result dict with id, name, and result_str."""
        tool_name = tc["name"]
        tool_args = tc["input"]
        tool_id   = tc["id"]
        result_dict = mcp.call(tool_name, tool_args, permission_cb=permission_cb)
        if result_dict.get("success", False):
            result_str = str(result_dict.get("result", ""))
        else:
            err = result_dict.get("error", "Unknown tool error")
            result_str = f"ERROR: {err}"
            _log.warning("Tool call failed: %s — %s", tool_name, err)
        return {"id": tool_id, "name": tool_name, "result_str": result_str}

    def _execute_tool_calls_parallel(self, tool_calls: list, mcp, permission_cb) -> list:
        """Execute independent tool calls in parallel. Serializes writes to the same path."""
        if len(tool_calls) <= 1:
            # Fast path — no parallelism needed
            results = []
            for tc in tool_calls:
                results.append(self._execute_single_tool(tc, mcp, permission_cb))
            return results

        # Group by target path to avoid concurrent writes to same file
        path_locks: dict[str, list[int]] = {}
        for i, tc in enumerate(tool_calls):
            path = (
                tc.get("args", {}).get("path")
                or tc.get("input", {}).get("path")
                or tc.get("function", {}).get("arguments", {}).get("path")
            )
            if path:
                path_locks.setdefault(path, []).append(i)

        results: list = [None] * len(tool_calls)
        with ThreadPoolExecutor(max_workers=min(4, len(tool_calls))) as pool:
            serial: list[int] = []
            futures = {}
            for i, tc in enumerate(tool_calls):
                path = (
                    tc.get("args", {}).get("path")
                    or tc.get("input", {}).get("path")
                    or tc.get("function", {}).get("arguments", {}).get("path")
                )
                if path and len(path_locks.get(path, [])) > 1:
                    serial.append(i)
                else:
                    fut = pool.submit(self._execute_single_tool, tc, mcp, permission_cb)
                    futures[fut] = i
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:
                    tc = tool_calls[idx]
                    results[idx] = {
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "result_str": f"ERROR: {exc}",
                    }
            # Serial execution for same-path conflicts
            for i in serial:
                results[i] = self._execute_single_tool(tool_calls[i], mcp, permission_cb)
        return results

    def _send_with_tools(self, client, all_msgs: list[dict], system: str,
                         t_start: float, audit) -> bool:
        """Non-streaming tool-use loop — up to 5 rounds of tool calls."""
        import time

        import app.core.mcp_client as _mcp_mod
        import app.core.tool_result_formatter as fmt
        from app.core.spinner import Spinner
        from app.core.tool_schema import BUILTIN_TOOL_DEFS
        from cli.display import CYAN, DIM, GREEN, RED, RESET

        provider = getattr(self.cfg, "provider", "ollama")
        mcp = _mcp_mod.MCPClient(cfg=self.cfg)
        # Ensure built-in tools are available for dispatch
        mcp.register_builtin_tools()

        # Work on a mutable copy so we can append tool messages without
        # touching self.history until we have a final text response.
        msgs = list(all_msgs)
        final_text = ""

        spinner = Spinner("ILX AI thinking")
        spinner.start()

        user_msg_index = len(self.history) - 1  # track position before entering loop
        try:
            for _round in range(5):
                text, tool_calls = client.chat_with_tools(msgs, system=system,
                                                          tools=BUILTIN_TOOL_DEFS)
                if not tool_calls:
                    spinner.stop(clear=True)
                    final_text = text
                    break

                spinner.stop(clear=True)

                # Append the assistant tool-call message in provider format
                if provider == "anthropic":
                    msgs.append(fmt.format_assistant_tool_use_anthropic(tool_calls))
                elif provider == "gemini":
                    msgs.append(fmt.format_assistant_function_call_gemini(tool_calls))
                else:  # openai / groq / ollama
                    msgs.append(fmt.format_assistant_tool_calls_openai(tool_calls))

                # Execute tool calls in parallel where possible, then append results
                permission_cb = self._make_permission_cb()
                tool_results = self._execute_tool_calls_parallel(
                    tool_calls, mcp, permission_cb
                )
                for res in tool_results:
                    tool_name  = res["name"]
                    tool_id    = res["id"]
                    result_str = res["result_str"]
                    # Find original args for display (match by id)
                    orig_args = next(
                        (tc["input"] for tc in tool_calls if tc["id"] == tool_id),
                        {}
                    )
                    print(f"  {DIM}[tool] {CYAN}{tool_name}{RESET}{DIM}({orig_args}){RESET}")
                    print(f"  {DIM}       → {result_str[:120]}{RESET}")

                    if provider == "anthropic":
                        msgs.append(fmt.format_tool_result_anthropic(tool_id, result_str))
                    elif provider == "gemini":
                        msgs.append(fmt.format_tool_result_gemini(tool_name, result_str))
                    else:
                        msgs.append(fmt.format_tool_result_openai(tool_id, tool_name, result_str))

                spinner = Spinner("ILX AI thinking")
                spinner.start()

            else:
                # Exceeded max rounds
                spinner.stop(clear=True)
                if not final_text:
                    final_text = "(tool-use loop limit reached)"

        except Exception as exc:
            spinner.stop(clear=True)
            _log.error("Tool execution loop failed: %s", exc, exc_info=True)
            print(f"\n{RED}Error: {exc}{RESET}\n")
            # Restore history to the state before the user message was appended
            if len(self.history) > user_msg_index:
                self.history = self.history[:user_msg_index]
            return False

        latency_ms = (time.monotonic() - t_start) * 1000

        print(f"\n{GREEN}ILX AI:{RESET} ", end="", flush=True)
        print(final_text, flush=True)

        usage = client.last_usage
        if usage.prompt_tokens or usage.completion_tokens:
            from app.core.cost_tracker import tracker as _cost_tracker
            from cli.display import estimate_cost, format_cost
            cost = estimate_cost(provider, client.model,
                                 usage.prompt_tokens, usage.completion_tokens)
            # Accumulate into session tracker
            _cost_tracker.add(provider, client.model,
                               usage.prompt_tokens, usage.completion_tokens)
            cost_str = format_cost(cost, provider)
            cost_part = f"  ({cost_str})" if cost_str else ""
            try:
                print(
                    f"\n  {DIM}"
                    f"↳ {usage.prompt_tokens} prompt"
                    f" + {usage.completion_tokens} completion"
                    f" = {usage.total_tokens} tokens"
                    f"{cost_part}"
                    f"{RESET}"
                )
            except UnicodeEncodeError:
                print(
                    f"\n  {DIM}"
                    f"-> {usage.prompt_tokens} prompt"
                    f" + {usage.completion_tokens} completion"
                    f" = {usage.total_tokens} tokens"
                    f"{cost_part}"
                    f"{RESET}"
                )
        print()

        self.history.append({"role": "assistant", "content": final_text})

        audit.log_llm_call(
            model=client.model,
            prompt_tokens=usage.prompt_tokens,
            response_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
            provider=provider,
        )
        return True
