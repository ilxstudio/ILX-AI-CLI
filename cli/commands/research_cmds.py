"""Research CLI commands — fetch and inject technical docs into RAG context.

Commands
--------
/research <query>   — fetch docs for a topic, inject into RAG, show summary
/research list      — list all known topics in RESEARCH_SOURCES
/research clear     — clear the on-disk research cache
/research stats     — show cache stats (file count, total size)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.rag import RAG

_log = logging.getLogger("ilx_cli.research_cmds")


class ResearchCommands:
    """Handles /research sub-commands."""

    def __init__(self, rag: RAG) -> None:
        self._rag = rag

    # ------------------------------------------------------------------
    # Public dispatcher
    # ------------------------------------------------------------------

    def cmd_research(self, args: list[str]) -> None:
        """
        /research <query>   — fetch docs for a topic, inject into RAG context
        /research list      — list all known research topics
        /research clear     — clear the research cache
        /research stats     — show cache stats
        """
        if not args:
            self._print_usage()
            return

        sub = args[0].lower()

        if sub == "list":
            self._cmd_list()
        elif sub == "clear":
            self._cmd_clear()
        elif sub == "stats":
            self._cmd_stats()
        else:
            # Treat all non-subcommand tokens as the search query
            self._cmd_fetch(args)

    # ------------------------------------------------------------------
    # Sub-command implementations
    # ------------------------------------------------------------------

    def _cmd_fetch(self, args: list[str]) -> None:
        """Infer topics from the query, fetch docs, inject into RAG."""
        from app.core.research_fetcher import (
            fetch_research,
            get_default_cache,
            infer_topics,
        )
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

        query = " ".join(args)
        print(f"  {DIM}Inferring topics for: {query!r}...{RESET}")

        topics = infer_topics(query)
        if not topics:
            print(
                f"  {YELLOW}No matching topics found for '{query}'.{RESET}\n"
                f"  {DIM}Use /research list to see available topics.{RESET}"
            )
            return

        print(f"  {DIM}Topics: {', '.join(topics)}{RESET}")
        print(f"  {DIM}Fetching documentation...{RESET}")

        results = fetch_research(
            topics, max_urls=4, timeout=8, cache=get_default_cache()
        )

        if not results:
            print(f"  {YELLOW}Could not fetch any documentation (network unavailable?){RESET}")
            return

        # Inject each fetched document into the RAG index
        for entry in results:
            self._rag.add(entry["url"], entry["text"])
            _log.debug("Injected research doc into RAG: %s", entry["url"])

        # Print summary with excerpts
        print(f"\n{BOLD}Research results ({len(results)} source(s)):{RESET}")
        for entry in results:
            from urllib.parse import urlparse
            hostname = urlparse(entry["url"]).hostname or entry["url"]
            topic = entry.get("topic", "")
            excerpt = entry["text"][:200].replace("\n", " ").strip()
            print(f"  {CYAN}{hostname}{RESET}  {DIM}[{topic}]{RESET}")
            print(f"    {DIM}{excerpt}...{RESET}")
            print()

        print(
            f"  {GREEN}Research added to context.{RESET} "
            f"{DIM}Your next message will have access to these docs.{RESET}"
        )

    def _cmd_list(self) -> None:
        """List all known research topics."""
        from app.core.research_fetcher import RESEARCH_SOURCES
        from cli.display import BOLD, CYAN, DIM, RESET

        print(f"\n{BOLD}Available research topics:{RESET}")
        for topic, urls in sorted(RESEARCH_SOURCES.items()):
            url_count = len(urls)
            print(f"  {CYAN}{topic}{RESET}  {DIM}({url_count} source(s)){RESET}")
        print(
            f"\n  {DIM}Use /research <topic> to fetch and inject into context.{RESET}\n"
        )

    def _cmd_clear(self) -> None:
        """Clear the research cache."""
        from app.core.research_fetcher import get_default_cache
        from cli.display import DIM, GREEN, RESET

        cache = get_default_cache()
        removed = cache.clear()
        print(f"  {GREEN}Research cache cleared:{RESET} {DIM}{removed} file(s) removed.{RESET}")

    def _cmd_stats(self) -> None:
        """Show research cache statistics."""
        from app.core.research_fetcher import get_default_cache
        from cli.display import BOLD, CYAN, DIM, RESET

        cache = get_default_cache()
        stats = cache.stats()
        files = stats["files"]
        total_bytes = stats["total_bytes"]
        size_kb = total_bytes / 1024

        print(f"\n{BOLD}Research cache stats:{RESET}")
        print(f"  {CYAN}Cached pages :{RESET} {DIM}{files}{RESET}")
        print(f"  {CYAN}Total size   :{RESET} {DIM}{size_kb:.1f} KB ({total_bytes} bytes){RESET}")
        print(
            f"  {CYAN}Cache dir    :{RESET} "
            f"{DIM}{cache._dir}{RESET}\n"
        )

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _print_usage(self) -> None:
        from cli.display import CYAN, DIM, RESET, YELLOW
        print(
            f"  {YELLOW}Usage:{RESET}\n"
            f"    {CYAN}/research <query>{RESET}   — fetch docs for a topic, inject into context\n"
            f"    {CYAN}/research list{RESET}       — list all known research topics\n"
            f"    {CYAN}/research clear{RESET}      — clear the research cache\n"
            f"    {CYAN}/research stats{RESET}      — show cache stats\n"
            f"  {DIM}Fetched docs are added to the RAG index for your next message.{RESET}"
        )
