"""Tests for the CLI module."""

import pytest

from branchfs.cli import main


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_text("world")
    return ws


class TestCLI:
    def test_init(self, workspace, capsys):
        main(["init", str(workspace)])
        out = capsys.readouterr().out
        assert "Initialized" in out

    def test_init_no_snapshot(self, workspace, capsys):
        main(["init", "--no-snapshot", str(workspace)])
        out = capsys.readouterr().out
        assert "Initialized" in out

    def test_snap(self, workspace, capsys):
        main(["init", str(workspace)])
        main(["snap", "v1", str(workspace)])
        out = capsys.readouterr().out
        assert "Snapshot created" in out

    def test_fork_and_checkout(self, workspace, capsys):
        main(["init", str(workspace)])
        capsys.readouterr()
        # Get snapshot id from status.
        from branchfs.api import BranchFS
        fs = BranchFS(workspace)
        snap_id = fs.active_snapshot()

        main(["fork", snap_id, str(workspace)])
        out = capsys.readouterr().out
        assert "Branch created" in out
        branch_id = out.strip().split(": ")[1]

        main(["checkout", branch_id, str(workspace)])
        out = capsys.readouterr().out
        assert "Checked out" in out

    def test_diff(self, workspace, capsys):
        main(["init", str(workspace)])
        from branchfs.api import BranchFS
        fs = BranchFS(workspace)
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)

        main(["diff", bid, str(workspace)])
        out = capsys.readouterr().out
        assert "no changes" in out

    def test_merge(self, workspace, capsys):
        main(["init", str(workspace)])
        from branchfs.api import BranchFS
        fs = BranchFS(workspace)
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)

        main(["merge", bid, str(workspace)])
        out = capsys.readouterr().out
        assert "Merged" in out

    def test_discard(self, workspace, capsys):
        main(["init", str(workspace)])
        from branchfs.api import BranchFS
        fs = BranchFS(workspace)
        snap_id = fs.active_snapshot()
        bid = fs.fork(snap_id)
        fs.checkout(bid)

        main(["discard", bid, str(workspace)])
        out = capsys.readouterr().out
        assert "discarded" in out

    def test_log(self, workspace, capsys):
        main(["init", str(workspace)])
        main(["log", str(workspace)])
        out = capsys.readouterr().out
        assert "init" in out

    def test_branches_empty(self, workspace, capsys):
        main(["init", str(workspace)])
        main(["branches", str(workspace)])
        out = capsys.readouterr().out
        assert "no branches" in out

    def test_snapshots(self, workspace, capsys):
        main(["init", str(workspace)])
        main(["snapshots", str(workspace)])
        out = capsys.readouterr().out
        assert "init" in out

    def test_status(self, workspace, capsys):
        main(["init", str(workspace)])
        main(["status", str(workspace)])
        out = capsys.readouterr().out
        assert "Workspace" in out

    def test_status_not_initialized(self, tmp_path, capsys):
        ws = tmp_path / "empty"
        ws.mkdir()
        main(["status", str(ws)])
        out = capsys.readouterr().out
        assert "Not initialized" in out

    def test_no_command(self, capsys):
        with pytest.raises(SystemExit):
            main([])
