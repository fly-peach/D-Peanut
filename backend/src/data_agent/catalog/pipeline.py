"""Catalog pipeline: registration + background scan/profile + rescan.

Shared entry point for FastAPI BackgroundTasks AND tests (design risk 2: tests call
run()/rescan() directly, never relying on the framework's background execution).
Per-child failures are isolated: one bad file marks that child failed, the batch
continues. All error strings pass through SecretsStore.redact before storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..settings import (
    PREVIEW_MAX_ROWS,
    PROFILE_SAMPLE_ROWS_DEFAULT,
    SettingsService,
    Workspace,
)
from .models import (
    DATA_FORMATS,
    Dataset,
    DatasetKind,
    FileMeta,
    FolderMeta,
    ProfileStatus,
    ScanStatus,
    SqlMeta,
)
from .profiler import profile_dataframe
from .registry import CatalogRepository, NotFoundError
from .sampler import effective_privacy
from .scan import diff_entries, scan_tree, tree_fingerprint
from .sources import sql as sql_source
from .sources.file import detect_format, file_revision, list_sheets

_ERR_MAX = 500


class RegisterError(ValueError):
    pass


class CatalogPipeline:
    def __init__(self, repo: CatalogRepository, settings: SettingsService, workspace: Workspace):
        self.repo = repo
        self.settings = settings
        self.ws = workspace

    # -- registration (sync, cheap) -------------------------------------------

    def register_file(self, raw_path: str, name: str | None = None,
                      privacy_mode: bool | None = None) -> list[Dataset]:
        path = self.ws.jail(raw_path)
        fmt = detect_format(path)
        if fmt is None:
            raise RegisterError(f"unsupported file format: {path.name}")
        if not path.is_file():
            raise RegisterError(f"not a file: {path}")
        base = name or path.name
        if fmt == "xlsx":
            sheets = list_sheets(path)
            if len(sheets) > 1:
                return [
                    self._insert(Dataset(name=f"{base}#{s}", kind=DatasetKind.file,
                                         privacy_mode=privacy_mode,
                                         meta=FileMeta(path=str(path), format="xlsx", sheet=s)))
                    for s in sheets
                ]
        ds = Dataset(name=base, kind=DatasetKind.file, privacy_mode=privacy_mode,
                     meta=FileMeta(path=str(path), format=fmt))
        return [self._insert(ds)]

    def register_folder(self, raw_root: str, name: str | None = None,
                        extensions: list[str] | None = None,
                        privacy_mode: bool | None = None) -> Dataset:
        root = self.ws.jail(raw_root)
        if not root.is_dir():
            raise RegisterError(f"not a directory: {root}")
        ds = Dataset(
            name=name or root.name, kind=DatasetKind.folder, privacy_mode=privacy_mode,
            meta=FolderMeta(root=str(root), extensions=list(extensions or DATA_FORMATS)),
        )
        return self._insert(ds)

    def register_sql(self, conn_target: str, table: str, name: str | None = None,
                     privacy_mode: bool | None = None) -> Dataset:
        """conn_target: sqlite file path. Stored as a secret; the Dataset only keeps conn_ref."""
        path = self.ws.jail(conn_target)
        if not path.is_file():
            raise RegisterError(f"sqlite file not found: {path}")
        label = name or f"{path.stem}.{table}"
        conn_ref = f"sql.{label}"
        self.settings.secrets.set(conn_ref, str(path))
        ds = Dataset(name=label, kind=DatasetKind.sql, privacy_mode=privacy_mode,
                     meta=SqlMeta(conn_ref=conn_ref, table=table))
        return self._insert(ds)

    def _insert(self, ds: Dataset) -> Dataset:
        self.repo.insert(ds)
        return ds

    # -- background preparation -------------------------------------------------

    def run(self, dataset_id: str) -> Dataset:
        ds = self.repo.get(dataset_id)
        try:
            if ds.kind is DatasetKind.file:
                self._prepare_file(ds)
            elif ds.kind is DatasetKind.folder:
                self._prepare_folder(ds)
            else:
                self._prepare_sql(ds)
        except Exception as e:  # noqa: BLE001 - batch isolation per design
            ds = self.repo.get(dataset_id)
            ds.scan_status = ScanStatus.failed
            ds.profile_status = ProfileStatus.failed
            ds.last_error = self.settings.secrets.redact(f"{type(e).__name__}: {e}")[:_ERR_MAX]
            self.repo.update(ds)
        return self.repo.get(dataset_id)

    def rescan(self, dataset_id: str) -> Dataset:
        """file: re-stat + re-profile if revision moved; folder: diff; sql: re-reflect."""
        return self.run(dataset_id)

    def _conn_target(self, ds: Dataset) -> str:
        target = self.settings.secrets.get(ds.meta.conn_ref)
        if not target:
            raise RegisterError(f"missing secret for conn_ref {ds.meta.conn_ref!r}")
        return target

    def _prepare_file(self, ds: Dataset) -> None:
        rev = file_revision(ds.meta.path)
        ds.revision = rev
        ds.scan_status = ScanStatus.ready
        if self.repo.get_profile(ds.id, rev) is not None:
            ds.profile_status = ProfileStatus.ready
            self.repo.update(ds)
            return
        self._profile_into(ds)

    def _prepare_folder(self, ds: Dataset) -> None:
        ds.scan_status = ScanStatus.scanning
        self.repo.update(ds)
        entries = scan_tree(ds.meta.root, ds.meta.extensions)
        ds.meta.fingerprint = tree_fingerprint(entries)
        existing = {c.name[len(ds.name) + 1:]: c.revision for c in self.repo.children(ds.id)}
        changed, removed = diff_entries(existing, entries)
        for rel in removed:
            try:
                child = self.repo.get_by_name(f"{ds.name}/{rel}")
            except NotFoundError:
                continue
            child.scan_status = ScanStatus.failed
            child.last_error = "source removed at rescan"
            self.repo.update(child)
        for rel, rev in changed:
            full = str(Path(ds.meta.root) / rel)
            child_name = f"{ds.name}/{rel}"
            try:
                child = self.repo.get_by_name(child_name)
                if child.revision == rev and child.scan_status is ScanStatus.ready:
                    continue
            except NotFoundError:
                child = self._insert(Dataset(
                    name=child_name, kind=DatasetKind.file, parent_id=ds.id,
                    privacy_mode=ds.privacy_mode,
                    meta=FileMeta(path=full, format=detect_format(full) or "csv")))
            self._prepare_one_child(child)
        ds.scan_status = ScanStatus.ready
        ds.profile_status = ProfileStatus.ready
        self.repo.update(ds)

    def _prepare_one_child(self, child: Dataset) -> None:
        try:
            child.revision = file_revision(child.meta.path)
            child.scan_status = ScanStatus.ready
            if self.repo.get_profile(child.id, child.revision) is None:
                self._profile_into(child)
            else:
                child.profile_status = ProfileStatus.ready
                self.repo.update(child)
        except Exception as e:  # noqa: BLE001
            child.scan_status = ScanStatus.failed
            child.profile_status = ProfileStatus.failed
            child.last_error = self.settings.secrets.redact(f"{type(e).__name__}: {e}")[:_ERR_MAX]
            self.repo.update(child)

    def _prepare_sql(self, ds: Dataset) -> None:
        conn = sql_source.open_readonly(self._conn_target(ds))
        try:
            tables = sql_source.reflect(conn)
        finally:
            conn.close()
        if ds.meta.table not in tables:
            raise RegisterError(f"table {ds.meta.table!r} not in source "
                                f"(found: {sorted(tables)})")
        ds.revision = sql_source.schema_hash(tables[ds.meta.table])
        ds.scan_status = ScanStatus.ready
        if self.repo.get_profile(ds.id, ds.revision) is not None:
            ds.profile_status = ProfileStatus.ready
            self.repo.update(ds)
            return
        self._profile_into(ds)

    # -- shared profiling step ----------------------------------------------------

    def _profile_into(self, ds: Dataset) -> None:
        from . import reader

        ds.profile_status = ProfileStatus.profiling
        self.repo.update(ds)
        kwargs: dict[str, Any] = {}
        if ds.kind is DatasetKind.sql:
            kwargs["conn_target"] = self._conn_target(ds)
        df = reader.read_dataset(ds, limit=self.settings.get_setting(
            "profile_sample_rows", PROFILE_SAMPLE_ROWS_DEFAULT), **kwargs)
        total = reader.count_rows(ds, **kwargs)
        profile = profile_dataframe(df, ds.id, ds.revision, row_count=total)
        if effective_privacy(ds, self.settings):
            for c in profile.columns:
                c.sample_values = []
                c.top_values = []
        self.repo.put_profile(ds, profile)
        ds.profile_status = ProfileStatus.ready
        self.repo.update(ds)

    def preview_limit(self) -> int:
        return int(self.settings.get_setting("preview_max_rows", PREVIEW_MAX_ROWS))
