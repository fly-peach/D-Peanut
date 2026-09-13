"""Folder scan: extension filter, symlink skip, fingerprint diff semantics (tasks 2.2)."""

import os
import time

import pytest

from data_agent.catalog.scan import diff_entries, scan_tree, tree_fingerprint


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "a.csv").write_text("x\n1\n")
    (root / "b.csv").write_text("x\n2\n")
    (root / "sub" / "c.parquet").write_bytes(b"parquet-ish")
    (root / "notes.txt").write_text("ignored")
    (root / "noext").write_text("ignored")
    return root


def test_scan_filters_sorted_rel_paths(tree):
    entries = scan_tree(tree)
    assert [rel for rel, _ in entries] == ["a.csv", "b.csv", "sub/c.parquet"]


def test_extension_narrowing(tree):
    assert [rel for rel, _ in scan_tree(tree, ["csv"])] == ["a.csv", "b.csv"]


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_symlinks_skipped(tree):
    outside = tree.parent / "elsewhere.csv"
    outside.write_text("x\n9\n")
    link_file = tree / "link.csv"
    link_dir = tree / "linkdir"
    link_file.symlink_to(outside)
    link_dir.symlink_to(tree.parent, target_is_directory=True)
    rels = [rel for rel, _ in scan_tree(tree)]
    assert "link.csv" not in rels
    assert not any(r.startswith("linkdir/") for r in rels)


def test_fingerprint_stable_and_content_sensitive(tree):
    e1 = scan_tree(tree)
    assert tree_fingerprint(e1) == tree_fingerprint(sorted(reversed(e1)))
    time.sleep(1.05)
    (tree / "a.csv").write_text("x\n1\n2\n3\n")
    e2 = scan_tree(tree)
    assert tree_fingerprint(e1) != tree_fingerprint(e2)


def test_diff_entries_added_changed_removed():
    old = {"a.csv": "100-2", "b.csv": "100-2", "gone.csv": "100-2"}
    new = [("a.csv", "100-2"), ("b.csv", "200-9"), ("new.csv", "50-1")]
    changed, removed = diff_entries(old, new)
    assert dict(changed) == {"b.csv": "200-9", "new.csv": "50-1"}
    assert removed == ["gone.csv"]
