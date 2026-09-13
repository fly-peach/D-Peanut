"""Folder tree scan + fingerprint diff (N1 decision 3).

Rules: only files whose suffix is in `extensions`; symlinks (dir or file) are NEVER
followed nor listed; stable ordering (sorted rel paths, "/" separator) so the tree
fingerprint is platform-independent.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .models import DATA_FORMATS
from .sources.file import file_revision

Entry = tuple[str, str]  # (relpath, revision)


def scan_tree(root: str | Path, extensions: list[str] | None = None) -> list[Entry]:
    exts = set(extensions or DATA_FORMATS)
    root = Path(root)
    out: list[Entry] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # prune symlinked dirs (os.walk with followlinks=False already won't descend,
        # but they appear in dirnames; drop to be explicit)
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if os.path.islink(full):
                continue
            suffix = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if suffix not in exts:
                continue
            rel = Path(full).relative_to(root).as_posix()
            out.append((rel, file_revision(full)))
    return sorted(out)


def tree_fingerprint(entries: list[Entry]) -> str:
    h = hashlib.sha1()
    for rel, rev in entries:
        h.update(f"{rel}:{rev}\n".encode())
    return h.hexdigest()


def diff_entries(
    old: dict[str, str], new: list[Entry]
) -> tuple[list[Entry], list[str]]:
    """Return (added_or_changed, removed_relpaths); unchanged files appear in neither."""
    new_map = dict(new)
    changed = [(rel, rev) for rel, rev in new if old.get(rel) != rev]
    removed = [rel for rel in old if rel not in new_map]
    return changed, removed
