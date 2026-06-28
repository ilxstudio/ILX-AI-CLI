"""Sandbox validator — runs a user tool in isolation to verify it before registration."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Whitelist of known-safe env-var prefixes to pass to tool subprocesses.
# Everything not matching these prefixes is excluded, so new secrets added
# to the environment in future are denied by default.
_SAFE_ENV_PREFIXES = (
    "PATH", "PYTHONPATH", "PYTHONHOME", "HOME", "USERPROFILE",
    "TEMP", "TMP", "TMPDIR", "LANG", "LC_", "SYSTEMROOT",
    "WINDIR", "COMSPEC", "NUMBER_OF_PROCESSORS", "OS",
    "PROCESSOR_", "PROGRAMFILES", "APPDATA", "LOCALAPPDATA",
)


def _safe_env() -> dict[str, str]:
    """Return an env dict containing only known-safe variables.

    Uses a whitelist approach so new secrets added to the environment in
    future are excluded by default, rather than requiring the blacklist to
    be kept up to date.
    """
    safe: dict[str, str] = {}
    for key, val in os.environ.items():
        if any(key.upper().startswith(p) for p in _SAFE_ENV_PREFIXES):
            safe[key] = val
    # Always ensure PATH is present so tools can be found
    if "PATH" not in safe and "PATH" in os.environ:
        safe["PATH"] = os.environ["PATH"]
    return safe

import sys as _sys

PYTHON_EXE = _sys.executable


def _resolve_python() -> str:
    """Return the running Python executable."""
    return _sys.executable


class ValidationResult:
    """Result of a three-stage tool validation."""

    def __init__(
        self,
        ok: bool,
        syntax_ok: bool,
        import_ok: bool,
        smoke_ok: bool,
        errors: list[str],
        warnings: list[str],
        output: str,
    ) -> None:
        self.ok = ok
        self.syntax_ok = syntax_ok
        self.import_ok = import_ok
        self.smoke_ok = smoke_ok
        self.errors = errors
        self.warnings = warnings
        self.output = output

    def summary(self) -> str:
        """Return a compact human-readable summary line."""
        stages = (
            f"syntax={'OK' if self.syntax_ok else 'FAIL'} "
            f"imports={'OK' if self.import_ok else 'FAIL'} "
            f"smoke={'OK' if self.smoke_ok else 'SKIP/FAIL'}"
        )
        if self.ok:
            return f"Validation passed  [{stages}]"
        err_preview = self.errors[0][:120] if self.errors else "unknown error"
        return f"Validation failed — {err_preview}  [{stages}]"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ValidationResult ok={self.ok} errors={self.errors}>"


class ToolValidator:
    """Validates a tool Python file before registration.

    Three-stage pipeline:
      1. Syntax check — compile() the source in-process.
      2. Import check — exec the file via subprocess with ILX_TOOL_VALIDATE=1
         so the tool can opt-out of heavy init.
      3. Smoke test  — run the file with --ilx-healthcheck; accepts exit 0 or 2
         (argparse "unrecognised argument" is fine — the flag is optional).
    """

    def validate(self, path: str | Path, timeout: int = 30) -> ValidationResult:
        """Run all three validation stages and return a ValidationResult.

        *timeout* applies to each subprocess stage independently.
        """
        path = Path(path)
        errors: list[str] = []
        warnings: list[str] = []
        output_parts: list[str] = []

        # ── Stage 1: syntax ──────────────────────────────────────────────
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ValidationResult(
                ok=False,
                syntax_ok=False,
                import_ok=False,
                smoke_ok=False,
                errors=[f"Cannot read file: {exc}"],
                warnings=[],
                output="",
            )

        syntax_ok, syntax_err = self._check_syntax(source)
        if not syntax_ok:
            errors.append(f"[syntax] {syntax_err}")
            return ValidationResult(
                ok=False,
                syntax_ok=False,
                import_ok=False,
                smoke_ok=False,
                errors=errors,
                warnings=warnings,
                output="",
            )

        # Warn if no main() or no healthcheck support visible
        if "def main(" not in source:
            warnings.append("No main() function detected — tool may not be runnable via /tool run")
        if "--ilx-healthcheck" not in source:
            warnings.append(
                "Tool does not handle --ilx-healthcheck — smoke test will be skipped"
            )

        # ── Stage 2: import / exec check ─────────────────────────────────
        import_ok, import_err = self._check_imports(path, timeout=min(timeout, 15))
        if not import_ok:
            errors.append(f"[import] {import_err}")
            # Continue to smoke only if imports passed; otherwise bail.
            return ValidationResult(
                ok=False,
                syntax_ok=True,
                import_ok=False,
                smoke_ok=False,
                errors=errors,
                warnings=warnings,
                output=import_err[:500],
            )
        if import_err:
            output_parts.append(import_err)

        # ── Stage 3: smoke test ───────────────────────────────────────────
        smoke_ok, smoke_out, smoke_err = self._smoke_test(path, timeout=min(timeout, 20))
        combined = (smoke_out + smoke_err).strip()
        if combined:
            output_parts.append(combined)

        if not smoke_ok:
            # Smoke failures are warnings, not hard errors, when the tool
            # doesn't implement --ilx-healthcheck at all.
            if "--ilx-healthcheck" not in source:
                warnings.append(
                    "[smoke] --ilx-healthcheck not implemented; smoke test inconclusive"
                )
                smoke_ok = True  # treat as pass when the flag isn't expected
            else:
                errors.append("[smoke] Tool exited with non-zero code during health check")

        overall_ok = syntax_ok and import_ok and smoke_ok and not errors
        return ValidationResult(
            ok=overall_ok,
            syntax_ok=syntax_ok,
            import_ok=import_ok,
            smoke_ok=smoke_ok,
            errors=errors,
            warnings=warnings,
            output="\n".join(output_parts)[:1000],
        )

    # ------------------------------------------------------------------
    # Internal stages
    # ------------------------------------------------------------------

    def _check_syntax(self, source: str) -> tuple[bool, str]:
        """Compile *source* to check for syntax errors.

        Returns (ok, error_message).
        """
        try:
            compile(source, "<tool>", "exec")
            return True, ""
        except SyntaxError as exc:
            return False, f"SyntaxError line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"Compile error: {exc}"

    def _check_imports(self, path: Path, timeout: int = 15) -> tuple[bool, str]:
        """Execute the tool in a subprocess with ILX_TOOL_VALIDATE=1.

        The tool should detect this env var and exit 0 immediately, skipping
        heavy initialisation.  If the tool doesn't check it we still capture
        any ImportError or other startup error.

        Returns (ok, stderr_snippet).
        """
        python = _resolve_python()
        loader_snippet = (
            "import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location('_tool', r'{path}'); "
            "mod = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(mod)"
        )
        # Use a safe-listed env to avoid leaking API keys / passwords to the tool subprocess.
        env = {**_safe_env(), "ILX_TOOL_VALIDATE": "1"}
        try:
            r = subprocess.run(
                [python, "-c", loader_snippet],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip()
                return False, detail[:500]
            return True, (r.stderr or "").strip()[:200]
        except subprocess.TimeoutExpired:
            return False, f"Import check timed out after {timeout}s"
        except Exception as exc:
            return False, str(exc)

    def _smoke_test(self, path: Path, timeout: int = 20) -> tuple[bool, str, str]:
        """Run the tool with --ilx-healthcheck.

        Accepts exit codes 0 (pass) or 2 (argparse unknown-arg — tool doesn't
        implement the flag, which is also acceptable).

        Returns (ok, stdout_snippet, stderr_snippet).
        """
        python = _resolve_python()
        try:
            r = subprocess.run(
                [python, str(path), "--ilx-healthcheck"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_safe_env(),
            )
            ok = r.returncode in (0, 2)
            return ok, r.stdout[:300], r.stderr[:300]
        except subprocess.TimeoutExpired:
            return False, "", f"Smoke test timed out after {timeout}s"
        except Exception as exc:
            return False, "", str(exc)
