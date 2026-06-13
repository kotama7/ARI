"""Wiring test: write_paper_iterative injects the verified-context grounded block
into the system prompt (handoff: 'secure the flow' — consumption side).

Mirrors production by putting ari-core on sys.path (mcp.client injects it onto
the skill subprocess PYTHONPATH) so render_grounded_block is importable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ARI_CORE = str(Path(__file__).resolve().parents[2] / "ari-core")
if _ARI_CORE not in sys.path:
    sys.path.insert(0, _ARI_CORE)

from unittest.mock import patch  # noqa: E402

from src import server  # noqa: E402


@pytest.mark.asyncio
async def test_write_paper_injects_grounded_block(tmp_path):
    vc = tmp_path / "verified_context.json"
    vc.write_text(json.dumps({
        "usable_for_claims": [
            {"text": "The kernel sustains 150 GFLOP/s on cpuX",
             "repro_status": "rerun_passed",
             "artifact_refs": [{"path": "ear/code/kernel.cu"}]},
        ]
    }))

    captured = {}

    class _Stop(Exception):
        pass

    async def _cap(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        raise _Stop("captured")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        with pytest.raises(Exception):
            await server.write_paper_iterative(
                experiment_summary="some experiment context",
                verified_context_json=str(vc),
                venue="arxiv",
            )

    assert "messages" in captured, "litellm.acompletion was never reached"
    system_prompt = captured["messages"][0]["content"]
    assert "VERIFIED CONTEXT" in system_prompt
    assert "150 GFLOP/s" in system_prompt
    assert "rerun_passed" in system_prompt


@pytest.mark.asyncio
async def test_write_paper_no_verified_context_is_graceful(tmp_path):
    """Absent verified_context => no grounded block, no crash (default path)."""
    captured = {}

    async def _cap(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        raise RuntimeError("stop")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        with pytest.raises(Exception):
            await server.write_paper_iterative(
                experiment_summary="ctx", verified_context_json="", venue="arxiv",
            )
    system_prompt = captured["messages"][0]["content"]
    assert "VERIFIED CONTEXT" not in system_prompt
