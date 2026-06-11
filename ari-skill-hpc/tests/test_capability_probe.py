"""Platform capability probe (P2c of PLAN_claims_fulfillment_final).

Deterministic parts only — the srun path needs a real cluster (verified manually:
the probe's exact check found perf absent on partA). Covers output parsing, the
cache short-circuit, and the graceful skip paths.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.slurm import _parse_capability_output, probe_platform_capabilities  # noqa: E402


def test_parse_capability_output():
    text = "arch=aarch64\nperf=no\nnumactl=yes\ngarbage line\nvalgrind=no\n"
    d = _parse_capability_output(text)
    assert d["arch"] == "aarch64"
    assert d["available"] == {"perf": False, "numactl": True, "valgrind": False}


def test_parse_capability_output_empty():
    assert _parse_capability_output("")["available"] == {}


def test_probe_returns_cached_without_srun(tmp_path):
    cached = {"partition": "partA", "arch": "aarch64",
              "available": {"perf": False}}
    (tmp_path / "platform_capabilities.json").write_text(json.dumps(cached))
    out = asyncio.run(probe_platform_capabilities(str(tmp_path), partition="partA"))
    assert out["status"] == "cached"
    assert out["available"] == {"perf": False}


def test_probe_skips_without_partition(tmp_path, monkeypatch):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    out = asyncio.run(probe_platform_capabilities(str(tmp_path)))
    assert out["status"] == "skipped"
    assert not (tmp_path / "platform_capabilities.json").exists()


def test_probe_skips_gracefully_when_srun_missing(tmp_path, monkeypatch):
    # srun absent (non-cluster env) -> FileNotFoundError -> skipped, nothing written.
    monkeypatch.setenv("PATH", str(tmp_path))   # no srun on PATH
    out = asyncio.run(probe_platform_capabilities(str(tmp_path), partition="partA"))
    assert out["status"] == "skipped"
    assert "probe failed" in out["reason"]
    assert not (tmp_path / "platform_capabilities.json").exists()
