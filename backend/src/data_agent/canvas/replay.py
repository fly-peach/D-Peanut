"""Replay service: the deterministic heart of the canvas (zero AI on this path).

pipeline: acquire clean kernel -> %reset -f -> inject shim (lazy ctx.data loading
through the SAME catalog.reader code, so "AI trial passed == replay passes" holds)
-> importlib-load processor.py -> process(ctx) -> sentinel JSON back -> gate ->
render.json/config.json artifacts + replays audit row.

Secrets boundary: sql conn targets resolve from the secrets store and are injected
ONLY into the kernel payload (never persisted with the asset, never returned).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import ValidationError

from ..catalog.registry import CatalogRepository, NotFoundError
from ..schemas.chart import CHART_TYPES, ChartConfig, RenderData, assert_json_safe
from .assets import AssetService
from .gate import stamp_schema, validate_output
from .kernels import ReplayKernelPool
from .models import AssetStatus, ReplayResult

REPLAY_TIMEOUT_S = 30.0
_TIMEOUT_MARK = "TimeoutError: execution exceeded"
_SENT_RE = re.compile(r"<<<DA_RESULT_([0-9a-f]{32})>>>(.*?)<<<DA_END>>>", re.DOTALL)

_SHIM = '''
import importlib.util as _ilu, json as _json, uuid as _uuid
_SPEC = _json.loads(r"""__SPEC_JSON__""")
class _Ctx:
    params = _SPEC["params"]
    _logs = []
    @staticmethod
    def log(msg):
        _Ctx._logs.append(str(msg))
class _LazyData(dict):
    def __missing__(self, key):
        spec = _SPEC["sources"][key]
        from data_agent.catalog.models import Dataset, FileMeta, SqlMeta
        from data_agent.catalog import reader
        if spec["kind"] == "sql":
            ds = Dataset(name=key, kind="sql", meta=SqlMeta(conn_ref="inline", table=spec["table"]))
            df = reader.read_dataset(ds, conn_target=spec["conn_target"])
        else:
            ds = Dataset(name=key, kind="file", meta=FileMeta(
                path=spec["path"], format=spec["format"], sheet=spec.get("sheet")))
            df = reader.read_dataset(ds)
        df.attrs["dataset_ref"] = {"name": spec["name"], "revision": spec["revision"]}
        self[key] = df
        return df
_ctx = _Ctx()
_ctx.data = _LazyData()
_pspec = _ilu.spec_from_file_location("processor", _SPEC["processor_path"])
_pmod = _ilu.module_from_spec(_pspec)
_pspec.loader.exec_module(_pmod)
_r = _pmod.process(_ctx)
if not (isinstance(_r, tuple) and len(_r) == 2):
    raise TypeError("process(ctx) must return (RenderData, ChartConfig), got " + repr(type(_r)))
_render, _config = _r
_dump = lambda o: o.model_dump() if hasattr(o, "model_dump") else o
_sentinel = "<<<DA_RESULT_" + _uuid.uuid4().hex + ">>>"
print(_sentinel + _json.dumps({"render": _dump(_render), "config": _dump(_config),
                               "logs": _Ctx._logs}, ensure_ascii=False) + "<<<DA_END>>>")
'''


class ReplayService:
    def __init__(self, assets: AssetService, repo: CatalogRepository,
                 secrets, pool: ReplayKernelPool) -> None:
        self.assets = assets
        self.repo = repo
        self.secrets = secrets
        self.pool = pool

    # -- binding specs ----------------------------------------------------------

    def _binding_specs(self, asset) -> tuple[dict[str, dict[str, Any]], list[str]]:
        sources: dict[str, dict[str, Any]] = {}
        problems: list[str] = []
        for b in asset.bindings:
            try:
                ds = self.repo.get_by_name(b.dataset.name)
            except NotFoundError:
                problems.append(f"binding {b.alias!r}: dataset {b.dataset.name!r} not found")
                continue
            if ds.revision != b.dataset.revision:
                problems.append(
                    f"binding {b.alias!r}: dataset revision drift (bound {b.dataset.revision!r}, "
                    f"now {ds.revision!r}) — rescan then rebind/update asset"
                )
                continue
            if ds.kind == "sql":
                target = self.secrets.get(ds.meta.conn_ref)
                if not target:
                    problems.append(f"binding {b.alias!r}: secret for {ds.meta.conn_ref!r} missing")
                    continue
                sources[b.alias] = {"kind": "sql", "table": ds.meta.table,
                                    "conn_target": target, "name": ds.name, "revision": ds.revision}
            else:
                sources[b.alias] = {
                    "kind": "file", "path": ds.meta.path, "format": ds.meta.format,
                    "sheet": ds.meta.sheet, "name": ds.name, "revision": ds.revision,
                }
        return sources, problems

    # -- replay -------------------------------------------------------------------

    def replay(self, asset_id: str, *, trigger: str = "manual") -> ReplayResult:
        t0 = time.monotonic()
        asset = self.assets.get(asset_id)
        render: RenderData | None = None
        config: ChartConfig | None = None
        notes: list[str] = []
        exec_error: str | None = None
        timed_out = False

        if asset.status is AssetStatus.broken:
            exec_error = "asset drift (meta/content hash mismatch) — rewrite source to revalidate"
        elif asset.chart_type not in CHART_TYPES:
            exec_error = f"chart_type {asset.chart_type!r} outside whitelist {list(CHART_TYPES)}"

        sources: dict[str, Any] = {}
        if exec_error is None:
            sources, problems = self._binding_specs(asset)
            if problems:
                exec_error = "; ".join(problems)
            elif set(sources) != {b.alias for b in asset.bindings}:
                exec_error = "binding resolution incomplete"

        if exec_error is None:
            spec_blob = json.dumps({
                "params": asset.params,
                "sources": sources,
                "processor_path": str(self.assets.path_of(asset_id) / "processor.py"),
            }, ensure_ascii=False)
            sid = self.pool.acquire()
            discard = False
            try:
                if not self.pool.reset(sid):
                    discard = True
                    exec_error = "kernel reset failed"
                else:
                    res = self.pool.inner.execute(
                        sid, _SHIM.replace("__SPEC_JSON__", spec_blob), timeout_s=REPLAY_TIMEOUT_S
                    )
                    if _TIMEOUT_MARK in res.error:
                        timed_out, discard = True, True
                    elif not res.ok:
                        exec_error = res.error[:2000]
                    else:
                        render, config, notes, exec_error = self._parse(res.stdout)
            finally:
                self.pool.release(sid, discard=discard)

        elapsed = time.monotonic() - t0
        report = validate_output(
            asset.id, asset.version, render, asset.output_schema,
            exec_error=exec_error, timed_out=timed_out, elapsed_s=elapsed,
        )
        if report.passed and render is not None and config is not None:
            if asset.output_schema is None:
                asset.output_schema = stamp_schema(render)
            self.assets.write_render(asset.id, render.model_dump(), config.model_dump())
            if asset.status in (AssetStatus.draft, AssetStatus.broken):
                asset.status = AssetStatus.validated
        self.assets.update(asset)
        self.assets.record_replay(asset.id, asset.version, trigger, report.passed,
                                  report.errors, report.elapsed_s, report.ran_at)
        return ReplayResult(
            gate=report,
            render=None if render is None else render.model_dump(),
            config=None if config is None else config.model_dump(),
            version=asset.version,
            notes=notes,
        )

    @staticmethod
    def _parse(stdout: str):
        matches = _SENT_RE.findall(stdout)
        if not matches:
            tail = stdout.strip()[-500:]
            return (None, None, [], f"no result sentinel in kernel output; tail: {tail!r}")
        payload = json.loads(matches[-1][1])
        logs = [str(x) for x in payload.get("logs", [])]
        try:
            render = RenderData.model_validate(payload["render"]).with_defaults()
            config = ChartConfig.model_validate(payload["config"])
        except (KeyError, ValidationError) as e:
            return None, None, logs, f"result not RenderData/ChartConfig shaped: {e}"
        try:
            assert_json_safe(config.option_template, path="option_template")
            assert_json_safe(config.data_map.map, path="data_map")
        except Exception as e:  # ChartSpecError
            return None, None, logs, str(e)
        return render, config, logs, None
