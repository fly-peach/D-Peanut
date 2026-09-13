"""Catalog registry: sqlite-backed Dataset index + profile cache (workspace/index.db).

At N1 the index IS the source of truth for datasets (no FS artifacts yet — the
content_hash self-healing story belongs to N2 assets, design decision 1).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..storage import connect
from .models import Dataset, DatasetBrief, DatasetKind, ScanStatus, TableProfile


class DuplicateNameError(ValueError):
    pass


class NotFoundError(KeyError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  parent_id TEXT,
  revision TEXT NOT NULL DEFAULT '',
  scan_status TEXT NOT NULL,
  profile_status TEXT NOT NULL,
  privacy_mode INTEGER,
  description TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  last_error TEXT,
  meta_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_datasets_parent ON datasets(parent_id);
CREATE TABLE IF NOT EXISTS profiles(
  dataset_id TEXT NOT NULL,
  revision TEXT NOT NULL,
  privacy INTEGER NOT NULL,
  profile_json TEXT NOT NULL,
  profiled_at TEXT NOT NULL,
  PRIMARY KEY (dataset_id, revision, privacy)
);
"""


def _to_dataset(row: sqlite3.Row) -> Dataset:
    data = dict(row)
    meta = data.pop("meta_json")
    privacy = data.pop("privacy_mode")
    tags = data.pop("tags")
    data["meta"] = json.loads(meta)
    data["tags"] = json.loads(tags)
    data["privacy_mode"] = None if privacy is None else bool(privacy)
    kind = DatasetKind(data["kind"])
    if kind is DatasetKind.file:
        from .models import FileMeta

        data["meta"] = FileMeta(**data["meta"])
    elif kind is DatasetKind.folder:
        from .models import FolderMeta

        data["meta"] = FolderMeta(**data["meta"])
    else:
        from .models import SqlMeta

        data["meta"] = SqlMeta(**data["meta"])
    return Dataset(**data)


class CatalogRepository:
    def __init__(self, index_db: Path) -> None:
        self._conn = connect(index_db)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- datasets --------------------------------------------------------------

    def insert(self, ds: Dataset) -> Dataset:
        try:
            self._conn.execute(
                "INSERT INTO datasets(id,name,kind,parent_id,revision,scan_status,profile_status,"
                "privacy_mode,description,tags,last_error,meta_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ds.id,
                    ds.name,
                    ds.kind.value,
                    ds.parent_id,
                    ds.revision,
                    ds.scan_status.value,
                    ds.profile_status.value,
                    None if ds.privacy_mode is None else int(ds.privacy_mode),
                    ds.description,
                    json.dumps(ds.tags, ensure_ascii=False),
                    ds.last_error,
                    ds.meta.model_dump_json(),
                    ds.created_at,
                    ds.updated_at,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateNameError(f"dataset name {ds.name!r} already exists") from e
        return ds

    def get(self, dataset_id: str) -> Dataset:
        row = self._conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if row is None:
            raise NotFoundError(dataset_id)
        return _to_dataset(row)

    def get_by_name(self, name: str) -> Dataset:
        row = self._conn.execute("SELECT * FROM datasets WHERE name=?", (name,)).fetchone()
        if row is None:
            raise NotFoundError(name)
        return _to_dataset(row)

    def exists_name(self, name: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM datasets WHERE name=?", (name,)).fetchone()
            is not None
        )

    def list(self, kind: DatasetKind | None = None) -> list[DatasetBrief]:
        sql = "SELECT * FROM datasets"
        args: tuple = ()
        if kind is not None:
            sql += " WHERE kind=?"
            args = (kind.value,)
        rows = self._conn.execute(sql + " ORDER BY name", args).fetchall()
        out = []
        for r in rows:
            ds = _to_dataset(r)
            prof = self.get_profile(ds.id, ds.revision)
            out.append(
                DatasetBrief(
                    id=ds.id,
                    name=ds.name,
                    kind=ds.kind,
                    revision=ds.revision,
                    parent_id=ds.parent_id,
                    scan_status=ds.scan_status,
                    profile_status=ds.profile_status,
                    privacy_mode=ds.privacy_mode,
                    row_count=prof.row_count if prof else None,
                )
            )
        return out

    def children(self, folder_id: str) -> list[Dataset]:
        rows = self._conn.execute(
            "SELECT * FROM datasets WHERE parent_id=? ORDER BY name", (folder_id,)
        ).fetchall()
        return [_to_dataset(r) for r in rows]

    def referrers(self, dataset_id: str) -> list[str]:
        """Names of folder parents / (N2 hook) assets referencing this dataset. N1: folders only."""
        ds = self.get(dataset_id)
        refs: list[str] = []
        if ds.parent_id:
            refs.append(self.get(ds.parent_id).name)
        return refs

    def update(self, ds: Dataset) -> Dataset:
        ds.touch()
        try:
            cur = self._conn.execute(
                "UPDATE datasets SET name=?,kind=?,parent_id=?,revision=?,scan_status=?,"
                "profile_status=?,privacy_mode=?,description=?,tags=?,last_error=?,meta_json=?,"
                "updated_at=? WHERE id=?",
                (
                    ds.name,
                    ds.kind.value,
                    ds.parent_id,
                    ds.revision,
                    ds.scan_status.value,
                    ds.profile_status.value,
                    None if ds.privacy_mode is None else int(ds.privacy_mode),
                    ds.description,
                    json.dumps(ds.tags, ensure_ascii=False),
                    ds.last_error,
                    ds.meta.model_dump_json(),
                    ds.updated_at,
                    ds.id,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateNameError(f"dataset name {ds.name!r} already exists") from e
        if cur.rowcount == 0:
            raise NotFoundError(ds.id)
        return ds

    def delete(self, dataset_id: str) -> None:
        cur = self._conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
        self._conn.execute("DELETE FROM profiles WHERE dataset_id=?", (dataset_id,))
        self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError(dataset_id)

    def mark_scan_status(
        self, dataset_id: str, status: ScanStatus, error: str | None = None
    ) -> Dataset:
        ds = self.get(dataset_id)
        ds.scan_status = status
        ds.last_error = error
        return self.update(ds)

    # -- profile cache (keyed by dataset_id + revision + privacy) ---------------

    def put_profile(self, ds: Dataset, profile: TableProfile) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO profiles(dataset_id,revision,privacy,profile_json,profiled_at)"
            " VALUES(?,?,?,?,?)",
            (
                ds.id,
                profile.revision,
                int(bool(_effective_privacy(ds))),
                profile.model_dump_json(),
                profile.profiled_at,
            ),
        )
        self._conn.commit()

    def get_profile(self, dataset_id: str, revision: str) -> TableProfile | None:
        ds = self.get(dataset_id)
        row = self._conn.execute(
            "SELECT profile_json FROM profiles WHERE dataset_id=? AND revision=? AND privacy=?",
            (dataset_id, revision, int(bool(_effective_privacy(ds)))),
        ).fetchone()
        return TableProfile.model_validate_json(row["profile_json"]) if row else None

    def rebuild_index(self, reseed: Any | None = None) -> None:
        """Wipe and re-register from sources. N1 scope: sqlite datasets are the truth,
        so rebuild = re-scan every folder root (reseed callback runs the pipeline);
        single-file/sql rows that lost their source are marked failed."""
        orphans = 0
        for brief in self.list():
            ds = self.get(brief.id)
            if ds.kind is DatasetKind.file:
                from pathlib import Path as _P

                if not _P(ds.meta.path).exists():
                    ds.scan_status = ScanStatus.failed
                    ds.last_error = "source file missing at rebuild"
                    self.update(ds)
                    orphans += 1
        if reseed is not None:
            reseed(self)
        return orphans


def _effective_privacy(ds: Dataset) -> bool | None:
    return ds.privacy_mode
