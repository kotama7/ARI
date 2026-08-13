from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from ari import cli
from ari.config import ARIConfig


def test_paper_command_returns_nonzero_when_pipeline_fails(tmp_path, monkeypatch):
    checkpoint = tmp_path / "run"
    checkpoint.mkdir()
    (checkpoint / "tree.json").write_text(
        json.dumps({"run_id": "failed-paper", "nodes": []}),
        encoding="utf-8",
    )
    (checkpoint / "experiment.md").write_text("# Failure propagation\n", encoding="utf-8")

    cfg = ARIConfig()
    mcp = SimpleNamespace(close_all=lambda: None)
    bfts = SimpleNamespace(rqgm=None)
    monkeypatch.setattr(cli, "_resolve_cfg", lambda *_a, **_kw: cfg)
    monkeypatch.setattr(cli, "_setup_logging", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        cli,
        "build_runtime",
        lambda *_a, **_kw: (object(), object(), mcp, bfts),
    )

    from ari.cli import paper_dispatch

    monkeypatch.setattr(
        paper_dispatch,
        "run_paper_phase",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("paper lock blocked")),
    )

    result = CliRunner().invoke(cli.app, ["paper", str(checkpoint)])

    assert result.exit_code == 1
    assert "Paper pipeline failed" in result.output
    assert "Paper pipeline complete" not in result.output
