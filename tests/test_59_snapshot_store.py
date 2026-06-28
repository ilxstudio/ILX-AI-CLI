"""Tests for app.core.snapshot_store — snapshot/rollback subsystem.

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import unittest


class TestSnapshotStoreImport(unittest.TestCase):
    """PIECE 1 — clean import."""

    def test_snapshot_store_import(self) -> None:
        """Module imports without error and exposes expected names."""
        import app.core.snapshot_store as mod

        self.assertTrue(hasattr(mod, "SnapshotStore"))
        self.assertTrue(hasattr(mod, "Snapshot"))
        self.assertTrue(hasattr(mod, "init_snapshot_store"))
        self.assertTrue(hasattr(mod, "get_store"))


class TestSnapshotStoreCoreOps(unittest.TestCase):
    """Core save / peek / pop operations."""

    def setUp(self) -> None:
        from app.core.snapshot_store import SnapshotStore

        # Use a fresh unnamed store so no disk I/O happens during tests.
        self.store = SnapshotStore(sid="")

    # ── save ─────────────────────────────────────────────────────────────────

    def test_save_creates_snapshot(self) -> None:
        """save() returns a Snapshot with the correct content and path."""
        snap = self.store.save("/tmp/alpha.py", "original content", run_id="r1")

        self.assertIsNotNone(snap)
        self.assertEqual(snap.path, "/tmp/alpha.py")
        self.assertEqual(snap.content, "original content")
        self.assertEqual(snap.run_id, "r1")
        # ts must be a non-empty string
        self.assertTrue(snap.ts)

    # ── peek ─────────────────────────────────────────────────────────────────

    def test_peek_does_not_remove(self) -> None:
        """peek() twice returns the same snapshot and does not change depth."""
        self.store.save("/tmp/beta.py", "v1")
        self.store.save("/tmp/beta.py", "v2")

        first  = self.store.peek("/tmp/beta.py")
        second = self.store.peek("/tmp/beta.py")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.content, second.content)  # type: ignore[union-attr]
        self.assertEqual(self.store.depth("/tmp/beta.py"), 2)

    # ── pop ──────────────────────────────────────────────────────────────────

    def test_pop_removes_snapshot(self) -> None:
        """pop() returns the most recent snapshot and reduces depth by 1."""
        self.store.save("/tmp/gamma.py", "v1")
        self.store.save("/tmp/gamma.py", "v2")

        popped = self.store.pop("/tmp/gamma.py")

        self.assertIsNotNone(popped)
        self.assertEqual(popped.content, "v2")  # type: ignore[union-attr]
        self.assertEqual(self.store.depth("/tmp/gamma.py"), 1)

    def test_pop_keeps_original(self) -> None:
        """Popping repeatedly never removes the bottom (original) snapshot."""
        self.store.save("/tmp/delta.py", "original")
        self.store.save("/tmp/delta.py", "edit-1")
        self.store.save("/tmp/delta.py", "edit-2")

        # Pop twice — should get edit-2 then edit-1
        pop1 = self.store.pop("/tmp/delta.py")
        pop2 = self.store.pop("/tmp/delta.py")

        self.assertEqual(pop1.content, "edit-2")  # type: ignore[union-attr]
        self.assertEqual(pop2.content, "edit-1")  # type: ignore[union-attr]

        # depth is now 1 (just the original)
        self.assertEqual(self.store.depth("/tmp/delta.py"), 1)

        # Another pop should return the original WITHOUT removing it
        pop3 = self.store.pop("/tmp/delta.py")
        self.assertEqual(pop3.content, "original")  # type: ignore[union-attr]
        # depth remains 1
        self.assertEqual(self.store.depth("/tmp/delta.py"), 1)

    # ── original ─────────────────────────────────────────────────────────────

    def test_original_returns_first(self) -> None:
        """original() always returns the oldest (first-saved) snapshot."""
        self.store.save("/tmp/epsilon.py", "first")
        self.store.save("/tmp/epsilon.py", "second")
        self.store.save("/tmp/epsilon.py", "third")

        orig = self.store.original("/tmp/epsilon.py")

        self.assertIsNotNone(orig)
        self.assertEqual(orig.content, "first")  # type: ignore[union-attr]

    # ── depth ────────────────────────────────────────────────────────────────

    def test_depth_counts_stack(self) -> None:
        """depth() returns the exact number of snapshots in the stack."""
        path = "/tmp/zeta.py"
        self.assertEqual(self.store.depth(path), 0)

        self.store.save(path, "a")
        self.assertEqual(self.store.depth(path), 1)

        self.store.save(path, "b")
        self.assertEqual(self.store.depth(path), 2)

        self.store.save(path, "c")
        self.assertEqual(self.store.depth(path), 3)

    # ── all_paths ────────────────────────────────────────────────────────────

    def test_all_paths_lists_files(self) -> None:
        """all_paths() returns all paths that have at least one snapshot."""
        self.store.save("/tmp/eta.py", "x")
        self.store.save("/tmp/theta.py", "y")

        paths = self.store.all_paths()

        self.assertIn("/tmp/eta.py", paths)
        self.assertIn("/tmp/theta.py", paths)
        self.assertEqual(len(paths), 2)

    # ── clear ────────────────────────────────────────────────────────────────

    def test_clear_empties_store(self) -> None:
        """clear() removes all snapshots so all_paths() returns empty list."""
        self.store.save("/tmp/iota.py", "content-a")
        self.store.save("/tmp/kappa.py", "content-b")

        self.store.clear()

        self.assertEqual(self.store.all_paths(), [])
        self.assertEqual(self.store.depth("/tmp/iota.py"), 0)

    # ── independence ─────────────────────────────────────────────────────────

    def test_multiple_files_independent(self) -> None:
        """Saves for path A do not affect the stack for path B."""
        path_a = "/tmp/lambda.py"
        path_b = "/tmp/mu.py"

        self.store.save(path_a, "a-v1")
        self.store.save(path_a, "a-v2")
        self.store.save(path_b, "b-v1")

        self.assertEqual(self.store.depth(path_a), 2)
        self.assertEqual(self.store.depth(path_b), 1)

        popped = self.store.pop(path_a)
        self.assertEqual(popped.content, "a-v2")  # type: ignore[union-attr]
        # B is untouched
        self.assertEqual(self.store.depth(path_b), 1)
        self.assertEqual(self.store.peek(path_b).content, "b-v1")  # type: ignore[union-attr]


class TestSnapshotStoreModuleLevel(unittest.TestCase):
    """Module-level singleton functions."""

    def test_init_snapshot_store_returns_store(self) -> None:
        """init_snapshot_store() returns a SnapshotStore instance."""
        from app.core.snapshot_store import SnapshotStore, init_snapshot_store

        store = init_snapshot_store(sid="test-init-42")

        self.assertIsInstance(store, SnapshotStore)

    def test_get_store_returns_same_instance(self) -> None:
        """get_store() returns the same object across multiple calls."""
        from app.core.snapshot_store import get_store, init_snapshot_store

        # Ensure a store is initialised first
        init_snapshot_store(sid="test-singleton-42")

        store_a = get_store()
        store_b = get_store()

        self.assertIs(store_a, store_b)


if __name__ == "__main__":
    unittest.main()
