"""Workspace media/web commands mixin — /readme, /convert, /fetch, /tool."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.workspace_media")


class WorkspaceMediaMixin:
    """Mixin providing /readme, /convert, /fetch, and /tool commands.

    Expects ``self.cfg`` to be an ``AppConfig`` instance (set by the
    host class ``WorkspaceCommands``).
    """

    cfg: "AppConfig"

    # ── /readme ───────────────────────────────────────────────────────────────

    def cmd_readme(self) -> None:
        """Generate a README.md for the current workspace using the LLM."""
        from cli.display import DIM, GREEN, RED, YELLOW, CYAN, RESET
        from codex.app.llm_client import get_llm_client
        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return
        root = Path(wf)
        # Gather context: file listing + any existing README
        files = sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and not any(
                d in p.relative_to(root).parts
                for d in {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
            )
        )[:60]
        existing = (root / "README.md").read_text(encoding="utf-8", errors="replace")[:500] \
            if (root / "README.md").exists() else ""
        file_list = "\n".join(files)
        prompt = (
            f"Generate a professional README.md for this project.\n\n"
            f"Project files:\n{file_list}\n\n"
            f"{'Existing README (partial):\n' + existing if existing else ''}\n\n"
            f"Include: project title, badges placeholder, overview, features list, "
            f"installation steps, usage examples, and a testing section. "
            f"Return only the markdown content."
        )
        print(f"  {DIM}Generating README.md with LLM...{RESET}")
        client = get_llm_client(self.cfg)
        try:
            content = client.chat([{"role": "user", "content": prompt}])
        except Exception as exc:
            print(f"  {RED}LLM error: {exc}{RESET}")
            return
        # Strip code fences if wrapped
        import re
        m = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", content, re.DOTALL)
        readme_text = m.group(1).strip() if m else content.strip()
        out_path = root / "README.md"
        print(f"\n  {DIM}Preview (first 400 chars):{RESET}\n  {readme_text[:400]}\n")
        try:
            ans = input(f"  {CYAN}Write README.md? [y/N] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans in ("y", "yes"):
            out_path.write_text(readme_text + "\n", encoding="utf-8")
            print(f"  {GREEN}Written: README.md{RESET}")
        else:
            print(f"  {DIM}Cancelled.{RESET}")

    # ── /convert ──────────────────────────────────────────────────────────────

    def cmd_convert(self, args: list[str]) -> None:
        """Handle /convert <input_file> [output_file].

        Reads PDF, DOCX, XLSX, or PNG and optionally writes a converted output.
        """
        from cli.display import DIM, GREEN, RED, YELLOW, CYAN, BOLD, RESET
        from app.core import file_converter

        _EXT_READERS = {
            ".pdf":  file_converter.read_pdf,
            ".docx": file_converter.read_docx,
            ".xlsx": file_converter.read_xlsx,
            ".png":  file_converter.read_png,
        }

        if not args:
            print(f"{YELLOW}Usage: /convert <input_file> [output_file]{RESET}")
            print(f"  Supported input formats: .pdf .docx .xlsx .png")
            print(f"  Example: /convert report.pdf report.txt")
            return

        in_path_raw = args[0]
        out_path_raw = args[1] if len(args) >= 2 else None

        # Resolve input relative to working folder when possible.
        # Use safe_resolve() to block path traversal (e.g. /convert ../../etc/shadow).
        from app.utils.file_utils import safe_resolve as _safe_resolve
        wf = self.cfg.working_folder
        if wf and not Path(in_path_raw).is_absolute():
            resolved_in = _safe_resolve(in_path_raw, wf)
            if resolved_in is None:
                print(f"{RED}Path traversal blocked:{RESET} {in_path_raw!r} is outside the workspace.")
                return
            in_path = Path(resolved_in)
        else:
            in_path = Path(in_path_raw) if Path(in_path_raw).is_absolute() else Path(in_path_raw).resolve()

        in_ext = in_path.suffix.lower()
        reader = _EXT_READERS.get(in_ext)
        if reader is None:
            print(f"{YELLOW}Unsupported input format '{in_ext}'.{RESET}")
            print(f"  Supported: {', '.join(_EXT_READERS)}")
            return

        if not in_path.exists():
            print(f"{RED}File not found:{RESET} {in_path}")
            return

        print(f"  {DIM}Reading {in_path.name}...{RESET}")
        result = reader(str(in_path))

        if not result.get("ok"):
            err = result.get("error", "unknown error")
            if "not installed" in err or "pip install" in err:
                print(f"{YELLOW}Missing dependency:{RESET} {err}")
            else:
                print(f"{RED}Read error:{RESET} {err}")
            return

        # Print summary
        if in_ext == ".pdf":
            pages = result.get("pages", 0)
            text_len = len(result.get("text", ""))
            print(f"  {GREEN}PDF read:{RESET} {pages} page(s), {text_len} chars extracted")
            preview = result.get("text", "")[:300].replace("\n", " ")
            if preview:
                print(f"  {DIM}{preview}...{RESET}")

        elif in_ext == ".docx":
            text_len = len(result.get("text", ""))
            print(f"  {GREEN}DOCX read:{RESET} {text_len} chars extracted")
            preview = result.get("text", "")[:300].replace("\n", " ")
            if preview:
                print(f"  {DIM}{preview}...{RESET}")

        elif in_ext == ".xlsx":
            sheets = result.get("sheets", {})
            total_rows = sum(len(rows) for rows in sheets.values())
            print(f"  {GREEN}XLSX read:{RESET} {len(sheets)} sheet(s), {total_rows} total rows")
            for sname, rows in sheets.items():
                print(f"    {CYAN}{sname}{RESET}: {len(rows)} row(s)")

        elif in_ext == ".png":
            w = result.get("width", 0)
            h = result.get("height", 0)
            mode = result.get("mode", "")
            print(f"  {GREEN}PNG read:{RESET} {w}x{h}  mode={mode}")
            print(f"  {DIM}Note: PNG cannot be converted to text — dimensions only.{RESET}")
            return  # No write step for PNG

        # Optionally write output
        if out_path_raw is None:
            return

        # Sandbox the output path the same way we did the input path.
        if wf and not Path(out_path_raw).is_absolute():
            resolved_out = _safe_resolve(out_path_raw, wf)
            if resolved_out is None:
                print(f"{RED}Path traversal blocked:{RESET} output {out_path_raw!r} is outside the workspace.")
                return
            out_path = Path(resolved_out)
        else:
            out_path = Path(out_path_raw) if Path(out_path_raw).is_absolute() else Path(out_path_raw).resolve()

        out_ext = out_path.suffix.lower()

        # Conversion matrix
        _valid_out: dict[str, set[str]] = {
            ".pdf":  {".txt", ".docx"},
            ".docx": {".txt", ".pdf"},
            ".xlsx": {".txt", ".csv"},
        }
        allowed = _valid_out.get(in_ext, set())
        if out_ext not in allowed:
            print(f"{YELLOW}Cannot convert {in_ext} → {out_ext}.{RESET}")
            print(f"  Allowed output formats for {in_ext}: {', '.join(sorted(allowed))}")
            return

        text = result.get("text", "")

        try:
            if out_ext == ".txt":
                out_path.write_text(text, encoding="utf-8")
                print(f"  {GREEN}Written:{RESET} {out_path}  ({len(text)} chars)")

            elif out_ext == ".docx":
                r = file_converter.write_docx(str(out_path), text)
                if r["ok"]:
                    print(f"  {GREEN}Written:{RESET} {out_path}")
                else:
                    print(f"  {RED}Write error:{RESET} {r['error']}")

            elif out_ext == ".pdf":
                r = file_converter.write_pdf(str(out_path), text)
                if r["ok"]:
                    print(f"  {GREEN}Written:{RESET} {out_path}")
                else:
                    print(f"  {RED}Write error:{RESET} {r['error']}")

            elif out_ext == ".csv":
                import csv
                import io
                sheets = result.get("sheets", {})
                first_rows: list[list] = next(iter(sheets.values()), []) if sheets else []
                buf = io.StringIO()
                writer = csv.writer(buf)
                for row in first_rows:
                    writer.writerow(["" if v is None else str(v) for v in row])
                out_path.write_text(buf.getvalue(), encoding="utf-8")
                print(f"  {GREEN}Written:{RESET} {out_path}  ({len(first_rows)} rows)")

        except Exception as exc:
            print(f"  {RED}Conversion failed:{RESET} {exc}")

    # ── /fetch ────────────────────────────────────────────────────────────────

    def cmd_fetch(self, args: list[str]) -> None:
        """/fetch <url> [save]  — fetch a URL and display the page text."""
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
        from app.core import web_fetch

        if not args:
            print(f"  {YELLOW}Usage: /fetch <url> [save]{RESET}")
            print(f"  {DIM}Example: /fetch https://example.com{RESET}")
            print(f"  {DIM}         /fetch https://example.com save{RESET}")
            return

        url = args[0]
        do_save = len(args) >= 2 and args[1].lower() == "save"

        print(f"  {DIM}Fetching {url} ...{RESET}")
        result = web_fetch.fetch_url(url)

        if not result["ok"]:
            err = result["error"]
            print(f"  {RED}Fetch failed:{RESET} {err}")
            if any(k in err for k in ("Blocked", "private", "loopback")):
                print(
                    f"  {DIM}To allow local/private URLs, set the environment variable:{RESET}\n"
                    f"    {CYAN}ILX_ALLOW_LOCAL_HTTP=1{RESET}"
                )
            return

        title = result["title"]
        text  = result["text"]

        if title:
            print(f"\n{BOLD}Title:{RESET} {title}")
        print(f"{DIM}URL:{RESET} {result['url']}\n")

        preview = text[:3000]
        print(preview)
        if len(text) > 3000:
            print(f"\n{DIM}... (truncated — {len(text)} total chars){RESET}")

        if do_save:
            wf = self.cfg.working_folder
            if not wf:
                print(f"\n  {YELLOW}No workspace set — cannot save. Use /workspace first.{RESET}")
                return
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path(wf) / f"fetch_{ts}.txt"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            header = f"URL: {url}\nTitle: {title}\nFetched: {ts}\n\n"
            out_path.write_text(header + text, encoding="utf-8")
            print(f"\n  {GREEN}Saved:{RESET} {out_path}")

    # ── /tool ─────────────────────────────────────────────────────────────────

    def cmd_tool(self, args: list[str]) -> None:
        """/tool list|create|run — manage dynamic Python tools."""
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
        from app.core.tool_builder import ToolBuilder
        from codex.app.llm_client import get_llm_client

        sub = args[0].lower() if args else "list"

        try:
            llm = get_llm_client(self.cfg)
        except Exception:
            llm = None
        builder = ToolBuilder(self.cfg, llm_client=llm)

        def _permission(kind: str, target: str, detail: str) -> bool:
            label = "create tool" if "create" in kind else "run tool"
            try:
                ans = input(
                    f"  {YELLOW}Allow {label} '{Path(target).name}'? [y/N]{RESET} "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return ans in ("y", "yes")

        if sub == "list":
            paths = builder.list_tools()
            if not paths:
                print(f"  {DIM}No tools in workspace/tools/ yet.{RESET}")
                print(f"  {DIM}Use /tool create <name> <description> to generate one.{RESET}")
            else:
                print(f"\n{BOLD}Workspace tools:{RESET}")
                for p in paths:
                    name = Path(p).stem
                    print(f"  {CYAN}{name}{RESET}  {DIM}({p}){RESET}")
                print()

        elif sub == "create":
            if len(args) < 3:
                print(f"  {YELLOW}Usage: /tool create <name> <description of what the tool does>{RESET}")
                return
            tool_name = args[1]
            description = " ".join(args[2:])
            print(f"  {DIM}Asking LLM to write '{tool_name}' ...{RESET}")
            result = builder.generate_tool(description, permission_callback=_permission)
            if result["ok"]:
                print(f"  {GREEN}Tool created:{RESET} {result['path']}")
                if result.get("code"):
                    preview = result["code"][:400]
                    print(f"\n{DIM}--- Preview ---{RESET}\n{preview}")
                    if len(result["code"]) > 400:
                        print(f"{DIM}... ({len(result['code'])} total chars){RESET}")
            else:
                print(f"  {RED}Failed:{RESET} {result['error']}")

        elif sub == "run":
            if len(args) < 2:
                print(f"  {YELLOW}Usage: /tool run <name> [args...]{RESET}")
                return
            tool_name = args[1]
            run_args  = args[2:]
            result = builder.run_tool(tool_name, run_args, permission_callback=_permission)
            if result["ok"]:
                output = result["output"] or "(no output)"
                print(f"\n{BOLD}Tool output:{RESET}\n{output}\n")
            else:
                print(f"  {RED}Tool error:{RESET} {result['error']}")
                if result.get("output"):
                    print(result["output"])

        else:
            print(
                f"  {YELLOW}Usage: /tool list | "
                f"/tool create <name> <desc> | "
                f"/tool run <name> [args]{RESET}"
            )
