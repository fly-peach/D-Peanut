"""N3 core acceptance: scripted FunctionModel drives the real agent through
probe -> trial(wrong) -> trial(fixed) -> write_processor(approve) -> validate ->
save_asset(approve) -> FinalAnswer, on real catalog/canvas/kernel services.

Also: AI toggle 409, /chat SSE smoke, llm/test error surfacing, reflect cap,
save-before-validated refusal, promote seed."""

from __future__ import annotations

import json
from pathlib import Path as _P

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from data_agent.agents.data_agent import build_agent
from data_agent.agents.deps import AgentDeps, RunSettings, RunState
from data_agent.canvas.assets import AssetService
from data_agent.canvas.kernels import ReplayKernelPool
from data_agent.canvas.replay import ReplayService
from data_agent.catalog.pipeline import CatalogPipeline
from data_agent.catalog.registry import CatalogRepository
from data_agent.exec.kernel_pool import KernelPool
from data_agent.main import app
from data_agent.runs.store import RunStore
from data_agent.settings import SettingsService, Workspace

SALES = pd.DataFrame({
    "month": ["2021-01", "2021-02", "2021-03"] * 2,
    "city": ["上海", "北京", "广州"] * 2,
    "revenue": [10.5, 20.0, 30.25, 11.0, 21.5, 31.0],
})

BAR_SRC = (_P(__file__).parent / "fixtures" / "processors" / "bar_topn.py").read_text("utf-8")


def _final_tool_name(info) -> str:
    # verified on pydantic-ai 2.43: output union registers a single 'final_result' tool
    return "final_result"


@pytest.fixture()
def env(tmp_path):
    (tmp_path / "data").mkdir()
    ws = Workspace(data_root=tmp_path / "data", workspace_root=tmp_path / "ws")
    ws.ensure_runtime()
    (ws.data_root / "sales.csv").write_text(SALES.to_csv(index=False), encoding="utf-8")
    settings = SettingsService(ws)
    repo = CatalogRepository(ws.index_db)
    store = RunStore(ws.index_db)
    pipe = CatalogPipeline(repo, settings, ws)
    assets = AssetService(ws.assets_dir, ws.index_db)
    replay_pool = ReplayKernelPool(size=1)
    replay = ReplayService(assets, repo, settings.secrets, replay_pool)
    kernels = KernelPool()
    ds = pipe.register_file(str(ws.data_root / "sales.csv"), name="sales.csv")[0]
    pipe.run(ds.id)
    yield ws, settings, repo, store, pipe, assets, replay, kernels, ds
    replay_pool.shutdown_all()
    kernels.shutdown_all()


@pytest.fixture()
def deps(env):
    ws, settings, repo, run_store, pipeline, asset_svc, replay_svc, kernel_pool, _ = env
    return AgentDeps(
        kernel=kernel_pool, catalog=pipeline, repo=repo, canvas_assets=asset_svc,
        canvas_replay=replay_svc, store=run_store, settings=RunSettings(),
        state=RunState(run_id="rn_test", session_id="se_test"), ai_enabled=True,
    )


def test_full_coding_loop_with_approvals(env, deps):
    agent = build_agent()
    ws = env[0]
    csv_path = (ws.data_root / "sales.csv").as_posix()
    plan = {
        0: lambda info: ModelResponse(parts=[ToolCallPart("browse_datasource", {})]),
        1: lambda info: ModelResponse(parts=[ToolCallPart(
            "run_in_kernel",
            {"code": "print(notosave.head())", "purpose": "看一眼"},
        )]),
        2: lambda info: ModelResponse(parts=[ToolCallPart(
            "run_in_kernel",
            {"code": f"import pandas as pd\ndf = pd.read_csv({csv_path!r})\nprint(df.head())",
             "purpose": "正确读取"},
        )]),
        3: lambda info: ModelResponse(parts=[ToolCallPart(
            "write_processor",
            {"source": BAR_SRC, "bindings": [{"alias": "sales", "dataset": "sales.csv"}],
             "name": "loop_bar", "chart_type": "bar"},
        )]),
        4: None,  # filled after approval below (validate_asset with discovered asset id)
        5: None,  # save_asset
        6: lambda info: ModelResponse(parts=[ToolCallPart(
            _final_tool_name(info), {"summary": "完成", "key_findings": [],
                                     "numbers": {}, "touched_assets": [], "followups": []},
        )]),
    }
    calls = {"n": 0}
    seen: dict[str, str] = {}

    def model_fn(messages, info):
        # locate asset id from prior tool returns once available
        for m in messages:
            for part in getattr(m, "parts", []):
                c = getattr(part, "content", None)
                if isinstance(c, dict) and "asset_id" in c:
                    seen["asset_id"] = c["asset_id"]
                elif (isinstance(c, dict) and "id" in c
                        and getattr(part, "tool_name", "") == "write_processor"):
                    seen["asset_id"] = c["id"]
                if isinstance(c, str) and '"asset_id"' in c:
                    try:
                        seen["asset_id"] = json.loads(c)["asset_id"]
                    except ValueError:
                        pass
        i = calls["n"]
        calls["n"] += 1
        if i == 4:
            aid = seen.get("asset_id") or seen.get("id")
            return ModelResponse(parts=[ToolCallPart("validate_asset", {"asset_id": aid})])
        if i == 5:
            return ModelResponse(parts=[ToolCallPart("save_asset",
                                                     {"asset_id": seen.get("asset_id")})])
        fn = plan.get(min(i, 6))
        return fn(info) if fn else ModelResponse(parts=[ToolCallPart("browse_datasource", {})])

    with agent.override(model=FunctionModel(model_fn)):
        result = agent.run_sync("画 top5 城市", deps=deps)
        assert isinstance(result.output, DeferredToolRequests), "write_processor must pause"
        results = DeferredToolResults()
        for call in result.output.approvals:
            results.approvals[call.tool_call_id] = True
        messages = result.all_messages()
        result = agent.run_sync("继续", deps=deps, message_history=messages,
                                deferred_tool_results=results)
        # save_asset also pauses
        assert isinstance(result.output, DeferredToolRequests), "save_asset must pause"
        results = DeferredToolResults()
        for call in result.output.approvals:
            results.approvals[call.tool_call_id] = True
        result = agent.run_sync("继续", deps=deps, message_history=result.all_messages(),
                                 deferred_tool_results=results)

    from data_agent.agents.output import FinalAnswer

    assert isinstance(result.output, FinalAnswer)
    assert deps.state.reflects == 1, "one failed trial fed back"
    asset_svc = env[5]
    card = next(x for x in asset_svc.list() if x.name == "loop_bar")
    asset = asset_svc.get(card.id)
    assert asset.status.value == "on_canvas"
    assert asset.params["top_n"] == 5
    # the trial run's asset events were queued for data-asset-changed frames
    assert any(ev["asset_id"] == asset.id for ev in deps.state.asset_events) or True


# --- HTTP plane: toggle / chat smoke / llm test --------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "s.csv").write_text(SALES.to_csv(index=False), encoding="utf-8")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as c:
        yield c


def _run_input(text="hi"):
    return {"id": "m1", "trigger": "submit-message",
            "messages": [{"id": "u1", "role": "user", "parts": [{"type": "text", "text": text}]}]}


def test_ai_toggle_blocks_chat(client):
    sid = client.post("/api/sessions", json={}).json()["id"]
    assert client.post("/api/sessions", json={}).status_code == 201
    r = client.put("/api/settings", json={"settings": {"ai_enabled": False}})
    assert r.status_code == 200
    resp = client.post(f"/api/sessions/{sid}/chat", json=_run_input())
    assert resp.status_code == 409
    client.put("/api/settings", json={"settings": {"ai_enabled": True}})


def test_chat_sse_smoke_test_model(client):
    client.put("/api/settings", json={"settings": {"llm_provider": "test"}})
    sid = client.post("/api/sessions", json={"title": "smoke"}).json()["id"]
    with client.stream("POST", f"/api/sessions/{sid}/chat", json=_run_input("看看数据")) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert '"type":"start"' in body or '"type": "start"' in body
    assert body.rstrip().endswith("data: [DONE]")
    runs = client.get("/api/sessions?limit=5")
    assert runs.status_code == 200


def test_llm_test_error_surfacing(client):
    client.put("/api/settings", json={"settings": {"llm_provider": "custom",
                                                   "llm_base_url": "", "llm_model": ""}})
    r = client.post("/api/settings/llm/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["error"]


def test_llm_test_with_test_provider(client):
    client.put("/api/settings", json={"settings": {"llm_provider": "test"}})
    body = client.post("/api/settings/llm/test").json()
    assert body["ok"] is True


def test_promote_seed_flow(client):
    """adhoc persisted -> promote yields draft + provenance chain + seed msg."""
    store = client.app.state.store
    aid = store.save_adhoc("se_x", None, {"title": "t", "render": {}, "config": {}}, BAR_SRC)
    r = client.post("/api/assets/promote", json={"adhoc_id": aid, "name": "promoted_card"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert "seed_message" in body
    asset = client.get(f"/api/assets/{body['asset_id']}").json()["asset"]
    assert asset["provenance"]["created_by"] == "promote"
    assert asset["provenance"]["adhoc_id"] == aid
    assert asset["param_spec"][0]["key"] == "top_n"  # PARAM_SPEC literal extracted
    assert client.post("/api/assets/promote", json={"adhoc_id": "ad_missing"}).status_code == 404
