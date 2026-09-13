"""Unified Dataset -> DataFrame read path (frozen at N1; N2 bindings + N3 query_data reuse).

Engine split (design decision 4):
  csv/parquet -> DuckDB (predicate/limit pushdown, never materializes full table)
  xlsx        -> pandas.read_excel (openpyxl; bypasses DuckDB excel extension = no network)
  sqlite      -> stdlib sqlite3 (read-only URI) + pandas.read_sql with LIMIT

conn_target (resolved sqlite path) is passed by the caller after secrets lookup —
this module never touches the secrets store itself.
"""

from __future__ import annotations

import pandas as pd

from .models import Dataset
from .sources import sql as sql_source


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def build_select_sql(
    ds: Dataset, columns: list[str] | None = None, limit: int | None = None
) -> str:
    """SQL for the DuckDB engines; assertion-friendly (pushdown contract)."""
    meta = ds.meta
    src = "read_csv(?, auto_detect=true)" if meta.format == "csv" else "read_parquet(?)"
    cols = ", ".join(_q(c) for c in columns) if columns else "*"
    sql = f"SELECT {cols} FROM {src}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return sql


def read_dataset(
    ds: Dataset,
    *,
    conn_target: str | None = None,
    columns: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    meta = ds.meta
    if ds.kind == "file" and meta.format in ("csv", "parquet"):
        import duckdb

        con = duckdb.connect()
        try:
            return con.execute(
                build_select_sql(ds, columns, limit), [str(meta.path)]
            ).fetch_df()
        finally:
            con.close()
    if ds.kind == "file" and meta.format == "xlsx":
        return pd.read_excel(
            meta.path,
            sheet_name=meta.sheet or 0,
            usecols=columns,
            nrows=limit,
            engine="openpyxl",
        )
    if ds.kind == "sql":
        if conn_target is None:
            raise ValueError("sql dataset requires conn_target resolved from secrets")
        conn = sql_source.open_readonly(conn_target)
        try:
            cols = ", ".join(_q(c) for c in columns) if columns else "*"
            lim = f" LIMIT {int(limit)}" if limit is not None else ""
            sql = f'SELECT {cols} FROM {_q(meta.table)}{lim}'
            return pd.read_sql_query(sql, conn)
        finally:
            conn.close()
    raise ValueError(f"unsupported dataset {ds.kind}/{getattr(meta, 'format', '?')}")


def count_rows(ds: Dataset, *, conn_target: str | None = None) -> int:
    meta = ds.meta
    if ds.kind == "file" and meta.format in ("csv", "parquet"):
        import duckdb

        con = duckdb.connect()
        try:
            fn = "read_csv(?, auto_detect=true)" if meta.format == "csv" else "read_parquet(?)"
            return int(con.execute(f"SELECT COUNT(*) FROM {fn}", [str(meta.path)]).fetchone()[0])
        finally:
            con.close()
    if ds.kind == "file" and meta.format == "xlsx":
        from .sources.file import xlsx_row_count

        return xlsx_row_count(meta.path, meta.sheet or 0)
    if ds.kind == "sql":
        if conn_target is None:
            raise ValueError("sql dataset requires conn_target resolved from secrets")
        conn = sql_source.open_readonly(conn_target)
        try:
            return sql_source.count_table(conn, meta.table)
        finally:
            conn.close()
    raise ValueError(f"unsupported dataset {ds.kind}")
