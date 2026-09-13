"""ChartAsset service: workspace FS is the source of truth, sqlite mirrors index.

Layout: workspace/assets/{id}/{meta.json, processor.py, params.json,
versions/{n}.tar, render.json, config.json}.

Drift model: the index stores hash(meta.json bytes); meta.json itself stores
processor_hash = sha1(processor.py + params.json bytes). get() re-checks both —
hand-edited source or half-finished writes surface as AssetStatus.broken instead of
silently rendering stale logic. Rollback restores the full snapshot (incl. render)
as a NEW version. Version CAS: writers pass expected_version.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from ..storage import connect
from .models import AssetIndexRow, AssetStatus, ChartAsset, Placement, ReplayResult  # noqa: F401

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  chart_type TEXT NOT NULL,
  meta_hash TEXT NOT NULL,
  px INTEGER NOT NULL DEFAULT 0,
  py INTEGER NOT NULL DEFAULT 0,
  pw INTEGER NOT NULL DEFAULT 6,
  ph INTEGER NOT NULL DEFAULT 4,
  pz INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replays(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  trigger TEXT NOT NULL,
  passed INTEGER NOT NULL,
  errors_json TEXT NOT NULL DEFAULT '[]',
  elapsed_s REAL NOT NULL DEFAULT 0,
  ran_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replays_asset ON replays(asset_id, id);
"""

_SNAPSHOT_FILES = ("processor.py", "params.json", "meta.json", "render.json", "config.json")


class ConflictError(RuntimeError):
    pass


class AssetNotFound(KeyError):
    pass


class DuplicateAssetName(ValueError):
    pass


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def _atomic_write(path: Path, data: str | bytes) -> None:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class AssetService:
    def __init__(self, assets_dir: Path, index_db: Path) -> None:
        self._dir = assets_dir
        self.conn = connect(index_db)
        self.conn.executescript(_SCHEMA)

    # -- paths --------------------------------------------------------------

    def path_of(self, asset_id: str) -> Path:
        return self._dir / asset_id

    def _meta_path(self, asset_id: str) -> Path:
        return self.path_of(asset_id) / "meta.json"

    # -- create / persist -----------------------------------------------------

    def create(self, asset: ChartAsset, processor_source: str) -> ChartAsset:
        root = self.path_of(asset.id)
        root.mkdir(parents=True, exist_ok=False)
        _atomic_write(root / "processor.py", processor_source)
        _atomic_write(root / "params.json", json.dumps(asset.params, ensure_ascii=False, indent=1))
        self.recompute_content_hash(asset)
        try:
            self._persist(asset)
        except sqlite3.IntegrityError as e:
            shutil.rmtree(root, ignore_errors=True)
            raise DuplicateAssetName(f"asset name {asset.name!r} exists") from e
        return asset

    def recompute_content_hash(self, asset: ChartAsset) -> str:
        root = self.path_of(asset.id)
        h = hashlib.sha1()
        for f in ("processor.py", "params.json"):
            h.update((root / f).read_bytes())
        asset.processor_hash = "ph" + h.hexdigest()[:16]
        return asset.processor_hash

    def _persist(self, asset: ChartAsset) -> None:
        asset.touch()
        data = asset.model_dump_json(indent=1)
        _atomic_write(self._meta_path(asset.id), data)
        self.conn.execute(
            "INSERT INTO assets(id,name,status,version,chart_type,meta_hash,"
            "px,py,pw,ph,pz,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,status=excluded.status,"
            "version=excluded.version,chart_type=excluded.chart_type,meta_hash=excluded.meta_hash,"
            "px=excluded.px,py=excluded.py,pw=excluded.pw,ph=excluded.ph,pz=excluded.pz,"
            "updated_at=excluded.updated_at",
            (
                asset.id, asset.name, asset.status.value, asset.version, asset.chart_type,
                _hash_bytes(data.encode("utf-8")),
                asset.placement.x, asset.placement.y, asset.placement.w, asset.placement.h,
                asset.placement.z, asset.updated_at if hasattr(asset, "updated_at") else "",
            ),
        )
        self.conn.commit()

    def update(self, asset: ChartAsset, *, expected_version: int | None = None) -> ChartAsset:
        """Caller-owned asset mutated; version CAS checked against the CURRENT stored one."""
        current = self.conn.execute("SELECT version FROM assets WHERE id=?", (asset.id,)).fetchone()
        if current is None:
            raise AssetNotFound(asset.id)
        if expected_version is not None and current["version"] != expected_version:
            raise ConflictError(f"asset at v{current['version']}, expected v{expected_version}")
        self._persist(asset)
        return asset

    # -- read with drift checks ----------------------------------------------

    def get(self, asset_id: str) -> ChartAsset:
        row = self.conn.execute(
            "SELECT meta_hash, status FROM assets WHERE id=?", (asset_id,)
        ).fetchone()
        if row is None:
            raise AssetNotFound(asset_id)
        meta_p = self._meta_path(asset_id)
        if not meta_p.is_file():
            raise AssetNotFound(f"{asset_id}: meta.json missing on disk")
        raw = meta_p.read_bytes()
        asset = ChartAsset.model_validate_json(raw)
        drifted = _hash_bytes(raw) != row["meta_hash"] or self._content_drift(asset_id, asset)
        if drifted and asset.status is not AssetStatus.broken:
            self.conn.execute("UPDATE assets SET status=? WHERE id=?",
                              (AssetStatus.broken.value, asset_id))
            self.conn.commit()
            asset.status = AssetStatus.broken
        return asset

    def _content_drift(self, asset_id: str, asset: ChartAsset) -> bool:
        root = self.path_of(asset_id)
        h = hashlib.sha1()
        for f in ("processor.py", "params.json"):
            p = root / f
            if not p.is_file():
                return True
            h.update(p.read_bytes())
        return ("ph" + h.hexdigest()[:16]) != asset.processor_hash

    def load_source(self, asset_id: str) -> str:
        return (self.path_of(asset_id) / "processor.py").read_text(encoding="utf-8")

    def save_source(self, asset_id: str, source: str, params: dict[str, Any] | None = None,
                       *, expected_version: int | None = None) -> ChartAsset:
        """Write new processor/params + snapshot the PREVIOUS state as versions/{v}.tar."""
        asset = self.get(asset_id)
        if expected_version is not None and asset.version != expected_version:
            raise ConflictError(f"asset at v{asset.version}, expected v{expected_version}")
        self._snapshot(asset_id, asset.version)
        root = self.path_of(asset_id)
        _atomic_write(root / "processor.py", source)
        if params is not None:
            asset.params = params
            _atomic_write(root / "params.json", json.dumps(params, ensure_ascii=False, indent=1))
        asset.version += 1
        asset.status = AssetStatus.draft  # new logic must re-pass the gate
        self.recompute_content_hash(asset)
        self._persist(asset)
        return asset

    # -- render artifacts -------------------------------------------------------

    def write_render(self, asset_id: str, render: dict[str, Any], config: dict[str, Any]) -> None:
        root = self.path_of(asset_id)
        _atomic_write(root / "render.json", json.dumps(render, ensure_ascii=False))
        _atomic_write(root / "config.json", json.dumps(config, ensure_ascii=False))

    def read_render(self, asset_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        root = self.path_of(asset_id)
        r, c = root / "render.json", root / "config.json"
        if not (r.is_file() and c.is_file()):
            return None
        return json.loads(r.read_text("utf-8")), json.loads(c.read_text("utf-8"))

    # -- versions / rollback / history ------------------------------------------

    def _snapshot(self, asset_id: str, version: int) -> Path:
        root = self.path_of(asset_id)
        vdir = root / "versions"
        vdir.mkdir(exist_ok=True)
        tar_p = vdir / f"{version}.tar"
        with tarfile.open(tar_p, "w") as tf:
            for f in _SNAPSHOT_FILES:
                if (root / f).is_file():
                    tf.add(root / f, arcname=f)
        return tar_p

    def rollback(self, asset_id: str, to_version: int,
                 *, expected_version: int | None = None) -> ChartAsset:
        asset = self.get(asset_id)
        if expected_version is not None and asset.version != expected_version:
            raise ConflictError(f"asset at v{asset.version}, expected v{expected_version}")
        tar_p = self.path_of(asset_id) / "versions" / f"{to_version}.tar"
        if not tar_p.is_file():
            raise AssetNotFound(f"version {to_version} of {asset_id}")
        self._snapshot(asset_id, asset.version)  # keep current before rewinding
        with tarfile.open(tar_p) as tf:
            tf.extractall(self.path_of(asset_id), filter="data")
        restored = ChartAsset.model_validate_json(self._meta_path(asset_id).read_bytes())
        restored.version = asset.version + 1
        restored.status = AssetStatus.validated if self.read_render(asset_id) else AssetStatus.draft
        restored.description = f"rollback to v{to_version}"
        self.recompute_content_hash(restored)
        self._persist(restored)
        return restored

    def history(self, asset_id: str) -> dict[str, Any]:
        vdir = self.path_of(asset_id) / "versions"
        versions = (sorted((int(p.stem) for p in vdir.glob("*.tar")), reverse=True)
                    if vdir.is_dir() else [])
        rows = self.conn.execute(
            "SELECT version,trigger,passed,errors_json,elapsed_s,ran_at FROM replays "
            "WHERE asset_id=? ORDER BY id DESC LIMIT 100",
            (asset_id,),
        ).fetchall()
        replays = []
        for r in rows:
            d = dict(r)
            d["errors"] = json.loads(d.pop("errors_json"))
            d["passed"] = bool(d["passed"])
            replays.append(d)
        return {"versions": versions, "replays": replays}

    # -- listing / audit -----------------------------------------------------------

    def list(self) -> list[AssetIndexRow]:
        rows = self.conn.execute("SELECT * FROM assets ORDER BY pz, py, px").fetchall()
        out = []
        for r in rows:
            asset_id = r["id"]
            gate_errors = self.conn.execute(
                "SELECT passed, ran_at, errors_json FROM replays "
                "WHERE asset_id=? ORDER BY id DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
            out.append(
                AssetIndexRow(
                    id=asset_id, name=r["name"], status=r["status"], version=r["version"],
                    chart_type=r["chart_type"],
                    placement=Placement(x=r["px"], y=r["py"], w=r["pw"], h=r["ph"], z=r["pz"]),
                    gate_passed=None if gate_errors is None else bool(gate_errors["passed"]),
                    gate_at=None if gate_errors is None else gate_errors["ran_at"],
                    has_render=(self.path_of(asset_id) / "render.json").is_file(),
                )
            )
        return out

    def record_replay(self, asset_id: str, version: int, trigger: str, passed: bool,
                      errors: list[str], elapsed_s: float, ran_at: str) -> None:
        self.conn.execute(
            "INSERT INTO replays(asset_id,version,trigger,passed,errors_json,elapsed_s,ran_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (asset_id, version, trigger, int(passed), json.dumps(errors, ensure_ascii=False),
             elapsed_s, ran_at),
        )
        self.conn.commit()

    def set_placement(self, asset_id: str, p: Placement) -> None:
        cur = self.conn.execute(
            "UPDATE assets SET px=?,py=?,pw=?,ph=?,pz=? WHERE id=?",
            (p.x, p.y, p.w, p.h, p.z, asset_id),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            raise AssetNotFound(asset_id)

    def delete(self, asset_id: str) -> None:
        row = self.conn.execute("SELECT id FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise AssetNotFound(asset_id)
        shutil.rmtree(self.path_of(asset_id), ignore_errors=True)
        self.conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        self.conn.execute("DELETE FROM replays WHERE asset_id=?", (asset_id,))
        self.conn.commit()
