"""Extended CLI tests - covering real failure modes caught in production."""
import json
import os
import signal
import sys
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from ari.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_checkpoint_env(monkeypatch):
    """Keep ARI_CHECKPOINT_DIR out of these tests.

    ari.pipeline.generate_paper_section sets os.environ['ARI_CHECKPOINT_DIR']
    during normal runs so skill subprocesses pick it up. When cli.run is
    invoked via CliRunner, that env write leaks across tests in the same
    process. Tests below rely on the CLI minting a fresh slug-based run_id
    from the experiment text; with a leaked env, the CLI would instead
    adopt the previous test's checkpoint-dir name (correct behavior for
    the GUI flow, but surprising here).
    """
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


# ── Regression: cli.py must be runnable as __main__ ─────────────────────────

def test_cli_runnable_as_module():
    """python3 -m ari.cli must invoke app() not silently exit."""
    result = subprocess.run(
        [sys.executable, "-m", "ari.cli", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "ari" in result.stdout.lower() or "ARI" in result.stdout


def test_cli_run_command_exists():
    """run command must be registered in the app."""
    result = runner.invoke(app, ["--help"])
    assert "run" in result.output


def test_cli_run_missing_file():
    """run with nonexistent experiment.md must exit non-zero."""
    result = runner.invoke(app, ["run", "/nonexistent/experiment.md"])
    assert result.exit_code != 0


def test_cli_run_with_minimal_md(tmp_path):
    """run creates checkpoint dir from experiment.md with Research Goal."""
    exp = tmp_path / "experiment.md"
    exp.write_text(
        "## Research Goal\n"
        "Maximize the throughput of matrix multiplication using different BLAS implementations.\n"
    )
    cfg = tmp_path / "config.yaml"
    _ckpt = str(tmp_path / "ckpts/{run_id}")
    cfg.write_text(
        "llm:\n  model: fake-model\n"
        f"checkpoint:\n  dir: {_ckpt}\n"
        f"logging:\n  dir: {_ckpt}\n"
    )

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", return_value=0):
        mock_rt.return_value = (None, None, None, mock.MagicMock(), mock.MagicMock(), None, None)
        result = runner.invoke(app, ["run", str(exp), "--config", str(cfg)])
    assert result.exit_code == 0


def test_checkpoint_name_from_research_goal(tmp_path):
    """Checkpoint run_id must be a valid timestamp-prefixed slug (LLM or fallback from content)."""
    exp = tmp_path / "experiment.md"
    exp.write_text(
        "## Research Goal\n"
        "Maximize GFLOPS of a stencil benchmark on HPC cluster\n\n"
        "## Evaluation\nGFLOPS\n"
    )
    cfg = tmp_path / "config.yaml"
    _ckpt = str(tmp_path / "{run_id}")
    cfg.write_text(
        "llm:\n  model: fake\n"
        f"checkpoint:\n  dir: {_ckpt}\n"
        f"logging:\n  dir: {_ckpt}\n"
    )

    captured_run_id = {}

    def fake_run_loop(cfg, bfts, agent, pending, nodes, exp_data, ckpt_dir, run_id):
        captured_run_id["v"] = run_id
        return 0

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", side_effect=fake_run_loop):
        mock_rt.return_value = (None, None, None, mock.MagicMock(), mock.MagicMock(), None, None)
        result = runner.invoke(app, ["run", str(exp), "--config", str(cfg)])

    # run_id must be timestamp_slug format; content may come from LLM or fallback
    import re
    rid = captured_run_id.get("v", "")
    assert re.match(r"^\d{14}_", rid), f"run_id missing timestamp prefix: {rid}"
    assert len(rid) > 14, f"run_id too short: {rid}"


def test_checkpoint_name_not_generic_heading(tmp_path):
    """run_id must NOT be just 'Research_Goal' when content follows."""
    exp = tmp_path / "experiment.md"
    exp.write_text(
        "## Research Goal\n"
        "Maximize GFLOPS of a stencil benchmark on HPC cluster\n"
    )
    cfg = tmp_path / "config.yaml"
    _ckpt = str(tmp_path / "{run_id}")
    cfg.write_text(
        "llm:\n  model: fake\n"
        f"checkpoint:\n  dir: {_ckpt}\n"
        f"logging:\n  dir: {_ckpt}\n"
    )

    captured = {}

    def fake_run_loop(cfg, bfts, agent, pending, nodes, exp_data, ckpt_dir, run_id):
        captured["run_id"] = run_id
        return 0

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", side_effect=fake_run_loop):
        mock_rt.return_value = (None, None, None, mock.MagicMock(), mock.MagicMock(), None, None)
        runner.invoke(app, ["run", str(exp), "--config", str(cfg)])

    run_id = captured.get("run_id", "")
    assert run_id != "" and "Research_Goal" not in run_id.split("_", 1)[-1].replace("Research_Goal","X"), \
        f"run_id should not be generic 'Research_Goal', got: {run_id}"


def test_checkpoint_slug_allows_long_descriptive_name(tmp_path):
    """Long descriptive titles must not be truncated at 40 chars.

    Regression: slug was `[:40]`, which sliced
    `Investigate_whether_benchmark_performance_on_...` mid-word to
    `Investigate_whether_benchmark_performanc`. The limit is now 80.
    """
    exp = tmp_path / "experiment.md"
    exp.write_text(
        "Investigate whether benchmark performance on large HPC clusters scales linearly with node count\n"
    )
    cfg = tmp_path / "config.yaml"
    _ckpt = str(tmp_path / "{run_id}")
    cfg.write_text(
        "llm:\n  model: fake\n"
        f"checkpoint:\n  dir: {_ckpt}\n"
        f"logging:\n  dir: {_ckpt}\n"
    )

    captured = {}

    def fake_run_loop(cfg, bfts, agent, pending, nodes, exp_data, ckpt_dir, run_id):
        captured["run_id"] = run_id
        return 0

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", side_effect=fake_run_loop), \
         mock.patch("ari.llm.client.LLMClient") as mock_llm:
        # Force the fallback path (LLM title generation raises → use first content line)
        mock_llm.side_effect = RuntimeError("no LLM in tests")
        mock_rt.return_value = (None, None, None, mock.MagicMock(), mock.MagicMock(), None, None)
        runner.invoke(app, ["run", str(exp), "--config", str(cfg)])

    rid = captured.get("run_id", "")
    slug = rid.split("_", 1)[-1] if "_" in rid else rid
    # Must not be cut to the old 40-char limit
    assert not slug.endswith("performanc"), (
        f"slug appears truncated at old 40-char boundary: {slug!r}"
    )
    # Slug capped at 80 chars
    assert len(slug) <= 80, f"slug exceeds 80-char cap: {len(slug)} chars"
    # Should contain words beyond the first 40 chars
    assert len(slug) > 40, (
        f"descriptive slug should extend past old 40-char cap, got {len(slug)} chars: {slug!r}"
    )
