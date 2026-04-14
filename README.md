# BranchFS

**AI-optimized branching filesystem for Linux.**

BranchFS gives AI agents lightweight, programmatic branch and snapshot control over a working directory. It is modelled loosely on git but designed for machine consumption: no staging area, no commit messages, no interactive rebase — just fast, deterministic operations that an agent can call in a tight loop while exploring different approaches to a problem.

The core insight is that AI agents need to **explore and backtrack** constantly. Try an approach, evaluate it, throw it away if it fails, try another. Today this means either careful manual undo (fragile), full Docker containers (heavyweight), or git (designed for humans). BranchFS sits in the sweet spot: copy-on-write branching with sub-millisecond fork/discard, a content-addressable blob store for automatic deduplication, and a FUSE mode that makes it completely transparent to the agent's file I/O.

When FUSE is unavailable (unprivileged containers, macOS, CI), a fallback mode provides the same API using temporary directories and shutil — no kernel module needed.

## Architecture

```
                         ┌──────────────────────────┐
                         │      AI Agent / CLI       │
                         └────────────┬─────────────┘
                                      │
                              BranchFS Python API
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
              FUSE Mode         Fallback Mode       CLI (branchfs)
           (transparent)      (context manager)    (shell commands)
                    │                 │                  │
                    └─────────────────┼─────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
               BlobStore       SnapshotStore       BranchStore
            (SHA-256 dedup)   (immutable trees)   (mutable layers)
                    │                 │                  │
                    └─────────────────┼─────────────────┘
                                      │
                              .branchfs/ on disk
```

### Storage layout

```
workspace/
├── .branchfs/
│   ├── objects/        # Content-addressable blob store (SHA-256 named files)
│   ├── snapshots/      # Snapshot metadata (JSON: id, parent, tree)
│   ├── branches/       # Branch metadata (JSON: id, base_snapshot, modified)
│   └── meta.json       # Active branch/snapshot state
├── app.py              # ← The AI works here, reads/writes normally
├── lib/
│   └── core.py
└── ...
```

### Core concepts

| Concept    | Description |
|------------|-------------|
| **Snapshot** | Immutable point-in-time capture of the entire directory tree. Like a git commit but without messages or author info. |
| **Branch**   | Mutable layer on top of a snapshot. Writes go here; reads fall through to the base snapshot. Copy-on-write. |
| **Workspace** | The directory the AI actually works in. In FUSE mode, it is a mount point. In fallback mode, files are materialized with shutil. |

## Installation

```bash
# Basic install (fallback mode, works everywhere)
pip install .

# With FUSE support (Linux, requires libfuse)
pip install ".[fuse]"

# Development
pip install -e ".[dev]"
```

### Requirements

- Python 3.9+
- Linux (primary target)
- Optional: `fusepy` for FUSE mode
- Optional: `libfuse-dev` / `fuse` system package for FUSE mode

## Quick Start

```python
from branchfs import BranchFS

# Initialize
fs = BranchFS("/path/to/workspace")
fs.init()  # scans existing files, takes initial snapshot

# Take a snapshot
snap_id = fs.snapshot("baseline")

# Fork a branch and explore
branch_id = fs.fork(snap_id, name="experiment")
fs.checkout(branch_id)
# ... AI writes files normally ...

# See what changed
fs.sync_branch()
diff = fs.diff(branch_id)       # {'new_file.py': 'added', 'app.py': 'modified'}

# Happy with the result? Merge.
new_snap = fs.merge(branch_id)  # creates new snapshot, deletes branch

# Not happy? Discard.
fs.discard(branch_id)           # workspace restored to snapshot state
```

### Context manager (isolated branches)

```python
# No need to manage checkout/sync/merge manually
with fs.branch_context(snap_id, name="try-something") as branch:
    (branch.workdir / "solution.py").write_text("def solve(): ...")
    result = evaluate(branch.workdir)
    if result.good:
        branch.merge()
    # If merge() not called, changes are automatically discarded
```

## Full API Reference

### `BranchFS(workspace)`

Create a BranchFS instance for the given workspace directory.

#### Methods

| Method | Description | Returns |
|--------|-------------|---------|
| `init(take_snapshot=True)` | Initialize `.branchfs/` storage. Optionally captures initial snapshot. | `str \| None` (snapshot id) |
| `snapshot(name)` | Capture current workspace state as immutable snapshot. | `str` (snapshot id) |
| `fork(snap_id, name=None)` | Create a branch from a snapshot. | `str` (branch id) |
| `checkout(branch_id)` | Switch workspace to a branch (materializes files). | `None` |
| `checkout_snapshot(snap_id)` | Switch workspace to a snapshot (detached, no branch). | `None` |
| `sync_branch(branch_id=None)` | Scan workspace and record changes in active branch. | `None` |
| `diff(branch_id)` | Get changes vs base snapshot. | `dict` (`{path: status}`) |
| `diff_formatted(branch_id)` | Human-readable diff string. | `str` |
| `merge(branch_id, snapshot_name=None)` | Merge branch into new snapshot, delete branch. | `str` (snapshot id) |
| `discard(branch_id)` | Delete branch, restore workspace to base snapshot. | `None` |
| `branch_context(snap_id, name=None)` | Context manager for isolated branch work. | `FallbackBranch` |
| `log()` | ASCII history tree. | `str` |
| `list_snapshots()` | All snapshots. | `list[Snapshot]` |
| `list_branches()` | All branches. | `list[Branch]` |
| `active_branch()` | Currently checked-out branch id. | `str \| None` |
| `active_snapshot()` | Currently active snapshot id. | `str \| None` |
| `get_snapshot(snap_id)` | Load snapshot by id. | `Snapshot` |
| `get_branch(branch_id)` | Load branch by id. | `Branch` |

## CLI Reference

```bash
branchfs init [path]                    # Initialize BranchFS
branchfs snap [name] [path]             # Create snapshot
branchfs fork <snap-id> [--name N]      # Fork branch from snapshot
branchfs checkout <branch-id>           # Switch to branch
branchfs checkout-snap <snap-id>        # Switch to snapshot (detached)
branchfs diff <branch-id>               # Show branch diff
branchfs sync [branch-id]               # Sync workspace → branch
branchfs merge <branch-id> [--name N]   # Merge branch → new snapshot
branchfs discard <branch-id>            # Discard branch
branchfs log                            # Show history tree
branchfs branches                       # List branches
branchfs snapshots                      # List snapshots
branchfs status                         # Show current state
```

## How It Compares

| Feature | BranchFS | Git | Docker |
|---------|----------|-----|--------|
| Fork time | ~1ms (metadata only) | ~100ms (checkout) | ~1s (container create) |
| Storage overhead | Deduped blobs | Full repo | Full filesystem image |
| API | Python-native | CLI/libgit2 | Docker SDK |
| Transparency | FUSE mount or shutil | Working tree | Full container |
| Designed for | AI agents | Human developers | Process isolation |
| Requires root | No (fallback mode) | No | Yes (usually) |
| Works in Docker | Yes (fallback always; FUSE with --privileged) | Yes | Docker-in-Docker |

## Use Cases for AI Agents

- **Speculative execution**: Try multiple approaches to a coding task, keep the best one
- **Safe exploration**: Modify config files, test the result, roll back if broken
- **A/B testing**: Fork two branches, run benchmarks in each, merge the faster one
- **Checkpoint/restore**: Snapshot before a risky operation, restore if it fails
- **Parallel search**: Fork N branches for N strategies, evaluate in parallel
- **Iterative refinement**: Snapshot after each improvement, backtrack if a step regresses

## Running Tests

```bash
pip install -e ".[dev]"
pytest                    # all tests (no FUSE required)
pytest -v                 # verbose
pytest --tb=short -q      # compact
```

## License

MIT License. See [LICENSE](LICENSE).
