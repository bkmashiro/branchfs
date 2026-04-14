"""FUSE filesystem implementation for BranchFS.

Provides a transparent overlay where reads fall through to the base
snapshot and writes land in the active branch layer (copy-on-write).

Requires ``fusepy`` (``pip install fusepy``).  The rest of BranchFS
works without it — this module is imported lazily.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

try:
    from fuse import FUSE, FuseOSError, Operations  # type: ignore[import-untyped]

    FUSE_AVAILABLE = True
except ImportError:
    FUSE_AVAILABLE = False

    class FuseOSError(OSError):  # type: ignore[no-redef]
        pass

    class Operations:  # type: ignore[no-redef]
        pass

from branchfs.branch import DELETED_SENTINEL, Branch, BranchStore
from branchfs.snapshot import Snapshot
from branchfs.store import BlobStore

logger = logging.getLogger(__name__)


class BranchFUSE(Operations):  # type: ignore[misc]
    """FUSE operations that overlay branch modifications on a snapshot."""

    def __init__(
        self,
        blob_store: BlobStore,
        snapshot: Snapshot,
        branch: Branch,
        branch_store: BranchStore,
    ) -> None:
        self.blob_store = blob_store
        self.snapshot = snapshot
        self.branch = branch
        self.branch_store = branch_store
        self._open_files: Dict[int, bytes] = {}
        self._next_fh = 1
        self._dirty_files: Dict[str, bytes] = {}
        now = time.time()
        self._default_stat = {
            "st_mode": stat.S_IFREG | 0o644,
            "st_nlink": 1,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
            "st_size": 0,
            "st_atime": now,
            "st_mtime": now,
            "st_ctime": now,
        }

    @property
    def _tree(self) -> Dict[str, str]:
        return BranchStore.effective_tree(self.snapshot.tree, self.branch.modified)

    def _rel(self, path: str) -> str:
        return path.lstrip("/")

    # ------------------------------------------------------------------
    # Filesystem operations
    # ------------------------------------------------------------------

    def getattr(self, path: str, fh: Optional[int] = None) -> dict:
        rel = self._rel(path)
        tree = self._tree

        if rel == "":
            # Root directory.
            return {
                **self._default_stat,
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
            }

        if rel in tree:
            data = self._read_blob(tree[rel])
            return {**self._default_stat, "st_size": len(data)}

        # Check if it's a directory (any tree entry starts with rel + /).
        prefix = rel + "/"
        if any(k.startswith(prefix) for k in tree):
            return {
                **self._default_stat,
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
            }

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path: str, fh: int) -> list[str]:
        rel = self._rel(path)
        tree = self._tree
        entries = {".", ".."}

        prefix = (rel + "/") if rel else ""
        for key in tree:
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            part = rest.split("/")[0]
            entries.add(part)

        return list(entries)

    def open(self, path: str, flags: int) -> int:
        rel = self._rel(path)
        tree = self._tree
        if rel not in tree and rel not in self._dirty_files:
            raise FuseOSError(errno.ENOENT)
        fh = self._next_fh
        self._next_fh += 1
        return fh

    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        rel = self._rel(path)
        if rel in self._dirty_files:
            data = self._dirty_files[rel]
        else:
            tree = self._tree
            if rel not in tree:
                raise FuseOSError(errno.ENOENT)
            data = self._read_blob(tree[rel])
        return data[offset : offset + size]

    def write(self, path: str, data: bytes, offset: int, fh: int) -> int:
        rel = self._rel(path)
        if rel in self._dirty_files:
            existing = bytearray(self._dirty_files[rel])
        else:
            tree = self._tree
            if rel in tree:
                existing = bytearray(self._read_blob(tree[rel]))
            else:
                existing = bytearray()

        end = offset + len(data)
        if end > len(existing):
            existing.extend(b"\x00" * (end - len(existing)))
        existing[offset:end] = data
        self._dirty_files[rel] = bytes(existing)
        return len(data)

    def create(self, path: str, mode: int, fi: Optional[object] = None) -> int:
        rel = self._rel(path)
        self._dirty_files[rel] = b""
        fh = self._next_fh
        self._next_fh += 1
        return fh

    def truncate(self, path: str, length: int, fh: Optional[int] = None) -> None:
        rel = self._rel(path)
        if rel in self._dirty_files:
            self._dirty_files[rel] = self._dirty_files[rel][:length]
        else:
            tree = self._tree
            if rel in tree:
                data = self._read_blob(tree[rel])[:length]
                self._dirty_files[rel] = data

    def unlink(self, path: str) -> None:
        rel = self._rel(path)
        self._dirty_files.pop(rel, None)
        self.branch.modified[rel] = DELETED_SENTINEL
        self.branch_store.save(self.branch)

    def mkdir(self, path: str, mode: int) -> None:
        # Directories are implicit — no-op, they exist if files exist under them.
        pass

    def rmdir(self, path: str) -> None:
        rel = self._rel(path)
        prefix = rel + "/"
        tree = self._tree
        for key in list(tree.keys()):
            if key.startswith(prefix):
                self.branch.modified[key] = DELETED_SENTINEL
        self.branch_store.save(self.branch)

    def flush(self, path: str, fh: int) -> None:
        rel = self._rel(path)
        if rel in self._dirty_files:
            blob_hash = self.blob_store.put_bytes(self._dirty_files[rel])
            self.branch.modified[rel] = blob_hash
            self.branch_store.save(self.branch)
            del self._dirty_files[rel]

    def release(self, path: str, fh: int) -> None:
        self.flush(path, fh)

    def rename(self, old: str, new: str) -> None:
        old_rel = self._rel(old)
        new_rel = self._rel(new)
        tree = self._tree
        if old_rel in tree:
            self.branch.modified[new_rel] = tree[old_rel]
            self.branch.modified[old_rel] = DELETED_SENTINEL
            self.branch_store.save(self.branch)
        if old_rel in self._dirty_files:
            self._dirty_files[new_rel] = self._dirty_files.pop(old_rel)

    def chmod(self, path: str, mode: int) -> None:
        pass

    def chown(self, path: str, uid: int, gid: int) -> None:
        pass

    def utimens(self, path: str, times: Optional[tuple] = None) -> None:
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_blob(self, blob_hash: str) -> bytes:
        return self.blob_store.get_bytes(blob_hash)


def mount_fuse(
    mountpoint: str | Path,
    blob_store: BlobStore,
    snapshot: Snapshot,
    branch: Branch,
    branch_store: BranchStore,
    foreground: bool = True,
) -> None:
    """Mount the FUSE filesystem.

    Blocks until unmounted (Ctrl-C or ``fusermount -u``).
    """
    if not FUSE_AVAILABLE:
        raise ImportError("fusepy is required for FUSE mode: pip install fusepy")
    ops = BranchFUSE(blob_store, snapshot, branch, branch_store)
    FUSE(ops, str(mountpoint), foreground=foreground, nothreads=True, allow_other=False)
