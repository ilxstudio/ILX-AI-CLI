"""CLI configuration — backed by ~/.ilx_cli/config.json."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.core.json_store import JsonStore

_log = logging.getLogger("ilx_cli.config")


class PermissionMode(str, Enum):
    ASK          = "ask"
    AUTO_APPROVE = "auto_approve"
    DENY_ALL     = "deny_all"


@dataclass
class AppConfig:
    ollama_url:            str            = "http://localhost:11434"
    ollama_model:          str            = "codellama:7b"
    provider:              str            = "ollama"   # ollama | anthropic | openai | groq | gemini | meta
    chat_model:            str            = ""         # if set, used in chat mode instead of ollama_model
    working_folder:        str            = ""
    permission_mode:       PermissionMode = PermissionMode.ASK
    autofix_enabled:       bool           = True
    autofix_max_iterations: int           = 5
    exec_timeout:          int            = 30
    temperature:           float          = 0.7
    top_p:                 float          = 0.9
    max_tokens:            int            = -1
    num_ctx:               int            = 4096
    system_prompt:         str            = ""
    tool_use_enabled:      bool           = False
    auto_yes:              bool           = False          # --yes flag / ILX_YES=1
    output_mode:           str            = "ansi"         # "ansi" | "json" | "quiet"
    dry_run:               bool           = False          # --dry-run: show edits, don't write
    fallback_providers:    list[str]      = field(default_factory=list)  # providers to try on failure
    sandbox_mode:          str            = "workspace"    # "workspace" | "read_only" | "disabled"
    route_strategy:        str            = "auto"         # "auto"|"free-only"|"local-only"|"quality"
    rag_bm25_weight:       float          = 0.6            # BM25 score threshold (0.0–1.0)
    rag_semantic_weight:   float          = 0.75           # Semantic similarity threshold (0.0–1.0)
    permission_profile:    str            = "coding"       # "safe"|"coding"|"review"|"ci"|"locked"
    command_allowlist:     list[str]      = field(default_factory=list)   # commands auto-approved without prompting
    command_denylist:      list[str]      = field(default_factory=list)   # commands always blocked

    def __post_init__(self):
        if not self.working_folder:
            self.working_folder = str(
                Path.home() / "Documents" / "ILX CLI Workspace"
            )

    def validate(self) -> list[str]:
        """Return a list of validation error strings. Empty list means valid."""
        errors: list[str] = []
        if not 0.0 <= self.temperature <= 2.0:
            errors.append(
                f"temperature must be between 0.0 and 2.0, got {self.temperature}"
            )
        if not 0.0 <= self.top_p <= 1.0:
            errors.append(
                f"top_p must be between 0.0 and 1.0, got {self.top_p}"
            )
        if self.exec_timeout < 1:
            errors.append(
                f"exec_timeout must be >= 1 second, got {self.exec_timeout}"
            )
        if self.autofix_max_iterations < 1:
            errors.append(
                f"autofix_max_iterations must be >= 1, got {self.autofix_max_iterations}"
            )
        if self.max_tokens != -1 and self.max_tokens < 1:
            errors.append(
                f"max_tokens must be -1 (unlimited) or positive, got {self.max_tokens}"
            )
        _valid_providers = {"ollama", "anthropic", "openai", "groq", "gemini", "meta"}
        if self.provider not in _valid_providers:
            errors.append(f"unknown provider '{self.provider}'")
        return errors


class ConfigManager:
    def __init__(self):
        self._qs = JsonStore.get()

    def load(self) -> AppConfig:
        cfg = AppConfig()
        cfg.ollama_url             = self._qs.value("ollama_url",             cfg.ollama_url,             str)
        cfg.ollama_model           = self._qs.value("ollama_model",           cfg.ollama_model,           str)
        cfg.provider               = self._qs.value("provider",               cfg.provider,               str)
        cfg.chat_model             = self._qs.value("chat_model",             cfg.chat_model,             str)
        cfg.working_folder         = self._qs.value("working_folder",         cfg.working_folder,         str)
        cfg.autofix_enabled        = self._qs.value("autofix_enabled",        cfg.autofix_enabled,        bool)
        cfg.autofix_max_iterations = self._qs.value("autofix_max_iterations", cfg.autofix_max_iterations, int)
        cfg.exec_timeout           = self._qs.value("exec_timeout",           cfg.exec_timeout,           int)
        cfg.temperature            = self._qs.value("temperature",            cfg.temperature,            float)
        cfg.top_p                  = self._qs.value("top_p",                  cfg.top_p,                  float)
        cfg.max_tokens             = self._qs.value("max_tokens",             cfg.max_tokens,             int)
        cfg.num_ctx                = self._qs.value("num_ctx",                cfg.num_ctx,                int)
        cfg.system_prompt          = self._qs.value("system_prompt",          cfg.system_prompt,          str)
        cfg.tool_use_enabled       = self._qs.value("tool_use_enabled",       cfg.tool_use_enabled,       bool)

        raw_mode = self._qs.value("permission_mode", cfg.permission_mode.value, str)
        try:
            cfg.permission_mode = PermissionMode(raw_mode)
        except ValueError:
            cfg.permission_mode = PermissionMode.ASK

        cfg.route_strategy       = self._qs.value("route_strategy",       "auto",  str)
        cfg.rag_bm25_weight      = self._qs.value("rag_bm25_weight",      cfg.rag_bm25_weight,    float)
        cfg.rag_semantic_weight  = self._qs.value("rag_semantic_weight",  cfg.rag_semantic_weight, float)
        cfg.permission_profile   = self._qs.value("permission_profile",   "coding", str)
        cfg.command_allowlist = self._qs.value("command_allowlist", [], list)
        cfg.command_denylist  = self._qs.value("command_denylist",  [], list)

        # Environment overrides applied after disk load
        if os.environ.get("ILX_YES") == "1":
            cfg.auto_yes = True

        # ILX_FREE_TIER=1 forces route_strategy to "free-only" (local Ollama, no API cost)
        if os.environ.get("ILX_FREE_TIER") == "1":
            cfg.route_strategy = "free-only"

        errors = cfg.validate()
        for err in errors:
            _log.warning("config validation: %s", err)

        return cfg

    def save(self, cfg: AppConfig) -> None:
        self._qs.setValue("ollama_url",             cfg.ollama_url)
        self._qs.setValue("ollama_model",           cfg.ollama_model)
        self._qs.setValue("provider",               cfg.provider)
        self._qs.setValue("chat_model",             cfg.chat_model)
        self._qs.setValue("working_folder",         cfg.working_folder)
        self._qs.setValue("permission_mode",        cfg.permission_mode.value)
        self._qs.setValue("autofix_enabled",        cfg.autofix_enabled)
        self._qs.setValue("autofix_max_iterations", cfg.autofix_max_iterations)
        self._qs.setValue("exec_timeout",           cfg.exec_timeout)
        self._qs.setValue("temperature",            cfg.temperature)
        self._qs.setValue("top_p",                  cfg.top_p)
        self._qs.setValue("max_tokens",             cfg.max_tokens)
        self._qs.setValue("num_ctx",                cfg.num_ctx)
        self._qs.setValue("system_prompt",          cfg.system_prompt)
        self._qs.setValue("tool_use_enabled",       cfg.tool_use_enabled)
        self._qs.setValue("route_strategy",         cfg.route_strategy)
        self._qs.setValue("rag_bm25_weight",        cfg.rag_bm25_weight)
        self._qs.setValue("rag_semantic_weight",    cfg.rag_semantic_weight)
        self._qs.setValue("permission_profile",     cfg.permission_profile)
        self._qs.setValue("command_allowlist",      cfg.command_allowlist)
        self._qs.setValue("command_denylist",       cfg.command_denylist)
        self._qs.sync()
