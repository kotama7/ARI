"""Tests for the reproducibility sandbox shim.

Coverage:
- T-3: ``git clone <paper-URL>`` is rewritten to ``ari clone --expect-sha256``
- T-4: ``git status`` / ``git log`` / non-clone subcommands are passed through
- T-5: ``clone_policy=deny`` causes external clones to exit 13
- T-9: (removed) — build_repro_report deletion in §4.1 of rubric.md.

The shim is a bash script. We test it by writing a fake ``git`` and
``ari`` to a tmp dir and putting them on PATH, then running the shim
script with controlled env vars. This avoids requiring a live MCP run.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ari.agent.react_driver import setup_sandbox_shims, restore_env, snapshot_env


SHIM_SRC = Path(__file__).parent.parent / "ari" / "agent" / "shims" / "git.sh"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_git(tmp_path: Path) -> Path:
    """A 'real git' that just records its argv into a sentinel file."""
    sentinel = tmp_path / "git.argv"
    fake = tmp_path / "fake_git"
    body = f'''#!/usr/bin/env bash
echo "real-git: $@" > "{sentinel}"
exit 0
'''
    _write_executable(fake, body)
    return fake


def _make_fake_ari(tmp_path: Path) -> Path:
    """A 'real ari' that records its argv to a sentinel file."""
    sentinel = tmp_path / "ari.argv"
    fake = tmp_path / "fake_ari"
    body = f'''#!/usr/bin/env bash
echo "real-ari: $@" > "{sentinel}"
exit 0
'''
    _write_executable(fake, body)
    return fake


def _run_shim(
    shim_src: Path,
    args: list[str],
    *,
    real_git: Path,
    fake_ari: Path,
    sandbox: Path,
    paper_ref: str = "",
    paper_sha: str = "",
    policy: str = "passthrough",
) -> subprocess.CompletedProcess:
    sandbox.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "ARI_REAL_GIT": str(real_git),
        "ARI_REPRO_CODE_AVAIL_REF": paper_ref,
        "ARI_REPRO_CODE_AVAIL_SHA256": paper_sha,
        "ARI_REPRO_CLONE_POLICY": policy,
        "ARI_REPRO_CLONE_LOG": str(sandbox / "repro_clone_log.jsonl"),
        # Make sure the shim's "exec ari clone ..." finds our fake.
        "PATH": f"{fake_ari.parent}{os.pathsep}{env.get('PATH', '')}",
    })
    # Run the shim *script* directly (not via setup_sandbox_shims) so we don't
    # need to copy it; pass argv through.
    return subprocess.run(
        ["bash", str(shim_src), *args],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# T-3: rewrite scenarios
# ---------------------------------------------------------------------------

PAPER_REF = "ari://abc123"
PAPER_SHA = "f" * 64


def test_shim_rewrites_paper_ref_clone(tmp_path: Path):
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    fake_ari.rename(fake_ari.parent / "ari")
    fake_ari = fake_ari.parent / "ari"
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, ["clone", PAPER_REF, "dest"],
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref=PAPER_REF, paper_sha=PAPER_SHA,
    )
    assert res.returncode == 0, res.stderr
    # Real git must NOT have been called.
    assert not (tmp_path / "git.argv").exists()
    # Fake ari must have been called with `clone <ref> <dest> --expect-sha256 ...`.
    ari_args = (tmp_path / "ari.argv").read_text().strip()
    assert "clone" in ari_args
    assert PAPER_REF in ari_args
    assert PAPER_SHA in ari_args
    # Log line written.
    log_path = sandbox / "repro_clone_log.jsonl"
    assert log_path.exists()
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["action"] == "rewrite"


def test_shim_rewrites_gh_ref_via_https_form(tmp_path: Path):
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    fake_ari.rename(fake_ari.parent / "ari")
    fake_ari = fake_ari.parent / "ari"
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, ["clone", "https://github.com/user/repo.git"],
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref="gh:user/repo", paper_sha=PAPER_SHA,
    )
    assert res.returncode == 0, res.stderr
    ari_args = (tmp_path / "ari.argv").read_text().strip()
    assert "gh:user/repo" in ari_args


# ---------------------------------------------------------------------------
# T-4: retain test — non-clone git subcommands pass through
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "argv",
    [
        ["status"],
        ["log", "--oneline"],
        ["submodule", "update", "--init"],
        ["fetch", "origin"],
        ["clone", "--help"],  # No URL argv → pass through to real git --help
    ],
)
def test_shim_passes_through_non_clone(tmp_path: Path, argv: list[str]):
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, argv,
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref=PAPER_REF, paper_sha=PAPER_SHA,
    )
    assert res.returncode == 0, res.stderr
    # Real git WAS called.
    assert (tmp_path / "git.argv").exists()
    # ari was NOT called.
    assert not (tmp_path / "ari.argv").exists()


def test_shim_passthrough_other_url_default(tmp_path: Path):
    """Default policy is passthrough — clone of an unrelated URL hits real git."""
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, ["clone", "https://github.com/random/lib.git"],
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref=PAPER_REF, paper_sha=PAPER_SHA,
        policy="passthrough",
    )
    assert res.returncode == 0
    assert (tmp_path / "git.argv").exists()
    assert not (tmp_path / "ari.argv").exists()
    log_path = sandbox / "repro_clone_log.jsonl"
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["action"] == "passthrough"


# ---------------------------------------------------------------------------
# T-5: clone_policy=deny
# ---------------------------------------------------------------------------

def test_shim_denies_external_clone_when_policy_deny(tmp_path: Path):
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, ["clone", "https://github.com/random/lib.git"],
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref=PAPER_REF, paper_sha=PAPER_SHA,
        policy="deny",
    )
    assert res.returncode == 13
    assert "denied" in res.stderr.lower()
    assert not (tmp_path / "git.argv").exists()
    log_path = sandbox / "repro_clone_log.jsonl"
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["action"] == "deny"


def test_shim_warn_policy_logs_but_passes_through(tmp_path: Path):
    real_git = _make_fake_git(tmp_path)
    fake_ari = _make_fake_ari(tmp_path)
    sandbox = tmp_path / "sandbox"
    res = _run_shim(
        SHIM_SRC, ["clone", "https://github.com/random/lib.git"],
        real_git=real_git, fake_ari=fake_ari, sandbox=sandbox,
        paper_ref=PAPER_REF, paper_sha=PAPER_SHA,
        policy="warn",
    )
    assert res.returncode == 0
    assert (tmp_path / "git.argv").exists()
    assert "warn" in res.stderr.lower()
    log_path = sandbox / "repro_clone_log.jsonl"
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["action"] == "warn"


# ---------------------------------------------------------------------------
# setup_sandbox_shims helper: env vars are well-formed
# ---------------------------------------------------------------------------

def test_setup_sandbox_shims_emits_expected_env(tmp_path: Path):
    sandbox = tmp_path / "s"
    env = setup_sandbox_shims(
        sandbox,
        code_availability_ref="ari://x",
        code_availability_sha256="ABCDEF" + "0" * 58,
        clone_policy="deny",
    )
    assert env["ARI_REPRO_CODE_AVAIL_REF"] == "ari://x"
    # sha256 normalised to lowercase
    assert env["ARI_REPRO_CODE_AVAIL_SHA256"] == ("abcdef" + "0" * 58)
    assert env["ARI_REPRO_CLONE_POLICY"] == "deny"
    # Shim is on disk and executable.
    shim = sandbox / ".shims" / "git"
    assert shim.exists()
    assert os.access(shim, os.X_OK)
    # PATH starts with our shim dir.
    assert env["PATH"].startswith(str(sandbox / ".shims"))


def test_snapshot_and_restore_env_roundtrip(monkeypatch):
    monkeypatch.setenv("PATH", "/x:/y:/z")
    monkeypatch.delenv("ARI_REAL_GIT", raising=False)
    snap = snapshot_env(["PATH", "ARI_REAL_GIT"])
    os.environ["PATH"] = "/changed"
    os.environ["ARI_REAL_GIT"] = "/whatever"
    restore_env(snap)
    assert os.environ["PATH"] == "/x:/y:/z"
    assert "ARI_REAL_GIT" not in os.environ


# T-9 removed: build_repro_report and its _summarise_clone_log helper were
# deleted in the §4.1 rewrite (see rubric.md §4.1). The git shim still emits
# repro_clone_log.jsonl during Phase 1 — downstream consumers that need the
# breakdown should re-implement a JSONL reader if/when the count is surfaced
# by a future tool.
