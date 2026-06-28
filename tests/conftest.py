"""Shared pytest fixtures for ILX AI CLI tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "provider_live: marks tests requiring a live cloud LLM provider (deselect with '-m not provider_live')")
    config.addinivalue_line("markers", "ollama_live: marks tests requiring a running local Ollama instance")
    config.addinivalue_line("markers", "model_quality: marks non-deterministic model quality tests")
    config.addinivalue_line("markers", "slow: marks tests that take more than 10 seconds")
    config.addinivalue_line("markers", "integration: marks end-to-end integration tests")
    config.addinivalue_line("markers", "security: marks security-specific tests")
    config.addinivalue_line("markers", "windows: marks Windows-specific tests")

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Preferred test models in priority order — first one found on the server is used.
_PREFERRED_MODELS = ["qwen2.5:14b", "qwen2.5:3b"]


def _resolve_model(ollama_url: str) -> str:
    """Return the first preferred model available on the Ollama server.

    Falls back to the first model in the server list if neither preferred
    model is present, or to 'qwen2.5:3b' if the server is unreachable.
    """
    try:
        import httpx
        r = httpx.get(f"{ollama_url}/api/tags", timeout=6.0)
        r.raise_for_status()
        available = [m["name"] for m in r.json().get("models", [])]
        for preferred in _PREFERRED_MODELS:
            if preferred in available:
                return preferred
        # Neither preferred model found — fall back to first available
        if available:
            print(
                f"\n[conftest] WARNING: neither {_PREFERRED_MODELS} found on server. "
                f"Available: {available[:5]}. Using '{available[0]}'."
            )
            return available[0]
    except Exception as exc:
        print(f"\n[conftest] WARNING: could not reach Ollama ({exc}). "
              f"Defaulting to '{_PREFERRED_MODELS[-1]}'.")
    return _PREFERRED_MODELS[-1]


@pytest.fixture(scope="session")
def cfg():
    """Load app config and pin ollama_model to qwen2.5:14b or qwen2.5:3b."""
    from app.core.config import ConfigManager
    c = ConfigManager().load()
    c.ollama_model = _resolve_model(c.ollama_url)
    print(f"\n[conftest] Test model pinned to: {c.ollama_model}")
    return c


@pytest.fixture(scope="session")
def llm(cfg):
    """Return a live LLM client pointed at the configured provider."""
    from codex.app.llm_client import get_llm_client
    return get_llm_client(cfg)


@pytest.fixture(scope="session")
def ollama_url(cfg):
    return cfg.ollama_url


@pytest.fixture(scope="session")
def model(cfg):
    """Always returns the pinned test model (qwen2.5:14b or qwen2.5:3b)."""
    return cfg.ollama_model
