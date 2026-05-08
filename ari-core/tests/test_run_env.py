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
                           slurm_job_id="1274", slurm_partition="sx40")
        assert info["slurm_job_id"] == "1274"
        assert info["slurm_partition"] == "sx40"
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
        capture_env(tmp_path, executor="slurm",
                    slurm_job_id="42", slurm_partition="sx40")

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

        report = build_node_report(
            node=_Node(), work_dir=tmp_path, parent_work_dir=None,
            eval_result=None, delta_vs_parent="", what_was_done="",
        )
        assert report["executor"] == "slurm"
        assert report["slurm_job_id"] == "42"
        assert report["slurm_partition"] == "sx40"
        assert isinstance(report["cpu_info"], dict)

    def test_node_report_legacy_run_no_capture(self, tmp_path):
        """When _run_env.json absent (legacy/dry runs), fields default empty."""
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
            eval_result=None, delta_vs_parent="", what_was_done="",
        )
        assert report["executor"] == ""
        assert report["hostname"] == ""
        assert report["cpu_info"] == {}
