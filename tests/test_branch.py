"""Tests for branch management."""

import pytest

from branchfs.branch import DELETED_SENTINEL, Branch, BranchStore


@pytest.fixture
def branch_store(tmp_path):
    return BranchStore(tmp_path / "branches")


class TestBranchModel:
    def test_roundtrip(self):
        b = Branch("id1", "main", "snap1", modified={"a": "h1"})
        d = b.to_dict()
        b2 = Branch.from_dict(d)
        assert b2.id == "id1"
        assert b2.name == "main"
        assert b2.base_snapshot == "snap1"
        assert b2.modified == {"a": "h1"}

    def test_repr(self):
        b = Branch("id1", "feat", "snap1")
        r = repr(b)
        assert "id1" in r and "feat" in r

    def test_effective_tree_raises(self):
        b = Branch("id1", "x", "snap1")
        with pytest.raises(NotImplementedError):
            _ = b.effective_tree


class TestBranchStore:
    def test_create_and_load(self, branch_store):
        b = branch_store.create("snap1", name="feature")
        loaded = branch_store.load(b.id)
        assert loaded.name == "feature"
        assert loaded.base_snapshot == "snap1"
        assert loaded.modified == {}

    def test_create_auto_name(self, branch_store):
        b = branch_store.create("snap1")
        assert b.name.startswith("branch-")

    def test_save_update(self, branch_store):
        b = branch_store.create("snap1", name="dev")
        b.modified["new.txt"] = "hash123"
        branch_store.save(b)
        loaded = branch_store.load(b.id)
        assert loaded.modified == {"new.txt": "hash123"}

    def test_exists(self, branch_store):
        b = branch_store.create("snap1")
        assert branch_store.exists(b.id)
        assert not branch_store.exists("bogus")

    def test_delete(self, branch_store):
        b = branch_store.create("snap1")
        assert branch_store.delete(b.id)
        assert not branch_store.exists(b.id)
        assert not branch_store.delete(b.id)

    def test_list_all(self, branch_store):
        branch_store.create("s1", name="a")
        branch_store.create("s1", name="b")
        all_b = branch_store.list_all()
        assert len(all_b) == 2

    def test_list_all_empty(self, branch_store):
        assert branch_store.list_all() == []


class TestEffectiveTree:
    def test_no_modifications(self):
        snap_tree = {"a": "1", "b": "2"}
        tree = BranchStore.effective_tree(snap_tree, {})
        assert tree == snap_tree

    def test_added_file(self):
        snap_tree = {"a": "1"}
        modified = {"b": "2"}
        tree = BranchStore.effective_tree(snap_tree, modified)
        assert tree == {"a": "1", "b": "2"}

    def test_modified_file(self):
        snap_tree = {"a": "1"}
        modified = {"a": "999"}
        tree = BranchStore.effective_tree(snap_tree, modified)
        assert tree == {"a": "999"}

    def test_deleted_file(self):
        snap_tree = {"a": "1", "b": "2"}
        modified = {"a": DELETED_SENTINEL}
        tree = BranchStore.effective_tree(snap_tree, modified)
        assert tree == {"b": "2"}

    def test_mixed(self):
        snap_tree = {"a": "1", "b": "2", "c": "3"}
        modified = {"a": DELETED_SENTINEL, "b": "new", "d": "4"}
        tree = BranchStore.effective_tree(snap_tree, modified)
        assert tree == {"b": "new", "c": "3", "d": "4"}

    def test_delete_nonexistent_is_noop(self):
        tree = BranchStore.effective_tree({"a": "1"}, {"z": DELETED_SENTINEL})
        assert tree == {"a": "1"}


class TestBranchDiff:
    def test_no_changes(self):
        assert BranchStore.diff({"a": "1"}, {}) == {}

    def test_added(self):
        diff = BranchStore.diff({"a": "1"}, {"b": "2"})
        assert diff == {"b": "added"}

    def test_modified(self):
        diff = BranchStore.diff({"a": "1"}, {"a": "2"})
        assert diff == {"a": "modified"}

    def test_same_hash_no_change(self):
        diff = BranchStore.diff({"a": "1"}, {"a": "1"})
        assert diff == {}

    def test_deleted(self):
        diff = BranchStore.diff({"a": "1"}, {"a": DELETED_SENTINEL})
        assert diff == {"a": "deleted"}

    def test_delete_nonexistent(self):
        diff = BranchStore.diff({}, {"z": DELETED_SENTINEL})
        assert diff == {}
