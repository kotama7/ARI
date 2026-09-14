"""gui_refresh task 06 Wave 4d — secret assignment PUT + model catalog.

ADR-05 (Wave-4 delivery of the canonical secret write) and plan 05
§Configuration API:

- ``PUT /api/v1/secrets/{secret_id}`` — write-only assignment restricted to
  the ``ari.viz.v1.secrets.SECRET_NAMES`` allowlist (404 otherwise); body is
  exactly ``{"value": "<non-empty string>"}`` (unknown keys / non-string /
  empty-after-strip / newline-control characters → 400); the write delegates
  to the hardened ``api_settings._upsert_env_key`` (atomic 0o600 upsert +
  live ``os.environ`` export); the response is the post-write READINESS row
  only — the value NEVER appears in any serialized response;
- readiness flip: a name reporting ``configured=False`` before the PUT
  reports ``configured=True`` (with a source class) afterwards, from the
  same ``GET /api/v1/secrets/status`` the Studio SecretField displays;
- ``GET /api/v1/config/catalogs/models`` — the legacy ``GET /api/models``
  static provider/model suggestions re-served single-source, plus the
  per-provider env-key names (``PROVIDER_ENV_KEYS``), every one of which
  must be a ``SECRET_NAMES`` member.

Deterministic: handlers called via ``v1.router.dispatch``; the .env chain is
redirected into ``tmp_path`` by monkeypatching the ``api_settings.__file__``
anchor, ``Path.home``, the active checkpoint, and ``state._env_write_path``
— the same technique as ``test_gui_secret_readiness.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import api_settings
from ari.viz import state as _st
from ari.viz.checkpoint_api import _api_models
from ari.viz.v1.catalogs import PROVIDER_ENV_KEYS, get_model_catalog
from ari.viz.v1.router import dispatch, match
from ari.viz.v1.secrets import SECRET_NAMES

FAKE_VALUE = "sk-proj-FAKEFAKEFAKE9001"


@pytest.fixture
def env_root(tmp_path, monkeypatch) -> Path:
    """An isolated .env world: ``tmp_path`` is the ARI root (api_settings
    re-anchored), ``tmp_path/home`` is $HOME, ``tmp_path/ckpt`` the active
    checkpoint, and the legacy write path targets ``tmp_path/.env``."""
    fake_file = tmp_path / "ari-core" / "ari" / "viz" / "api_settings.py"
    fake_file.parent.mkdir(parents=True)
    monkeypatch.setattr(api_settings, "__file__", str(fake_file))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")

    for name in SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _put(secret_id: str, body: dict | bytes) -> dict:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return dispatch("PUT", f"/api/v1/secrets/{secret_id}", body=raw)


# ══════════════════════════════════════════════════════════════════════════
# 1. PUT /api/v1/secrets/{secret_id} — routing + validation envelopes
# ══════════════════════════════════════════════════════════════════════════


class TestPutSecretValidation:
    def test_route_is_registered(self):
        hit = match("/api/v1/secrets/OPENAI_API_KEY", method="PUT")
        assert hit is not None
        assert hit[0].__name__ == "_handle_put_secret"
        assert hit[1] == {"secret_id": "OPENAI_API_KEY"}

    def test_unknown_secret_id_is_404(self, env_root):
        r = _put("NOT_ON_ALLOWLIST", {"value": FAKE_VALUE})
        assert r["_status"] == 404
        assert r["error"]["code"] == "not_found"
        # nothing was written
        assert not (env_root / ".env").exists()

    def test_status_is_not_a_valid_secret_id(self, env_root):
        # The GET /secrets/status literal can never alias into the PUT
        # resource space: 'status' is not on the allowlist.
        r = _put("status", {"value": FAKE_VALUE})
        assert r["_status"] == 404

    @pytest.mark.parametrize(
        "body",
        [
            {},  # value missing
            {"value": ""},  # empty
            {"value": "   "},  # empty after strip (legacy strip rule)
            {"value": 123},  # not a string
            {"value": None},
            {"value": "ok", "extra": 1},  # unknown body key
            {"value": "a\nOTHER_KEY=b"},  # newline injection
            {"value": "a\rb"},
            {"value": "a\x00b"},
            {"value": "a\x7fb"},
        ],
    )
    def test_invalid_bodies_are_400_and_write_nothing(self, env_root, body):
        r = _put("OPENAI_API_KEY", body)
        assert r["_status"] == 400
        assert r["error"]["code"] == "invalid_request"
        assert not (env_root / ".env").exists()

    def test_malformed_json_body_is_400(self, env_root):
        r = _put("OPENAI_API_KEY", b"{not json")
        assert r["_status"] == 400
        assert r["error"]["code"] == "invalid_request"


# ══════════════════════════════════════════════════════════════════════════
# 2. PUT happy path — hardened write, readiness flip, no value echo
# ══════════════════════════════════════════════════════════════════════════


class TestPutSecretHappyPath:
    def test_readiness_flips_after_put(self, env_root):
        before = dispatch("GET", "/api/v1/secrets/status")
        by_name = {s["name"]: s for s in before["secrets"]}
        assert by_name["OPENAI_API_KEY"]["configured"] is False

        r = _put("OPENAI_API_KEY", {"value": FAKE_VALUE})
        assert "_status" not in r  # 200
        assert r["schema_version"] == 1
        assert r["secret"]["name"] == "OPENAI_API_KEY"
        assert r["secret"]["configured"] is True
        assert r["secret"]["source_class"] == "repo_env"

        after = dispatch("GET", "/api/v1/secrets/status")
        by_name = {s["name"]: s for s in after["secrets"]}
        assert by_name["OPENAI_API_KEY"]["configured"] is True
        assert by_name["OPENAI_API_KEY"]["source_class"] == "repo_env"

    def test_put_delegates_to_hardened_upsert(self, env_root):
        _put("SEMANTIC_SCHOLAR_API_KEY", {"value": FAKE_VALUE})
        env_path = env_root / ".env"
        assert env_path.exists()
        # env-key editor on-disk form (quote=True) + owner-only mode.
        assert f'SEMANTIC_SCHOLAR_API_KEY="{FAKE_VALUE}"' in env_path.read_text()
        assert (env_path.stat().st_mode & 0o777) == 0o600
        # live export (the launch subprocess environment sees it).
        import os

        assert os.environ["SEMANTIC_SCHOLAR_API_KEY"] == FAKE_VALUE

    def test_put_strips_value_like_the_legacy_editor(self, env_root):
        _put("ZENODO_TOKEN", {"value": f"  {FAKE_VALUE}  "})
        assert f'ZENODO_TOKEN="{FAKE_VALUE}"' in (env_root / ".env").read_text()

    def test_response_never_echoes_the_value(self, env_root):
        r = _put("OPENAI_API_KEY", {"value": FAKE_VALUE})
        assert FAKE_VALUE not in json.dumps(r)
        # ... and the readiness read stays value-free too.
        assert FAKE_VALUE not in json.dumps(
            dispatch("GET", "/api/v1/secrets/status")
        )

    def test_second_put_replaces_in_place(self, env_root):
        _put("OPENAI_API_KEY", {"value": FAKE_VALUE})
        _put("OPENAI_API_KEY", {"value": "sk-proj-FAKEFAKEFAKE9002"})
        text = (env_root / ".env").read_text()
        assert text.count("OPENAI_API_KEY=") == 1
        assert FAKE_VALUE not in text


# ══════════════════════════════════════════════════════════════════════════
# 3. GET /api/v1/config/catalogs/models — single-source catalog
# ══════════════════════════════════════════════════════════════════════════


class TestModelCatalog:
    def test_route_is_registered(self):
        hit = match("/api/v1/config/catalogs/models")
        assert hit is not None
        assert hit[0].__name__ == "_handle_get_model_catalog"

    def test_catalog_mirrors_legacy_api_models(self):
        r = dispatch("GET", "/api/v1/config/catalogs/models")
        assert r["schema_version"] == 1
        legacy = _api_models()["providers"]
        assert [(p["id"], p["name"], p["models"]) for p in r["providers"]] == [
            (p["id"], p["name"], p["models"]) for p in legacy
        ]

    def test_env_keys_join_and_allowlist_membership(self):
        r = dispatch("GET", "/api/v1/config/catalogs/models")
        by_id = {p["id"]: p for p in r["providers"]}
        # The exact _api_save_settings provider map, keyless providers None.
        assert by_id["openai"]["env_key"] == "OPENAI_API_KEY"
        assert by_id["anthropic"]["env_key"] == "ANTHROPIC_API_KEY"
        assert by_id["gemini"]["env_key"] == "GOOGLE_API_KEY"
        assert by_id["ollama"]["env_key"] is None
        assert by_id["cli-shim"]["env_key"] is None
        # Every catalog env key must be PUT-able (SECRET_NAMES member).
        assert set(PROVIDER_ENV_KEYS.values()) <= set(SECRET_NAMES)

    def test_catalog_is_deterministic(self):
        a = get_model_catalog().model_dump()
        b = get_model_catalog().model_dump()
        assert a == b
