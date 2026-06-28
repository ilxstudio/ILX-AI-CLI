"""User tool builder — LLM generates tool code, validator verifies, registry stores it."""
from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Callable
from pathlib import Path

from app.core.user_tools.registry import UserTool, UserToolRegistry
from app.core.user_tools.registry import registry as _registry
from app.core.user_tools.validator import ToolValidator

_log = logging.getLogger("ilx_cli.user_tools.builder")

_TOOL_TEMPLATE = '''\
#!/usr/bin/env python3
"""ILX User Tool: {name}

{description}

Usage:
    /{name} [args...]
    python {name}.py --ilx-healthcheck   # self-test

Created by ILX AI CLI self-improvement system.
"""
from __future__ import annotations
import os
import sys
import argparse


def main(args: list[str] = None) -> int:
    """Main entry point. Return 0 on success."""
    # ILX_TOOL_VALIDATE: quick-exit for import/syntax checks
    if os.environ.get("ILX_TOOL_VALIDATE") == "1":
        sys.exit(0)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ilx-healthcheck", action="store_true",
                        help="Run self-test and exit")
    # TODO: add your arguments here
    parsed = parser.parse_args(args)

    if parsed.ilx_healthcheck:
        print("OK: {name} health check passed")
        return 0

    # TODO: implement the tool logic here
    print("Hello from {name}!")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

_LLM_PROMPT = """\
Write a complete, self-contained Python 3.11+ script for an ILX AI CLI user tool.

Tool name: {name}
Description: {description}
Task: {task_detail}

Requirements:
- Use argparse for CLI arguments.
- Support --ilx-healthcheck flag that prints 'OK: {name} health check passed' and exits 0.
- Check os.environ.get('ILX_TOOL_VALIDATE') == '1' near the top of main(); if true,
  call sys.exit(0) immediately to skip heavy init during import validation.
- All imports at the top; handle optional deps with try/except ImportError and
  print a helpful "pip install <pkg>" message.
- A main(args=None) function that returns an int exit code.
- if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
- Include a docstring explaining what the tool does.

Return ONLY the Python code, no explanation or markdown fences.
"""


class ToolBuilder:
    """Orchestrates LLM code generation, validation, disk write, and registry entry.

    Collaborates with:
      - ToolValidator      — three-stage sandbox validation before registration
      - UserToolRegistry   — persistent metadata store
    """

    def __init__(
        self,
        cfg,
        llm_client=None,
        tool_registry: UserToolRegistry | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm_client
        self._registry = tool_registry or _registry
        self._validator = ToolValidator()
        wf = getattr(cfg, "working_folder", "") or ""
        self._tools_dir = (
            Path(wf) / "user_tools" if wf else Path.home() / ".ilx_cli" / "user_tools"
        )
        # Populated by generate_code when use_research=True
        self._last_research: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_code(
        self,
        name: str,
        description: str,
        task_detail: str,
        *,
        use_research: bool = False,
    ) -> str:
        """Ask the LLM to write a complete tool Python file.

        Falls back to the built-in template when no LLM client is available
        or when the LLM call fails.  Always returns non-empty source code.

        When ``use_research=True`` and an LLM client is available, relevant
        documentation is fetched and prepended to the generation prompt.
        Fetched research context is stored in ``self._last_research``.
        """
        self._last_research = ""

        if not self.llm:
            _log.debug("No LLM client — using built-in template for tool '%s'", name)
            return _TOOL_TEMPLATE.format(name=name, description=description)

        base_prompt = _LLM_PROMPT.format(
            name=name,
            description=description,
            task_detail=task_detail,
        )

        # ── Optional research augmentation ───────────────────────────────────
        research_prefix = ""
        if use_research:
            try:
                from app.core.research_fetcher import (
                    build_research_context,
                    fetch_research,
                    get_default_cache,
                    infer_topics,
                )
                topics = infer_topics(description, task_detail)
                if topics:
                    print(
                        f"  [research] Fetching docs for: {', '.join(topics)}..."
                    )
                    results = fetch_research(
                        topics, max_urls=4, timeout=8, cache=get_default_cache()
                    )
                    if results:
                        research_prefix = build_research_context(results) + "\n\n"
                        self._last_research = research_prefix
                        _log.debug(
                            "Research augmentation: %d source(s) fetched for %s",
                            len(results), name,
                        )
            except Exception as exc:
                _log.warning("Research fetch failed for tool '%s': %s", name, exc)

        prompt = research_prefix + base_prompt

        try:
            response = self.llm.chat([{"role": "user", "content": prompt}])
        except Exception as exc:
            _log.warning("LLM code generation failed: %s", exc)
            print(
                f"  [warning] LLM generation failed ({type(exc).__name__}): falling back to template"
            )
            return _TOOL_TEMPLATE.format(name=name, description=description)

        # Strip fenced code block if the LLM wrapped the code anyway
        m = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
        code = m.group(1).strip() if m else response.strip()

        if not code:
            _log.warning("LLM returned empty response for tool '%s' — using template", name)
            return _TOOL_TEMPLATE.format(name=name, description=description)

        return code

    def create_tool(
        self,
        name: str,
        description: str,
        code: str,
        permission_callback: Callable | None = None,
    ) -> dict:
        """Write tool source to disk after permission check.

        Args:
            name:                Tool command name (without /).
            description:         One-line description.
            code:                Python source code string.
            permission_callback: Callable(kind, target, detail) -> bool.
                                 Always invoked regardless of permission_mode.

        Returns:
            {"ok": bool, "path": str, "error": str}
        """
        self._tools_dir.mkdir(parents=True, exist_ok=True)
        tool_path = self._tools_dir / f"{name}.py"

        # Always request explicit user approval — writing scripts is destructive.
        if permission_callback is not None:
            allowed = permission_callback(
                "write_file",
                str(tool_path),
                f"Create user tool /{name}: {description}",
            )
            if not allowed:
                return {"ok": False, "path": str(tool_path), "error": "Permission denied by user"}

        try:
            tool_path.write_text(code, encoding="utf-8")
            _log.debug("Tool written: %s", tool_path)
            return {"ok": True, "path": str(tool_path), "error": ""}
        except OSError as exc:
            return {"ok": False, "path": str(tool_path), "error": str(exc)}

    def build_and_register(
        self,
        name: str,
        description: str,
        task_detail: str,
        permission_callback: Callable | None = None,
        validate: bool = True,
        use_research: bool = False,
    ) -> dict:
        """Full pipeline: generate code → validate → write to disk → register.

        When an LLM client is available, autofix is enabled in cfg, and
        validation fails, the Reflexion loop is used to iteratively improve
        the generated code before giving up.

        Returns a dict with keys:
            ok (bool), path (str), error (str),
            validation (ValidationResult | None), code (str),
            generation_attempts (int)
        """
        # 1. Validate name against the registry
        valid, name_err = self._registry.check_name(name)
        if not valid:
            return {
                "ok": False, "path": "", "error": name_err,
                "validation": None, "code": "", "generation_attempts": 0,
            }

        autofix_enabled = getattr(self.cfg, "autofix_enabled", True)
        use_reflexion = validate and self.llm and autofix_enabled

        # 2. Reflexion path — LLM + autofix enabled
        if use_reflexion:
            from app.core.reflexion import ReflexionLoop, ReflexionResult
            base_prompt = _LLM_PROMPT.format(
                name=name,
                description=description,
                task_detail=task_detail,
            )
            # Prepend research context when requested
            research_prefix = ""
            if use_research:
                try:
                    from app.core.research_fetcher import (
                        build_research_context,
                        fetch_research,
                        get_default_cache,
                        infer_topics,
                    )
                    topics = infer_topics(description, task_detail)
                    if topics:
                        print(f"  [research] Fetching docs for: {', '.join(topics)}...")
                        results = fetch_research(
                            topics, max_urls=4, timeout=8, cache=get_default_cache()
                        )
                        if results:
                            research_prefix = build_research_context(results) + "\n\n"
                            self._last_research = research_prefix
                except Exception as exc:
                    _log.warning("Research fetch failed for tool '%s': %s", name, exc)
            initial_prompt = research_prefix + base_prompt
            loop = ReflexionLoop(
                llm_client=self.llm,
                validator=self._validator,
                max_attempts=3,
            )
            try:
                reflexion_result = loop.run(initial_prompt)
            except Exception as exc:
                _log.warning(
                    "Reflexion loop failed (%s), falling back to single-attempt generation", exc
                )
                fallback_code = self.generate_code(
                    name, description, task_detail,
                    use_research=use_research,
                )
                reflexion_result = ReflexionResult(
                    success=True,
                    final_code=fallback_code,
                    attempts=[],
                    total_attempts=1,
                )
            generation_attempts = reflexion_result.total_attempts

            if reflexion_result.success:
                code = reflexion_result.final_code
            else:
                # All attempts failed — collect reflection summaries and return
                all_reflections = [
                    {
                        "attempt": a.attempt_number,
                        "errors": a.errors,
                        "reflection": a.reflection,
                    }
                    for a in reflexion_result.attempts
                ]
                last_errors = reflexion_result.attempts[-1].errors if reflexion_result.attempts else []
                err = "; ".join(last_errors) if last_errors else "All Reflexion attempts failed"
                return {
                    "ok": False,
                    "path": "",
                    "error": f"Validation failed after {generation_attempts} attempt(s): {err}",
                    "validation": None,
                    "code": reflexion_result.final_code,
                    "generation_attempts": generation_attempts,
                    "reflexion_attempts": all_reflections,
                }

            # Run final validation to capture the ValidationResult object
            import os as _os
            import tempfile
            validation = None
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False,
                encoding="utf-8", prefix=f"ilx_tool_{name}_",
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            try:
                validation = self._validator.validate(tmp_path)
            finally:
                try:
                    _os.unlink(tmp_path)
                except OSError:
                    pass

        else:
            # 2b. Non-Reflexion path — generate once, validate once
            code = self.generate_code(name, description, task_detail, use_research=use_research)
            generation_attempts = 1
            validation = None

            if validate:
                import os as _os
                import tempfile
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False,
                    encoding="utf-8", prefix=f"ilx_tool_{name}_",
                ) as tmp:
                    tmp.write(code)
                    tmp_path = tmp.name
                try:
                    validation = self._validator.validate(tmp_path)
                finally:
                    try:
                        _os.unlink(tmp_path)
                    except OSError:
                        pass

                if not validation.ok:
                    err = "; ".join(validation.errors)
                    return {
                        "ok": False,
                        "path": "",
                        "error": f"Validation failed: {err}",
                        "validation": validation,
                        "code": code,
                        "generation_attempts": generation_attempts,
                    }

        # 3. Write to disk
        write_result = self.create_tool(name, description, code, permission_callback)
        if not write_result["ok"]:
            return {**write_result, "validation": validation, "code": code,
                    "generation_attempts": generation_attempts}

        # 4. Register in the persistent registry
        now = datetime.datetime.now().isoformat(timespec="seconds")
        tool = UserTool(
            name=name,
            description=description,
            path=write_result["path"],
            enabled=True,
            version=1,
            created_at=now,
            last_run="",
            generation_attempts=generation_attempts,
        )
        try:
            self._registry.register(tool)
        except Exception as exc:
            _log.error("Failed to register tool '%s': %s", name, exc)
            return {
                "ok": False,
                "error": f"Tool code generated but registration failed: {exc}",
                "path": write_result["path"],
                "validation": validation,
                "code": code,
                "generation_attempts": generation_attempts,
            }
        _log.info(
            "Registered user tool '/%s' at %s (generation_attempts=%d)",
            name, write_result["path"], generation_attempts,
        )

        return {
            "ok": True,
            "path": write_result["path"],
            "error": "",
            "validation": validation,
            "code": code,
            "generation_attempts": generation_attempts,
        }

    def update_tool(
        self,
        name: str,
        new_code: str,
        permission_callback: Callable | None = None,
        validate: bool = True,
    ) -> dict:
        """Replace an existing tool's code on disk and bump its version in the registry.

        Returns {"ok": bool, "path": str, "error": str, "version": int}.
        """
        tool = self._registry.get(name)
        if tool is None:
            return {
                "ok": False, "path": "", "version": 0,
                "error": f"Tool '/{name}' not found in registry",
            }

        # Validate new code against a temp file
        if validate:
            import os as _os
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False,
                encoding="utf-8", prefix=f"ilx_tool_{name}_v",
            ) as tmp:
                tmp.write(new_code)
                tmp_path = tmp.name
            try:
                validation = self._validator.validate(tmp_path)
            finally:
                try:
                    _os.unlink(tmp_path)
                except OSError:
                    pass

            if not validation.ok:
                err = "; ".join(validation.errors)
                return {
                    "ok": False, "path": tool.path, "version": tool.version,
                    "error": f"Validation failed: {err}",
                }

        # Permission check before overwrite
        tool_path = Path(tool.path)
        if permission_callback is not None:
            allowed = permission_callback(
                "write_file",
                str(tool_path),
                f"Update user tool /{name} (version {tool.version} → {tool.version + 1})",
            )
            if not allowed:
                return {
                    "ok": False, "path": tool.path, "version": tool.version,
                    "error": "Permission denied by user",
                }

        try:
            tool_path.write_text(new_code, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "path": tool.path, "version": tool.version, "error": str(exc)}

        new_version = self._registry.bump_version(name)
        _log.info("Updated user tool '/%s' to version %d", name, new_version)
        return {"ok": True, "path": tool.path, "error": "", "version": new_version}

    def tools_dir(self) -> Path:
        """Return the directory where user tool files are stored."""
        return self._tools_dir
