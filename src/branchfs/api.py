"""BranchFS — High-level API for AI-optimized branching filesystem.

Design
------
BranchFS gives AI agents lightweight, programmatic branch/snapshot
control over a working directory.  It is modelled loosely on git but
optimised for machine consumption:

  * **Snapshots** are immutable point-in-time captures (like commits).
  * **Branches** are mutable copy-on-write layers on top of a snapshot.
  * **The workspace** is the directory the AI actually works in.

Two modes of operation:

  1. **FUSE mode** — a real FUSE mount intercepts all I/O so the agent
     needs no code changes.  Requires ``fusepy`` and (in Docker)
     ``--privileged`` or ``--cap-add SYS_ADMIN --device /dev/fuse``.

  2. **Fallback mode** — pure-Python; materialises files with shutil,
     provides a context-manager for isolated branches.  Works
     everywhere, including unprivileged containers.

Typical workflow::

    fs = BranchFS("/tmp/workspace")
    fs.init()
    snap = fs.snapshot("baseline")
    branch = fs.fork(snap)
    fs.checkout(branch)
    # ... agent writes files ...
    fs.diff(branch)
    fs.merge(branch)           # creates a new snapshot
    fs.log()                   # ASCII history

All metadata lives under ``<workspace>/.branchfs/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from branchfs.branch import DELETED_SENTINEL, Branch, BranchStore
from branchfs.fallback import FallbackBranch, FallbackWorkspace
from branchfs.snapshot import Snapshot, SnapshotStore
from branchfs.store import BlobStore
from branchfs.visualize import build_log, format_diff


class BranchFS:
    """Unified high-level interface for BranchFS.

    Parameters
    ----------
    workspace : str or Path
        The directory the AI agent works in.  A ``.branchfs/``
        subdirectory is created here for internal storage.
    """

    META_DIR = ".branchfs"

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.meta_dir = self.workspace / self.META_DIR
        self.meta_file = self.meta_dir / "meta.json"

        self.blob_store = BlobStore(self.meta_dir / "objects")
        self.snapshot_store = SnapshotStore(self.meta_dir / "snapshots")
        self.branch_store = BranchStore(self.meta_dir / "branches")

        self._fallback_ws = FallbackWorkspace(
            self.blob_store,
            self.snapshot_store,
            self.branch_store,
            self.workspace,
        )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self, take_snapshot: bool = True) -> Optional[str]:
        """Initialize BranchFS storage.

        If *take_snapshot* is ``True`` and the workspace already contains
        files, an initial snapshot named ``"init"`` is created.

        Returns the snapshot id (or ``None``).
        """
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        (self.meta_dir / "objects").mkdir(exist_ok=True)
        (self.meta_dir / "snapshots").mkdir(exist_ok=True)
        (self.meta_dir / "branches").mkdir(exist_ok=True)

        meta = {"active_branch": None, "active_snapshot": None}

        snap_id = None
        if take_snapshot:
            tree = self._scan_workspace()
            if tree:
                snap = self.snapshot_store.create("init", tree)
                meta["active_snapshot"] = snap.id
                snap_id = snap.id

        self._write_meta(meta)
        return snap_id

    @property
    def is_initialized(self) -> bool:
        return self.meta_file.exists()

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def snapshot(self, name: str = "snapshot") -> str:
        """Capture the current workspace state as an immutable snapshot.

        If a branch is active, its effective tree becomes the snapshot.
        Returns the snapshot id.
        """
        meta = self._read_meta()
        active_branch_id = meta.get("active_branch")

        if active_branch_id:
            branch = self.branch_store.load(active_branch_id)
            base = self.snapshot_store.load(branch.base_snapshot)
            tree = BranchStore.effective_tree(base.tree, branch.modified)
        else:
            tree = self._scan_workspace()

        parent = meta.get("active_snapshot")
        snap = self.snapshot_store.create(name, tree, parent=parent)
        meta["active_snapshot"] = snap.id
        self._write_meta(meta)
        return snap.id

    def get_snapshot(self, snap_id: str) -> Snapshot:
        return self.snapshot_store.load(snap_id)

    def list_snapshots(self) -> List[Snapshot]:
        return self.snapshot_store.list_all()

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def fork(self, snap_id: str, name: Optional[str] = None) -> str:
        """Create a new branch from *snap_id*.  Returns the branch id."""
        if not self.snapshot_store.exists(snap_id):
            raise ValueError(f"Snapshot {snap_id!r} does not exist")
        branch = self.branch_store.create(base_snapshot=snap_id, name=name)
        return branch.id

    def checkout(self, branch_id: str) -> None:
        """Switch the workspace to *branch_id*.

        In fallback mode this materializes the effective tree (snapshot +
        branch overlay) into the workspace directory.
        """
        branch = self.branch_store.load(branch_id)
        snapshot = self.snapshot_store.load(branch.base_snapshot)
        self._fallback_ws.materialize(snapshot, branch)

        meta = self._read_meta()
        meta["active_branch"] = branch_id
        meta["active_snapshot"] = snapshot.id
        self._write_meta(meta)

    def checkout_snapshot(self, snap_id: str) -> None:
        """Switch the workspace to a snapshot (detached, no branch)."""
        snapshot = self.snapshot_store.load(snap_id)
        self._fallback_ws.materialize(snapshot)

        meta = self._read_meta()
        meta["active_branch"] = None
        meta["active_snapshot"] = snap_id
        self._write_meta(meta)

    def get_branch(self, branch_id: str) -> Branch:
        return self.branch_store.load(branch_id)

    def list_branches(self) -> List[Branch]:
        return self.branch_store.list_all()

    def active_branch(self) -> Optional[str]:
        meta = self._read_meta()
        return meta.get("active_branch")

    def active_snapshot(self) -> Optional[str]:
        meta = self._read_meta()
        return meta.get("active_snapshot")

    # ------------------------------------------------------------------
    # Diff / Merge / Discard
    # ------------------------------------------------------------------

    def diff(self, branch_id: str) -> Dict[str, str]:
        """Return ``{path: status}`` diff of *branch_id* against its base snapshot."""
        branch = self.branch_store.load(branch_id)
        snapshot = self.snapshot_store.load(branch.base_snapshot)
        return BranchStore.diff(snapshot.tree, branch.modified)

    def sync_branch(self, branch_id: Optional[str] = None) -> None:
        """Scan the workspace and update the active (or given) branch's modifications.

        Call this after the AI has written files to the workspace to
        record changes in the branch layer.
        """
        if branch_id is None:
            branch_id = self.active_branch()
        if branch_id is None:
            raise RuntimeError("No active branch to sync")

        branch = self.branch_store.load(branch_id)
        snapshot = self.snapshot_store.load(branch.base_snapshot)
        current_tree = self._scan_workspace()
        branch.modified = self._fallback_ws.compute_branch_modifications(
            snapshot.tree, current_tree
        )
        self.branch_store.save(branch)

    def merge(self, branch_id: str, snapshot_name: Optional[str] = None) -> str:
        """Merge *branch_id* back, creating a new snapshot.

        First syncs any workspace changes, then creates a snapshot from
        the effective tree.  Returns the new snapshot id.
        """
        self.sync_branch(branch_id)
        branch = self.branch_store.load(branch_id)
        snapshot = self.snapshot_store.load(branch.base_snapshot)
        effective = BranchStore.effective_tree(snapshot.tree, branch.modified)

        name = snapshot_name or f"merge-{branch.name}"
        new_snap = self.snapshot_store.create(
            name, effective, parent=branch.base_snapshot
        )

        # Clean up branch.
        self.branch_store.delete(branch_id)

        meta = self._read_meta()
        meta["active_branch"] = None
        meta["active_snapshot"] = new_snap.id
        self._write_meta(meta)
        return new_snap.id

    def discard(self, branch_id: str) -> None:
        """Discard a branch and restore the workspace to its base snapshot."""
        branch = self.branch_store.load(branch_id)
        self.branch_store.delete(branch_id)

        meta = self._read_meta()
        if meta.get("active_branch") == branch_id:
            # Restore workspace to the base snapshot.
            snapshot = self.snapshot_store.load(branch.base_snapshot)
            self._fallback_ws.materialize(snapshot)
            meta["active_branch"] = None
            meta["active_snapshot"] = branch.base_snapshot
            self._write_meta(meta)

    def branch_context(
        self, snap_id: str, name: Optional[str] = None
    ) -> FallbackBranch:
        """Return a ``FallbackBranch`` context manager for isolated exploration.

        Usage::

            with fs.branch_context(snap_id) as fb:
                (fb.workdir / "file.txt").write_text("hi")
                fb.merge()
        """
        return FallbackBranch(
            self.blob_store,
            self.snapshot_store,
            self.branch_store,
            snap_id,
            branch_name=name,
        )

    # ------------------------------------------------------------------
    # History / Visualization
    # ------------------------------------------------------------------

    def log(self) -> str:
        """Return an ASCII-formatted history of snapshots and branches."""
        return build_log(
            self.snapshot_store.list_all(),
            self.branch_store.list_all(),
            active_branch=self.active_branch(),
        )

    def diff_formatted(self, branch_id: str) -> str:
        """Return a human-readable diff string."""
        return format_diff(self.diff(branch_id))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_workspace(self) -> Dict[str, str]:
        """Walk the workspace and store all files.  Returns ``{path: hash}``."""
        return self._fallback_ws.scan()

    def _read_meta(self) -> dict:
        if self.meta_file.exists():
            return json.loads(self.meta_file.read_text())
        return {}

    def _write_meta(self, meta: dict) -> None:
        self.meta_file.write_text(json.dumps(meta, indent=2))
