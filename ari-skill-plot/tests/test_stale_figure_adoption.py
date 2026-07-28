"""The figure rescue path must not publish a previous run's figures.

`out_dir` IS the checkpoint dir (workflow.yaml: `output_dir: {{checkpoint_dir}}`),
so `fig_*.pdf` from an earlier run — or from the very `loop_back_to` iteration a
VLM review just REJECTED — is already sitting there. The rescue glob adopted
those files under a caption fabricated on the spot, and because `figures` was
then non-empty the "No figures produced" error never fired, so the paper shipped
figures that were never generated from its data.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace


def _plot_server():
    """Load THIS skill's server by path.

    Every skill ships its server as ``src/server.py``, so a plain
    ``import src.server`` in a shared pytest process resolves to whichever
    skill imported first (observed: ari-skill-coding). That collision is the
    reason scripts/run_all_tests.sh forks per skill; loading by explicit path
    makes this file correct under either invocation.
    """
    import importlib.util
    from pathlib import Path as _P

    path = _P(__file__).resolve().parent.parent / "src" / "server.py"
    spec = importlib.util.spec_from_file_location("plot_skill_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, reply: str):
    server = _plot_server()

    (tmp_path / "nodes.json").write_text(json.dumps(
        {"nodes": [{"id": "n1", "metrics": {"gbps": 1.0}, "status": "success"}]}))

    async def _fake(**kw):
        msg = SimpleNamespace(content=reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    orig = server.litellm.acompletion
    server.litellm.acompletion = _fake
    try:
        return asyncio.run(server.generate_figures_llm(
            nodes_json_path=str(tmp_path / "nodes.json"),
            output_dir=str(tmp_path), experiment_summary="s"))
    finally:
        server.litellm.acompletion = orig


def test_a_preexisting_figure_is_declined_and_reported(tmp_path):
    (tmp_path / "fig_1.pdf").write_bytes(b"%PDF-1.4 stale from an earlier run")
    out = _run(tmp_path, "I could not produce figures.")

    assert not (out.get("figures") or {}), out.get("figures")
    assert "No figures produced" in str(out.get("error"))
    assert "stale" in str(out.get("error"))
    assert any("predate this invocation" in w for w in (out.get("warnings") or []))


def test_no_preexisting_figures_means_no_stale_warning(tmp_path):
    """The guard must not fire when the directory starts clean."""
    out = _run(tmp_path, "I could not produce figures.")
    assert not (out.get("figures") or {})
    assert "stale" not in str(out.get("error"))
    assert not [w for w in (out.get("warnings") or []) if "predate" in w]
