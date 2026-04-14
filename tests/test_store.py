"""Tests for the content-addressable blob store."""

import os
import tempfile
from pathlib import Path

import pytest

from branchfs.store import BlobStore


@pytest.fixture
def store(tmp_path):
    return BlobStore(tmp_path / "objects")


@pytest.fixture
def sample_file(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("hello world")
    return p


class TestBlobStoreHash:
    def test_hash_bytes_deterministic(self, store):
        h1 = store.hash_bytes(b"test data")
        h2 = store.hash_bytes(b"test data")
        assert h1 == h2

    def test_hash_bytes_different_for_different_content(self, store):
        h1 = store.hash_bytes(b"data A")
        h2 = store.hash_bytes(b"data B")
        assert h1 != h2

    def test_hash_bytes_is_sha256(self, store):
        h = store.hash_bytes(b"")
        assert len(h) == 64  # sha256 hex digest length

    def test_hash_file(self, store, sample_file):
        h = store.hash_file(sample_file)
        assert h == store.hash_bytes(sample_file.read_bytes())


class TestBlobStorePut:
    def test_put_bytes_returns_hash(self, store):
        h = store.put_bytes(b"data")
        assert isinstance(h, str) and len(h) == 64

    def test_put_bytes_creates_file(self, store):
        h = store.put_bytes(b"data")
        assert (store.objects_dir / h).exists()

    def test_put_bytes_dedup(self, store):
        h1 = store.put_bytes(b"same content")
        h2 = store.put_bytes(b"same content")
        assert h1 == h2
        blobs = store.list_blobs()
        assert blobs.count(h1) == 1

    def test_put_file(self, store, sample_file):
        h = store.put_file(sample_file)
        assert store.has(h)
        assert store.get_bytes(h) == sample_file.read_bytes()

    def test_put_file_dedup(self, store, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical")
        f2.write_text("identical")
        h1 = store.put_file(f1)
        h2 = store.put_file(f2)
        assert h1 == h2


class TestBlobStoreGet:
    def test_get_bytes(self, store):
        h = store.put_bytes(b"payload")
        assert store.get_bytes(h) == b"payload"

    def test_get_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.get_bytes("nonexistent_hash")

    def test_extract_to(self, store, tmp_path):
        h = store.put_bytes(b"extract me")
        dest = tmp_path / "out" / "file.bin"
        store.extract_to(h, dest)
        assert dest.read_bytes() == b"extract me"

    def test_extract_creates_parent_dirs(self, store, tmp_path):
        h = store.put_bytes(b"deep")
        dest = tmp_path / "a" / "b" / "c" / "file"
        store.extract_to(h, dest)
        assert dest.exists()


class TestBlobStoreManagement:
    def test_has(self, store):
        h = store.put_bytes(b"x")
        assert store.has(h)
        assert not store.has("bogus")

    def test_delete(self, store):
        h = store.put_bytes(b"del")
        assert store.delete(h)
        assert not store.has(h)
        assert not store.delete(h)  # already gone

    def test_list_blobs(self, store):
        h1 = store.put_bytes(b"one")
        h2 = store.put_bytes(b"two")
        blobs = store.list_blobs()
        assert h1 in blobs
        assert h2 in blobs

    def test_size(self, store):
        store.put_bytes(b"12345")
        assert store.size >= 5

    def test_empty_store(self, store):
        assert store.list_blobs() == []
        assert store.size == 0


class TestBlobStoreBinaryData:
    def test_binary_roundtrip(self, store):
        data = bytes(range(256))
        h = store.put_bytes(data)
        assert store.get_bytes(h) == data

    def test_large_data(self, store):
        data = os.urandom(1 << 20)  # 1 MB
        h = store.put_bytes(data)
        assert store.get_bytes(h) == data
