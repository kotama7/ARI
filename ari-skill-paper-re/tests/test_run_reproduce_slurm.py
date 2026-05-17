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


# ── v0.7.2: shared FS heuristic ──────────────────────────────────────────


def test_is_shared_fs_recognises_home(tmp_path, monkeypatch):
    home = Path.home()
    assert S._is_shared_fs(home) is True


def test_is_shared_fs_rejects_tmp():
    assert S._is_shared_fs(Path("/tmp/foo")) is False
    assert S._is_shared_fs(Path("/var/tmp/x")) is False


def test_is_shared_fs_recognises_typical_shared_prefixes():
    assert S._is_shared_fs(Path("/work/user/repo")) is True
    assert S._is_shared_fs(Path("/scratch/run-42")) is True
    assert S._is_shared_fs(Path("/lustre/foo")) is True
    assert S._is_shared_fs(Path("/nfs/bar")) is True


# ── v0.7.2: GRES probe ──────────────────────────────────────────────────


def test_slurm_has_gres_false_without_sinfo():
    with patch.object(S, "_has_bin", lambda n: n != "sinfo"):
        assert S._slurm_has_gres() is False


def test_slurm_has_gres_true_when_sinfo_reports_gpu():
    def fake_run(cmd, **kw):
        return _FakeProc(returncode=0, stdout="gpu:v100:4\ngpu:a100:8\n", stderr="")
    with patch.object(S, "_has_bin", lambda n: n == "sinfo"):
        with patch.object(S.subprocess, "run", fake_run):
            assert S._slurm_has_gres() is True


def test_slurm_has_gres_false_when_sinfo_reports_null():
    def fake_run(cmd, **kw):
        return _FakeProc(returncode=0, stdout="(null)\n(null)\n", stderr="")
    with patch.object(S, "_has_bin", lambda n: n == "sinfo"):
        with patch.object(S.subprocess, "run", fake_run):
            assert S._slurm_has_gres() is False


# ── v0.7.2: 15-arg sbatch command construction (S6-S10) ─────────────────


def _capture_cmd_call(captured: dict):
    """Helper: return a fake subprocess.run that captures cmd + creates the
    --output file so post-checks pass."""
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ok\n")
        return _FakeProc(returncode=0)
    return fake_run


def _patch_slurm_has_gres(monkeypatch, has_gres: bool):
    monkeypatch.setattr(S, "_slurm_has_gres", lambda: has_gres)
    # Most tests assume a modern SLURM that accepts --cpu-bind /
    # --mem-bind at sbatch level. The sx40 sandbox in production reality
    # does not — see test_cpu_bind_dropped_when_sbatch_does_not_support_it
    # for the regression guard. Default to True here so the suite stays
    # readable; override per-test for the drop path.
    monkeypatch.setattr(S, "_sbatch_supports", lambda flag: True)


def test_S6_exclusive_arg_appears_in_sbatch(tmp_path, monkeypatch):
    """S6: exclusive=True → ``--exclusive`` in sbatch cmd."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                exclusive=True,
            )
    assert "--exclusive" in captured["cmd"]


def test_S7_memory_arg_appears_in_sbatch(tmp_path, monkeypatch):
    """S7: memory_gb_per_node=128 → ``--mem=128G`` in sbatch cmd."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                memory_gb_per_node=128,
            )
    assert "--mem=128G" in captured["cmd"]


def test_S7b_memory_per_cpu_arg_appears_in_sbatch(tmp_path, monkeypatch):
    """S7b: memory_gb_per_cpu=4 → ``--mem-per-cpu=4G`` in sbatch cmd."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                memory_gb_per_cpu=4,
            )
    assert "--mem-per-cpu=4G" in captured["cmd"]


def test_S8_gpu_type_combined_with_per_task(tmp_path, monkeypatch):
    """S8: gpu_type="v100", gpus_per_task=2 → ``--gres=gpu:v100:2`` AND
    ``--gpus-per-task 2`` both present."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                gpus_per_task=2, gpu_type="v100",
            )
    cmd = captured["cmd"]
    assert "--gres=gpu:v100:2" in cmd
    assert cmd[cmd.index("--gpus-per-task") + 1] == "2"


def test_S9_hw_constraint_and_cpu_bind(tmp_path, monkeypatch):
    """S9: constraint="skylake", cpu_bind="cores" → both as ``--FLAG=VAL``."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                constraint="skylake", cpu_bind="cores",
            )
    cmd = captured["cmd"]
    assert "--constraint=skylake" in cmd
    assert "--cpu-bind=cores" in cmd


def test_S10_extra_sbatch_args_pass_through(tmp_path, monkeypatch):
    """S10: extra_sbatch_args=["--hint=nomultithread", "--account=projX"]
    appears verbatim before the wrapper path."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                extra_sbatch_args=["--account=projX", "--reservation=res1"],
            )
    cmd = captured["cmd"]
    assert "--account=projX" in cmd
    assert "--reservation=res1" in cmd


def test_S11_complex_profile_all_args_emitted(tmp_path, monkeypatch):
    """S11: 16-arg full profile produces every expected flag in one sbatch."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=7200,
                nodes=4, ntasks=32, ntasks_per_node=8,
                nodelist="node[01-04]", exclude_nodes="badnode01",
                exclusive=True,
                gpus_per_task=1, gpus_per_node=4, gpu_type="v100",
                memory_gb_per_node=256, memory_gb_per_cpu=8,
                constraint="skylake", cpu_bind="cores",
                mem_bind="local", hint="nomultithread",
                extra_sbatch_args=["--account=projX"],
            )
    cmd = captured["cmd"]
    # Pair-style flags
    assert cmd[cmd.index("--nodes") + 1] == "4"
    assert cmd[cmd.index("--ntasks") + 1] == "32"
    assert cmd[cmd.index("--ntasks-per-node") + 1] == "8"
    assert cmd[cmd.index("--nodelist") + 1] == "node[01-04]"
    assert cmd[cmd.index("--exclude") + 1] == "badnode01"
    assert cmd[cmd.index("--gpus-per-task") + 1] == "1"
    assert cmd[cmd.index("--gpus-per-node") + 1] == "4"
    # Standalone / KEY=VAL flags
    assert "--exclusive" in cmd
    assert "--gres=gpu:v100:1" in cmd
    assert "--mem=256G" in cmd
    assert "--mem-per-cpu=8G" in cmd
    assert "--constraint=skylake" in cmd
    assert "--cpu-bind=cores" in cmd
    assert "--mem-bind=local" in cmd
    assert "--hint=nomultithread" in cmd
    assert "--account=projX" in cmd


def test_gpu_flags_all_dropped_when_cluster_has_no_gres(tmp_path, monkeypatch):
    """T15 / S13 (v0.7.2 real-SLURM smoke finding): GRES-less cluster —
    ALL GPU-related flags (``--gres``, ``--gpus-per-task``,
    ``--gpus-per-node``) must be dropped, not just ``--gres``. Modern
    SLURM rejects every GPU resource request with ``Invalid generic
    resource (gres) specification`` when GRES is unconfigured, even when
    physical GPUs are visible on the host. The agent prompt's CLUSTER
    SHAPE block still surfaces the visible GPUs via nvidia-smi, so the
    replicator can use them at runtime without going through SLURM.
    """
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, False)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                gpus_per_task=1, gpus_per_node=4, gpu_type="v100",
            )
    cmd = captured["cmd"]
    assert all(not c.startswith("--gres=") for c in cmd), cmd
    assert "--gpus-per-task" not in cmd, cmd
    assert "--gpus-per-node" not in cmd, cmd


def test_cpu_bind_dropped_when_sbatch_does_not_support_it(tmp_path, monkeypatch):
    """v0.7.2 real-SLURM smoke finding: ``--cpu-bind`` / ``--mem-bind``
    are documented srun-only on many SLURM versions (incl. sx40). When
    ``sbatch --help`` does not advertise them, the implementation must
    drop them silently with a warning rather than letting sbatch reject
    the whole submission with "unrecognized option".
    """
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    # Override: this local sbatch does NOT support --cpu-bind / --mem-bind
    monkeypatch.setattr(S, "_sbatch_supports", lambda flag: False)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                cpu_bind="cores", mem_bind="local",
            )
    cmd = captured["cmd"]
    assert all(not c.startswith("--cpu-bind") for c in cmd), cmd
    assert all(not c.startswith("--mem-bind") for c in cmd), cmd


def test_S4_nodelist_arg_propagates(tmp_path, monkeypatch):
    """S4: nodelist="sx40" → ``--nodelist sx40`` in sbatch cmd. Used when
    operator wants to pin a specific debug node."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
                nodelist="sx40",
            )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--nodelist") + 1] == "sx40"


def test_S1_legacy_call_emits_only_4_extra_flags(tmp_path, monkeypatch):
    """S1: legacy single-CPU paper (no new args) emits the same sbatch flag
    set as pre-v0.7.2 — backward-compat regression guard."""
    repo = _setup_slurm(tmp_path)
    captured: dict = {}
    _patch_slurm_has_gres(monkeypatch, True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", _capture_cmd_call(captured)):
            S._run_reproduce_slurm(
                repo, repo / "reproduce.log", timeout=600,
            )
    cmd = captured["cmd"]
    # New v0.7.2 flags must all be ABSENT
    for forbidden in (
        "--nodes", "--ntasks", "--ntasks-per-node", "--nodelist",
        "--exclude", "--exclusive", "--gpus-per-task", "--gpus-per-node",
    ):
        assert forbidden not in cmd, f"{forbidden} leaked into legacy sbatch"
    for prefix in (
        "--gres=", "--mem=", "--mem-per-cpu=", "--constraint=",
        "--cpu-bind=", "--mem-bind=", "--hint=",
    ):
        assert all(not c.startswith(prefix) for c in cmd), f"{prefix}* leaked"


# ── v0.7.2: run_reproduce auto-resolve from execution_profile ────────────


@pytest.mark.asyncio
async def test_S5_execution_profile_auto_resolves_into_sbatch(tmp_path, monkeypatch):
    """S5: rubric.execution_profile.requested_* fills run_reproduce caller
    args that are at the zero default. End-to-end pass through the MCP
    tool surface."""
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({
        "reproduce_contract": {
            "max_runtime_sec": 600,
            "expected_artifacts": [],
            "execution_profile": {
                "kind": "mpi_gpu",
                "requested_nodes": 4,
                "min_ranks": 32,
                "ntasks_per_node": 8,
                "exclusive": True,
                "requested_gpus_per_task": 1,
                "gpu_type": "v100",
                "memory_gb_per_node": 256,
                "constraint": "skylake",
                "cpu_bind": "cores",
                "extra_sbatch_args": ["--account=projX"],
            },
        },
    }))

    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ok\n")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(S, "_slurm_has_gres", lambda: True)
    monkeypatch.setattr(S, "_sbatch_supports", lambda flag: True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            res = await S.run_reproduce(
                rubric_path=str(rubric),
                repo_dir=str(repo),
                sandbox_kind="slurm",
                partition="sx40",
            )
    assert res["executed"] is True
    cmd = captured["cmd"]
    # Profile-derived flags all present:
    assert cmd[cmd.index("--nodes") + 1] == "4"
    assert cmd[cmd.index("--ntasks") + 1] == "32"
    assert cmd[cmd.index("--ntasks-per-node") + 1] == "8"
    assert "--exclusive" in cmd
    assert cmd[cmd.index("--gpus-per-task") + 1] == "1"
    assert "--gres=gpu:v100:1" in cmd
    assert "--mem=256G" in cmd
    assert "--constraint=skylake" in cmd
    assert "--cpu-bind=cores" in cmd
    assert "--account=projX" in cmd
    # MCP-surface metadata reflects the chosen shape
    assert res["nodes"] == 4
    assert res["ntasks"] == 32
    assert res["exclusive"] is True
    assert res["gpu"]["type"] == "v100"


@pytest.mark.asyncio
async def test_caller_arg_overrides_rubric_hint(tmp_path, monkeypatch):
    """Explicit run_reproduce caller arg WINS over execution_profile hint."""
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({
        "reproduce_contract": {
            "max_runtime_sec": 600,
            "execution_profile": {
                "requested_nodes": 4,        # ← rubric wants 4
                "exclusive": True,
            },
        },
    }))
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ok\n")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(S, "_slurm_has_gres", lambda: True)
    monkeypatch.setattr(S, "_sbatch_supports", lambda flag: True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            await S.run_reproduce(
                rubric_path=str(rubric),
                repo_dir=str(repo),
                sandbox_kind="slurm",
                partition="sx40",
                nodes=2,  # ← caller forces 2; overrides rubric's 4
            )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--nodes") + 1] == "2", "caller arg must win"
    # exclusive is OR-merged, not overridden — preserved from rubric
    assert "--exclusive" in cmd


@pytest.mark.asyncio
async def test_legacy_rubric_without_execution_profile_unchanged(tmp_path, monkeypatch):
    """Backward-compat: a rubric without execution_profile emits the same
    4-flag sbatch as pre-v0.7.2 (S1 at the MCP-tool surface)."""
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({
        "reproduce_contract": {"max_runtime_sec": 600, "expected_artifacts": []},
    }))
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_idx = cmd.index("--output")
        Path(cmd[out_idx + 1]).write_text("ok\n")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(S, "_slurm_has_gres", lambda: True)
    monkeypatch.setattr(S, "_sbatch_supports", lambda flag: True)
    with patch.object(S, "_has_bin", lambda n: n == "sbatch"):
        with patch.object(S.subprocess, "run", fake_run):
            res = await S.run_reproduce(
                rubric_path=str(rubric),
                repo_dir=str(repo),
                sandbox_kind="slurm",
                partition="sx40",
            )
    cmd = captured["cmd"]
    for forbidden in ("--nodes", "--ntasks", "--exclusive", "--gpus-per-task"):
        assert forbidden not in cmd
    # New metadata keys absent in legacy response
    for k in ("nodes", "ntasks", "exclusive", "gpu"):
        assert k not in res
