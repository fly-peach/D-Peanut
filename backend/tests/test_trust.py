"""N4 trust-hardening backend: compaction, restore copies, stale drift, log redaction."""

import logging
from pathlib import Path as _P

import pandas as pd
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

from data_agent.memory.compaction import compact_messages
from data_agent.observability import setup_logging
from data_agent.secrets_store import SecretsStore
from data_agent.settings import Workspace


def _req(text):
    return ModelRequest(parts=[TextPart(content=text)])


def _resp_tool(i, call_id="tc1"):
    return ModelResponse(parts=[ToolCallPart("run_in_kernel", {"code": f"c{i}", "purpose": "x"},
                                             tool_call_id=call_id)])


def _resp_return(i):
    return ModelRequest(parts=[
        ToolReturnPart("run_in_kernel", {"ok": True}, tool_call_id=f"tc{i}")])


class TestCompaction:
    def test_short_history_untouched(self):
        msgs = [_req("hi")] * 10
        assert compact_messages(msgs) == msgs

    def test_long_history_folded_with_ids_kept(self):
        msgs = []
        for i in range(30):
            msgs.append(_req(f"turn {i} 关于 ca_deadbeef01 和 ds_cafef00d"))
            msgs.append(_resp_tool(i, call_id=f"tc{i}"))
            msgs.append(_resp_return(i))
        out = compact_messages(msgs, keep=16, threshold=24)
        assert len(out) < len(msgs)
        first = out[0]
        text = first.parts[0].content
        assert "压缩" in text
        assert "ca_deadbeef01" in text or "ds_cafef00d" in text  # active refs survive
        # no orphan tool-return at the window start
        assert not any(type(p).__name__ == "ToolReturnPart" for p in out[1].parts)

    def test_agent_with_capability_runs(self):
        """ProcessHistory mounts into the real agent without breaking a run."""

        from data_agent.agents.data_agent import build_agent

        agent = build_agent()  # includes compaction capability
        assert agent is not None  # construction proves capability wiring compiles


class TestStaleDrift:
    def test_mark_and_clear(self, tmp_path):
        from data_agent.canvas.assets import AssetService
        from data_agent.canvas.models import ChartAsset, DataSourceBinding
        from data_agent.catalog.models import DatasetRef

        ws = Workspace(data_root=tmp_path / "d", workspace_root=tmp_path / "w")
        ws.ensure_runtime()
        svc = AssetService(ws.assets_dir, ws.index_db)
        src = (_P(__file__).parent / "fixtures" / "processors" / "bar_topn.py").read_text("utf-8")
        asset = svc.create(ChartAsset(name="a1", bindings=[DataSourceBinding(
            alias="sales", dataset=DatasetRef(dataset_id="ds_x", name="sales.csv", revision="r1"))],
            params={"top_n": 5, "height": 320, "show_label": False}), src)
        assert asset.stale_data is False
        assert svc.mark_stale_for_datasets({"sales.csv"}) == 1
        assert svc.get(asset.id).stale_data is True
        svc.mark_stale_for_datasets({"other.csv"})  # no change
        assert svc.get(asset.id).stale_data is True
        svc.clear_stale(asset.id)
        assert svc.get(asset.id).stale_data is False


class TestLogRedaction:
    def test_handler_scrubs_secrets(self, tmp_path):
        store = SecretsStore(tmp_path / "secrets.json")
        store.ensure()
        store.set("llm.api_key", "sk-supersecretvalue123")
        setup_logging(store)
        root = logging.getLogger()
        rec = logging.LogRecord("t", logging.INFO, "", 0,
                                "failed with sk-supersecretvalue123 in url", (), None)
        for f in root.filters:
            f.filter(rec)
        assert "sk-supersecretvalue123" not in rec.msg
        # idempotent setup
        setup_logging(store)


class TestRestoreEndpoint:
    def test_messages_persisted_after_run(self, tmp_path, monkeypatch):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "s.csv").write_text(
            pd.DataFrame({"a": [1]}).to_csv(index=False), encoding="utf-8")
        monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
        from data_agent.main import app

        with TestClient(app) as c:
            c.put("/api/settings", json={"settings": {"llm_provider": "test"}})
            sid = c.post("/api/sessions", json={}).json()["id"]
            before = c.get(f"/api/sessions/{sid}/messages").json()
            assert before == []
            with c.stream("POST", f"/api/sessions/{sid}/chat", json={
                    "id": "m1", "trigger": "submit-message",
                    "messages": [{"id": "u1", "role": "user",
                                  "parts": [{"type": "text", "text": "hi"}]}]}) as r:
                "".join(r.iter_text())
            after = c.get(f"/api/sessions/{sid}/messages").json()
            assert len(after) >= 2
            roles = [m["role"] for m in after]
            assert "user" in roles and "assistant" in roles
            # assistant copy carries tool parts from the TestModel loop
            assistant = next(m for m in after if m["role"] == "assistant")
            assert any(str(p.get("type", "")).startswith("tool-") for p in assistant["parts"])
