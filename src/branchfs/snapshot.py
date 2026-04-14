"""Snapshot management — immutable point-in-time captures of directory state.

A snapshot is a JSON metadata file that records:
  - id:       unique identifier (uuid4-based)
  - name:     human-readable label
  - parent:   id of the parent snapshot (or null for the root)
  - tree:     mapping of relative paths to blob hashes
  - created:  ISO-8601 timestamp
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class Snapshot:
    """Represents a single immutable snapshot."""

    def __init__(
        self,
        snap_id: str,
        name: str,
        tree: Dict[str, str],
        parent: Optional[str] = None,
        created: Optional[str] = None,
    ) -> None:
        self.id = snap_id
        self.name = name
        self.tree = dict(tree)  # {relative_path: blob_hash}
        self.parent = parent
        self.created = created or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parent": self.parent,
            "tree": self.tree,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Snapshot":
        return cls(
            snap_id=d["id"],
            name=d["name"],
            tree=d["tree"],
            parent=d.get("parent"),
            created=d.get("created"),
        )

    def __repr__(self) -> str:
        return f"Snapshot(id={self.id!r}, name={self.name!r}, files={len(self.tree)})"


class SnapshotStore:
    """Manages snapshot metadata on disk."""

    def __init__(self, snapshots_dir: str | Path) -> None:
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        name: str,
        tree: Dict[str, str],
        parent: Optional[str] = None,
    ) -> Snapshot:
        """Create and persist a new snapshot.  Returns the ``Snapshot`` object."""
        snap_id = uuid.uuid4().hex[:12]
        snap = Snapshot(snap_id=snap_id, name=name, tree=tree, parent=parent)
        self._save(snap)
        return snap

    def load(self, snap_id: str) -> Snapshot:
        """Load a snapshot by id.  Raises ``FileNotFoundError`` if missing."""
        path = self._path(snap_id)
        data = json.loads(path.read_text())
        return Snapshot.from_dict(data)

    def list_all(self) -> List[Snapshot]:
        """Return all snapshots sorted by creation time."""
        snaps: list[Snapshot] = []
        for p in self.snapshots_dir.glob("*.json"):
            data = json.loads(p.read_text())
            snaps.append(Snapshot.from_dict(data))
        snaps.sort(key=lambda s: s.created)
        return snaps

    def exists(self, snap_id: str) -> bool:
        return self._path(snap_id).exists()

    def delete(self, snap_id: str) -> bool:
        p = self._path(snap_id)
        if p.exists():
            p.unlink()
            return True
        return False

    @staticmethod
    def diff_trees(
        old_tree: Dict[str, str],
        new_tree: Dict[str, str],
    ) -> Dict[str, str]:
        """Compare two trees.  Returns dict of changes.

        Each entry is ``{path: status}`` where status is one of:
        ``"added"``, ``"modified"``, ``"deleted"``.
        """
        changes: Dict[str, str] = {}
        all_paths = set(old_tree) | set(new_tree)
        for p in sorted(all_paths):
            in_old = p in old_tree
            in_new = p in new_tree
            if in_old and not in_new:
                changes[p] = "deleted"
            elif not in_old and in_new:
                changes[p] = "added"
            elif old_tree[p] != new_tree[p]:
                changes[p] = "modified"
        return changes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path(self, snap_id: str) -> Path:
        return self.snapshots_dir / f"{snap_id}.json"

    def _save(self, snap: Snapshot) -> None:
        self._path(snap.id).write_text(json.dumps(snap.to_dict(), indent=2))
