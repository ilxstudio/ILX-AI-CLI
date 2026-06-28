"""Tests for AppConfig validation and RAG eviction policy."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.core.config import AppConfig, ConfigManager, PermissionMode


class TestAppConfigValidation:
    def test_valid_default_config(self):
        cfg = AppConfig()
        assert cfg.validate() == []

    def test_temperature_out_of_range_high(self):
        cfg = AppConfig()
        cfg.temperature = 5.0
        errors = cfg.validate()
        assert any("temperature" in e for e in errors)

    def test_temperature_out_of_range_low(self):
        cfg = AppConfig()
        cfg.temperature = -0.1
        errors = cfg.validate()
        assert any("temperature" in e for e in errors)

    def test_top_p_out_of_range(self):
        cfg = AppConfig()
        cfg.top_p = 1.5
        errors = cfg.validate()
        assert any("top_p" in e for e in errors)

    def test_exec_timeout_too_low(self):
        cfg = AppConfig()
        cfg.exec_timeout = 0
        errors = cfg.validate()
        assert any("exec_timeout" in e for e in errors)

    def test_autofix_max_iterations_too_low(self):
        cfg = AppConfig()
        cfg.autofix_max_iterations = 0
        errors = cfg.validate()
        assert any("autofix_max_iterations" in e for e in errors)

    def test_unknown_provider(self):
        cfg = AppConfig()
        cfg.provider = "unicorn_ai"
        errors = cfg.validate()
        assert any("provider" in e for e in errors)

    def test_known_providers_valid(self):
        for p in ("ollama", "anthropic", "openai", "groq", "gemini", "meta"):
            cfg = AppConfig()
            cfg.provider = p
            errors = cfg.validate()
            assert not any("provider" in e for e in errors), f"Provider {p!r} should be valid"

    def test_max_tokens_minus_one_valid(self):
        cfg = AppConfig()
        cfg.max_tokens = -1
        errors = cfg.validate()
        assert not any("max_tokens" in e for e in errors)

    def test_max_tokens_zero_invalid(self):
        cfg = AppConfig()
        cfg.max_tokens = 0
        errors = cfg.validate()
        assert any("max_tokens" in e for e in errors)

    def test_multiple_errors_returned(self):
        cfg = AppConfig()
        cfg.temperature = 99.0
        cfg.top_p = 5.0
        cfg.provider = "bad_provider"
        errors = cfg.validate()
        assert len(errors) >= 3

    def test_valid_boundary_temperature(self):
        cfg = AppConfig()
        cfg.temperature = 0.0
        assert cfg.validate() == []
        cfg.temperature = 2.0
        assert cfg.validate() == []

    def test_valid_boundary_top_p(self):
        cfg = AppConfig()
        cfg.top_p = 0.0
        assert cfg.validate() == []
        cfg.top_p = 1.0
        assert cfg.validate() == []


class TestRAGEviction:
    def test_clear_empties_files(self):
        from app.core.rag import RAG
        rag = RAG()
        rag.add("file1.py", "x = 1")
        rag.add("file2.py", "y = 2")
        rag.clear()
        assert len(rag._files) == 0

    def test_eviction_fires_at_cap(self):
        from app.core.rag import RAG
        rag = RAG()
        cap = rag._MAX_FILES
        # Add cap+1 files and verify the oldest was evicted
        for i in range(cap + 1):
            rag.add(f"file_{i:04d}.py", f"x = {i}")
        assert len(rag._files) <= cap
        # file_0000.py should have been evicted
        assert "file_0000.py" not in rag._files

    def test_below_cap_no_eviction(self):
        from app.core.rag import RAG
        rag = RAG()
        for i in range(10):
            rag.add(f"f{i}.py", f"x = {i}")
        assert len(rag._files) == 10
