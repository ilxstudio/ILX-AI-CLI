"""Unified-diff parser for per-hunk review."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    header:    str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines:     list[str] = field(default_factory=list)

    def summary(self) -> str:
        adds = sum(1 for l in self.lines if l.startswith("+") and not l.startswith("+++"))
        rems = sum(1 for l in self.lines if l.startswith("-") and not l.startswith("---"))
        return f"@@ {self.old_start}+{self.old_count} → {self.new_start}+{self.new_count}  ({adds}+ / {rems}-)"


def parse_unified(diff_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    cur: Hunk | None = None
    for line in diff_text.splitlines():
        m = _HUNK_HEADER.match(line)
        if m:
            if cur is not None:
                hunks.append(cur)
            cur = Hunk(
                header=line,
                old_start=int(m.group(1)),
                old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) or 1),
            )
            continue
        if line.startswith("---") or line.startswith("+++") or line.startswith("diff "):
            continue
        if cur is None:
            continue
        cur.lines.append(line)
    if cur is not None:
        hunks.append(cur)
    return hunks


def synthesize_new_file_hunk(new_content: str) -> Hunk:
    new_lines = new_content.splitlines() if new_content else []
    hunk_lines = [f"+{l}" for l in new_lines] or ["+"]
    return Hunk(
        header=f"@@ -0,0 +1,{len(new_lines)} @@",
        old_start=0, old_count=0,
        new_start=1, new_count=len(new_lines),
        lines=hunk_lines,
    )


def apply_selected(old_content: str, hunks: list[Hunk], selected: list[bool]) -> str:
    if len(hunks) != len(selected):
        raise ValueError("hunks and selected must be the same length")
    old_lines = old_content.splitlines(keepends=False)
    out: list[str] = []
    cursor = 0
    pairs = sorted(zip(hunks, selected), key=lambda p: p[0].old_start)
    for h, take in pairs:
        target = max(0, h.old_start - 1)
        while cursor < target and cursor < len(old_lines):
            out.append(old_lines[cursor])
            cursor += 1
        if take:
            for hl in h.lines:
                if not hl:
                    continue
                tag, body = hl[0], hl[1:]
                if tag == " ":
                    out.append(body)
                    cursor += 1
                elif tag == "+":
                    out.append(body)
                elif tag == "-":
                    cursor += 1
        else:
            for hl in h.lines:
                if not hl:
                    continue
                tag, body = hl[0], hl[1:]
                if tag in (" ", "-"):
                    if cursor < len(old_lines):
                        out.append(old_lines[cursor])
                    cursor += 1
    while cursor < len(old_lines):
        out.append(old_lines[cursor])
        cursor += 1
    sep = "\n"
    suffix = sep if old_content.endswith("\n") else ""
    return sep.join(out) + suffix
