"""Runtime settings layer.

Three configuration tiers (design-architecture §1):
  1. bootstrap env      DATA_ROOT / WORKSPACE_ROOT (container sets /data, /workspace;
                        local dev/tests fall back to cwd-relative paths)
  2. runtime settings   workspace index.db `settings` table — hot-editable, non-sensitive
                        (privacy default, budgets, AI toggle default from N3…)
  3. secrets            workspace/secrets.json 0600 — sensitive (conn strings, LLM keys);
                        API view is masked, logs go through SecretsStore.redact.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .secrets_store import SecretsStore
from .storage import connect

# Budget/limits defaults (overridable via the settings table).
PROFILE_TOKEN_BUDGET_DEFAULT = 500  # ≤500 tokens per table injected into prompts
PROFILE_SAMPLE_ROWS_DEFAULT = 5000  # per-file profiling cost must stay constant
PREVIEW_MAX_ROWS = 50


class JailError(ValueError):
    """Requested path resolves outside DATA_ROOT."""


@dataclass(frozen=True)
class Workspace:
    data_root: Path
    workspace_root: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Workspace:
        e = os.environ if env is None else env
        return cls(
            data_root=Path(e.get("DATA_ROOT", "data")).resolve(),
            workspace_root=Path(e.get("WORKSPACE_ROOT", ".data/workspace")).resolve(),
        )

    # -- layout --------------------------------------------------------------

    @property
    def index_db(self) -> Path:
        return self.workspace_root / "index.db"

    @property
    def assets_dir(self) -> Path:
        return self.workspace_root / "assets"

    @property
    def drafts_dir(self) -> Path:
        return self.workspace_root / "drafts"

    @property
    def secrets(self) -> SecretsStore:
        return SecretsStore(self.workspace_root / "secrets.json")

    def ensure_runtime(self) -> None:
        """Create workspace dirs + secrets file (0600); index.db is created by storage.connect."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.secrets.ensure()

    # -- path jail ------------------------------------------------------------

    def jail(self, raw: str | Path) -> Path:
        """Resolve under DATA_ROOT or refuse; all registration paths pass here."""
        p = Path(raw).expanduser()
        p = p.resolve() if p.is_absolute() else (self.data_root / p).resolve()
        if not p.is_relative_to(self.data_root):
            raise JailError(f"path {raw!r} escapes DATA_ROOT ({self.data_root})")
        return p


class SettingsService:
    """Merged view over the settings table + secrets store.

    Contract: get_view() output may go to API/logs verbatim — it never contains
    plaintext secrets. update() splits writes by tier; omitted keys are untouched.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace
        self._secrets = workspace.secrets
        self._secrets.ensure()

    @property
    def secrets(self) -> SecretsStore:
        return self._secrets

    def _conn(self):
        conn = connect(self._ws.index_db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        return conn

    def get_setting(self, key: str, default: Any = None) -> Any:
        conn = self._conn()
        try:
            row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        return json.loads(row["value_json"]) if row else default

    def all_settings(self) -> dict[str, Any]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
        finally:
            conn.close()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def get_view(self) -> dict[str, Any]:
        return {
            "settings": self.all_settings(),
            "secrets": self._secrets.masked_view(),
            "data_root": str(self._ws.data_root),
            "workspace_root": str(self._ws.workspace_root),
        }

    def update(
        self, settings: Mapping[str, Any] | None = None, secrets: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        if settings:
            now = datetime.now(UTC).isoformat()
            conn = self._conn()
            try:
                conn.executemany(
                    "INSERT INTO settings(key, value_json, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                    "updated_at=excluded.updated_at",
                    [(k, json.dumps(v, ensure_ascii=False), now) for k, v in settings.items()],
                )
                conn.commit()
            finally:
                conn.close()
        if secrets:
            for k, v in secrets.items():  # omitted keys stay untouched; "" clears
                if v == "":
                    self._secrets.delete(k)
                else:
                    self._secrets.set(k, v)
        return self.get_view()
