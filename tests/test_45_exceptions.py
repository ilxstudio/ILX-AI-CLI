# Copyright 2026 ILX Studio — MIT License
"""Tests for the ILX exception hierarchy."""
from __future__ import annotations

import pytest
from app.core.exceptions import (
    ILXError, ConfigError, ILXPermissionError, SandboxError,
    ProviderError, ToolError, ProcessError, AuditError, MCPError, RAGError,
)

_ALL_SUBCLASSES = [
    ProcessError, ILXPermissionError, SandboxError, ProviderError,
    ToolError, AuditError, MCPError, RAGError,
]


def test_ilx_error_is_base_exception():
    assert issubclass(ILXError, Exception)


def test_all_errors_inherit_ilx_error():
    for cls in _ALL_SUBCLASSES:
        assert issubclass(cls, ILXError), f"{cls.__name__} does not inherit ILXError"


def test_errors_have_messages():
    for cls in _ALL_SUBCLASSES:
        exc = cls("test message")
        assert str(exc) == "test message"


def test_process_error_caught_as_ilx_error():
    with pytest.raises(ILXError):
        raise ProcessError("subprocess timed out")


def test_errors_have_distinct_types():
    types = _ALL_SUBCLASSES + [ILXError, ConfigError]
    assert len(types) == len(set(types)), "Duplicate exception class found"
