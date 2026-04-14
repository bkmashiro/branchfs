"""Integration tests: full end-to-end workflows without FUSE."""

import pytest

from branchfs.api import BranchFS


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    (ws / "app.py").write_text("v1")
    (ws / "config.json").write_text('{"debug": false}')
    (ws / "lib").mkdir()
    (ws / "lib" / "core.py").write_text("class Core: pass")
    return ws


@pytest.fixture
def fs(workspace):
    bfs = BranchFS(workspace)
    bfs.init()
    return bfs


class TestFullWorkflow:
    """Simulates a complete AI agent workflow."""

    def test_explore_and_merge(self, fs, workspace):
        snap_id = fs.active_snapshot()

        # Fork a branch.
        bid = fs.fork(snap_id, name="experiment")
        fs.checkout(bid)

        # AI modifies files.
        (workspace / "app.py").write_text("v2 - improved")
        (workspace / "new_module.py").write_text("def new(): pass")

        # Sync and check diff.
        fs.sync_branch(bid)
        diff = fs.diff(bid)
        assert diff["app.py"] == "modified"
        assert diff["new_module.py"] == "added"

        # Merge.
        new_snap = fs.merge(bid)
        snap = fs.get_snapshot(new_snap)
        assert "app.py" in snap.tree
        assert "new_module.py" in snap.tree

    def test_explore_and_discard(self, fs, workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id, name="bad-idea")
        fs.checkout(bid)

        # AI breaks things.
        (workspace / "app.py").write_text("BROKEN CODE!")
        (workspace / "config.json").unlink()

        # Discard.
        fs.discard(bid)
        assert (workspace / "app.py").read_text() == "v1"
        assert (workspace / "config.json").exists()

    def test_parallel_branches(self, fs, workspace):
        snap_id = fs.active_snapshot()

        # Create two branches.
        b1 = fs.fork(snap_id, name="approach-A")
        b2 = fs.fork(snap_id, name="approach-B")

        # Work on branch A.
        fs.checkout(b1)
        (workspace / "app.py").write_text("approach A")
        fs.sync_branch(b1)

        # Work on branch B.
        fs.checkout(b2)
        assert (workspace / "app.py").read_text() == "v1"  # clean slate
        (workspace / "app.py").write_text("approach B")
        fs.sync_branch(b2)

        # Pick B.
        fs.discard(b1)
        new_snap = fs.merge(b2)
        snap = fs.get_snapshot(new_snap)
        content = fs.blob_store.get_bytes(snap.tree["app.py"])
        assert content == b"approach B"

    def test_snapshot_chain(self, fs, workspace):
        s1 = fs.active_snapshot()

        bid = fs.fork(s1)
        fs.checkout(bid)
        (workspace / "step1.txt").write_text("one")
        s2 = fs.merge(bid)

        bid2 = fs.fork(s2)
        fs.checkout(bid2)
        (workspace / "step2.txt").write_text("two")
        s3 = fs.merge(bid2)

        snap3 = fs.get_snapshot(s3)
        assert "step1.txt" in snap3.tree
        assert "step2.txt" in snap3.tree

    def test_context_manager_workflow(self, fs):
        snap_id = fs.active_snapshot()

        # Successful branch.
        with fs.branch_context(snap_id, name="good") as fb:
            (fb.workdir / "result.txt").write_text("success!")
            fb.merge()

        good_branch = fs.branch_store.load(fb.branch.id)
        assert "result.txt" in good_branch.modified

        # Failed branch (auto-discard).
        with fs.branch_context(snap_id, name="bad") as fb:
            bad_id = fb.branch.id
            (fb.workdir / "junk.txt").write_text("garbage")
        assert not fs.branch_store.exists(bad_id)

    def test_delete_file_in_branch(self, fs, workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (workspace / "lib" / "core.py").unlink()
        fs.sync_branch(bid)
        diff = fs.diff(bid)
        assert diff["lib/core.py"] == "deleted"

    def test_add_nested_directory(self, fs, workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (workspace / "deep" / "nested").mkdir(parents=True)
        (workspace / "deep" / "nested" / "file.txt").write_text("deep")
        fs.sync_branch(bid)
        diff = fs.diff(bid)
        assert "deep/nested/file.txt" in diff

    def test_log_with_branches(self, fs):
        snap_id = fs.active_snapshot()
        fs.fork(snap_id, name="alpha")
        fs.fork(snap_id, name="beta")
        log = fs.log()
        assert "alpha" in log
        assert "beta" in log
        assert "init" in log

    def test_multiple_merges(self, fs, workspace):
        snap_id = fs.active_snapshot()

        for i in range(3):
            bid = fs.fork(snap_id, name=f"iter-{i}")
            fs.checkout(bid)
            (workspace / f"file_{i}.txt").write_text(f"content {i}")
            snap_id = fs.merge(bid)

        final = fs.get_snapshot(snap_id)
        assert "file_0.txt" in final.tree
        assert "file_1.txt" in final.tree
        assert "file_2.txt" in final.tree

    def test_binary_files(self, fs, workspace):
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)
        (workspace / "data.bin").write_bytes(bytes(range(256)))
        fs.sync_branch(bid)
        new_snap = fs.merge(bid)
        snap = fs.get_snapshot(new_snap)
        content = fs.blob_store.get_bytes(snap.tree["data.bin"])
        assert content == bytes(range(256))


class TestEdgeCases:
    def test_empty_workspace_init(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        bfs = BranchFS(ws)
        snap_id = bfs.init()
        assert snap_id is None

    def test_fork_from_empty_snapshot(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        bfs = BranchFS(ws)
        bfs.init(take_snapshot=False)
        # Create an empty snapshot manually.
        snap = bfs.snapshot_store.create("empty", {})
        bid = bfs.fork(snap.id)
        bfs.checkout(bid)
        # Should have an empty workspace (except .branchfs).
        non_meta = [p for p in ws.iterdir() if p.name != ".branchfs"]
        assert len(non_meta) == 0

    def test_large_number_of_files(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        for i in range(100):
            (ws / f"file_{i:03d}.txt").write_text(f"content {i}")
        bfs = BranchFS(ws)
        snap_id = bfs.init()
        snap = bfs.get_snapshot(snap_id)
        assert len(snap.tree) == 100
