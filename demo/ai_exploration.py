#!/usr/bin/env python3
"""Demo: Simulates an AI agent trying 3 approaches in parallel branches.

The agent explores different solutions to a problem, evaluates each,
discards the failures, and merges the winner.

Usage:
    python demo/ai_exploration.py
"""

import random
import sys
import tempfile
from pathlib import Path

# Allow running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from branchfs import BranchFS


def simulate_approach(workdir: Path, name: str, quality: float) -> float:
    """Simulate an AI writing code in a workspace.  Returns a 'score'."""
    (workdir / "solution.py").write_text(
        f"# Approach: {name}\n"
        f"# Quality score: {quality:.2f}\n\n"
        f"def solve():\n"
        f"    return '{name}'\n"
    )
    (workdir / "tests.py").write_text(
        f"from solution import solve\n\n"
        f"def test_solve():\n"
        f"    assert solve() == '{name}'\n"
    )
    if quality > 0.7:
        (workdir / "README.md").write_text(
            f"# Solution: {name}\n\nThis approach scored {quality:.2f}.\n"
        )
    return quality


def main() -> None:
    # Create a temporary workspace.
    with tempfile.TemporaryDirectory(prefix="branchfs_demo_") as tmpdir:
        workspace = Path(tmpdir)
        print(f"Workspace: {workspace}\n")

        # Initialize with some starter files.
        (workspace / "problem.txt").write_text(
            "Find the optimal sorting algorithm for nearly-sorted data.\n"
        )
        (workspace / "constraints.txt").write_text(
            "Must be stable. O(n) best case. O(n log n) worst case.\n"
        )

        fs = BranchFS(workspace)
        snap_id = fs.init()
        print(f"Initialized. Baseline snapshot: {snap_id}")
        print(f"Files: {list(fs.get_snapshot(snap_id).tree.keys())}\n")

        # --- Try 3 approaches in parallel ---
        approaches = [
            ("timsort", 0.95),
            ("bubble-optimized", 0.3),
            ("insertion-adaptive", 0.75),
        ]

        results = []
        for name, quality in approaches:
            print(f"--- Exploring: {name} ---")
            branch_id = fs.fork(snap_id, name=name)
            fs.checkout(branch_id)

            score = simulate_approach(workspace, name, quality)
            fs.sync_branch(branch_id)

            diff = fs.diff(branch_id)
            print(f"  Changes: {diff}")
            print(f"  Score:   {score:.2f}")
            results.append((branch_id, name, score))
            print()

        # --- Pick the winner ---
        results.sort(key=lambda r: r[2], reverse=True)
        winner_id, winner_name, winner_score = results[0]
        print(f"Winner: {winner_name} (score={winner_score:.2f})\n")

        # Discard losers.
        for branch_id, name, score in results[1:]:
            print(f"Discarding: {name}")
            fs.discard(branch_id)

        # Merge winner.
        print(f"Merging: {winner_name}")
        fs.checkout(winner_id)
        new_snap = fs.merge(winner_id, snapshot_name=f"winner-{winner_name}")
        print(f"New snapshot: {new_snap}\n")

        # --- Show final state ---
        print("=== History ===")
        print(fs.log())
        print()

        final_snap = fs.get_snapshot(new_snap)
        print("=== Final files ===")
        for path in sorted(final_snap.tree.keys()):
            print(f"  {path}")

        print("\nDone!")


if __name__ == "__main__":
    main()
