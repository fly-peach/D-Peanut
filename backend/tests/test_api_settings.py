"""GET|PUT /api/settings skeleton: tiered write, masked read, no plaintext anywhere (1.4)."""

import pytest
from fastapi.testclient import TestClient

from data_agent.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    with TestClient(app) as c:
        yield c


def test_get_empty_view(client):
    body = client.get("/api/settings").json()
    assert body["settings"] == {}
    assert body["secrets"] == {}
    assert body["data_root"].endswith("data")


def test_put_splits_tiers(client):
    secret = "sk-verysecret-0000abcd"
    body = client.put(
        "/api/settings",
        json={
            "settings": {"privacy_mode_default": True, "profile_token_budget": 400},
            "secrets": {"llm.api_key": secret},
        },
    ).json()
    assert body["settings"]["profile_token_budget"] == 400
    assert body["secrets"] == {"llm.api_key": "****abcd"}
    assert secret not in client.get("/api/settings").text


def test_put_omitted_section_keeps_existing(client):
    client.put("/api/settings", json={"settings": {"a": 1}, "secrets": {"llm.api_key": "k-123456"}})
    body = client.put("/api/settings", json={"settings": {"a": 2}}).json()
    assert body["settings"]["a"] == 2
    assert body["secrets"] == {"llm.api_key": "****3456"}  # secrets section omitted → kept
