"""Custom exception hierarchy for ILX AI CLI.

All ILX-specific exceptions inherit from ILXError, allowing callers to
catch the full family with a single ``except ILXError`` clause while still
being able to distinguish sub-types for targeted handling.
"""
from __future__ import annotations


class ILXError(Exception):
    """Base exception for all ILX AI CLI errors."""


class ConfigError(ILXError):
    """Raised when configuration is missing, invalid, or cannot be loaded."""


class ILXPermissionError(ILXError):
    """Raised when an operation is denied by the permission engine."""


class SandboxError(ILXError):
    """Raised when a path or command violates sandbox containment rules."""


class ProviderError(ILXError):
    """Raised when an LLM provider returns an unrecoverable error."""


class ToolError(ILXError):
    """Raised when a tool call fails (MCP builtin, subprocess, or HTTP tool)."""


class ProcessError(ILXError):
    """Raised when a subprocess invocation fails or times out."""


class AuditError(ILXError):
    """Raised when the audit log cannot be written or queried."""


class MCPError(ILXError):
    """Raised for errors in MCP protocol framing or tool dispatch."""


class RAGError(ILXError):
    """Raised when the retrieval-augmented generation pipeline encounters an error."""
