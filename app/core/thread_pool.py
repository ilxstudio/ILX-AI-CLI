"""Shared thread-pool executor for I/O-bound background work.

Usage:
    from app.core.thread_pool import submit, pool
    future = submit(my_function, arg1, arg2)
    executor = pool()   # direct access to the ThreadPoolExecutor

The pool is initialised by main._configure_runtime() at startup.
Callers that import before init() is called get a lazily-created
fallback pool with os.cpu_count()*2 workers.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar

_log = logging.getLogger("ilx_cli.thread_pool")
_T = TypeVar("_T")

_executor: ThreadPoolExecutor | None = None
_lock_imported = False


def init(max_workers: int) -> None:
    """Initialise (or replace) the global thread pool. Call once at startup."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=False)
    _executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ilx-pool")
    _log.debug("Thread pool initialised: %d workers", max_workers)


def _get() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        workers = min(32, (os.cpu_count() or 2) * 4)
        _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ilx-pool")
        _log.debug("Thread pool lazy-init: %d workers", workers)
    return _executor


def submit(fn: Callable[..., _T], *args, **kwargs) -> Future[_T]:
    """Submit a callable to the shared pool. Returns a Future."""
    return _get().submit(fn, *args, **kwargs)


def map(fn: Callable, *iterables, timeout=None):
    """Map fn over iterables in parallel using the shared pool."""
    return _get().map(fn, *iterables, timeout=timeout)


def pool() -> ThreadPoolExecutor:
    """Return the shared ThreadPoolExecutor (lazy-initialised if needed)."""
    return _get()
