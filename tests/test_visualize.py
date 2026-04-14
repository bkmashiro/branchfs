"""Tests for ASCII visualization."""

import pytest

from branchfs.branch import DELETED_SENTINEL, Branch
from branchfs.snapshot import Snapshot
from branchfs.visualize import build_log, format_diff


class TestBuildLog:
    def test_empty(self):
        assert build_log([], []) == "(no snapshots)"

    def test_single_snapshot(self):
        s = Snapshot("abc", "root", {"a": "1"})
        out = build_log([s], [])
        assert "abc" in out
        assert "root" in out
        assert "1 files" in out

    def test_snapshot_with_branches(self):
        s = Snapshot("s1", "base", {"a": "1", "b": "2"})
        b = Branch("b1", "feature", "s1", modified={"c": "3"})
        out = build_log([s], [b])
        assert "feature" in out
        assert "b1" in out

    def test_active_branch_marker(self):
        s = Snapshot("s1", "base", {})
        b = Branch("b1", "active-one", "s1")
        out = build_log([s], [b], active_branch="b1")
        assert "<- active" in out

    def test_parent_child_snapshots(self):
        s1 = Snapshot("s1", "root", {"a": "1"})
        s2 = Snapshot("s2", "child", {"a": "1", "b": "2"}, parent="s1")
        out = build_log([s1, s2], [])
        assert "root" in out
        assert "child" in out

    def test_branch_with_deletions(self):
        s = Snapshot("s1", "base", {"a": "1"})
        b = Branch("b1", "pruner", "s1", modified={"a": DELETED_SENTINEL})
        out = build_log([s], [b])
        assert "-1" in out


class TestFormatDiff:
    def test_no_changes(self):
        assert format_diff({}) == "(no changes)"

    def test_added(self):
        out = format_diff({"new.txt": "added"})
        assert "+ new.txt" in out

    def test_modified(self):
        out = format_diff({"mod.txt": "modified"})
        assert "~ mod.txt" in out

    def test_deleted(self):
        out = format_diff({"old.txt": "deleted"})
        assert "- old.txt" in out

    def test_sorted_output(self):
        changes = {"c.txt": "added", "a.txt": "deleted", "b.txt": "modified"}
        out = format_diff(changes)
        lines = out.strip().split("\n")
        paths = [l.strip().split()[-1] for l in lines]
        assert paths == ["a.txt", "b.txt", "c.txt"]
