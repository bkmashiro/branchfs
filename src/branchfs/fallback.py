"""Fallback mode — branch isolation using temp directories and shutil.

When FUSE is unavailable this module provides a context-manager that
copies the effective workspace into a temporary directory, lets the
caller work there, and optionally merges results back.

Usage::

    from branchfs.fallback import FallbackBranch

    with FallbackBranch(store, snapshot_store, branch_store, snap_id) as fb:
        # fb.workdir is a Path pointing to the isolated copy
        (fb.workdir / "new_file.txt").write_text("hello")
        fb.merge()   # commit changes back

If ``merge()`` is not called before the context exits, changes are
discarded.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from branchfs.branch import DELETED_SENTINEL, Branch, BranchStore
from branchfs.snapshot import Snapshot, SnapshotStore
from branchfs.store import BlobStore


class FallbackWorkspace:
    """Manages the materialized workspace directory for fallback mode.

    The workspace is a real directory whose contents reflect the
    effective tree (snapshot + branch overlay).  All mutations are
    tracked so they can later be committed back to the branch layer.
    """

    def __init__(
        self,
        blob_store: BlobStore,
        snapshot_store: SnapshotStore,
        branch_store: BranchStore,
        workspace_dir: str | Path,
    ) -> None:
        self.blob_store = blob_store
        self.snapshot_store = snapshot_store
        self.branch_store = branch_store
        self.workspace_dir = Path(workspace_dir)

    def materialize(self, snapshot: Snapshot, branch: Optional[Branch] = None) -> None:
        """Write out the effective tree to *workspace_dir*."""
        tree = dict(snapshot.tree)
        if branch is not None:
            tree = BranchStore.effective_tree(snapshot.tree, branch.modified)

        # Clear existing workspace content (but keep the dir itself).
        if self.workspace_dir.exists():
            for child in self.workspace_dir.iterdir():
                if child.name == ".branchfs":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

        # Extract blobs.
        for rel_path, blob_hash in tree.items():
            dest = self.workspace_dir / rel_path
            self.blob_store.extract_to(blob_hash, dest)

    def scan(self) -> Dict[str, str]:
        """Scan workspace and store all files, returning ``{path: blob_hash}``."""
        tree: Dict[str, str] = {}
        for root, _dirs, files in os.walk(self.workspace_dir):
            # Skip the internal metadata directory.
            rel_root = Path(root).relative_to(self.workspace_dir)
            if str(rel_root).startswith(".branchfs"):
                continue
            for fname in files:
                full = Path(root) / fname
                rel = str(full.relative_to(self.workspace_dir))
                blob_hash = self.blob_store.put_file(full)
                tree[rel] = blob_hash
        return tree

    def compute_branch_modifications(
        self,
        snapshot_tree: Dict[str, str],
        current_tree: Dict[str, str],
    ) -> Dict[str, str]:
        """Compute the branch modification dict from a snapshot tree and the current workspace tree."""
        modified: Dict[str, str] = {}
        # New or changed files.
        for path, blob_hash in current_tree.items():
            if path not in snapshot_tree or snapshot_tree[path] != blob_hash:
                modified[path] = blob_hash
        # Deleted files.
        for path in snapshot_tree:
            if path not in current_tree:
                modified[path] = DELETED_SENTINEL
        return modified


class FallbackBranch:
    """Context manager that provides an isolated branch workspace.

    Copies the effective tree into a temp directory; on exit, optionally
    merges changes back into the branch layer.

    Example::

        with FallbackBranch(blob, snap_store, branch_store, snap_id) as fb:
            (fb.workdir / "file.txt").write_text("data")
            fb.merge()
    """

    def __init__(
        self,
        blob_store: BlobStore,
        snapshot_store: SnapshotStore,
        branch_store: BranchStore,
        snapshot_id: str,
        branch_name: Optional[str] = None,
    ) -> None:
        self.blob_store = blob_store
        self.snapshot_store = snapshot_store
        self.branch_store = branch_store
        self.snapshot_id = snapshot_id
        self.branch_name = branch_name
        self._tmpdir: Optional[tempfile.TemporaryDirectory] = None
        self.workdir: Optional[Path] = None
        self.branch: Optional[Branch] = None
        self._merged = False

    def __enter__(self) -> "FallbackBranch":
        self._tmpdir = tempfile.TemporaryDirectory(prefix="branchfs_")
        self.workdir = Path(self._tmpdir.name)

        snapshot = self.snapshot_store.load(self.snapshot_id)

        # Materialize snapshot into the temp dir.
        for rel_path, blob_hash in snapshot.tree.items():
            self.blob_store.extract_to(blob_hash, self.workdir / rel_path)

        # Create a branch object to track this.
        self.branch = self.branch_store.create(
            base_snapshot=self.snapshot_id, name=self.branch_name
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        if not self._merged and self.branch is not None:
            # Discard — delete branch metadata.
            self.branch_store.delete(self.branch.id)
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
        return None

    def merge(self) -> str:
        """Merge changes from the temp workspace back into the branch layer.

        Returns the updated branch id.
        """
        if self.workdir is None or self.branch is None:
            raise RuntimeError("Cannot merge outside of context manager")

        snapshot = self.snapshot_store.load(self.snapshot_id)

        # Scan current temp dir.
        current_tree: Dict[str, str] = {}
        for root, _dirs, files in os.walk(self.workdir):
            for fname in files:
                full = Path(root) / fname
                rel = str(full.relative_to(self.workdir))
                blob_hash = self.blob_store.put_file(full)
                current_tree[rel] = blob_hash

        workspace = FallbackWorkspace(
            self.blob_store, self.snapshot_store, self.branch_store, self.workdir
        )
        self.branch.modified = workspace.compute_branch_modifications(
            snapshot.tree, current_tree
        )
        self.branch_store.save(self.branch)
        self._merged = True
        return self.branch.id
