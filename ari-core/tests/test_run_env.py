"""Unit tests for ari.agent.run_env (compute-resource capture)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ari.agent.run_env import (
    capture_env,
    read_run_env,
    shell_capture_snippet,
)


class TestCaptureEnv:
    def test_writes_json_with_required_keys(self, tmp_path):
        info = capture_env(tmp_path, executor="local")
        f = tmp_path / "_run_env.json"
        assert f.exists()
        on_disk = json.loads(f.read_text())
        assert on_disk == info
        for k in ("captured_at", "executor", "hostname", "cpu_info"):
            assert k in on_disk
        assert on_disk["executor"] == "local"

    def test_slurm_kwargs_override_env(self, tmp_path, monkeypatch):
        # Even if the agent process has SLURM env vars set (it shouldn't, but
        # capture_env runs in the agent process for run_bash), explicit
        # kwargs win — that's the contract for slurm-injected snippets.
        monkeypatch.setenv("SLURM_JOB_ID", "9999")
        info = capture_env(tmp_path, executor="slurm",
                           slurm_job_id="1274", slurm_partition="gpu-private")
        assert info["slurm_job_id"] == "1274"
        assert info["slurm_partition"] == "gpu-private"
        assert info["executor"] == "slurm"

    def test_overwrites_on_repeat(self, tmp_path):
        capture_env(tmp_path, executor="local")
        capture_env(tmp_path, executor="slurm", slurm_job_id="42")
        info = read_run_env(tmp_path)
        assert info["executor"] == "slurm"
        assert info["slurm_job_id"] == "42"

    def test_cpu_info_populated_on_linux(self, tmp_path):
        # Best-effort: lscpu or /proc/cpuinfo should give us SOMETHING on a
        # Linux test runner. Skip cleanly on macOS/Windows.
        if not Path("/proc/cpuinfo").exists():
            pytest.skip("non-Linux: /proc/cpuinfo absent")
        info = capture_env(tmp_path, executor="local")
        cpu = info.get("cpu_info") or {}
        assert cpu.get("model") or cpu.get("threads"), \
            "cpu_info should have at least a model or thread count"


class TestReadRunEnv:
    def test_missing_file_returns_empty(self, tmp_path):
        assert read_run_env(tmp_path) == {}

    def test_malformed_file_returns_empty(self, tmp_path):
        (tmp_path / "_run_env.json").write_text("not json {")
        assert read_run_env(tmp_path) == {}

    def test_roundtrip(self, tmp_path):
        capture_env(tmp_path, executor="local")
        info = read_run_env(tmp_path)
        assert info["executor"] == "local"
        assert "captured_at" in info


class TestShellCaptureSnippet:
    def test_contains_expected_fields(self):
        snippet = shell_capture_snippet(executor="slurm")
        # The snippet writes a JSON heredoc — check that it references
        # all the SLURM env vars we want to surface to node_report.
        for token in (
            "_run_env.json",
            "SLURM_JOB_ID",
            "SLURM_JOB_PARTITION",
            "lscpu",
            "MemTotal",
            '"executor": "slurm"',
        ):
            assert token in snippet, f"snippet missing {token!r}"

    def test_executor_local_variant(self):
        # The same helper supports a 'local' executor for documentation parity
        # with capture_env, even though the typical user is sbatch scripts.
        s = shell_capture_snippet(executor="local")
        assert '"executor": "local"' in s


class TestNodeReportIntegration:
    """End-to-end: capture → node_report includes the new fields."""

    def test_node_report_includes_run_env_fields(self, tmp_path):
        # capture_env still writes _run_env.json, but the builder NO LONGER reads
        # it — compute-env provenance is now agent-authored (grounded note), and
        # machine info is never auto-scraped into the deliverable.
        capture_env(tmp_path, executor="slurm",
                    slurm_job_id="42", slurm_partition="gpu-private")

        from ari.orchestrator.node_report import build_node_report

        class _Node:
            id = "node_x"
            parent_id = None
            ancestor_ids: list[str] = []
            label = "draft"
            raw_label = "draft"
            depth = 0
            status = "success"
            created_at = "2026-01-01T00:00:00Z"
            completed_at = "2026-01-01T00:01:00Z"
            metrics: dict = {}
            artifacts: list = []
            trace_log = None
            agent_environment = "Intel Xeon 6142, gcc 11.5.0, AVX-512"

        report = build_node_report(
            node=_Node(), work_dir=tmp_path, parent_work_dir=None,
            eval_result=None, what_was_done="",
        )
        assert report["executor"] == "slurm"
        assert report["slurm_job_id"] == "42"
        assert report["slurm_partition"] == "gpu-private"
        assert isinstance(report["cpu_info"], dict)

    def test_node_report_legacy_run_no_capture(self, tmp_path):
        """No ``_run_env.json`` (legacy / dry runs): the resource-provenance keys
        are still PRESENT, carrying empty values.

        Machine provenance is deliberately auto-embedded. The keys are emitted
        unconditionally so a consumer can tell "nothing was captured" (empty)
        apart from "this key predates the field" (absent) — an omitted key
        would make those two indistinguishable.
        """
        from ari.orchestrator.node_report import build_node_report

        class _Node:
            id = "node_y"
            parent_id = None
            ancestor_ids: list[str] = []
            label = "draft"
            raw_label = "draft"
            depth = 0
            status = "success"
            created_at = ""
            completed_at = ""
            metrics: dict = {}
            artifacts: list = []
            trace_log = None

        report = build_node_report(
            node=_Node(), work_dir=tmp_path, parent_work_dir=None,
            eval_result=None, what_was_done="",
        )
        assert report["executor"] == ""
        assert report["hostname"] == ""
        assert report["slurm_partition"] == ""
        assert report["cpu_info"] == {}
        assert report["partitions_used"]["used"] == []
        # `environment` stays agent-authored: the builder never synthesises one.
        assert "environment" not in report

    def test_node_report_records_every_partition_the_run_used(self, tmp_path):
        """The report names EVERY partition the run touched, not just this node's.

        A run that spreads across a heterogeneous cluster otherwise left no
        single record of where it had executed, so a cross-node metric
        comparison could not be checked against the hardware behind it.

        Partition names here are deliberately fictitious.
        """
        from ari.orchestrator.node_report import build_node_report

        run_root = tmp_path / "run_1"
        for node_id, part, nodelist in (
            ("node_a", "partition-a", "testnode01"),
            ("node_b", "partition-b", "testnode02"),
            ("node_c", "partition-a", "testnode03"),
        ):
            wd = run_root / node_id
            wd.mkdir(parents=True)
            # capture_env takes the nodelist from the environment, as it does
            # on a real compute node.
            os.environ["SLURM_JOB_NODELIST"] = nodelist
            try:
                capture_env(wd, executor="slurm", slurm_job_id="1",
                            slurm_partition=part)
            finally:
                os.environ.pop("SLURM_JOB_NODELIST", None)

        class _Node:
            id = "node_a"
            parent_id = None
            ancestor_ids: list[str] = []
            label = "draft"
            raw_label = "draft"
            depth = 0
            status = "success"
            created_at = ""
            completed_at = ""
            metrics: dict = {}
            artifacts: list = []
            trace_log = None

        report = build_node_report(
            node=_Node(), work_dir=run_root / "node_a",
            parent_work_dir=None, eval_result=None, what_was_done="",
        )
        used = report["partitions_used"]
        # This node's own allocation, and the run-wide set it belongs to.
        assert used["this_node"] == "partition-a"
        assert used["used"] == ["partition-a", "partition-b"]
        # Two nodes ran on partition-a, one on partition-b.
        assert used["by_partition"]["partition-a"]["node_count"] == 2
        assert used["by_partition"]["partition-b"]["node_count"] == 1
        assert used["by_partition"]["partition-a"]["nodelists"] == [
            "testnode01", "testnode03"]
