"""Regression tests for the Letta start scripts.

These scripts launch the Letta server. Without them sourcing the
project's .env, provider API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY,
…) typed into Settings/.env never reach the Letta process. New agents
created with ``openai/text-embedding-3-small`` (the recommended
embedding handle to avoid the flaky ``embeddings.memgpt.ai`` upstream)
then fail at archival_insert with no key — surfaced to ari-skill-memory
as an opaque 400 ``Expecting value: line 1 column 1 (char 0)``.

Each deployment path has a different injection mechanism:

  - ``start_pip.sh``:        export $ARI_ROOT/.env into the shell
                             before ``letta server``
  - ``start_singularity.sh``: pass ``--env-file`` on
                             ``singularity instance start``
  - ``docker-compose.yml``:  ``env_file:`` directive on the
                             ``letta`` service

These tests are static — they assert the pattern is present in each
file. We don't actually spawn Letta from CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LETTA_DIR = REPO_ROOT / "scripts" / "letta"


def _read(p: Path) -> str:
    return p.read_text()


# ─ pip (default; what most ARI users hit) ──────────────────────────────

def test_pip_start_loads_dotenv_before_launch():
    """start_pip.sh must source $ARI_ROOT/.env so OPENAI_API_KEY etc.
    reach the Letta server."""
    src = _read(LETTA_DIR / "start_pip.sh")
    assert "ARI_ROOT" in src
    assert "ENV_FILE" in src
    # The loop must come before the actual launch line.
    launch_idx = src.find("letta server")
    assert launch_idx >= 0
    loader_idx = src.find("ENV_FILE")
    assert loader_idx >= 0 and loader_idx < launch_idx, (
        "ENV_FILE handling must run BEFORE `letta server`; otherwise "
        "the daemon never sees the exported keys."
    )


def test_pip_start_does_not_clobber_shell_keys():
    """If the user has already exported OPENAI_API_KEY in the shell,
    .env must NOT override it. Asserts the conditional-assignment
    idiom (``if [[ -z "${!key:-}" ]]``)."""
    src = _read(LETTA_DIR / "start_pip.sh")
    assert "${!key" in src or "if [[ -z" in src, (
        "start_pip.sh must guard against overriding pre-set shell vars"
    )


def test_pip_start_skips_comments_and_blanks():
    """The .env loader must skip ``# comments`` and blank lines so
    ``setup_env.sh``'s placeholder commented keys don't break parse."""
    src = _read(LETTA_DIR / "start_pip.sh")
    assert "^[[:space:]]*#" in src, "must skip comment lines"
    assert "^[[:space:]]*$" in src, "must skip blank lines"


# ─ singularity (HPC path) ──────────────────────────────────────────────

def test_singularity_start_passes_env_file():
    """start_singularity.sh must use ``--env-file`` so the host's .env
    crosses into the container. Apptainer scrubs most host env by
    default. The script now uses ``apptainer run`` (not ``instance
    start``) because Docker-derived SIFs have an empty %startscript;
    the ENV_ARGS array must be expanded onto that ``run`` invocation.
    """
    src = _read(LETTA_DIR / "start_singularity.sh")
    assert "--env-file" in src, (
        "start_singularity.sh must pass --env-file to apptainer run"
    )
    assert "ENV_FILE" in src
    # The flag must actually appear on a launch command. The script
    # backgrounds ``apptainer run``; ENV_ARGS must follow that.
    run_idx = src.find('"${RUNTIME}" run')
    assert run_idx >= 0, "expected `\"${RUNTIME}\" run` invocation"
    after = src[run_idx:run_idx + 600]
    assert "ENV_ARGS" in after or "--env-file" in after


# ─ docker-compose ──────────────────────────────────────────────────────

def test_docker_compose_uses_env_file_directive():
    """docker-compose.yml must include an ``env_file:`` directive on
    the letta service that points at $ARI_ROOT/.env."""
    import yaml
    doc = yaml.safe_load(_read(LETTA_DIR / "docker-compose.yml"))
    letta_svc = doc["services"]["letta"]
    assert "env_file" in letta_svc, (
        "docker-compose.yml letta service missing env_file directive"
    )
    files = letta_svc["env_file"]
    if isinstance(files, str):
        files = [files]
    # Path must reach the project's .env. Compose paths are relative
    # to the compose file's directory (scripts/letta/), so the .env
    # at the repo root is two levels up.
    assert any(f.endswith(".env") for f in files)
    assert any(".." in f for f in files), (
        "env_file path must be relative to the compose file"
    )


# ─ cross-script consistency ────────────────────────────────────────────

@pytest.mark.parametrize(
    "name", ["start_pip.sh", "start_singularity.sh"],
)
def test_start_script_resolves_ari_root_portably(name):
    """All start scripts must derive ARI_ROOT from BASH_SOURCE rather
    than hardcoding ``/home/...`` or assuming ``$PWD``. Otherwise the
    install fails when invoked from another directory."""
    src = _read(LETTA_DIR / name)
    assert "BASH_SOURCE" in src, (
        f"{name} must derive ARI_ROOT from BASH_SOURCE for portability"
    )


# ─ restart endpoint ────────────────────────────────────────────────────

def test_restart_endpoint_runs_stop_then_start(monkeypatch):
    """``_api_memory_restart`` must invoke ``stop_local`` and then
    ``start_local`` (in that order), threading through the body so a
    user-specified deployment ``path`` overrides auto-detection."""
    from ari.viz import api_memory as M

    calls: list[str] = []

    def fake_stop():
        calls.append("stop")
        return {"ok": True, "attempts": ["pkill rc=0"]}

    def fake_start(body):
        calls.append("start")
        import json
        data = json.loads(body) if body else {}
        return {"ok": True, "path": data.get("path", "auto"), "stdout": "ok"}

    # Skip the inter-phase sleep so the test stays fast.
    monkeypatch.setattr(M, "_api_memory_stop_local", fake_stop)
    monkeypatch.setattr(M, "_api_memory_start_local", fake_start)
    monkeypatch.setattr(M.time, "sleep", lambda *_a, **_kw: None)

    r = M._api_memory_restart(b'{"path": "pip"}')
    assert calls == ["stop", "start"], (
        f"stop must come before start; got {calls}"
    )
    assert r["ok"] is True
    assert r["start"]["path"] == "pip"
    assert r["stop"]["ok"] is True


def test_restart_endpoint_failure_propagates():
    """If start_local fails, ``ok`` must be False so the GUI can show
    a clear error instead of pretending the restart succeeded."""
    from ari.viz import api_memory as M

    def fake_start(_body):
        return {"ok": False, "error": "boom"}

    import unittest.mock as _mock
    with _mock.patch.object(M, "_api_memory_stop_local", return_value={"ok": True}), \
         _mock.patch.object(M, "_api_memory_start_local", side_effect=fake_start), \
         _mock.patch.object(M.time, "sleep"):
        r = M._api_memory_restart(b'')
    assert r["ok"] is False
    assert r["start"]["error"] == "boom"


def test_server_routes_restart_endpoint():
    """server.py must wire POST /api/memory/restart → _api_memory_restart."""
    src = (Path(__file__).resolve().parents[1] / "ari" / "viz" / "server.py").read_text()
    assert "/api/memory/restart" in src
    assert "_api_memory_restart" in src
