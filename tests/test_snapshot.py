"""Tests for snapshot management."""

import pytest

from branchfs.snapshot import Snapshot, SnapshotStore


@pytest.fixture
def snap_store(tmp_path):
    return SnapshotStore(tmp_path / "snapshots")


class TestSnapshotModel:
    def test_roundtrip(self):
        s = Snapshot("abc", "test", {"a.txt": "hash1"}, parent=None)
        d = s.to_dict()
        s2 = Snapshot.from_dict(d)
        assert s2.id == "abc"
        assert s2.name == "test"
        assert s2.tree == {"a.txt": "hash1"}

    def test_repr(self):
        s = Snapshot("abc", "test", {"a.txt": "h"})
        assert "abc" in repr(s) and "test" in repr(s)


class TestSnapshotStore:
    def test_create_and_load(self, snap_store):
        tree = {"file.py": "aaa", "lib/mod.py": "bbb"}
        snap = snap_store.create("v1", tree)
        loaded = snap_store.load(snap.id)
        assert loaded.name == "v1"
        assert loaded.tree == tree

    def test_create_with_parent(self, snap_store):
        s1 = snap_store.create("root", {"a": "1"})
        s2 = snap_store.create("child", {"a": "1", "b": "2"}, parent=s1.id)
        loaded = snap_store.load(s2.id)
        assert loaded.parent == s1.id

    def test_load_missing_raises(self, snap_store):
        with pytest.raises(FileNotFoundError):
            snap_store.load("nonexistent")

    def test_exists(self, snap_store):
        snap = snap_store.create("x", {})
        assert snap_store.exists(snap.id)
        assert not snap_store.exists("nope")

    def test_delete(self, snap_store):
        snap = snap_store.create("x", {})
        assert snap_store.delete(snap.id)
        assert not snap_store.exists(snap.id)
        assert not snap_store.delete(snap.id)

    def test_list_all(self, snap_store):
        snap_store.create("a", {})
        snap_store.create("b", {})
        snap_store.create("c", {})
        all_snaps = snap_store.list_all()
        assert len(all_snaps) == 3
        names = [s.name for s in all_snaps]
        assert "a" in names and "b" in names and "c" in names

    def test_list_all_empty(self, snap_store):
        assert snap_store.list_all() == []


class TestTreeDiff:
    def test_no_changes(self):
        tree = {"a": "1", "b": "2"}
        assert SnapshotStore.diff_trees(tree, tree) == {}

    def test_added_file(self):
        old = {"a": "1"}
        new = {"a": "1", "b": "2"}
        diff = SnapshotStore.diff_trees(old, new)
        assert diff == {"b": "added"}

    def test_deleted_file(self):
        old = {"a": "1", "b": "2"}
        new = {"a": "1"}
        diff = SnapshotStore.diff_trees(old, new)
        assert diff == {"b": "deleted"}

    def test_modified_file(self):
        old = {"a": "1"}
        new = {"a": "2"}
        diff = SnapshotStore.diff_trees(old, new)
        assert diff == {"a": "modified"}

    def test_mixed_changes(self):
        old = {"a": "1", "b": "2", "c": "3"}
        new = {"a": "1", "b": "999", "d": "4"}
        diff = SnapshotStore.diff_trees(old, new)
        assert diff == {"b": "modified", "c": "deleted", "d": "added"}

    def test_empty_to_populated(self):
        diff = SnapshotStore.diff_trees({}, {"a": "1"})
        assert diff == {"a": "added"}

    def test_populated_to_empty(self):
        diff = SnapshotStore.diff_trees({"a": "1"}, {})
        assert diff == {"a": "deleted"}
