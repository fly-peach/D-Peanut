"""Assets API end-to-end through the real app lifespan (kernels included)."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from data_agent.main import app

FIXTURE = (Path(__file__).parent / "fixtures" / "processors" / "bar_topn.py").read_text("utf-8")
SALES = pd.DataFrame({
    "month": ["2021-01", "2021-02"] * 3,
    "city": ["上海", "北京", "广州"] * 2,
    "revenue": [10.5, 20.0, 30.25, 11.0, 21.5, 31.0],
})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sales.csv").write_text(SALES.to_csv(index=False), encoding="utf-8")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as c:
        c.post("/api/datasets", json={"kind": "file", "path": str(tmp_path / "data" / "sales.csv")})
        yield c


def put_params(client, aid, top_n, ev):
    return client.put(f"/api/assets/{aid}/params",
                      json={"params": {"top_n": top_n}, "expected_version": ev})


def render_top(client, aid):
    r = client.get(f"/api/assets/{aid}/render").json()
    return r["render"]["tables"]["main"]["source"][0]["values"]


def create_asset(client, name="top_cities", top_n=5):
    return client.post("/api/assets", json={
        "name": name,
        "source": FIXTURE,
        "bindings": [{"alias": "sales", "dataset": "sales.csv"}],
        "chart_type": "bar",
        "params": {"top_n": top_n},
    })


class TestCreateAndRender:
    def test_create_validates_and_stamps(self, client):
        r = create_asset(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["gate"]["passed"] is True
        assert body["asset"]["status"] == "validated"
        asset_id = body["asset"]["id"]

        cold = client.get("/api/assets").json()
        row = next(x for x in cold if x["id"] == asset_id)
        assert row["has_render"] is True and row["chart_type"] == "bar"

        render = client.get(f"/api/assets/{asset_id}/render").json()
        cols = render["render"]["tables"]["main"]["dimensions"]
        assert cols == ["city", "revenue"]
        assert render["config"]["data_map"]["map"]["x"] == "main.city"

    def test_rejects_bad_source(self, client):
        r = client.post("/api/assets", json={
            "name": "nope", "source": "x = 1", "bindings": [], "chart_type": "bar"})
        assert r.status_code == 400 and "PARAM_SPEC" in r.text

    def test_rejects_unknown_dataset(self, client):
        r = client.post("/api/assets", json={
            "name": "n2", "source": FIXTURE,
            "bindings": [{"alias": "s", "dataset": "ghost.csv"}], "chart_type": "bar"})
        assert r.status_code == 400 and "ghost.csv" in r.text

    def test_duplicate_name_409(self, client):
        assert create_asset(client).status_code == 201
        r = create_asset(client, name="top_cities")
        assert r.status_code == 409


class TestParamsVersioningCas:
    def test_params_then_replay_bumps_version(self, client):
        aid = create_asset(client).json()["asset"]["id"]
        r = put_params(client, aid, 2, 1)
        assert r.status_code == 200
        assert r.json()["asset"]["version"] == 2 and r.json()["asset"]["status"] == "draft"
        rep = client.post(f"/api/assets/{aid}/replay").json()
        vals = rep["render"]["tables"]["main"]["source"][0]["values"]
        assert rep["gate"]["passed"] and len(vals) == 2

    def test_cas_conflict_409(self, client):
        aid = create_asset(client).json()["asset"]["id"]
        assert put_params(client, aid, 2, 1).status_code == 200
        assert put_params(client, aid, 3, 1).status_code == 409

    def test_param_validation_400(self, client):
        aid = create_asset(client).json()["asset"]["id"]
        r = client.put(f"/api/assets/{aid}/params",
                       json={"params": {"top_n": 9999, "bogus": 1}, "expected_version": 1})
        assert r.status_code == 400 and "max" in r.text and "bogus" in r.text

    def test_rollback_restores_render(self, client):
        aid = create_asset(client, top_n=5).json()["asset"]["id"]
        assert put_params(client, aid, 2, 1).status_code == 200
        client.post(f"/api/assets/{aid}/replay")
        assert len(render_top(client, aid)) == 2  # v2: top_n=2
        r = client.post(f"/api/assets/{aid}/rollback", json={"to_version": 1})
        assert r.status_code == 200 and r.json()["asset"]["version"] == 3
        # top_n=5 over 3 distinct cities → 3 rows (v1); top_n=2 would have been 2
        assert len(render_top(client, aid)) == 3
        hist = client.get(f"/api/assets/{aid}/history").json()
        assert 1 in hist["versions"] and len(hist["replays"]) >= 3

    def test_placement_and_delete(self, client):
        aid = create_asset(client, name="placey").json()["asset"]["id"]
        place = client.patch(f"/api/assets/{aid}/canvas",
                             json={"placement": {"x": 1, "y": 2, "w": 5, "h": 3, "z": 1}})
        assert place.status_code == 200
        assert client.delete(f"/api/assets/{aid}").status_code == 204
        assert client.get(f"/api/assets/{aid}").status_code == 404
        assert client.delete(f"/api/assets/{aid}").status_code == 404

    def test_history_missing_asset_404(self, client):
        assert client.get("/api/assets/ca_missing/history").status_code == 404
