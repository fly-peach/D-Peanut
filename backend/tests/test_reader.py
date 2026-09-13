"""reader.py: pushdown SQL contract + four-engine roundtrips (tasks 2.6)."""

import pandas as pd
import pytest

from data_agent.catalog import reader
from data_agent.catalog.models import Dataset, DatasetKind, FileMeta, SqlMeta

DF = pd.DataFrame({"city": ["a", "b", "c", "d"], "rev": [1.0, 2.5, 3.0, 4.75]})


@pytest.fixture()
def engines(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_p = tmp_path / "e.csv"
    DF.to_csv(csv_p, index=False)
    pq_p = tmp_path / "e.parquet"
    import duckdb

    duckdb.sql(f"COPY (SELECT * FROM DF) TO '{pq_p.as_posix()}' (FORMAT PARQUET)")
    xl_p = tmp_path / "e.xlsx"
    with pd.ExcelWriter(xl_p, engine="openpyxl") as w:
        DF.to_excel(w, sheet_name="s1", index=False)
        DF.assign(other=[9, 8, 7, 6]).to_excel(w, sheet_name="s2", index=False)
    db_p = tmp_path / "e.db"
    sqlite = pd.DataFrame(DF)
    import sqlite3 as s3

    conn = s3.connect(db_p)
    sqlite.to_sql("t1", conn, index=False)
    conn.close()
    return {"csv": csv_p, "parquet": pq_p, "xlsx": xl_p, "db": db_p}


def ds_file(p, fmt, sheet=None):
    return Dataset(name="d", kind=DatasetKind.file,
                   meta=FileMeta(path=str(p), format=fmt, sheet=sheet))


class TestPushdownContract:
    def test_limit_and_columns_in_sql(self):
        sql = reader.build_select_sql(
            ds_file("/x/a.csv", "csv"), columns=["city", 'q"uote'], limit=5
        )
        assert "LIMIT 5" in sql
        assert '"city"' in sql and '"q""uote"' in sql  # identifier escaping
        assert "read_csv(?" in sql  # path stays parameterized, never interpolated

    def test_parquet_source(self):
        assert "read_parquet(?)" in reader.build_select_sql(
            ds_file("/x/a.parquet", "parquet"), limit=1)


class TestReads:
    def test_csv_full_and_limited(self, engines):
        ds = ds_file(engines["csv"], "csv")
        assert len(reader.read_dataset(ds)) == 4
        assert len(reader.read_dataset(ds, limit=2)) == 2
        assert list(reader.read_dataset(ds, columns=["rev"]).columns) == ["rev"]
        assert reader.count_rows(ds) == 4

    def test_parquet(self, engines):
        ds = ds_file(engines["parquet"], "parquet")
        df = reader.read_dataset(ds, limit=3)
        assert len(df) == 3 and reader.count_rows(ds) == 4

    def test_xlsx_sheet_selection(self, engines):
        df1 = reader.read_dataset(ds_file(engines["xlsx"], "xlsx", sheet="s1"))
        df2 = reader.read_dataset(ds_file(engines["xlsx"], "xlsx", sheet="s2"))
        assert list(df1.columns) == ["city", "rev"]
        assert "other" in df2.columns
        assert reader.count_rows(ds_file(engines["xlsx"], "xlsx", sheet="s1")) == 4

    def test_sql_readonly(self, engines):
        ds = Dataset(name="t1", kind=DatasetKind.sql,
                     meta=SqlMeta(conn_ref="sql.t1", table="t1"))
        df = reader.read_dataset(ds, conn_target=str(engines["db"]), limit=2)
        assert len(df) == 2
        assert reader.count_rows(ds, conn_target=str(engines["db"])) == 4

    def test_sql_missing_conn_raises(self):
        ds = Dataset(name="t1", kind=DatasetKind.sql,
                     meta=SqlMeta(conn_ref="sql.t1", table="t1"))
        with pytest.raises(ValueError, match="conn_target"):
            reader.read_dataset(ds)
