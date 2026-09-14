"""Sqlite persistence: sessions / messages / runs / run_steps / adhoc.

Same-process connection (WAL). The /chat SSE plane stays the AI channel; this
store is the audit + resume source (message copies, usage/cost, approval chain).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..storage import connect
from .state import RunStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
  role TEXT NOT NULL, parts_json TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
  parent_run_id TEXT, message TEXT NOT NULL DEFAULT '',
  usage_json TEXT NOT NULL DEFAULT '{}', cost_usd REAL NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_steps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, idx INTEGER NOT NULL,
  tool TEXT NOT NULL, status TEXT NOT NULL, args_json TEXT NOT NULL DEFAULT '{}',
  output_digest TEXT NOT NULL DEFAULT '', retries INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adhoc(
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT,
  payload_json TEXT NOT NULL, source_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


@dataclass
class Run:
    run_id: str
    session_id: str
    status: RunStatus = RunStatus.PLANNED
    steps: list[dict] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0
    parent_run_id: str | None = None
    message: str = ""
    error: str | None = None


class RunStore:
    def __init__(self, index_db: Path) -> None:
        self.conn: sqlite3.Connection = connect(index_db)
        self.conn.executescript(_SCHEMA)

    # -- sessions -------------------------------------------------------------

    def create_session(self, title: str = "") -> str:
        sid = new_id("se")
        now = _now()
        self.conn.execute(
            "INSERT INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (sid, title, now, now),
        )
        self.conn.commit()
        return sid

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id,title,updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, sid: str) -> None:
        for sql in ("DELETE FROM messages WHERE session_id=?", "DELETE FROM sessions WHERE id=?",
                    "DELETE FROM runs WHERE session_id=?", "DELETE FROM adhoc WHERE session_id=?"):
            self.conn.execute(sql, (sid,))
        self.conn.commit()

    def touch_session(self, sid: str) -> None:
        self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), sid))
        self.conn.commit()

    def rename_session(self, sid: str, title: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), sid)
        )
        self.conn.commit()

    def auto_title(self, sid: str, title: str) -> None:
        """Codex-style: first user message names the session (only if untitled)."""
        row = self.conn.execute("SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        if row and not (row[0] or "").strip() and title.strip():
            self.rename_session(sid, title.strip()[:60])

    def ensure_session(self, sid: str) -> str:
        row = self.conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            return self.create_session()
        return sid

    # -- messages ---------------------------------------------------------------

    def add_message(self, session_id: str, role: str, parts: list[dict[str, Any]],
                    run_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO messages(session_id,role,parts_json,run_id,created_at) VALUES(?,?,?,?,?)",
            (session_id, role, json.dumps(parts, ensure_ascii=False, default=str), run_id, _now()),
        )
        self.conn.commit()

    def replace_messages(self, session_id: str, run_id: str,
                         ui_messages: list[dict[str, Any]]) -> None:
        """Server-side copy of the whole UIMessage list after a run
        (N4 restore source; last run wins)."""
        self.conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        for m in ui_messages:
            self.conn.execute(
                "INSERT INTO messages(session_id,role,parts_json,run_id,created_at)"
                " VALUES(?,?,?,?,?)",
                (session_id, str(m.get("role", "assistant")),
                 json.dumps(m.get("parts", []), ensure_ascii=False, default=str), run_id, _now()),
            )
        self.conn.commit()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT role, parts_json FROM messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return [{"id": f"restored-{i}", "role": r["role"], "parts": json.loads(r["parts_json"])}
                for i, r in enumerate(rows)]

    # -- runs -------------------------------------------------------------------

    def create_run(self, session_id: str, message: str,
                   parent_run_id: str | None = None) -> Run:
        run = Run(run_id=new_id("rn"), session_id=session_id, message=message,
                  parent_run_id=parent_run_id)
        now = _now()
        self.conn.execute(
            "INSERT INTO runs(id,session_id,status,parent_run_id,message,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (run.run_id, session_id, run.status.value, parent_run_id, message[:500], now, now),
        )
        self.conn.commit()
        return run

    def set_run_status(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET status=?, error=COALESCE(?, error), updated_at=? WHERE id=?",
            (status.value, error, _now(), run_id),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, status: RunStatus, usage: dict[str, Any],
                   cost: float, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET status=?, usage_json=?, cost_usd=?, error=?, updated_at=? WHERE id=?",
            (status.value, json.dumps(usage, ensure_ascii=False, default=str), cost, error,
             _now(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run_for_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_step(self, run_id: str, idx: int, tool: str, status: str,
                 args: dict[str, Any], digest: str = "", retries: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO run_steps(run_id,idx,tool,status,args_json,"
            "output_digest,retries,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (run_id, idx, tool, status, json.dumps(args, ensure_ascii=False, default=str),
             digest[:500], retries, _now()),
        )
        self.conn.commit()

    # -- adhoc (light mode) -------------------------------------------------------

    def save_adhoc(self, session_id: str, run_id: str | None, payload: dict[str, Any],
                   source_code: str) -> str:
        aid = new_id("ad")
        self.conn.execute(
            "INSERT INTO adhoc(id,session_id,run_id,payload_json,source_code,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (aid, session_id, run_id, json.dumps(payload, ensure_ascii=False, default=str),
             source_code, _now()),
        )
        self.conn.commit()
        return aid

    def get_adhoc(self, adhoc_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM adhoc WHERE id=?", (adhoc_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        return d
