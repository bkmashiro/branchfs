"""Content-addressable blob store with SHA-256 deduplication.

Blobs are stored as files named by their SHA-256 hash under an objects/
directory.  Identical content always maps to the same hash, giving
automatic deduplication.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional


class BlobStore:
    """Content-addressable blob store backed by a directory of hash-named files."""

    def __init__(self, objects_dir: str | Path) -> None:
        self.objects_dir = Path(objects_dir)
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        """Return the SHA-256 hex digest for *data*."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def hash_file(path: str | Path) -> str:
        """Return the SHA-256 hex digest of the file at *path*."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 16):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def put_bytes(self, data: bytes) -> str:
        """Store raw bytes, return the blob hash."""
        blob_hash = self.hash_bytes(data)
        dest = self._blob_path(blob_hash)
        if not dest.exists():
            # Write to a unique tmp file then atomic rename to avoid
            # partial blobs and races between concurrent writers.
            fd, tmp_path = tempfile.mkstemp(dir=self.objects_dir)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            try:
                os.rename(tmp_path, dest)
            except BaseException:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        return blob_hash

    def put_file(self, path: str | Path) -> str:
        """Store a file by path, return the blob hash."""
        path = Path(path)
        blob_hash = self.hash_file(path)
        dest = self._blob_path(blob_hash)
        if not dest.exists():
            fd, tmp_path = tempfile.mkstemp(dir=self.objects_dir)
            os.close(fd)
            try:
                shutil.copy2(str(path), tmp_path)
                os.rename(tmp_path, str(dest))
            except BaseException:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        return blob_hash

    def get_bytes(self, blob_hash: str) -> bytes:
        """Read and return the blob content for *blob_hash*.

        Raises ``FileNotFoundError`` if the blob does not exist.
        """
        return self._blob_path(blob_hash).read_bytes()

    def extract_to(self, blob_hash: str, dest: str | Path) -> None:
        """Copy the blob to *dest* on disk."""
        src = self._blob_path(blob_hash)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))

    def has(self, blob_hash: str) -> bool:
        """Return ``True`` if the blob exists in the store."""
        return self._blob_path(blob_hash).exists()

    def delete(self, blob_hash: str) -> bool:
        """Remove a blob.  Returns ``True`` if it existed."""
        p = self._blob_path(blob_hash)
        if p.exists():
            p.unlink()
            return True
        return False

    def list_blobs(self) -> list[str]:
        """Return all blob hashes present in the store."""
        return [p.name for p in self.objects_dir.iterdir() if p.is_file() and not p.name.endswith(".tmp")]

    @property
    def size(self) -> int:
        """Total bytes stored on disk (before filesystem overhead)."""
        return sum(p.stat().st_size for p in self.objects_dir.iterdir() if p.is_file())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _blob_path(self, blob_hash: str) -> Path:
        return self.objects_dir / blob_hash
