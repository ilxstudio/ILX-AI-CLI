"""JSON-backed settings store — replaces QSettings."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

_log = logging.getLogger("ilx_cli.json_store")


class JsonStore:
    DEFAULT_PATH: Path = Path.home() / ".ilx_cli" / "config.json"

    _instance: "JsonStore | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "JsonStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path is not None else self.DEFAULT_PATH
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._loaded = False
        self._load()

    def value(self, key: str, default: Any = None, type: type | None = None) -> Any:  # noqa: A002
        with self._lock:
            v = self._data.get(key, default)
        if type is None:
            return v
        return _coerce(v, type, default)

    def setValue(self, key: str, value: Any) -> None:
        value = _to_jsonable(value)
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
            self._save_locked()

    def remove(self, key: str) -> None:
        with self._lock:
            if key not in self._data:
                return
            self._data.pop(key, None)
            self._save_locked()

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def allKeys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def sync(self) -> None:
        return

    def reset(self) -> None:
        with self._lock:
            self._data = {}
            self._save_locked()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self._path.is_file():
                self._data = self._read_json(self._path)
            else:
                self._data = {}
            self._loaded = True

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("config: could not read %s (%s); starting empty", path, exc)
            try:
                bak = path.with_suffix(path.suffix + ".corrupt")
                if path.is_file():
                    path.replace(bak)
            except OSError:
                pass
            return {}

    def _save_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log.warning("config: cannot create parent dir: %s", exc)
            return
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except OSError as exc:
            _log.warning("config: write failed (%s)", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return
        if os.name != "nt":
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass


def _coerce(v: Any, t: type, default: Any) -> Any:
    if v is None:
        return default
    try:
        if t is bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        if t is int:
            return int(v)
        if t is float:
            return float(v)
        if t is str:
            return str(v)
        if t is list:
            return list(v) if v is not None else (default or [])
    except (TypeError, ValueError):
        return default if default is not None else t()
    return v


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(_to_jsonable(x) for x in value)
    return str(value)
