"""Tests for the SLURM dispatch path of ``run_reproduce``.

Restored in the v0.6.x rewrite after being lost in the §4.1 paper-re
overhaul (the v0.5.0 ``Executor`` class supported local/slurm/pbs/lsf;
the rewrite replaced it with sandbox-only kinds and accidentally dropped
slurm).

These tests mock ``which sbatch`` and ``sbatch`` itself so they run on
machines without SLURM installed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location("paper_re_server_slurm", SRC / "server.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_server_slurm"] = S
_spec.loader.exec_module(S)


# ── _phase1_sandbox_kind auto detection ─────────────────────────────────

def test_auto_picks_slurm_when_sbatch_and_partition_present(monkeypatch):
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    monkeypatch.delenv("ARI_PHASE1_SANDBOX", raising=False)
    with patch.object(S, "_has_bin", lambda name: name in ("sbatch", "apptainer")):
        with patch.object(S, "_docker_works", lambda: True):
            assert S._phase1_sandbox_kind() == "slurm"


def test_auto_skips_slurm_without_partition(monkeypatch):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("ARI_PHASE1_SANDBOX", raising=False)
    monkeypatch.delenv("SLURM_CLUSTER_NAME", raising=False)
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    with patch.object(S, "_has_bin", lambda name: name in ("sbatch", "apptainer")):
        with patch.object(S, "_docker_works", lambda: True):
            # No partition → sbatch alone is not enough. Falls through to
            # docker (since not on HPC).
            assert S._phase1_sandbox_kind() == "docker"


def test_auto_skips_slurm_without_sbatch(monkeypatch):
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    monkeypatch.delenv("ARI_PHASE1_SANDBOX", raising=False)
    with patch.object(S, "_has_bin", lambda name: name == "apptainer"):
        with patch.object(S, "_docker_works", lambda: False):
            # sbatch missing → apptainer wins.
            assert S._phase1_sandbox_kind() == "apptainer"


def test_explicit_env_override_wins(monkeypatch):
    monkeypatch.setenv("ARI_PHASE1_SANDBOX", "local")
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    with patch.object(S, "_has_bin", lambda name: True):
        assert S._phase1_sandbox_kind() == "local"


# ── _resolve_partition_for_repo precedence ──────────────────────────────

def test_partition_arg_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_SLURM_PARTITION", "from-env")
    assert S._resolve_partition_for_repo(tmp_path, partition="from-arg") == "from-arg"


def test_partition_env_wins_over_launch_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_SLURM_PARTITION", "from-env")
    ckpt = tmp_path / "ckpt"
    repo = ckpt / "repro_sandbox"
    repo.mkdir(parents=True)
    (ckpt / "launch_config.json").write_text(json.dumps({"partition": "from-launch"}))
    assert S._resolve_partition_for_repo(repo) == "from-env"


def test_partition_falls_back_to_launch_config(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("SLURM_PARTITION", raising=False)
    ckpt = tmp_path / "ckpt"
    repo = ckpt / "repro_sandbox"
    repo.mkdir(parents=True)
    (ckpt / "launch_config.json").write_text(json.dumps({"partition": "sx40"}))
    assert S._resolve_partition_for_repo(repo) == "sx40"


def test_partition_returns_empty_when_nothing_resolves(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("SLURM_PARTITION", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    assert S._resolve_partition_for_repo(repo) == ""


# ── _walltime_str ────────────────────────────────────────────────────────

def test_walltime_str_formats_correctly():
    assert S._walltime_str(3600) == "01:00:00"
    assert S._walltime_str(90) == "00:01:30"
    # Floor under 60s.
    assert S._walltime_str(0) == "00:01:00"


# ── _run_reproduce_slurm: command construction ──────────────────────────

class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "Submitted batch job 1234\n",
                 stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _setup_slurm(tmp_path: Path, *, with_partition: bool = True, monkeypatch=None):
    """Build a sandbox dir with reproduce.sh + launch_config (or env)."""
    repo = tmp_path / "repro_sandbox"
    repo.mkdir(parents=True)
    (repo / "reproduce.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"
    )
    if with_partition:
        # Use the parent-checkpoint path convention.
        (tmp_path / "launch_config.json").write_text(
            json.dumps({"partition": "sx40"})
        )
    return repo


def test_slurm_dispatch_constructs_correct_sbatch_command(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path)
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.setenv("ARI_SLURM_CPUS", "16")
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        # sbatch --wait writes the job's output to --output file; emulate
        # by creating the log file so the post-check passes.
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ok\n")
        return _FakeProc(returncode=0)

    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            res = S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
            )

    assert res["executed"] is True
    assert res["exit_code"] == 0
    assert res["partition"] == "sx40"
    assert res["cpus"] == 16
    cmd = captured["cmd"]
    assert cmd[0] == "sbatch"
    assert "--wait" in cmd
    assert cmd[cmd.index("--partition") + 1] == "sx40"
    assert cmd[cmd.index("--cpus-per-task") + 1] == "16"
    assert cmd[cmd.index("--chdir") + 1] == str(repo)
    assert cmd[cmd.index("--output") + 1] == str(repo / "reproduce.log")
    # We submit a wrapper that exec's reproduce.sh by absolute path so $0
    # in the user script resolves correctly (sbatch otherwise spools the
    # script and breaks ``$(dirname "$0")``).
    submitted = Path(cmd[-1])
    assert submitted == repo / ".slurm_wrap.sh"
    wrapper_text = submitted.read_text()
    assert "exec bash" in wrapper_text
    assert str(repo / "reproduce.sh") in wrapper_text


def test_slurm_dispatch_falls_back_to_local_without_sbatch(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    with patch.object(S, "_has_bin", lambda n: False):
        # No subprocess.run patch needed — _run_reproduce_local handles it.
        res = S._run_reproduce_slurm(repo, repo / "reproduce.log", timeout=10)
    # _run_reproduce_local was used → result has no partition key.
    assert "partition" not in res


def test_slurm_dispatch_falls_back_when_partition_unresolved(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path, with_partition=False)
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("SLURM_PARTITION", raising=False)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        res = S._run_reproduce_slurm(repo, repo / "reproduce.log", timeout=10)
    # No partition → fell back to local.
    assert "partition" not in res


def test_slurm_dispatch_surfaces_sbatch_errors(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")

    def fake_run(cmd, **kw):
        return _FakeProc(returncode=1, stdout="", stderr="bad partition\n")

    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            res = S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
            )

    # No log file was produced AND sbatch exit code != 0 → executed=False.
    assert res["executed"] is False
    assert res["exit_code"] == 1
    assert "bad partition" in res["error"]


# ── run_reproduce MCP tool: sandbox_kind=slurm dispatch ─────────────────

@pytest.mark.asyncio
async def test_run_reproduce_dispatches_to_slurm_when_kind_explicit(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({
        "reproduce_contract": {"max_runtime_sec": 60, "expected_artifacts": []},
    }))

    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ran on slurm\n")
        return _FakeProc(returncode=0)

    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            res = await S.run_reproduce(
                rubric_path=str(rubric),
                repo_dir=str(repo),
                sandbox_kind="slurm",
                partition="sx40",
                cpus=8,
            )

    assert res["sandbox_kind"] == "slurm"
    assert res["executed"] is True
    assert res["exit_code"] == 0
    assert res["partition"] == "sx40"
    assert "sbatch" in captured["cmd"][0]


@pytest.mark.asyncio
async def test_run_reproduce_returns_unknown_sandbox_error(tmp_path):
    repo = _setup_slurm(tmp_path)
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({"reproduce_contract": {"max_runtime_sec": 60}}))
    res = await S.run_reproduce(
        rubric_path=str(rubric),
        repo_dir=str(repo),
        sandbox_kind="quantum-foam",
    )
    assert "unknown sandbox_kind" in res["error"]
