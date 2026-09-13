"""Replay service on REAL clean kernels: contract-lock (100x byte-identical),
gate-fail keeps previous render, drift/timeout/sql-binding paths (N2 tasks 3.x)."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from data_agent.canvas.assets import AssetService
from data_agent.canvas.kernels import ReplayKernelPool
from data_agent.canvas.models import AssetStatus, ChartAsset, DataSourceBinding, ParamField
from data_agent.canvas.replay import ReplayService
from data_agent.catalog.pipeline import CatalogPipeline
from data_agent.catalog.registry import CatalogRepository
from data_agent.settings import SettingsService, Workspace

FIXTURES = Path(__file__).parent / "fixtures" / "processors"

SALES = pd.DataFrame({
    "month": ["2021-01", "2021-02", "2021-03"] * 2,
    "city": ["上海", "北京", "广州", "深圳", "杭州", "成都"],
    "revenue": [10.5, 20.0, 30.25, 11.0, 21.5, 31.0],
})


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("canvas")
    (tmp / "data").mkdir()
    ws = Workspace(data_root=tmp / "data", workspace_root=tmp / "ws")
    ws.ensure_runtime()
    settings = SettingsService(ws)
    repo = CatalogRepository(ws.index_db)
    pipe = CatalogPipeline(repo, settings, ws)
    (ws.data_root / "sales.csv").write_text(SALES.to_csv(index=False), encoding="utf-8")
    ds = pipe.register_file(str(ws.data_root / "sales.csv"), name="sales")[0]
    pipe.run(ds.id)
    assert repo.get(ds.id).scan_status == "ready"
    pool = ReplayKernelPool(size=1)
    assets = AssetService(ws.assets_dir, ws.index_db)
    svc = ReplayService(assets, repo, settings.secrets, pool)
    yield ws, repo, assets, svc
    pool.shutdown_all()


def make_asset(name: str, source: str, bindings: list[DataSourceBinding],
               params: dict | None = None) -> ChartAsset:
    return ChartAsset(
        name=name,
        bindings=bindings,
        param_spec=[ParamField(key="top_n", label="n", type="int", default=5, min=1, max=50)],
        params=params or {"top_n": 5},
        chart_type="bar",
    )


def bar_source() -> str:
    return (FIXTURES / "bar_topn.py").read_text("utf-8")


@pytest.fixture()
def sales_binding(env):
    _, repo, _, _ = env
    ds = repo.get_by_name("sales")
    return [DataSourceBinding(alias="sales", dataset=ds.ref)]


class TestContractLock:
    def test_create_validate_and_100x_identical(self, env, sales_binding):
        _, _, assets, svc = env
        asset = assets.create(make_asset("lock_bar", bar_source(), sales_binding), bar_source())
        first = svc.replay(asset.id, trigger="test")
        assert first.gate.passed, first.gate.errors
        assert first.render is not None
        base = hashlib.sha1(json.dumps(first.render, sort_keys=True).encode()).hexdigest()
        for _ in range(99):
            again = svc.replay(asset.id, trigger="test")
            assert again.gate.passed
            assert hashlib.sha1(
                json.dumps(again.render, sort_keys=True).encode()
            ).hexdigest() == base

    def test_canvas_plane_has_no_ai_dependency(self):
        # static contract: nothing under canvas/ or schemas/chart.py may import
        # pydantic_ai — process-level sys.modules checks would depend on test order
        root = Path(__file__).resolve().parents[1] / "src" / "data_agent"
        offenders: list[str] = []
        files = list((root / "canvas").rglob("*.py")) + [root / "schemas" / "chart.py"]
        for f in files:
            src = f.read_text("utf-8")
            if "pydantic_ai" in src or "data_agent.agents" in src:
                offenders.append(str(f))
        assert offenders == []

    def test_draft_stamped_schema_then_column_lost_blocked(self, env, sales_binding):
        _, _, assets, svc = env
        v1 = bar_source().replace('RenderColumn(name="revenue"', 'RenderColumn(name="amount"')
        asset = assets.create(make_asset("stamp_bar", v1, sales_binding), v1)
        ok = svc.replay(asset.id)  # stamps city/amount (its own truth)
        assert ok.gate.passed
        v2 = v1.replace('RenderColumn(name="amount", dtype="float", values=revs),', "")
        assets.save_source(asset.id, v2)  # v2 loses the stamped column
        r2 = svc.replay(asset.id)
        assert not r2.gate.passed
        assert any("amount" in e for e in r2.gate.errors)


class TestKeepPreviousRender:
    def test_failed_replay_preserves_render_json(self, env, sales_binding):
        _, _, assets, svc = env
        asset = assets.create(make_asset("keep_bar", bar_source(), sales_binding), bar_source())
        assert svc.replay(asset.id).gate.passed
        before = assets.read_render(asset.id)[0]
        broken_src = bar_source().replace('df = ctx.data["sales"]', 'df = ctx.data["nope"]')
        assets.save_source(asset.id, broken_src)
        fail = svc.replay(asset.id)
        assert not fail.gate.passed
        assert assets.read_render(asset.id)[0] == before  # untouched
        # recovery: fix source, replay passes again
        assets.save_source(asset.id, bar_source())
        assert svc.replay(asset.id).gate.passed


class TestKernelHygiene:
    def test_pool_reset_clears_namespace_between_replays(self, env):
        # the replay guarantee lives at the pool layer: every replay starts from a
        # %reset -f'd kernel, so whatever a processor leaves in user_ns is gone next run
        _, _, _, svc = env
        sid = svc.pool.acquire()
        try:
            svc.pool.inner.execute(sid, "leaky = 42", timeout_s=10)
            assert svc.pool.reset(sid)
            r = svc.pool.inner.execute(sid, "print('leaky' in globals())", timeout_s=10)
            assert r.stdout.strip() == "False"
        finally:
            svc.pool.release(sid)

    def test_timeout_flags_gate(self, env, sales_binding, monkeypatch):
        from data_agent.canvas import replay as replay_mod

        _, _, assets, svc = env
        monkeypatch.setattr(replay_mod, "REPLAY_TIMEOUT_S", 4.0)
        slow = bar_source().replace(
            "def process(ctx):", "def process(ctx):\n    import time; time.sleep(15)")
        asset = assets.create(make_asset("slow_bar", slow, sales_binding), slow)
        r = svc.replay(asset.id)
        assert not r.gate.passed
        assert any("timed out" in e for e in r.gate.errors)
        # pool survived: normal asset still replays
        ok_src = bar_source()
        a2 = assets.create(make_asset("after_slow", ok_src, sales_binding), ok_src)
        assert svc.replay(a2.id).gate.passed


class TestDriftBroken:
    def test_hand_edited_source_marks_broken(self, env, sales_binding):
        _, _, assets, svc = env
        asset = assets.create(make_asset("hand_bar", bar_source(), sales_binding), bar_source())
        assert svc.replay(asset.id).gate.passed
        p = assets.path_of(asset.id) / "processor.py"
        p.write_text(p.read_text("utf-8") + "\n# sneaky hand edit\n", encoding="utf-8")
        got = assets.get(asset.id)
        assert got.status is AssetStatus.broken
        r = svc.replay(asset.id)
        assert not r.gate.passed and "drift" in r.gate.errors[0]
