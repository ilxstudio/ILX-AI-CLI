from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass

from .response_parser import LLMResponse, FileAction


class ValidationError(Exception):
    pass


@dataclass
class ValidationWarning:
    field:   str
    message: str


class ResponseValidator:
    ALLOWED_ACTIONS   = {"replace", "append", "delete"}
    ALLOWED_COMMANDS  = {
        "python", "python3", "pytest",
        "pip", "pip3",
        "node", "npm", "npx",
        "make", "cmake",
        "git",
        "bash", "sh",
        "cargo", "rustc",
        "go",
        "java", "javac", "mvn", "gradle",
    }
    MAX_FILE_SIZE_BYTES = 512_000
    SUSPICIOUS_PATTERNS = [
        r"subprocess\.call\s*\(",
        r"shutil\.rmtree",
        r"__import__\s*\(",
    ]
    BLOCK_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"\bos\.system\s*\(",
        r"\bsubprocess\.Popen\s*\([^)]*shell\s*=\s*True",
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"shutil\.rmtree\s*\(\s*['\"]?[/\\]",
    ]

    _DRIVE_LETTER_RE: re.Pattern[str] = re.compile(r"^[A-Za-z]:[/\\]")
    _SUSPICIOUS_RES:  list[re.Pattern[str]] = [re.compile(p) for p in SUSPICIOUS_PATTERNS]
    _BLOCK_RES:       list[re.Pattern[str]] = [re.compile(p) for p in BLOCK_PATTERNS]

    def _validate_file_action(self, fa: FileAction, index: int, warnings: list[ValidationWarning]) -> None:
        prefix = f"files[{index}]"
        raw_path = fa.path
        if raw_path.startswith("/") or raw_path.startswith("\\"):
            raise ValidationError(f"{prefix}.path is absolute: {raw_path!r}")
        if self._DRIVE_LETTER_RE.match(raw_path):
            raise ValidationError(f"{prefix}.path contains a drive letter: {raw_path!r}")
        parts = Path(raw_path.replace("\\", "/")).parts
        if any(part == ".." for part in parts):
            raise ValidationError(f"{prefix}.path contains directory traversal '..': {raw_path!r}")
        if fa.action not in self.ALLOWED_ACTIONS:
            raise ValidationError(
                f"{prefix}.action {fa.action!r} is not allowed. Must be one of: {sorted(self.ALLOWED_ACTIONS)}"
            )
        if not isinstance(fa.content, str):
            raise ValidationError(f"{prefix}.content must be a str")
        content_bytes = len(fa.content.encode("utf-8"))
        if content_bytes > self.MAX_FILE_SIZE_BYTES:
            raise ValidationError(
                f"{prefix}.content exceeds max size ({content_bytes} bytes > {self.MAX_FILE_SIZE_BYTES} bytes)"
            )
        for pattern_re in self._BLOCK_RES:
            if pattern_re.search(fa.content):
                raise ValidationError(
                    f"{prefix}.content blocked: matches dangerous pattern {pattern_re.pattern!r}"
                )
        for pattern_re in self._SUSPICIOUS_RES:
            if pattern_re.search(fa.content):
                warnings.append(ValidationWarning(
                    field=f"{prefix}.content",
                    message=f"Suspicious pattern matched: {pattern_re.pattern!r}",
                ))

    def validate(self, response: LLMResponse) -> list[ValidationWarning]:
        warnings: list[ValidationWarning] = []
        for i, fa in enumerate(response.files):
            self._validate_file_action(fa, i, warnings)
        if response.command_to_run is not None:
            cmd = response.command_to_run.strip()
            if not cmd:
                raise ValidationError("command_to_run is an empty string")
            first_token = Path(cmd.split()[0]).name  # strip path prefix, keep basename
            if first_token not in self.ALLOWED_COMMANDS:
                raise ValidationError(
                    f"command_to_run starts with {first_token!r} which is not in "
                    f"ALLOWED_COMMANDS: {sorted(self.ALLOWED_COMMANDS)}"
                )
        return warnings
