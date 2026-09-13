"""Catalog models + registry: Dataset contract, index CRUD, profile cache (tasks 1.2)."""

import pytest

from data_agent.catalog.models import (
    ColumnProfile,
    Dataset,
    DatasetKind,
    FileMeta,
    FolderMeta,
    ProfileStatus,
    ScanStatus,
    SqlMeta,
    TableProfile,
)
from data_agent.catalog.registry import CatalogRepository, DuplicateNameError, NotFoundError


@pytest.fixture()
def repo(tmp_path):
    r = CatalogRepository(tmp_path / "index.db")
    yield r
    r.close()


def file_ds(name="sales", path="/data/sales.csv", revision="r1") -> Dataset:
    return Dataset(
        name=name, kind=DatasetKind.file, revision=revision, meta=FileMeta(path=path, format="csv")
    )


class TestModels:
    def test_kind_meta_mismatch_rejected(self):
        with pytest.raises(ValueError, match="requires meta"):
            Dataset(name="x", kind=DatasetKind.sql, meta=FileMeta(path="/a.csv", format="csv"))

    def test_ref_and_ids(self):
        ds = file_ds()
        assert ds.id.startswith("ds_")
        assert ds.ref.model_dump() == {
            "dataset_id": ds.id,
            "name": "sales",
            "revision": "r1",
        }


class TestRegistry:
    def test_insert_get_roundtrip_preserves_meta_type(self, repo):
        repo.insert(file_ds())
        got = repo.get_by_name("sales")
        assert isinstance(got.meta, FileMeta)
        assert got.meta.format == "csv"
        assert got.scan_status is ScanStatus.pending

    def test_duplicate_name_rejected(self, repo):
        repo.insert(file_ds())
        with pytest.raises(DuplicateNameError):
            repo.insert(file_ds(path="/data/other.csv"))

    def test_unknown_raises_notfound(self, repo):
        with pytest.raises(NotFoundError):
            repo.get("ds_missing")

    def test_sql_and_folder_metas_roundtrip(self, repo):
        folder = Dataset(
            name="root",
            kind=DatasetKind.folder,
            meta=FolderMeta(root="/data/sales", fingerprint="f0"),
        )
        child = Dataset(
            name="root/sales_jan.csv",
            kind=DatasetKind.file,
            parent_id=folder.id,
            meta=FileMeta(path="/data/sales/jan.csv", format="csv"),
        )
        repo.insert(folder)
        repo.insert(child)
        repo.insert(
            Dataset(
                name="pg_shop",
                kind=DatasetKind.sql,
                meta=SqlMeta(conn_ref="sql.pg1", table="orders"),
            )
        )
        assert [d.name for d in repo.children(folder.id)] == ["root/sales_jan.csv"]
        assert repo.get_by_name("root").meta.extensions == ["csv", "parquet", "xlsx"]
        assert repo.get_by_name("pg_shop").meta.conn_ref == "sql.pg1"

    def test_profile_cache_keyed_by_revision(self, repo):
        ds = repo.insert(file_ds())
        profile = TableProfile(
            dataset_id=ds.id,
            revision="r1",
            row_count=10,
            columns=[ColumnProfile(name="x", dtype="int64")],
        )
        repo.put_profile(ds, profile)
        assert repo.get_profile(ds.id, "r1").row_count == 10
        assert repo.get_profile(ds.id, "r2") is None  # revision bumped → cache miss

        brief = repo.list()[0]
        assert brief.row_count == 10

        ds.revision = "r2"
        ds.profile_status = ProfileStatus.outdated
        repo.update(ds)
        # current-revision lookup misses; explicit old revision is kept for audit
        assert repo.get_profile(ds.id, ds.revision) is None
        assert repo.get_profile(ds.id, "r1").row_count == 10
        assert repo.list()[0].row_count is None

    def test_update_and_delete(self, repo):
        ds = repo.insert(file_ds())
        ds.scan_status = ScanStatus.ready
        ds.revision = "r9"
        repo.update(ds)
        assert repo.get(ds.id).scan_status is ScanStatus.ready
        repo.delete(ds.id)
        assert repo.list() == []
        with pytest.raises(NotFoundError):
            repo.delete(ds.id)

    def test_duplicate_on_rename(self, repo):
        repo.insert(file_ds("sales"))
        other = repo.insert(file_ds("other", path="/data/o.csv"))
        other.name = "sales"
        with pytest.raises(DuplicateNameError):
            repo.update(other)

    def test_referrers_lists_parent_folder(self, repo):
        folder = Dataset(name="root", kind=DatasetKind.folder, meta=FolderMeta(root="/data/s"))
        repo.insert(folder)
        child = Dataset(
            name="c.csv",
            kind=DatasetKind.file,
            parent_id=folder.id,
            meta=FileMeta(path="/data/s/c.csv", format="csv"),
        )
        repo.insert(child)
        assert repo.referrers(child.id) == ["root"]

    def test_rebuild_marks_missing_files_failed(self, repo):
        repo.insert(file_ds(path="/nonexistent/definitely-missing.csv"))
        ready = repo.insert(file_ds(name="exists", path=str(__file__)))
        repo.rebuild_index()
        assert repo.get_by_name("sales").scan_status is ScanStatus.failed
        assert repo.get(ready.id).scan_status is not ScanStatus.failed
