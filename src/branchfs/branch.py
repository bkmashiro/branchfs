"""Branch management — mutable layers on top of snapshots.

A branch records:
  - id:            unique identifier
  - name:          human-readable label (auto-generated or user-supplied)
  - base_snapshot: the snapshot this branch was forked from
  - modified:      mapping  {path: blob_hash | "__deleted__"}
  - created:       ISO-8601 timestamp
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DELETED_SENTINEL = "__deleted__"


class Branch:
    """Represents a single mutable branch layer."""

    def __init__(
        self,
        branch_id: str,
        name: str,
        base_snapshot: str,
        modified: Optional[Dict[str, str]] = None,
        created: Optional[str] = None,
    ) -> None:
        self.id = branch_id
        self.name = name
        self.base_snapshot = base_snapshot
        self.modified: Dict[str, str] = modified or {}
        self.created = created or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_snapshot": self.base_snapshot,
            "modified": self.modified,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Branch":
        return cls(
            branch_id=d["id"],
            name=d["name"],
            base_snapshot=d["base_snapshot"],
            modified=d.get("modified", {}),
            created=d.get("created"),
        )

    @property
    def effective_tree(self) -> None:
        """This is computed externally because it needs the snapshot tree."""
        raise NotImplementedError("Use BranchStore.effective_tree()")

    def __repr__(self) -> str:
        return (
            f"Branch(id={self.id!r}, name={self.name!r}, "
            f"base={self.base_snapshot!r}, changes={len(self.modified)})"
        )


class BranchStore:
    """Manages branch metadata on disk."""

    def __init__(self, branches_dir: str | Path) -> None:
        self.branches_dir = Path(branches_dir)
        self.branches_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        base_snapshot: str,
        name: Optional[str] = None,
    ) -> Branch:
        branch_id = uuid.uuid4().hex[:12]
        if name is None:
            name = f"branch-{branch_id[:6]}"
        branch = Branch(branch_id=branch_id, name=name, base_snapshot=base_snapshot)
        self._save(branch)
        return branch

    def load(self, branch_id: str) -> Branch:
        path = self._path(branch_id)
        data = json.loads(path.read_text())
        return Branch.from_dict(data)

    def save(self, branch: Branch) -> None:
        self._save(branch)

    def list_all(self) -> List[Branch]:
        branches: list[Branch] = []
        for p in self.branches_dir.glob("*.json"):
            data = json.loads(p.read_text())
            branches.append(Branch.from_dict(data))
        branches.sort(key=lambda b: b.created)
        return branches

    def exists(self, branch_id: str) -> bool:
        return self._path(branch_id).exists()

    def delete(self, branch_id: str) -> bool:
        p = self._path(branch_id)
        if p.exists():
            p.unlink()
            return True
        return False

    @staticmethod
    def effective_tree(
        snapshot_tree: Dict[str, str],
        branch_modified: Dict[str, str],
    ) -> Dict[str, str]:
        """Merge snapshot tree with branch modifications.

        Returns the complete file tree as the workspace would see it.
        """
        tree = dict(snapshot_tree)
        for path, value in branch_modified.items():
            if value == DELETED_SENTINEL:
                tree.pop(path, None)
            else:
                tree[path] = value
        return tree

    @staticmethod
    def diff(
        snapshot_tree: Dict[str, str],
        branch_modified: Dict[str, str],
    ) -> Dict[str, str]:
        """Return a human-readable diff of the branch against its base.

        Returns ``{path: status}`` where status is ``"added"``,
        ``"modified"``, or ``"deleted"``.
        """
        changes: Dict[str, str] = {}
        for path, value in sorted(branch_modified.items()):
            if value == DELETED_SENTINEL:
                if path in snapshot_tree:
                    changes[path] = "deleted"
            elif path in snapshot_tree:
                if snapshot_tree[path] != value:
                    changes[path] = "modified"
                # else: same hash, no real change
            else:
                changes[path] = "added"
        return changes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path(self, branch_id: str) -> Path:
        return self.branches_dir / f"{branch_id}.json"

    def _save(self, branch: Branch) -> None:
        self._path(branch.id).write_text(json.dumps(branch.to_dict(), indent=2))
