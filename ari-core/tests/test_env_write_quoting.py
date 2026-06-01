"""Guard: pin the .env-write quoting of the two api_settings write paths (req 08).

The config-precedence mapping found two near-identical .env upsert blocks in
api_settings.py that differ ONLY in quoting:
  - _api_save_env_key  writes  KEY="value"   (quoted)
  - _api_save_settings writes  KEY=value      (unquoted)
No test pinned this before. These guards lock the CURRENT behavior so the req-08
extraction of a shared `_upsert_env_key(name, value, *, quote)` helper (the path
is read internally from `_st._env_write_path`) stays byte-identical (the quoting
difference is preserved, not unified — unifying it would be a behavior change,
out of scope for a refactor).
"""
from __future__ import annotations

import json

import pytest

from ari.viz import state as _st
from ari.viz import api_settings


@pytest.fixture
def env_path(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setattr(_st, "_env_write_path", p, raising=False)
    yield p


def test_save_env_key_writes_quoted(env_path, monkeypatch):
    monkeypatch.delenv("SOME_TOKEN", raising=False)
    out = api_settings._api_save_env_key(
        json.dumps({"key": "SOME_TOKEN", "value": "abc123"}).encode()
    )
    assert out == {"ok": True}
    text = env_path.read_text()
    assert 'SOME_TOKEN="abc123"' in text  # _api_save_env_key quotes the value
    assert "SOME_TOKEN=abc123\n" not in text


def test_save_env_key_updates_existing_in_place(env_path, monkeypatch):
    env_path.write_text('FOO=keepme\nSOME_TOKEN="old"\nBAR=keep2\n')
    monkeypatch.delenv("SOME_TOKEN", raising=False)
    api_settings._api_save_env_key(
        json.dumps({"key": "SOME_TOKEN", "value": "new"}).encode()
    )
    lines = env_path.read_text().splitlines()
    # unrelated keys preserved, target replaced in place (quoted)
    assert "FOO=keepme" in lines
    assert "BAR=keep2" in lines
    assert 'SOME_TOKEN="new"' in lines
    assert sum(1 for l in lines if l.startswith("SOME_TOKEN=")) == 1


def test_save_settings_writes_api_key_unquoted(env_path, tmp_path, monkeypatch):
    # _api_save_settings routes a real api key into the provider env name in
    # .env, UNQUOTED. Needs an active checkpoint settings_path to not 400.
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(_st, "_settings_path", sp, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = {
        "llm_provider": "anthropic",
        "api_key": "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaa",  # >=20 chars, no "test"
    }
    out = api_settings._api_save_settings(json.dumps(body).encode())
    assert out.get("ok") is True
    text = env_path.read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-aaaaaaaaaaaaaaaaaaaaaaaa" in text
    # unquoted: the quoted form must NOT appear
    assert 'ANTHROPIC_API_KEY="' not in text
    # and the key must never be persisted in settings.json
    assert "api_key" not in sp.read_text()
