"""Datasets API end-to-end via TestClient (tasks 3.2/3.3; DoD #1 scenarios).

BackgroundTasks execute synchronously inside TestClient's ASGI call, so a POST
returning means the dataset is already scanned/profiled — no polling in tests.
"""

import json
import sqlite3
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from data_agent.main import app

DF = pd.DataFrame(
    {
        "month": ["2021-01", "2021-02", "2021-03"] * 4,
        "city": ["上海", "北京", "广州"] * 4,
        "revenue": [10.5, 20.0, 30.25, 11.0, 21.5, 31.0, 12.0, 22.0, 32.5, 13, 23, 33],
    }
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_ROOT", str(data))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as c:
        yield c, data


def wait_ready(client, ds_id, tries=50):
    for _ in range(tries):
        body = client.get(f"/api/datasets/{ds_id}").json()
        if body["scan_status"] in ("ready", "failed") and body["profile_status"] in (
            "ready",
            "failed",
        ):
            return body
        time.sleep(0.05)
    raise AssertionError(f"dataset {ds_id} never settled: {body}")


class TestFileRegistration:
    def test_csv_register_profile_preview(self, env):
        client, data = env
        (data / "sales.csv").write_text(DF.to_csv(index=False), encoding="utf-8")
        r = client.post("/api/datasets", json={"kind": "file", "path": str(data / "sales.csv")})
        assert r.status_code == 201
        ds = wait_ready(client, r.json()["datasets"][0])
        assert ds["scan_status"] == "ready" and ds["profile_status"] == "ready"

        prof = client.get(f"/api/datasets/{ds['id']}/profile").json()
        cols = {c["name"]: c for c in prof["columns"]}
        assert prof["row_count"] == 12
        assert cols["month"]["is_time"] is True
        assert cols["revenue"]["num_range"][0] == 10.5
        assert cols["city"]["top_values"]

        prev = client.get(f"/api/datasets/{ds['id']}/preview?n=3").json()
        assert prev["mode"] == "rows" and len(prev["rows"]) == 3 and prev["truncated"]

    def test_jail_rejected(self, env):
        client, _ = env
        r = client.post("/api/datasets", json={"kind": "file", "path": "/etc/passwd"})
        assert r.status_code == 400
        assert client.get("/api/datasets").json() == []

    def test_duplicate_name_409(self, env):
        client, data = env
        (data / "dup.csv").write_text(DF.to_csv(index=False), encoding="utf-8")
        first = client.post("/api/datasets", json={"kind": "file", "path": str(data / "dup.csv")})
        assert first.status_code == 201
        second = client.post("/api/datasets", json={"kind": "file", "path": str(data / "dup.csv")})
        assert second.status_code == 409

    def test_xlsx_multi_sheet_expands(self, env):
        client, data = env
        p = data / "book.xlsx"
        with pd.ExcelWriter(p, engine="openpyxl") as w:
            DF.to_excel(w, sheet_name="jan", index=False)
            DF.to_excel(w, sheet_name="feb", index=False)
        r = client.post("/api/datasets", json={"kind": "file", "path": str(p)})
        ids = r.json()["datasets"]
        assert len(ids) == 2
        for i in ids:
            assert wait_ready(client, i)["profile_status"] == "ready"


class TestFolderRegistration:
    def _mk(self, data):
        root = data / "sales"
        (root / "sub").mkdir(parents=True)
        for n, sub in (("a.csv", ""), ("b.csv", "sub/")):
            (root / sub / n).write_text(DF.to_csv(index=False), encoding="utf-8")
        (root / "bad.csv").write_bytes(b"\xff\xfe\x00garbage\x00\x00")
        return root

    def test_folder_expand_with_failure_isolation(self, env):
        client, data = env
        root = self._mk(data)
        r = client.post("/api/datasets", json={"kind": "folder", "root": str(root)})
        assert r.status_code == 201, r.text
        fid = r.json()["datasets"][0]
        assert wait_ready(client, fid)["scan_status"] == "ready"
        briefs = {b["name"]: b for b in client.get("/api/datasets?kind=file").json()}
        assert briefs["sales/a.csv"]["profile_status"] == "ready"
        assert briefs["sales/sub/b.csv"]["profile_status"] == "ready"
        assert briefs["sales/bad.csv"]["profile_status"] == "failed"
        # children are individually addressable + profiled
        prof = client.get(f"/api/datasets/{briefs['sales/a.csv']['id']}/profile").json()
        assert prof["row_count"] == 12

    def test_rescan_touches_only_changed(self, env):
        client, data = env
        root = self._mk(data)
        (root / "bad.csv").write_bytes(b"a,b\n1,2\n")  # make it valid before folder scan
        r = client.post("/api/datasets", json={"kind": "folder", "root": str(root)})
        fid = r.json()["datasets"][0]
        wait_ready(client, fid)
        before = {b["name"]: b["revision"] for b in client.get("/api/datasets?kind=file").json()}
        time.sleep(1.05)
        (root / "a.csv").write_text(DF.assign(extra=1).to_csv(index=False), encoding="utf-8")
        client.post(f"/api/datasets/{fid}/rescan")
        wait_ready(client, fid)
        after = {b["name"]: b["revision"] for b in client.get("/api/datasets?kind=file").json()}
        assert after["sales/a.csv"] != before["sales/a.csv"]
        assert after["sales/sub/b.csv"] == before["sales/sub/b.csv"]
        assert after["sales/bad.csv"] == before["sales/bad.csv"]


class TestSqlRegistration:
    def test_sqlite_registration_no_secret_leak(self, env):
        client, data = env
        db = data / "shop.db"
        conn = sqlite3.connect(db)
        DF.to_sql("orders", conn, index=False)
        conn.close()
        r = client.post("/api/datasets",
                        json={"kind": "sql", "conn_target": str(db), "table": "orders"})
        assert r.status_code == 201, r.text
        ds = wait_ready(client, r.json()["datasets"][0])
        prof = client.get(f"/api/datasets/{ds['id']}/profile").json()
        assert prof["row_count"] == 12
        # dataset JSON and settings view never carry the plaintext path beyond DATA jail label
        body = client.get(f"/api/datasets/{ds['id']}").text
        meta = json.loads(body)["meta"]
        assert "conn_ref" in meta and str(db) not in meta["conn_ref"]
        assert str(db) not in client.get("/api/settings").text

    def test_unknown_table_fails_dataset(self, env):
        client, data = env
        db = data / "x.db"
        sqlite3.connect(db).close()
        r = client.post("/api/datasets",
                        json={"kind": "sql", "conn_target": str(db), "table": "nope"})
        ds = wait_ready(client, r.json()["datasets"][0])
        assert ds["scan_status"] == "failed"
        assert "nope" in ds["last_error"]


class TestPrivacyAndLifecycle:
    def test_privacy_toggle_returns_summary_only(self, env):
        client, data = env
        (data / "p.csv").write_text(DF.to_csv(index=False), encoding="utf-8")
        r = client.post("/api/datasets", json={"kind": "file", "path": str(data / "p.csv")})
        did = r.json()["datasets"][0]
        wait_ready(client, did)
        assert client.get(f"/api/datasets/{did}/preview?n=2").json()["mode"] == "rows"
        client.patch(f"/api/datasets/{did}", json={"privacy_mode": True})
        body = client.get(f"/api/datasets/{did}/preview?n=2").json()
        assert body["mode"] == "summary"
        assert "上海" not in json.dumps(body, ensure_ascii=False)
        prof = client.get(f"/api/datasets/{did}/profile").json()
        assert all(not c["sample_values"] and not c["top_values"] for c in prof["columns"])

    def test_delete_cascade_and_parent_protection(self, env):
        client, data = env
        root = data / "f"
        root.mkdir()
        (root / "x.csv").write_text(DF.to_csv(index=False), encoding="utf-8")
        r = client.post("/api/datasets", json={"kind": "folder", "root": str(root)})
        fid = r.json()["datasets"][0]
        wait_ready(client, fid)
        child = client.get("/api/datasets").json()[1]
        assert client.delete(f"/api/datasets/{child['id']}").status_code == 409  # parent refers
        assert client.delete(f"/api/datasets/{fid}").status_code == 204
        assert client.get("/api/datasets").json() == []

    def test_missing_404(self, env):
        client, _ = env
        assert client.get("/api/datasets/ds_nope").status_code == 404
        assert client.get("/api/datasets/ds_nope/profile").status_code == 404
