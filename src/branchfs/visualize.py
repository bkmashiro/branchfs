"""ASCII visualization of the snapshot/branch history tree."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from branchfs.branch import Branch
from branchfs.snapshot import Snapshot


def build_log(
    snapshots: List[Snapshot],
    branches: List[Branch],
    active_branch: Optional[str] = None,
) -> str:
    """Return a formatted ASCII tree of snapshots and branches.

    Example output::

        * [abc123] baseline  (3 files)
        |\\
        | o [def456] branch-def456  +2 ~1 -0
        | o [ghi789] branch-ghi789  +0 ~1 -1  <- active
        |
        * [jkl012] after-merge  (5 files)
    """
    if not snapshots:
        return "(no snapshots)"

    # Build parent-child map for snapshots.
    snap_children: Dict[Optional[str], List[Snapshot]] = {}
    for s in snapshots:
        snap_children.setdefault(s.parent, []).append(s)

    # Map snapshot id -> branches forked from it.
    snap_branches: Dict[str, List[Branch]] = {}
    for b in branches:
        snap_branches.setdefault(b.base_snapshot, []).append(b)

    lines: list[str] = []

    def render_snap(snap: Snapshot, depth: int = 0) -> None:
        indent = "  " * depth
        marker = "*"
        label = f"[{snap.id}] {snap.name}  ({len(snap.tree)} files)"
        lines.append(f"{indent}{marker} {label}")

        # Show branches off this snapshot.
        brs = snap_branches.get(snap.id, [])
        if brs:
            lines.append(f"{indent}|\\")
            for br in brs:
                active_marker = "  <- active" if br.id == active_branch else ""
                stats = _branch_stats(br)
                lines.append(
                    f"{indent}| o [{br.id}] {br.name}  {stats}{active_marker}"
                )
            lines.append(f"{indent}|")

        # Recurse into child snapshots.
        children = snap_children.get(snap.id, [])
        for child in children:
            render_snap(child, depth)

    # Start from root snapshots (no parent).
    roots = snap_children.get(None, [])
    for root in roots:
        render_snap(root)

    return "\n".join(lines)


def _branch_stats(branch: Branch) -> str:
    from branchfs.branch import DELETED_SENTINEL

    added = modified = deleted = 0
    for _path, value in branch.modified.items():
        if value == DELETED_SENTINEL:
            deleted += 1
        else:
            # We can't distinguish added vs modified without the snapshot tree,
            # so we just report them all as changes.
            added += 1
    return f"+{added} -{deleted}"


def format_diff(changes: Dict[str, str]) -> str:
    """Format a diff dict as a human-readable string."""
    if not changes:
        return "(no changes)"
    lines: list[str] = []
    symbols = {"added": "+", "modified": "~", "deleted": "-"}
    for path in sorted(changes):
        status = changes[path]
        sym = symbols.get(status, "?")
        lines.append(f"  {sym} {path}")
    return "\n".join(lines)
