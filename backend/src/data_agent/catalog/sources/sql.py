"""SQL source: sqlite reflection via stdlib (no DuckDB sqlite extension → no network).

Connection strings live ONLY in the secrets store; everything above this module deals
with conn_ref. Read-only enforcement: sqlite opened through URI mode=ro.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def open_readonly(conn_target: str) -> sqlite3.Connection:
    """conn_target: absolute sqlite file path (jail-checked upstream at registration)."""
    p = Path(conn_target)
    uri = f"file:{p.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def reflect(conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """table -> [(column, declared_type)], internal sqlite_* tables excluded."""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    out: dict[str, list[tuple[str, str]]] = {}
    for t in tables:
        cols = conn.execute(f'PRAGMA table_info("{t.replace(chr(34), chr(34) * 2)}")').fetchall()
        out[t] = [(c[1], (c[2] or "").lower()) for c in cols]
    return out


def schema_hash(columns: list[tuple[str, str]]) -> str:
    h = hashlib.sha1()
    for name, typ in columns:
        h.update(f"{name}:{typ};".encode())
    return "sh" + h.hexdigest()[:16]


def count_table(conn: sqlite3.Connection, table: str) -> int:
    ident = f'"{table.replace(chr(34), chr(34) * 2)}"'
    return conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()[0]
