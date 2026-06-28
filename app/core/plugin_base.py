# MIT License 2026 ILX Studio
"""Plugin API for ILX AI CLI.

Third-party plugins implement ILXPlugin and register via entry_points:
    [project.entry-points."ilx_ai.plugins"]
    my_plugin = "my_package:MyPlugin"
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


class ILXPlugin(ABC):
    """Base class for ILX AI CLI plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (snake_case)."""

    @property
    def description(self) -> str:
        return ""

    @property
    def version(self) -> str:
        return "0.1.0"

    def on_load(self, cfg: AppConfig) -> None:
        """Called when the plugin is loaded. Override to initialize resources."""

    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    def get_commands(self) -> dict[str, callable]:
        """Return a dict of {command_name: handler_function} to register."""
        return {}

    def get_hooks(self) -> list[dict]:
        """Return hook definitions in the hooks.json format."""
        return []


class PluginRegistry:
    """Discovers and manages plugins via entry_points."""

    def __init__(self) -> None:
        self._plugins: dict[str, ILXPlugin] = {}

    def discover(self) -> list[str]:
        """Load all plugins from entry_points group 'ilx_ai.plugins'. Returns loaded names."""
        loaded: list[str] = []
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="ilx_ai.plugins")
            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    plugin = plugin_cls()
                    self._plugins[plugin.name] = plugin
                    loaded.append(plugin.name)
                except Exception as exc:
                    logging.getLogger("ilx_cli.plugins").warning(
                        "Failed to load plugin %s: %s", ep.name, exc
                    )
        except Exception:
            pass
        return loaded

    def get(self, name: str) -> ILXPlugin | None:
        return self._plugins.get(name)

    def all(self) -> list[ILXPlugin]:
        return list(self._plugins.values())
