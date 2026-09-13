"""Workspace bootstrap, path jail, SettingsService tiering (tasks 1.1/1.4)."""

import json
from pathlib import Path

import pytest

from data_agent.settings import JailError, SettingsService, Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "data").mkdir()
    return Workspace(data_root=tmp_path / "data", workspace_root=tmp_path / "ws")


class TestWorkspace:
    def test_env_priority(self, tmp_path):
        ws = Workspace.from_env(
            {"DATA_ROOT": str(tmp_path / "d1"), "WORKSPACE_ROOT": str(tmp_path / "w1")}
        )
        assert ws.data_root == (tmp_path / "d1").resolve()
        assert ws.workspace_root == (tmp_path / "w1").resolve()

    def test_default_fallback_is_cwd_relative(self):
        ws = Workspace.from_env({})
        assert not ws.data_root.is_absolute() or ws.data_root == Path("data").resolve()
        assert str(ws.workspace_root).replace("\\", "/").endswith(".data/workspace")

    def test_ensure_runtime_creates_layout(self, tmp_path):
        ws = make_ws(tmp_path)
        ws.ensure_runtime()
        assert (ws.workspace_root / "assets").is_dir()
        assert (ws.workspace_root / "drafts").is_dir()
        assert (ws.workspace_root / "secrets.json").is_file()

    def test_jail_allows_inside_and_root(self, tmp_path):
        ws = make_ws(tmp_path)
        inside = ws.data_root / "sales" / "a.csv"
        assert ws.jail(str(inside)) == inside.resolve()
        assert ws.jail(str(ws.data_root)) == ws.data_root

    def test_jail_rejects_escape(self, tmp_path):
        ws = make_ws(tmp_path)
        (tmp_path / "outside").mkdir()
        with pytest.raises(JailError):
            ws.jail(str(tmp_path / "outside" / "secret.csv"))
        with pytest.raises(JailError):
            ws.jail("../escape.csv")
        with pytest.raises(JailError):
            ws.jail("sub/../../escape.csv")


class TestSettingsService:
    @pytest.fixture()
    def service(self, tmp_path):
        ws = make_ws(tmp_path)
        ws.ensure_runtime()
        return SettingsService(ws)

    def test_settings_roundtrip(self, service):
        view = service.update(settings={"privacy_mode_default": True, "preview_max": 50})
        assert view["settings"]["privacy_mode_default"] is True
        assert service.get_setting("privacy_mode_default") is True
        assert service.get_setting("missing", default="x") == "x"

    def test_secrets_masked_and_never_plaintext(self, service):
        secret = "sk-proj-supersecret-abcdef1234"
        service.update(secrets={"llm.api_key": secret, "sql.mydb": "postgres://u:p@h/db"})
        view = service.get_view()
        assert view["secrets"]["llm.api_key"].startswith("****")
        assert view["secrets"]["llm.api_key"].endswith("1234")
        assert secret not in json.dumps(view, ensure_ascii=False)
        assert "u:p@h" not in json.dumps(view, ensure_ascii=False)

    def test_put_semantics_omitted_keeps_empty_clears(self, service):
        service.update(secrets={"llm.api_key": "sk-aaaa1111"})
        service.update(settings={"a": 1})  # secrets omitted → kept
        assert service.secrets.get("llm.api_key") == "sk-aaaa1111"
        service.update(secrets={"llm.api_key": ""})  # explicit empty → cleared
        assert service.secrets.get("llm.api_key") is None
        assert service.get_setting("a") == 1

    def test_secret_plaintext_never_touches_index_db(self, service, tmp_path):
        service.update(secrets={"sql.db": "sqlite:///very/private/path"})
        service.update(settings={"x": 1})
        db_bytes = (tmp_path / "ws" / "index.db").read_bytes()
        assert b"very/private/path" not in db_bytes
