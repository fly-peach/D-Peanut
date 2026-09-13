"""Catalog data models — the Dataset contracts frozen at end of N1.

Addressability contract: everything upstream (canvas bindings in N2, AI tools in N3)
refers to data through `DatasetRef{dataset_id, name, revision}` — never raw paths.
revision is a content fingerprint: file=mtime+size, folder=tree fingerprint, sql=schema hash;
bumping revision marks the cached profile outdated (scan.py owns the rules).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

DATA_FORMATS = ("csv", "parquet", "xlsx")


def new_dataset_id() -> str:
    return "ds_" + uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DatasetKind(StrEnum):
    file = "file"
    folder = "folder"
    sql = "sql"


class ScanStatus(StrEnum):
    pending = "pending"
    scanning = "scanning"
    ready = "ready"
    stale = "stale"
    failed = "failed"


class ProfileStatus(StrEnum):
    pending = "pending"
    profiling = "profiling"
    ready = "ready"
    outdated = "outdated"
    failed = "failed"


class DatasetRef(BaseModel):
    dataset_id: str
    name: str
    revision: str


# -- profiles ----------------------------------------------------------------


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    null_rate: float = 0.0
    cardinality: int | None = None
    num_range: tuple[float, float] | None = None
    time_min: str | None = None
    time_max: str | None = None
    top_values: list[Any] = Field(default_factory=list)
    sample_values: list[Any] = Field(default_factory=list)  # cleared when privacy_mode
    is_time: bool = False
    pk_hint: bool = False


class TableProfile(BaseModel):
    dataset_id: str
    revision: str
    row_count: int
    columns: list[ColumnProfile]
    profiled_at: str = Field(default_factory=_now)


# -- source metas (discriminated by Dataset.kind) -----------------------------


class FileMeta(BaseModel):
    path: str  # container-absolute, always jail-checked at registration
    format: Literal["csv", "parquet", "xlsx"]
    sheet: str | None = None  # xlsx multi-sheet: one FileDataset per sheet
    size_bytes: int = 0


class FolderMeta(BaseModel):
    root: str
    extensions: list[str] = Field(default_factory=lambda: list(DATA_FORMATS))
    fingerprint: str = ""
    child_ids: list[str] = Field(default_factory=list)


class SqlMeta(BaseModel):
    engine: Literal["sqlite", "postgres", "mysql"] = "sqlite"  # N1 reflects sqlite only
    conn_ref: str  # key into workspace secrets.json — plaintext never lives here
    db_schema: str = "main"
    table: str
    column_allowlist: list[str] | None = None


_META_BY_KIND: dict[DatasetKind, type[BaseModel]] = {
    DatasetKind.file: FileMeta,
    DatasetKind.folder: FolderMeta,
    DatasetKind.sql: SqlMeta,
}


class Dataset(BaseModel):
    id: str = Field(default_factory=new_dataset_id)
    name: str  # unique workspace-wide addressing name
    kind: DatasetKind
    meta: FileMeta | FolderMeta | SqlMeta
    revision: str = ""
    parent_id: str | None = None  # folder-expanded children point back
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy_mode: bool | None = None  # None → global default (settings)
    scan_status: ScanStatus = ScanStatus.pending
    profile_status: ProfileStatus = ProfileStatus.pending
    last_error: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _meta_matches_kind(self) -> Dataset:
        expected = _META_BY_KIND[self.kind]
        if not isinstance(self.meta, expected):
            raise ValueError(f"kind={self.kind} requires meta {expected.__name__}")
        return self

    @property
    def ref(self) -> DatasetRef:
        return DatasetRef(dataset_id=self.id, name=self.name, revision=self.revision)

    def touch(self) -> None:
        self.updated_at = _now()


class DatasetBrief(BaseModel):
    """Directory listing shape (kept compact for UI polling and AI browse)."""

    id: str
    name: str
    kind: DatasetKind
    revision: str
    parent_id: str | None = None
    scan_status: ScanStatus
    profile_status: ProfileStatus
    privacy_mode: bool | None
    row_count: int | None = None  # filled from profile cache when ready
