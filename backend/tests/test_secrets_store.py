"""SecretsStore: 0600 file, masking, unified redaction filter (task 1.3)."""

import os
import stat

import pytest

from data_agent.secrets_store import SecretsStore


@pytest.fixture()
def store(tmp_path):
    s = SecretsStore(tmp_path / "secrets.json")
    s.ensure()
    return s


def test_set_get_delete_roundtrip(store):
    assert store.get("a") is None
    store.set("a", "value-a")
    assert store.get("a") == "value-a"
    assert store.keys() == ["a"]
    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.read_all() == {}


def test_mask_shape():
    assert SecretsStore.mask("sk-abcdefghij1234") == "****1234"
    assert SecretsStore.mask("short") == "****hort"
    assert SecretsStore.mask("abcd") == "****"
    assert SecretsStore.mask("") == "****"


def test_masked_view(store):
    store.set("k", "secret-value-9876")
    view = store.masked_view()
    assert view == {"k": "****9876"}
    assert "secret-value" not in str(view)


def test_redact_scrubs_all_known_values(store):
    store.set("pw", "hunter2-secret")
    text = "connect failed for hunter2-secret at host"
    assert store.redact(text) == "connect failed for *** at host"
    # short values (<6 chars) are not replaced to avoid destroying ordinary text
    store.set("tiny", "ab")
    assert store.redact("abc") == "abc"


@pytest.mark.skipif(os.name != "posix", reason="unix mode bits")
def test_file_mode_0600(store):
    store.set("x", "y")
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600
