from __future__ import annotations
import json
import re
from dataclasses import dataclass, field


class ParseError(Exception):
    pass


@dataclass
class FileAction:
    path:    str
    action:  str
    content: str = ""


@dataclass
class LLMResponse:
    summary:        str
    files:          list[FileAction]
    command_to_run: str | None = None


class ResponseParser:
    _FENCE_RE      = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
    _ALL_FENCES_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
    _OBJ_RE        = re.compile(r"\{[\s\S]*\}")
    _PREAMBLE_RE   = re.compile(
        r"^\s*(?:Here(?:'s| is) the (?:JSON|response|output)[:.]?\s*|"
        r"Sure[!,.]?\s*|Of course[!,.]?\s*|I'll [a-z ]+:?\s*)",
        re.IGNORECASE,
    )

    def _extract_json_text(self, raw: str) -> str:
        stripped = raw.strip()
        m = self._PREAMBLE_RE.match(stripped)
        if m:
            stripped = stripped[m.end():].lstrip()
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass
        fence_match = self._FENCE_RE.search(stripped)
        if fence_match:
            candidate = fence_match.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        all_fences = self._ALL_FENCES_RE.findall(stripped)
        for cand in all_fences:
            cand = cand.strip()
            if not cand.startswith("{"):
                continue
            try:
                json.loads(cand)
                return cand
            except json.JSONDecodeError:
                continue
        obj_match = self._OBJ_RE.search(stripped)
        if obj_match:
            candidate = obj_match.group(0).strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        first = stripped.find("{")
        if first >= 0:
            tail = stripped[first:]
            pos  = len(tail)
            while pos > 0:
                pos = tail.rfind("}", 0, pos)
                if pos < 0:
                    break
                try:
                    json.loads(tail[: pos + 1])
                    return tail[: pos + 1]
                except json.JSONDecodeError:
                    pass
            closed = self._close_truncated_json(tail)
            if closed:
                return closed
            lenient = self._loose_repair(tail)
            if lenient is not None:
                return lenient
        raise ParseError(
            "No valid JSON object found in model output. "
            f"Raw content (first 200 chars): {raw[:200]!r}"
        )

    @staticmethod
    def _loose_repair(raw: str) -> str | None:
        repaired = (
            raw
            .replace("“", '"').replace("”", '"')
            .replace("‘", "'").replace("’", "'")
        )
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        first = repaired.find("{")
        if first < 0:
            return None
        slice_ = repaired[first:]
        pos = len(slice_)
        while pos > 0:
            pos = slice_.rfind("}", 0, pos)
            if pos < 0:
                break
            cand = slice_[: pos + 1]
            try:
                json.loads(cand)
                return cand
            except json.JSONDecodeError:
                continue
        return None

    def _close_truncated_json(self, raw: str) -> str | None:
        stack: list[str] = []
        in_string = False
        escape = False
        for ch in raw:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ("{", "["):
                stack.append(ch)
            elif ch == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif ch == "]" and stack and stack[-1] == "[":
                stack.pop()
        if not stack and not in_string:
            return None
        suffix = ""
        if in_string:
            suffix += '"'
        for opener in reversed(stack):
            suffix += "}" if opener == "{" else "]"
        candidate = raw + suffix
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            return None

    def _parse_file_action(self, entry: object, index: int) -> FileAction:
        if not isinstance(entry, dict):
            raise ParseError(f"files[{index}] must be a JSON object, got {type(entry).__name__}")
        if "path" not in entry:
            raise ParseError(f"files[{index}] is missing required key 'path'")
        if "action" not in entry:
            raise ParseError(f"files[{index}] is missing required key 'action'")
        path    = entry["path"]
        action  = entry["action"]
        if not isinstance(path, str):
            raise ParseError(f"files[{index}].path must be a string")
        if not isinstance(action, str):
            raise ParseError(f"files[{index}].action must be a string")
        content = entry.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ParseError(f"files[{index}].content must be a string or absent")
        return FileAction(path=path, action=action, content=content)

    def parse(self, raw: str) -> LLMResponse:
        try:
            json_text = self._extract_json_text(raw)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Unexpected error extracting JSON: {exc}") from exc
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"JSON decode failed: {exc}") from exc
        if not isinstance(data, dict):
            raise ParseError(f"Top-level JSON value must be an object, got {type(data).__name__}")
        summary = data.get("summary", "")
        if not isinstance(summary, str):
            summary = ""
        if "files" not in data:
            raise ParseError("Response JSON missing required key 'files'")
        raw_files = data["files"]
        if not isinstance(raw_files, list):
            raise ParseError(f"'files' must be a JSON array, got {type(raw_files).__name__}")
        files: list[FileAction] = [
            self._parse_file_action(entry, i) for i, entry in enumerate(raw_files)
        ]
        command_to_run: str | None = data.get("command_to_run", None)
        if command_to_run is not None and not isinstance(command_to_run, str):
            raise ParseError(f"'command_to_run' must be a string or null")
        return LLMResponse(summary=summary, files=files, command_to_run=command_to_run)
