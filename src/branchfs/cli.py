"""CLI interface for BranchFS.

Usage::

    branchfs init [--no-snapshot] [path]
    branchfs snap [name] [path]
    branchfs fork <snapshot-id> [--name NAME] [path]
    branchfs checkout <branch-id> [path]
    branchfs checkout-snap <snapshot-id> [path]
    branchfs diff <branch-id> [path]
    branchfs sync [branch-id] [path]
    branchfs merge <branch-id> [--name NAME] [path]
    branchfs discard <branch-id> [path]
    branchfs log [path]
    branchfs branches [path]
    branchfs snapshots [path]
    branchfs status [path]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from branchfs.api import BranchFS


def _get_fs(args: argparse.Namespace) -> BranchFS:
    workspace = getattr(args, "path", None) or "."
    return BranchFS(workspace)


def cmd_init(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    snap_id = fs.init(take_snapshot=not args.no_snapshot)
    print(f"Initialized BranchFS in {fs.workspace}")
    if snap_id:
        print(f"Initial snapshot: {snap_id}")


def cmd_snap(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    name = args.name or "snapshot"
    snap_id = fs.snapshot(name)
    print(f"Snapshot created: {snap_id} ({name})")


def cmd_fork(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    branch_id = fs.fork(args.snapshot_id, name=args.name)
    print(f"Branch created: {branch_id}")


def cmd_checkout(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    fs.checkout(args.branch_id)
    print(f"Checked out branch {args.branch_id}")


def cmd_checkout_snap(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    fs.checkout_snapshot(args.snapshot_id)
    print(f"Checked out snapshot {args.snapshot_id}")


def cmd_diff(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    output = fs.diff_formatted(args.branch_id)
    print(output)


def cmd_sync(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    branch_id = args.branch_id
    fs.sync_branch(branch_id)
    bid = branch_id or fs.active_branch()
    print(f"Branch {bid} synced with workspace")


def cmd_merge(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    snap_id = fs.merge(args.branch_id, snapshot_name=args.name)
    print(f"Merged → new snapshot: {snap_id}")


def cmd_discard(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    fs.discard(args.branch_id)
    print(f"Branch {args.branch_id} discarded")


def cmd_log(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    print(fs.log())


def cmd_branches(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    active = fs.active_branch()
    branches = fs.list_branches()
    if not branches:
        print("(no branches)")
        return
    for b in branches:
        marker = " *" if b.id == active else ""
        print(f"  {b.id}  {b.name}  (base: {b.base_snapshot}){marker}")


def cmd_snapshots(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    active = fs.active_snapshot()
    snaps = fs.list_snapshots()
    if not snaps:
        print("(no snapshots)")
        return
    for s in snaps:
        marker = " *" if s.id == active else ""
        print(f"  {s.id}  {s.name}  ({len(s.tree)} files){marker}")


def cmd_status(args: argparse.Namespace) -> None:
    fs = _get_fs(args)
    if not fs.is_initialized:
        print("Not initialized. Run: branchfs init")
        return
    active_snap = fs.active_snapshot()
    active_br = fs.active_branch()
    snaps = fs.list_snapshots()
    branches = fs.list_branches()
    print(f"Workspace:  {fs.workspace}")
    print(f"Snapshots:  {len(snaps)}")
    print(f"Branches:   {len(branches)}")
    print(f"Active snapshot: {active_snap or '(none)'}")
    print(f"Active branch:   {active_br or '(none)'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="branchfs",
        description="AI-optimized branching filesystem",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init", help="Initialize BranchFS")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--no-snapshot", action="store_true")
    p.set_defaults(func=cmd_init)

    # snap
    p = sub.add_parser("snap", help="Create a snapshot")
    p.add_argument("name", nargs="?", default="snapshot")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_snap)

    # fork
    p = sub.add_parser("fork", help="Fork a branch from a snapshot")
    p.add_argument("snapshot_id")
    p.add_argument("--name", default=None)
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_fork)

    # checkout
    p = sub.add_parser("checkout", help="Checkout a branch")
    p.add_argument("branch_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_checkout)

    # checkout-snap
    p = sub.add_parser("checkout-snap", help="Checkout a snapshot (detached)")
    p.add_argument("snapshot_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_checkout_snap)

    # diff
    p = sub.add_parser("diff", help="Show diff for a branch")
    p.add_argument("branch_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_diff)

    # sync
    p = sub.add_parser("sync", help="Sync workspace changes to branch")
    p.add_argument("branch_id", nargs="?", default=None)
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_sync)

    # merge
    p = sub.add_parser("merge", help="Merge a branch into a new snapshot")
    p.add_argument("branch_id")
    p.add_argument("--name", default=None)
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_merge)

    # discard
    p = sub.add_parser("discard", help="Discard a branch")
    p.add_argument("branch_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_discard)

    # log
    p = sub.add_parser("log", help="Show snapshot/branch history")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_log)

    # branches
    p = sub.add_parser("branches", help="List branches")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_branches)

    # snapshots
    p = sub.add_parser("snapshots", help="List snapshots")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_snapshots)

    # status
    p = sub.add_parser("status", help="Show BranchFS status")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
