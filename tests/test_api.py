"""Tests for the high-level BranchFS API (fallback mode)."""

import pytest

from branchfs.api import BranchFS
from branchfs.branch import DELETED_SENTINEL


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def populated_workspace(workspace):
    (workspace / "main.py").write_text("print('hello')")
    (workspace / "lib").mkdir()
    (workspace / "lib" / "utils.py").write_text("def helper(): pass")
    return workspace


@pytest.fixture
def fs(populated_workspace):
    bfs = BranchFS(populated_workspace)
    bfs.init()
    return bfs


class TestInit:
    def test_init_creates_meta(self, workspace):
        bfs = BranchFS(workspace)
        bfs.init()
        assert bfs.is_initialized
        assert (workspace / ".branchfs" / "meta.json").exists()

    def test_init_empty_workspace_no_snapshot(self, workspace):
        bfs = BranchFS(workspace)
        snap_id = bfs.init()
        assert snap_id is None

    def test_init_with_files_creates_snapshot(self, populated_workspace):
        bfs = BranchFS(populated_workspace)
        snap_id = bfs.init()
        assert snap_id is not None
        snap = bfs.get_snapshot(snap_id)
        assert "main.py" in snap.tree
        assert "lib/utils.py" in snap.tree

    def test_init_no_snapshot_flag(self, populated_workspace):
        bfs = BranchFS(populated_workspace)
        snap_id = bfs.init(take_snapshot=False)
        assert snap_id is None

    def test_double_init_ok(self, populated_workspace):
        bfs = BranchFS(populated_workspace)
        bfs.init()
        bfs.init()  # should not crash


class TestSnapshot:
    def test_snapshot_from_workspace(self, fs, populated_workspace):
        snap_id = fs.snapshot("v2")
        snap = fs.get_snapshot(snap_id)
        assert snap.name == "v2"
        assert "main.py" in snap.tree

    def test_snapshot_chain(self, fs):
        s1 = fs.snapshot("first")
        s2 = fs.snapshot("second")
        snap2 = fs.get_snapshot(s2)
        assert snap2.parent == s1

    def test_list_snapshots(self, fs):
        fs.snapshot("a")
        fs.snapshot("b")
        snaps = fs.list_snapshots()
        # init snapshot + 2 more
        assert len(snaps) >= 3

    def test_active_snapshot(self, fs):
        s = fs.snapshot("check")
        assert fs.active_snapshot() == s


class TestForkAndCheckout:
    def test_fork(self, fs):
        snap_id = fs.active_snapshot()
        branch_id = fs.fork(snap_id)
        assert branch_id is not None
        branch = fs.get_branch(branch_id)
        assert branch.base_snapshot == snap_id

    def test_fork_nonexistent_snapshot_raises(self, fs):
        with pytest.raises(ValueError):
            fs.fork("nonexistent")

    def test_fork_with_name(self, fs):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id, name="experiment")
        branch = fs.get_branch(bid)
        assert branch.name == "experiment"

    def test_checkout_materializes(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        assert (populated_workspace / "main.py").exists()
        assert fs.active_branch() == bid

    def test_checkout_snapshot(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        fs.checkout_snapshot(snap_id)
        assert fs.active_branch() is None
        assert fs.active_snapshot() == snap_id
        assert (populated_workspace / "main.py").exists()


class TestDiffSyncMerge:
    def test_diff_empty_branch(self, fs):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        diff = fs.diff(bid)
        assert diff == {}

    def test_sync_picks_up_changes(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (populated_workspace / "new.txt").write_text("added")
        fs.sync_branch(bid)
        diff = fs.diff(bid)
        assert "new.txt" in diff
        assert diff["new.txt"] == "added"

    def test_sync_no_branch_raises(self, fs):
        with pytest.raises(RuntimeError):
            fs.sync_branch()

    def test_merge_creates_snapshot(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (populated_workspace / "merged.txt").write_text("yes")
        new_snap = fs.merge(bid)
        snap = fs.get_snapshot(new_snap)
        assert "merged.txt" in snap.tree
        assert fs.active_branch() is None

    def test_merge_custom_name(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        new_snap = fs.merge(bid, snapshot_name="custom-merge")
        snap = fs.get_snapshot(new_snap)
        assert snap.name == "custom-merge"

    def test_merge_deletes_branch(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        fs.merge(bid)
        assert not fs.branch_store.exists(bid)


class TestDiscard:
    def test_discard_restores_snapshot(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (populated_workspace / "main.py").write_text("corrupted!")
        fs.discard(bid)
        assert fs.active_branch() is None
        # Workspace restored.
        assert (populated_workspace / "main.py").read_text() == "print('hello')"

    def test_discard_removes_branch(self, fs):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        fs.discard(bid)
        assert not fs.branch_store.exists(bid)

    def test_discard_non_active_branch(self, fs):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        # Don't checkout, just discard.
        fs.discard(bid)
        assert not fs.branch_store.exists(bid)


class TestBranchContext:
    def test_context_merge(self, fs):
        snap_id = fs.active_snapshot()
        with fs.branch_context(snap_id, name="ctx-test") as fb:
            (fb.workdir / "ctx_file.txt").write_text("context data")
            fb.merge()
        branch = fs.branch_store.load(fb.branch.id)
        assert "ctx_file.txt" in branch.modified

    def test_context_discard(self, fs):
        snap_id = fs.active_snapshot()
        with fs.branch_context(snap_id) as fb:
            branch_id = fb.branch.id
            (fb.workdir / "temp.txt").write_text("discard me")
        assert not fs.branch_store.exists(branch_id)


class TestLog:
    def test_log_output(self, fs):
        snap_id = fs.active_snapshot()
        fs.fork(snap_id, name="feature-a")
        output = fs.log()
        assert "init" in output
        assert "feature-a" in output

    def test_diff_formatted(self, fs, populated_workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (populated_workspace / "new.txt").write_text("x")
        fs.sync_branch(bid)
        formatted = fs.diff_formatted(bid)
        assert "new.txt" in formatted


class TestListBranches:
    def test_list_branches(self, fs):
        snap_id = fs.active_snapshot()
        fs.fork(snap_id, name="b1")
        fs.fork(snap_id, name="b2")
        branches = fs.list_branches()
        assert len(branches) == 2
        names = {b.name for b in branches}
        assert names == {"b1", "b2"}
