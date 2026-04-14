"""Tests for fallback mode (no FUSE required)."""

import pytest

from branchfs.branch import DELETED_SENTINEL, BranchStore
from branchfs.fallback import FallbackBranch, FallbackWorkspace
from branchfs.snapshot import SnapshotStore
from branchfs.store import BlobStore


@pytest.fixture
def stores(tmp_path):
    blob = BlobStore(tmp_path / "objects")
    snap = SnapshotStore(tmp_path / "snapshots")
    branch = BranchStore(tmp_path / "branches")
    return blob, snap, branch


@pytest.fixture
def baseline_snapshot(stores):
    blob, snap_store, _ = stores
    h1 = blob.put_bytes(b"content A")
    h2 = blob.put_bytes(b"content B")
    tree = {"file_a.txt": h1, "dir/file_b.txt": h2}
    snap = snap_store.create("baseline", tree)
    return snap


class TestFallbackWorkspace:
    def test_materialize(self, stores, baseline_snapshot, tmp_path):
        blob, snap_store, branch_store = stores
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        ws = FallbackWorkspace(blob, snap_store, branch_store, ws_dir)
        ws.materialize(baseline_snapshot)
        assert (ws_dir / "file_a.txt").read_bytes() == b"content A"
        assert (ws_dir / "dir" / "file_b.txt").read_bytes() == b"content B"

    def test_materialize_with_branch(self, stores, baseline_snapshot, tmp_path):
        blob, snap_store, branch_store = stores
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        ws = FallbackWorkspace(blob, snap_store, branch_store, ws_dir)

        branch = branch_store.create(baseline_snapshot.id, name="test-branch")
        new_hash = blob.put_bytes(b"modified A")
        branch.modified = {
            "file_a.txt": new_hash,
            "dir/file_b.txt": DELETED_SENTINEL,
            "new.txt": blob.put_bytes(b"brand new"),
        }
        branch_store.save(branch)

        ws.materialize(baseline_snapshot, branch)
        assert (ws_dir / "file_a.txt").read_bytes() == b"modified A"
        assert not (ws_dir / "dir" / "file_b.txt").exists()
        assert (ws_dir / "new.txt").read_bytes() == b"brand new"

    def test_scan(self, stores, tmp_path):
        blob, snap_store, branch_store = stores
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "hello.txt").write_text("hi")
        (ws_dir / "sub").mkdir()
        (ws_dir / "sub" / "deep.txt").write_text("deep")

        ws = FallbackWorkspace(blob, snap_store, branch_store, ws_dir)
        tree = ws.scan()
        assert "hello.txt" in tree
        assert "sub/deep.txt" in tree
        # Verify blobs exist.
        for h in tree.values():
            assert blob.has(h)

    def test_scan_skips_branchfs_dir(self, stores, tmp_path):
        blob, snap_store, branch_store = stores
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / ".branchfs").mkdir()
        (ws_dir / ".branchfs" / "meta.json").write_text("{}")
        (ws_dir / "real.txt").write_text("yes")

        ws = FallbackWorkspace(blob, snap_store, branch_store, ws_dir)
        tree = ws.scan()
        assert "real.txt" in tree
        assert ".branchfs/meta.json" not in tree

    def test_compute_modifications(self, stores):
        blob, snap_store, branch_store = stores
        ws = FallbackWorkspace(blob, snap_store, branch_store, "/dummy")

        snap_tree = {"a": "h1", "b": "h2", "c": "h3"}
        current = {"a": "h1", "b": "h_new", "d": "h4"}
        mods = ws.compute_branch_modifications(snap_tree, current)
        assert mods["b"] == "h_new"  # modified
        assert mods["c"] == DELETED_SENTINEL  # deleted
        assert mods["d"] == "h4"  # added
        assert "a" not in mods  # unchanged


class TestFallbackBranch:
    def test_context_creates_workdir(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        with FallbackBranch(blob, snap_store, branch_store, baseline_snapshot.id) as fb:
            assert fb.workdir is not None
            assert fb.workdir.exists()
            assert (fb.workdir / "file_a.txt").read_bytes() == b"content A"

    def test_discard_on_exit(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        with FallbackBranch(blob, snap_store, branch_store, baseline_snapshot.id) as fb:
            branch_id = fb.branch.id
            (fb.workdir / "new.txt").write_text("temp")
        # Branch should be deleted after exit without merge.
        assert not branch_store.exists(branch_id)

    def test_merge_preserves_branch(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        with FallbackBranch(blob, snap_store, branch_store, baseline_snapshot.id) as fb:
            (fb.workdir / "added.txt").write_text("new file")
            branch_id = fb.merge()
        # Branch still exists after merge.
        assert branch_store.exists(branch_id)
        branch = branch_store.load(branch_id)
        assert "added.txt" in branch.modified

    def test_merge_records_modifications(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        with FallbackBranch(blob, snap_store, branch_store, baseline_snapshot.id) as fb:
            # Modify existing.
            (fb.workdir / "file_a.txt").write_text("changed!")
            # Delete.
            (fb.workdir / "dir" / "file_b.txt").unlink()
            # Add.
            (fb.workdir / "extra.py").write_text("print('hi')")
            fb.merge()
            mods = fb.branch.modified
            assert mods["file_a.txt"] != baseline_snapshot.tree["file_a.txt"]
            assert mods["dir/file_b.txt"] == DELETED_SENTINEL
            assert "extra.py" in mods

    def test_custom_branch_name(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        with FallbackBranch(
            blob, snap_store, branch_store, baseline_snapshot.id, branch_name="my-branch"
        ) as fb:
            assert fb.branch.name == "my-branch"
            fb.merge()

    def test_exception_discards(self, stores, baseline_snapshot):
        blob, snap_store, branch_store = stores
        try:
            with FallbackBranch(blob, snap_store, branch_store, baseline_snapshot.id) as fb:
                branch_id = fb.branch.id
                raise ValueError("oops")
        except ValueError:
            pass
        assert not branch_store.exists(branch_id)
