"""RQGM Task 01 — execution-mode switch (docs/guides/execution_modes.md
§Turning RQGM on / §Mode-switch timing policy).

Covers: config parsing (`ari.mode` / `rqgm.enabled`), the four-cell
`resolve_effective_mode` table with both warning paths,
`apply_rqgm_env_overrides` (`ARI_MODE` / `ARI_RQGM_ENABLED`),
`rqgm_state.json` round-trip + META_FILES / `_INTERNAL_JSON_NAMES`
registration, the simple_bfts identity regression (no RQGM imports, objects,
or files on a default run), the ari_rqgm startup smoke (Protocol conformance,
7-method delegation, `rqgm_state.json` persistence, short-loop lifecycle
parity), and the resume rule (persisted mode wins; no mid-run upgrade).

No test calls a real LLM: strategies/agents are deterministic mocks and
`build_runtime` collaborators are stubbed at their source modules.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from ari.config import (
    ARIConfig,
    AriModeConfig,
    RQGMConfig,
    apply_rqgm_env_overrides,
    load_config,
)


@pytest.fixture(autouse=True)
def _isolate_rqgm_env(monkeypatch):
    """Keep mode tests order-independent: no leaked ARI_MODE / ARI_RQGM_ENABLED."""
    for _v in ("ARI_MODE", "ARI_RQGM_ENABLED"):
        monkeypatch.delenv(_v, raising=False)


def _write_yaml(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "workflow.yaml"
    p.write_text(yaml.safe_dump(data))
    return str(p)


# ── config parsing (§6.1) ───────────────────────────────────────────────────


def test_absent_blocks_parse_to_defaults(tmp_path):
    """Every existing workflow.yaml (no ari:/rqgm: blocks) == simple_bfts."""
    cfg = ARIConfig()
    assert cfg.ari.mode == "simple_bfts"
    assert cfg.rqgm.enabled is False
    loaded = load_config(_write_yaml(tmp_path, {"llm": {"model": "fake"},
                                                "skills": []}))
    assert loaded.ari.mode == "simple_bfts"
    assert loaded.rqgm.enabled is False


def test_full_blocks_parse_from_yaml(tmp_path):
    cfg = load_config(_write_yaml(tmp_path, {
        "skills": [],
        "ari": {"mode": "ari_rqgm"},
        # Unknown subsection: forward-compat for later-task typed fields.
        "rqgm": {"enabled": True, "epoch": {"length": 5}},
    }))
    assert cfg.ari.mode == "ari_rqgm"
    assert cfg.rqgm.enabled is True


def test_invalid_mode_literal_rejected():
    with pytest.raises(ValidationError):
        AriModeConfig(mode="governed")
    with pytest.raises(ValidationError):
        ARIConfig(ari={"mode": "bogus"})


def test_rqgm_config_tolerates_unknown_subsections():
    cfg = RQGMConfig(enabled=False, governance={"reviewers": 3})
    assert cfg.enabled is False


# ── resolve_effective_mode: the four-cell table (§5.2) ───────────────────────


@pytest.mark.parametrize(
    "mode,enabled,expected,warns",
    [
        ("simple_bfts", False, "simple_bfts", False),
        ("simple_bfts", True, "simple_bfts", True),
        ("ari_rqgm", False, "simple_bfts", True),
        ("ari_rqgm", True, "ari_rqgm", False),
    ],
)
def test_resolve_effective_mode_table(mode, enabled, expected, warns, caplog):
    from ari.rqgm.mode import EffectiveMode, resolve_effective_mode

    cfg = ARIConfig(ari={"mode": mode}, rqgm={"enabled": enabled})
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.mode"):
        got = resolve_effective_mode(cfg)
    assert got is EffectiveMode(expected)
    warned = any(
        "falling back to simple_bfts" in r.getMessage() for r in caplog.records
    )
    assert warned == warns


def test_resolve_never_raises_on_pre_rqgm_cfg():
    """Pure + total: an object without ari/rqgm attrs resolves to the default."""
    from ari.rqgm.mode import EffectiveMode, resolve_effective_mode

    assert resolve_effective_mode(SimpleNamespace()) is EffectiveMode.SIMPLE_BFTS


def test_mode_resolution_never_reads_proposal_router():
    """VirSci independence (§5.6): mode code must not touch proposal_router.*"""
    from ari.rqgm.mode import EffectiveMode, resolve_effective_mode

    class _Cfg:
        ari = SimpleNamespace(mode="ari_rqgm")
        rqgm = SimpleNamespace(enabled=True)

        @property
        def proposal_router(self):
            raise AssertionError(
                "mode resolution must never read proposal_router.* "
                "(virsci.enabled is orthogonal to ari.mode)"
            )

    assert resolve_effective_mode(_Cfg()) is EffectiveMode.ARI_RQGM


def test_effective_mode_str_parity_with_resolver():
    """ari.config._effective_mode_str (import-free) matches the resolver."""
    from ari.config import _effective_mode_str
    from ari.rqgm.mode import resolve_effective_mode

    for mode in ("simple_bfts", "ari_rqgm"):
        for enabled in (False, True):
            cfg = ARIConfig(ari={"mode": mode}, rqgm={"enabled": enabled})
            assert _effective_mode_str(cfg) == resolve_effective_mode(cfg).value


# ── apply_rqgm_env_overrides (§5.2) ─────────────────────────────────────────


def test_env_overrides_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_MODE", "ari_rqgm")
    monkeypatch.setenv("ARI_RQGM_ENABLED", "true")
    cfg = load_config(_write_yaml(tmp_path, {"skills": []}))
    apply_rqgm_env_overrides(cfg)
    assert cfg.ari.mode == "ari_rqgm"
    assert cfg.rqgm.enabled is True


def test_env_can_disable_yaml_on_values(monkeypatch):
    """Applied-after-profile ordering: an explicit env off wins over YAML on."""
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    monkeypatch.setenv("ARI_MODE", "simple_bfts")
    monkeypatch.setenv("ARI_RQGM_ENABLED", "0")
    apply_rqgm_env_overrides(cfg)
    assert cfg.ari.mode == "simple_bfts"
    assert cfg.rqgm.enabled is False


def test_env_invalid_values_ignored_with_warning(monkeypatch, caplog):
    cfg = ARIConfig()
    monkeypatch.setenv("ARI_MODE", "governed")
    monkeypatch.setenv("ARI_RQGM_ENABLED", "maybe")
    with caplog.at_level(logging.WARNING, logger="ari.config"):
        apply_rqgm_env_overrides(cfg)
    assert cfg.ari.mode == "simple_bfts"
    assert cfg.rqgm.enabled is False
    msgs = [r.getMessage() for r in caplog.records]
    assert any("ARI_MODE" in m for m in msgs)
    assert any("ARI_RQGM_ENABLED" in m for m in msgs)


def test_export_resolved_config_bridges_effective_mode(monkeypatch):
    from ari.config import export_resolved_config_to_skill_env

    # Isolated env copy: the export mutates os.environ via setdefault.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ.pop("ARI_MODE", None)
    export_resolved_config_to_skill_env(ARIConfig())
    assert os.environ["ARI_MODE"] == "simple_bfts"
    # setdefault: an explicit env override is never clobbered.
    os.environ["ARI_MODE"] = "ari_rqgm"
    export_resolved_config_to_skill_env(ARIConfig())
    assert os.environ["ARI_MODE"] == "ari_rqgm"


# ── rqgm_state.json round-trip + registration (§6.2) ─────────────────────────


def test_rqgm_state_roundtrip(tmp_path):
    from ari.rqgm.state import (
        build_run_start_state,
        read_rqgm_state,
        write_rqgm_state,
    )

    st = build_run_start_state(mode="ari_rqgm", rqgm_enabled=True,
                               mode_source="config")
    write_rqgm_state(tmp_path, st)
    got = read_rqgm_state(tmp_path)
    assert got == st
    assert got["schema_version"] == 1
    assert got["mode"] == "ari_rqgm"
    assert got["rqgm_enabled"] is True
    assert got["mode_source"] == "config"
    assert got["switch_journal"] == [
        {"event": "run_start", "mode": "ari_rqgm", "epoch_id": None}
    ]


def test_rqgm_state_absent_read_returns_none(tmp_path):
    from ari.rqgm.state import read_rqgm_state

    assert read_rqgm_state(tmp_path) is None


def test_rqgm_state_write_is_best_effort(tmp_path):
    """A state-write failure (missing parent dir) must never raise."""
    from ari.rqgm.state import build_run_start_state, write_rqgm_state

    write_rqgm_state(
        tmp_path / "does" / "not" / "exist",
        build_run_start_state(mode="ari_rqgm", rqgm_enabled=True),
    )


def test_persist_run_start_is_write_once(tmp_path):
    """Resume never clobbers the run-start state (persisted journal wins)."""
    from ari.rqgm.state import persist_run_start, read_rqgm_state

    persist_run_start(tmp_path, mode="ari_rqgm", rqgm_enabled=True,
                      mode_source="config")
    first = read_rqgm_state(tmp_path)
    persist_run_start(tmp_path, mode="simple_bfts", rqgm_enabled=False,
                      mode_source="env")
    assert read_rqgm_state(tmp_path) == first


def test_new_filenames_are_meta_files():
    """Pattern: test_prompt_provenance.py::test_new_filenames_are_meta_files."""
    from ari.paths import PathManager
    from ari.rqgm.state import CONSTITUTION_FILENAME, RQGM_STATE_FILENAME

    assert RQGM_STATE_FILENAME in PathManager.META_FILES
    assert CONSTITUTION_FILENAME in PathManager.META_FILES
    assert PathManager.is_meta_file(RQGM_STATE_FILENAME) is True
    assert PathManager.is_meta_file(CONSTITUTION_FILENAME) is True


def test_rqgm_state_is_internal_json():
    from ari.orchestrator.node_report.builder import (
        _INTERNAL_JSON_NAMES,
        classify_artifact_role,
    )

    assert "rqgm_state.json" in _INTERNAL_JSON_NAMES
    assert classify_artifact_role("rqgm_state.json") == "unknown"


# ── build_runtime wiring (§5.4) ──────────────────────────────────────────────


def _stub_runtime_deps(monkeypatch):
    """Stub build_runtime's collaborators at their source modules.

    BFTS is deliberately NOT stubbed so the simple_bfts regression can assert
    the returned strategy is the real ``ari.orchestrator.bfts.BFTS`` object.
    """

    class _StubMCP:
        def __init__(self, skills, disabled_tools=None):
            self.skills = list(skills)
            self.disabled_tools = list(disabled_tools or [])

        def list_tools(self, phase=None):
            return []

    class _StubLLM:
        def __init__(self, cfg_llm, *a, **k):
            self.config = cfg_llm
            self.mcp_client = None

        def _model_name(self):
            return "stub-model"

    class _StubMem:
        def __init__(self, *a, **k):
            pass

    class _StubEval:
        def __init__(self, *a, **k):
            pass

    class _StubAgent:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr("ari.mcp.client.MCPClient", _StubMCP)
    monkeypatch.setattr("ari.llm.client.LLMClient", _StubLLM)
    monkeypatch.setattr("ari.memory.letta_client.LettaMemoryClient", _StubMem)
    monkeypatch.setattr("ari.evaluator.LLMEvaluator", _StubEval)
    monkeypatch.setattr("ari.agent.loop.AgentLoop", _StubAgent)


def _forget_rqgm_modules(monkeypatch):
    for name in [n for n in list(sys.modules)
                 if n == "ari.rqgm" or n.startswith("ari.rqgm.")]:
        monkeypatch.delitem(sys.modules, name)


def test_build_runtime_default_is_identity(monkeypatch, tmp_path):
    """simple_bfts regression: no RQGM import, object, or file on default cfg."""
    from ari.core import build_runtime

    _stub_runtime_deps(monkeypatch)
    _forget_rqgm_modules(monkeypatch)
    cfg = ARIConfig()
    llm, memory, mcp, bfts, agent, spec = build_runtime(
        cfg, "goal text", checkpoint_dir=tmp_path
    )
    assert getattr(bfts, "rqgm", None) is None
    assert type(bfts).__module__ == "ari.orchestrator.bfts"
    assert not any(n == "ari.rqgm" or n.startswith("ari.rqgm.")
                   for n in sys.modules), "default run must not import ari.rqgm"
    assert not (tmp_path / "rqgm_state.json").exists()
    assert not (tmp_path / "constitution.yaml").exists()


def test_build_runtime_interlock_disagreement_falls_back(monkeypatch, tmp_path,
                                                         caplog):
    """ari.mode=ari_rqgm + rqgm.enabled=false → plain BFTS + warning."""
    from ari.core import build_runtime

    _stub_runtime_deps(monkeypatch)
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": False})
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.mode"):
        _, _, _, bfts, _, _ = build_runtime(cfg, "goal", checkpoint_dir=tmp_path)
    assert getattr(bfts, "rqgm", None) is None
    assert type(bfts).__module__ == "ari.orchestrator.bfts"
    assert any("falling back to simple_bfts" in r.getMessage()
               for r in caplog.records)


def test_build_runtime_ari_rqgm_wraps_strategy(monkeypatch, tmp_path):
    """ari_rqgm startup: wrapper satisfies the Protocol and exposes .rqgm."""
    from ari.core import build_runtime
    from ari.protocols import SearchStrategy

    _stub_runtime_deps(monkeypatch)
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    llm, memory, mcp, bfts, agent, spec = build_runtime(
        cfg, "goal text", checkpoint_dir=tmp_path
    )
    assert isinstance(bfts, SearchStrategy)  # runtime_checkable, structural
    assert bfts.rqgm is not None
    assert bfts.rqgm.mode.value == "ari_rqgm"
    assert bfts.rqgm.checkpoint_dir == tmp_path
    # Inner strategy is the untouched real BFTS (wrap, never replace).
    assert type(bfts.inner).__module__ == "ari.orchestrator.bfts"
    # wrap_node_executor is identity in v1 (seam reserved for Tasks 05/06).
    assert bfts.rqgm.wrap_node_executor(agent) is agent


def test_governed_strategy_delegates_all_seven_methods():
    from ari.protocols import SearchStrategy
    from ari.rqgm.runtime import GovernedSearchStrategy, RQGMRuntime

    inner = MagicMock()
    gov = GovernedSearchStrategy(inner, RQGMRuntime(ARIConfig()))
    assert isinstance(gov, SearchStrategy)

    node, mem = object(), object()
    gov.select_next_node([node], "g", mem)
    inner.select_next_node.assert_called_once_with([node], "g", mem)
    gov.select_best_to_expand([node], "g", mem)
    inner.select_best_to_expand.assert_called_once_with([node], "g", mem)
    gov.should_prune(node, current_total=3)
    inner.should_prune.assert_called_once_with(node, current_total=3)
    gov.expand(node, "extra", key="val")
    inner.expand.assert_called_once_with(node, "extra", key="val")
    gov.record_run(node)
    inner.record_run.assert_called_once_with(node)
    gov.expansion_count("n1")
    inner.expansion_count.assert_called_once_with("n1")
    inner.diversity_bonus.return_value = 0.25
    assert gov.diversity_bonus(node) == 0.25
    inner.diversity_bonus.assert_called_once_with(node)


# ── short-loop smoke: ari_rqgm lifecycle parity (§9 smoke) ───────────────────


def _make_agent():
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    return agent


def _make_strategy():
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda frontier, goal, mem: frontier[0]
    bfts.select_next_node.side_effect = lambda pending, goal, mem: pending[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    return bfts


def _run_short_loop(tmp_path, strategy, cfg):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    all_nodes = [root]
    total = _run_loop(
        cfg, strategy, _make_agent(), [root], all_nodes,
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="rqgm-smoke",
    )
    return total, [(n.id, n.status.value) for n in all_nodes]


def test_short_loop_rqgm_matches_simple_bfts_lifecycle(monkeypatch, tmp_path):
    """Task-01 wrapper is pure delegation: identical node lifecycle, plus the
    rqgm_state.json provenance marker with mode_source='config'."""
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg_plain = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                                "timeout_per_node": 60})
    ctrl_dir = tmp_path / "control"
    ctrl_dir.mkdir()
    total_ctrl, lifecycle_ctrl = _run_short_loop(ctrl_dir, _make_strategy(),
                                                 cfg_plain)

    cfg_rqgm = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                               "timeout_per_node": 60},
                         ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    rqgm_dir = tmp_path / "governed"
    rqgm_dir.mkdir()
    runtime = RQGMRuntime(cfg_rqgm, checkpoint_dir=rqgm_dir)
    governed = runtime.wrap_search_strategy(_make_strategy())
    runtime.persist_mode(mode_source="config")  # as ari run does at launch
    total_gov, lifecycle_gov = _run_short_loop(rqgm_dir, governed, cfg_rqgm)

    assert total_gov == total_ctrl
    assert lifecycle_gov == lifecycle_ctrl
    state = json.loads((rqgm_dir / "rqgm_state.json").read_text())
    assert state["mode"] == "ari_rqgm"
    assert state["mode_source"] == "config"
    assert not (ctrl_dir / "rqgm_state.json").exists()


# ── CLI run smoke (default vs ari_rqgm checkpoints) ──────────────────────────


def _cli_run(tmp_path, extra_yaml: str = ""):
    from typer.testing import CliRunner

    from ari.cli import app

    runner = CliRunner()
    exp = tmp_path / "experiment.md"
    exp.write_text("## Research Goal\nMeasure sorting throughput.\n")
    cfg_file = tmp_path / "config.yaml"
    ckpt = str(tmp_path / "ckpts" / "{run_id}")
    cfg_file.write_text(
        "llm:\n  model: fake-model\nskills: []\n"
        f"checkpoint:\n  dir: {ckpt}\n"
        f"logging:\n  dir: {ckpt}\n" + extra_yaml
    )
    with mock.patch("ari.cli.build_runtime") as mock_rt, \
            mock.patch("ari.cli._run_loop", return_value=0):
        agent = MagicMock()
        mock_rt.return_value = (None, None, None, MagicMock(), agent, None)
        result = runner.invoke(app, ["run", str(exp), "--config", str(cfg_file)])
    assert result.exit_code == 0, result.output
    ckpts = list((tmp_path / "ckpts").iterdir())
    assert len(ckpts) == 1
    return ckpts[0]


def test_cli_run_default_writes_no_rqgm_files(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    ckpt = _cli_run(tmp_path)
    assert not (ckpt / "rqgm_state.json").exists()
    assert not (ckpt / "constitution.yaml").exists()


def test_cli_run_ari_rqgm_writes_state(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    ckpt = _cli_run(tmp_path, "ari:\n  mode: ari_rqgm\nrqgm:\n  enabled: true\n")
    state = json.loads((ckpt / "rqgm_state.json").read_text())
    assert state["mode"] == "ari_rqgm"
    assert state["rqgm_enabled"] is True
    assert state["mode_source"] == "config"
    assert state["switch_journal"][0]["event"] == "run_start"


# ── resume semantics (§5.5) ──────────────────────────────────────────────────


def test_resume_persisted_mode_wins(tmp_path, caplog):
    """Run started as ari_rqgm + conflicting env/config → persisted mode wins."""
    from ari.rqgm.state import persist_run_start, reconcile_resume_mode

    persist_run_start(tmp_path, mode="ari_rqgm", rqgm_enabled=True)
    cfg = ARIConfig()  # config/env say simple_bfts (e.g. ARI_MODE=simple_bfts)
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.state"):
        reconcile_resume_mode(cfg, tmp_path)
    assert cfg.ari.mode == "ari_rqgm"
    assert cfg.rqgm.enabled is True
    assert any("persisted mode wins" in r.getMessage() for r in caplog.records)


def test_resume_never_upgrades_simple_bfts_run(tmp_path, caplog):
    """No state file + ARI_MODE=ari_rqgm → stays simple_bfts, warning logged."""
    from ari.rqgm.state import reconcile_resume_mode

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.state"):
        reconcile_resume_mode(cfg, tmp_path)
    assert cfg.ari.mode == "simple_bfts"
    assert cfg.rqgm.enabled is False
    assert any("cannot upgrade mid-run" in r.getMessage()
               for r in caplog.records)


def test_resume_matching_state_is_silent(tmp_path, caplog):
    from ari.rqgm.state import persist_run_start, reconcile_resume_mode

    persist_run_start(tmp_path, mode="ari_rqgm", rqgm_enabled=True)
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.state"):
        reconcile_resume_mode(cfg, tmp_path)
    assert cfg.ari.mode == "ari_rqgm"
    assert cfg.rqgm.enabled is True
    assert not caplog.records
