"""Atomic parallel file writer.

Writes multiple files concurrently using ThreadPoolExecutor.
Each file is written atomically: write to a .tmp sibling, then rename.
All writes either succeed or the partial writes are rolled back.

Usage::

    from app.core.parallel_writer import FileEdit, write_parallel

    edits = [
        FileEdit(path="/abs/path/to/foo.py", content="print('hello')"),
        FileEdit(path="/abs/path/to/bar.py", content="x = 1"),
    ]
    results = write_parallel(edits)
    for r in results:
        print(r.path, "OK" if r.ok else r.error)
"""
from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("ilx_cli.parallel_writer")


# ── Public data types ─────────────────────────────────────────────────────────

@dataclass
class FileEdit:
    """Describes a single file to be written."""
    path: str          # absolute path
    content: str
    encoding: str = "utf-8"


@dataclass
class WriteResult:
    """Outcome of a single file write."""
    path: str
    ok: bool
    error: str = ""


# ── Path validation ───────────────────────────────────────────────────────────

def _validate_path(raw: str) -> Path:
    """Resolve *raw* to an absolute Path and reject dangerous inputs.

    Raises ValueError if:
    - the path is not absolute after resolution
    - any ``..`` component appears in the *raw* path before resolution
      (this catches path-traversal attempts like ``/tmp/safe/../etc/passwd``)
    - any ``..`` component remains after resolution (defence-in-depth)
    - the path contains null bytes
    """
    if "\x00" in raw:
        raise ValueError(f"Path contains null byte: {raw!r}")

    p = Path(raw)

    # Reject relative paths outright before resolution
    if not p.is_absolute():
        raise ValueError(f"Path must be absolute, got: {raw!r}")

    # Reject any path that contains '..' in its parts before resolution.
    # This is the primary traversal guard: an attacker can't sneak a traversal
    # past Path.resolve() on most OSes, but we reject it explicitly here to
    # give a clear error and avoid relying on OS-specific resolve behaviour.
    if ".." in p.parts:
        raise ValueError(
            f"Path traversal detected: '..' component found in {raw!r}"
        )

    resolved = p.resolve()

    # Defence-in-depth: if somehow '..' survived resolution, reject as well.
    if ".." in resolved.parts:
        raise ValueError(f"Path traversal detected after resolution: {resolved}")

    return resolved


# ── Atomic single-file writer ─────────────────────────────────────────────────

def _write_one(edit: FileEdit) -> WriteResult:
    """Write *edit* atomically. Returns a WriteResult."""
    try:
        resolved = _validate_path(edit.path)
    except ValueError as exc:
        return WriteResult(path=edit.path, ok=False, error=str(exc))

    parent = resolved.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return WriteResult(path=edit.path, ok=False, error=f"mkdir failed: {exc}")

    tmp_path: Path | None = None
    try:
        # Write to a sibling temp file in the same directory so that rename
        # is atomic on the same filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=edit.encoding,
            dir=parent,
            prefix=".tmp_pw_",
            delete=False,
        ) as tmp:
            tmp.write(edit.content)
            tmp_path = Path(tmp.name)

        tmp_path.replace(resolved)
        return WriteResult(path=edit.path, ok=True)

    except Exception as exc:
        # Best-effort cleanup of the temp file
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return WriteResult(path=edit.path, ok=False, error=str(exc))


# ── Rollback helper ───────────────────────────────────────────────────────────

def _rollback(written_paths: list[str]) -> None:
    """Best-effort removal of all successfully written files."""
    for p in written_paths:
        try:
            Path(p).unlink(missing_ok=True)
            _log.debug("Rolled back %s", p)
        except OSError as exc:
            _log.warning(
                "Rollback failed for %s: %s — file may be in inconsistent state", p, exc
            )


# ── Public API ────────────────────────────────────────────────────────────────

def write_parallel(
    edits: list[FileEdit],
    *,
    max_workers: int = 4,
    dry_run: bool = False,
) -> list[WriteResult]:
    """Write files in parallel with atomic rename semantics.

    Parameters
    ----------
    edits:
        List of :class:`FileEdit` objects describing files to write.
    max_workers:
        Maximum number of worker threads.  Capped internally at ``len(edits)``
        to avoid spinning up unnecessary threads.
    dry_run:
        If *True*, validate paths but do not write any files.  All results will
        have ``ok=True`` for valid paths and ``ok=False`` for invalid ones.

    Returns
    -------
    list[WriteResult]
        One result per edit, in the same order as *edits*.  On the first
        failure all successfully written files are rolled back (best-effort)
        and the remaining results are marked failed with ``error="rolled back"``.

    Notes
    -----
    - Path traversal is rejected: any path that is not absolute, contains null
      bytes, or still has ``..`` components after ``Path.resolve()`` is rejected
      with ``ok=False`` and no file is written.
    - Roll-back is best-effort only.  If the process is killed mid-write some
      temporary files may remain in the target directories.
    """
    if not edits:
        return []

    # ── dry-run: validate paths only ─────────────────────────────────────────
    if dry_run:
        results: list[WriteResult] = []
        for edit in edits:
            try:
                _validate_path(edit.path)
                results.append(WriteResult(path=edit.path, ok=True))
            except ValueError as exc:
                results.append(WriteResult(path=edit.path, ok=False, error=str(exc)))
        return results

    # ── live write ────────────────────────────────────────────────────────────
    workers = min(max_workers, len(edits))
    # Preserve ordering: map future -> original index
    index_map: dict = {}
    ordered: list[WriteResult | None] = [None] * len(edits)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_write_one, edit): i for i, edit in enumerate(edits)}
        index_map = {f: i for f, i in futures.items()}

        succeeded_paths: list[str] = []
        failed = False

        for future in as_completed(futures):
            idx  = index_map[future]
            edit = edits[idx]
            try:
                result = future.result()
            except Exception as exc:
                _log.warning("Parallel write failed for %s: %s", edit.path, exc)
                result = WriteResult(path=edit.path, ok=False, error=str(exc))
            ordered[idx] = result

            if result.ok:
                succeeded_paths.append(result.path)
            else:
                failed = True

    # ── rollback on failure ───────────────────────────────────────────────────
    if failed:
        _rollback(succeeded_paths)
        # Mark any None slots (shouldn't happen) and succeeded slots as rolled back
        final: list[WriteResult] = []
        for i, r in enumerate(ordered):
            if r is None:
                # Future result missing — shouldn't happen but handle defensively
                final.append(WriteResult(path=edits[i].path, ok=False, error="future missing"))
            elif r.ok:
                final.append(WriteResult(path=r.path, ok=False, error="rolled back"))
            else:
                final.append(r)
        return final

    # All succeeded
    return [r for r in ordered if r is not None]
