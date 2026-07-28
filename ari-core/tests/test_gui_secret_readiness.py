"""gui_refresh Wave 3a — secret readiness API + env-keys redaction.

RR-P0-2 / ADR-11 / MN-2 (plan 09 §Secret policy): the GUI may learn WHETHER a
secret is configured, never its value.

Covered here:

- ``GET /api/v1/secrets/status`` happy path against a tmp .env chain
  (project > repo > user precedence, ``source_class`` vocabulary, mtime as
  ``last_updated``, ``process_env`` fallback, first-occurrence-wins);
- value-leak guard: the fake secret strings never appear anywhere in the
  serialized readiness payload (structural: ``SecretV1`` has no value field);
- legacy ``GET /api/env-keys`` redaction: values replaced by
  ``***configured***`` (``""`` when empty), ``source`` map unchanged,
  top-level ``redacted: true`` marker, plaintext absent;
- ``POST /api/env-keys`` name allowlist (``^[A-Z][A-Z0-9_]{0,63}$``, no
  newline/control chars) rejects with ``_status`` 400 and writes nothing;
- ``POST /api/env-keys`` happy path unchanged (quoted upsert + live export).

Deterministic: handlers called directly / via ``v1.router.dispatch``; the
.env chain is redirected into ``tmp_path`` by monkeypatching the module
``__file__`` anchor, ``Path.home`` and the active checkpoint — the same
technique as ``test_gui_errors.TestGetEnvKeys``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import api_settings
from ari.viz import state as _st
from ari.viz.v1.router import dispatch, match
from ari.viz.v1.secrets import SECRET_NAMES, get_secrets_status

FAKE_OPENAI = "sk-proj-FAKEFAKEFAKE0001"
FAKE_ANTHROPIC = "sk-ant-FAKEFAKEFAKE0002"
FAKE_GEMINI = "AIzaFAKEFAKEFAKE0003"
FAKE_LETTA = "letta-FAKEFAKEFAKE0004"

_ALL_FAKES = (FAKE_OPENAI, FAKE_ANTHROPIC, FAKE_GEMINI, FAKE_LETTA)


@pytest.fixture
def env_chain(tmp_path, monkeypatch):
    """A full tmp .env chain: project (checkpoint) > repo (ARI/.env) > user.

    Layout: ``tmp_path`` acts as the ARI root (api_settings.__file__ is
    re-anchored under ``tmp_path/ari-core/ari/viz/``), ``tmp_path/home`` as
    $HOME, ``tmp_path/ckpt`` as the active checkpoint.
    """
    fake_file = tmp_path / "ari-core" / "ari" / "viz" / "api_settings.py"
    fake_file.parent.mkdir(parents=True)
    monkeypatch.setattr(api_settings, "__file__", str(fake_file))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

    for name in SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)

    # project .env wins for OPENAI; repo .env for ANTHROPIC; user for GEMINI.
    (ckpt / ".env").write_text(f"OPENAI_API_KEY={FAKE_OPENAI}\n")
    (tmp_path / ".env").write_text(
        f'ANTHROPIC_API_KEY="{FAKE_ANTHROPIC}"\n'
        f"OPENAI_API_KEY=shadowed-by-project\n"
    )
    (home / ".env").write_text(f"GEMINI_API_KEY='{FAKE_GEMINI}'\n")
    return {"root": tmp_path, "home": home, "ckpt": ckpt}


# ══════════════════════════════════════════════════════════════════════════
# 1. GET /api/v1/secrets/status — readiness happy path
# ══════════════════════════════════════════════════════════════════════════


class TestSecretsStatusReadiness:
    def test_route_is_registered(self):
        hit = match("/api/v1/secrets/status")
        assert hit is not None
        assert hit[0].__name__ == "_handle_secrets_status"

    def test_happy_path_source_class_and_mtime(self, env_chain, monkeypatch):
        # RR-P0-2 / ADR-11 / MN-2: readiness only, per source class.
        monkeypatch.setenv("LETTA_API_KEY", FAKE_LETTA)  # process_env fallback
        r = dispatch("GET", "/api/v1/secrets/status")
        assert r["schema_version"] == 1
        by_name = {s["name"]: s for s in r["secrets"]}
        assert list(by_name.keys()) == list(SECRET_NAMES)  # fixed order

        # project .env wins over the repo .env definition of the same name.
        s = by_name["OPENAI_API_KEY"]
        assert s["configured"] is True
        assert s["source_class"] == "project_env"
        exp = (env_chain["ckpt"] / ".env").stat().st_mtime
        from datetime import datetime, timezone
        assert s["last_updated"] == datetime.fromtimestamp(
            exp, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        assert by_name["ANTHROPIC_API_KEY"]["source_class"] == "repo_env"
        assert by_name["ANTHROPIC_API_KEY"]["configured"] is True
        assert by_name["GEMINI_API_KEY"]["source_class"] == "user_env"
        assert by_name["GEMINI_API_KEY"]["configured"] is True

        # process_env: configured, no file, no mtime.
        s = by_name["LETTA_API_KEY"]
        assert s["configured"] is True
        assert s["source_class"] == "process_env"
        assert s["last_updated"] is None

        # never configured anywhere.
        s = by_name["SEMANTIC_SCHOLAR_API_KEY"]
        assert s == {
            "name": "SEMANTIC_SCHOLAR_API_KEY",
            "configured": False,
            "source_class": None,
            "last_updated": None,
        }

    def test_empty_env_value_reports_not_configured(self, env_chain):
        (env_chain["ckpt"] / ".env").write_text("OPENAI_API_KEY=\n")
        r = get_secrets_status().model_dump()
        s = {x["name"]: x for x in r["secrets"]}["OPENAI_API_KEY"]
        # first-occurrence-wins: the empty project definition shadows the
        # repo one (mirrors the legacy _api_get_env_keys semantics).
        assert s["configured"] is False
        assert s["source_class"] == "project_env"

    def test_no_value_ever_in_serialized_payload(self, env_chain, monkeypatch):
        # RR-P0-2 / ADR-11: the fake key strings must NOT appear anywhere in
        # the wire payload, under any key.
        monkeypatch.setenv("LETTA_API_KEY", FAKE_LETTA)
        wire = json.dumps(dispatch("GET", "/api/v1/secrets/status"))
        for fake in _ALL_FAKES:
            assert fake not in wire
        assert "shadowed-by-project" not in wire

    def test_readiness_get_is_read_only(self, env_chain):
        import os

        env_before = dict(os.environ)
        files_before = {
            str(p): p.stat().st_mtime_ns
            for p in env_chain["root"].rglob("*")
            if p.is_file()
        }
        dispatch("GET", "/api/v1/secrets/status")
        assert dict(os.environ) == env_before
        assert files_before == {
            str(p): p.stat().st_mtime_ns
            for p in env_chain["root"].rglob("*")
            if p.is_file()
        }


# ══════════════════════════════════════════════════════════════════════════
# 2. Legacy GET /api/env-keys — redacted (RR-P0-2 close)
# ══════════════════════════════════════════════════════════════════════════


class TestEnvKeysRedaction:
    def test_values_redacted_and_marker_present(self, env_chain):
        # RR-P0-2 / ADR-11 / MN-2: plaintext values are gone for good.
        r = api_settings._api_get_env_keys()
        assert r["redacted"] is True
        assert r["keys"]["OPENAI_API_KEY"] == "***configured***"
        assert r["keys"]["ANTHROPIC_API_KEY"] == "***configured***"
        wire = json.dumps(r)
        for fake in _ALL_FAKES:
            assert fake not in wire

    def test_source_map_unchanged(self, env_chain):
        # RR-P0-2 / ADR-11 / MN-2: 'source' still names the winning file.
        r = api_settings._api_get_env_keys()
        assert r["source"]["OPENAI_API_KEY"] == str(env_chain["ckpt"] / ".env")
        assert r["source"]["ANTHROPIC_API_KEY"] == str(
            env_chain["root"] / ".env"
        )

    def test_empty_value_stays_empty_string(self, env_chain):
        (env_chain["ckpt"] / ".env").write_text("EMPTY_API_KEY=\n")
        r = api_settings._api_get_env_keys()
        assert r["keys"]["EMPTY_API_KEY"] == ""

    def test_os_environ_fallback_is_redacted_too(self, env_chain, monkeypatch):
        (env_chain["ckpt"] / ".env").write_text("")
        (env_chain["root"] / ".env").write_text("")
        (env_chain["home"] / ".env").write_text("")
        monkeypatch.setenv("GOOGLE_API_KEY", "proc-env-secret-0005")
        r = api_settings._api_get_env_keys()
        assert r["keys"]["GOOGLE_API_KEY"] == "***configured***"
        assert r["source"]["GOOGLE_API_KEY"] == "os.environ"
        assert "proc-env-secret-0005" not in json.dumps(r)


# ══════════════════════════════════════════════════════════════════════════
# 3. POST /api/env-keys — name allowlist; happy path unchanged
# ══════════════════════════════════════════════════════════════════════════


def _post_env_key(name: str, value: str = "some-value-123") -> dict:
    return api_settings._api_save_env_key(
        json.dumps({"key": name, "value": value}).encode()
    )


@pytest.fixture
def env_write_path(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setattr(_st, "_env_write_path", p, raising=False)
    return p


class TestSaveEnvKeyNameAllowlist:
    # plan 09 §Secret policy / ADR-11: reject names outside
    # ^[A-Z][A-Z0-9_]{0,63}$ or carrying newline/control chars, with 400.

    @pytest.mark.parametrize(
        "bad_name",
        ["lower", "HAS NEWLINE\n", "x" * 80, "1STARTS_WITH_DIGIT",
         "_UNDERSCORE_FIRST", "TAB\tNAME", "A" * 65, "PATH/TRAVERSAL"],
    )
    def test_rejected_with_400_and_no_write(self, env_write_path, bad_name):
        out = _post_env_key(bad_name)
        assert out["ok"] is False
        assert out["_status"] == 400
        assert "invalid key name" in out["error"]
        assert not env_write_path.exists()  # nothing written

    def test_embedded_newline_rejected_even_after_strip(self, env_write_path):
        # 'VALID\n'.strip() would pass the regex — the raw-name control-char
        # check must still reject it (a newline in a .env line is an
        # injection vector).
        out = _post_env_key("VALID_NAME\n")
        assert out["ok"] is False and out["_status"] == 400
        assert not env_write_path.exists()

    def test_max_length_64_accepted_65_rejected(self, env_write_path, monkeypatch):
        name64 = "A" + "B" * 63
        monkeypatch.delenv(name64, raising=False)
        assert _post_env_key(name64) == {"ok": True}
        out = _post_env_key("A" + "B" * 64)
        assert out["ok"] is False and out["_status"] == 400

    def test_happy_path_unchanged(self, env_write_path, monkeypatch):
        # Frozen legacy write behavior (test_env_write_quoting.py): quoted
        # form, in-place upsert, live os.environ export, {"ok": True}.
        import os

        monkeypatch.delenv("SOME_TOKEN", raising=False)
        out = _post_env_key("SOME_TOKEN", "abc123")
        assert out == {"ok": True}
        assert 'SOME_TOKEN="abc123"' in env_write_path.read_text()
        assert os.environ.get("SOME_TOKEN") == "abc123"

    def test_empty_key_value_legacy_error_unchanged(self, env_write_path):
        # The pre-existing required-field check still answers first (200-path
        # legacy payload, no _status) — frozen by test_gui_errors §10.
        out = api_settings._api_save_env_key(
            json.dumps({"key": "", "value": "v"}).encode()
        )
        assert out == {"ok": False, "error": "key and value required"}


class TestUpsertEnvKeyHardening:
    """RR-P0-4 remaining-scope hardening (gui_refresh Wave 3b): the .env
    upsert is atomic (same-dir tmp + os.replace) and owner-only (0o600).
    Closes the atomicity/permission half of risk register RR-P0-4; the
    name allowlist / control-char half landed in Wave 3a (ADR-11)."""

    def test_env_file_is_owner_only_after_upsert(self, env_write_path):
        import os

        api_settings._upsert_env_key("OPENAI_API_KEY", "sk-test-mode-check", quote=True)
        mode = os.stat(env_write_path).st_mode & 0o777
        assert mode == 0o600, f"project .env must be owner-only, got {oct(mode)}"

    def test_interrupted_replace_leaves_original_intact(self, env_write_path, monkeypatch):
        import os

        api_settings._upsert_env_key("OPENAI_API_KEY", "sk-original-value00", quote=True)
        before = env_write_path.read_text()

        def boom(src, dst):
            raise OSError("simulated crash during replace")

        monkeypatch.setattr(api_settings.os, "replace", boom)
        with pytest.raises(OSError, match="simulated crash"):
            api_settings._upsert_env_key("OPENAI_API_KEY", "sk-new-value-000000", quote=True)
        monkeypatch.undo()

        assert env_write_path.read_text() == before, ".env must be untouched on crash"
        leftovers = [p for p in env_write_path.parent.iterdir() if p.name.startswith(".env.tmp-")]
        assert leftovers == [], f"orphan tmp files must be cleaned up: {leftovers}"
