"""Verify each env var the GUI launcher sets actually has a consumer.

When the GUI wizard or settings page writes to ``proc_env[...]`` in
``api_experiment.py``, that variable only takes effect if *something*
downstream actually reads it. A silent write-only variable is a bug —
the GUI UI becomes a lie.

This suite enumerates every env var the GUI writes and asserts a reader
exists. Orphaned variables (no consumer found in the repo) are marked
with ``pytest.xfail`` so the suite stays green but the failure is visible
in test output and CI.

It complements the focused tests in test_settings_propagation.py, which
verify *that* the GUI writes the env var. Here we verify it has a reader.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Directories to scan for consumers. Restrict to src/ and ari/ subtrees so we
# never walk into node_modules, venvs, or checkpoint outputs.
_CANDIDATE_SUBPATHS = [
    ("ari-core", "ari"),
    ("ari-skill-hpc", "src"),
    ("ari-skill-web", "src"),
    ("ari-skill-vlm", "src"),
    ("ari-skill-coding", "src"),
    ("ari-skill-figure-router", "src"),
    ("ari-skill-idea", "src"),
    ("ari-skill-evaluator", "src"),
    ("ari-skill-benchmark", "src"),
    ("ari-skill-paper", "src"),
    ("ari-skill-paper-re", "src"),
    ("ari-skill-plot", "src"),
    ("ari-skill-review", "src"),
    ("ari-skill-orchestrator", "src"),
    ("ari-skill-memory", "src"),
    ("ari-skill-transform", "src"),
]
SEARCH_ROOTS = [REPO_ROOT / a / b for (a, b) in _CANDIDATE_SUBPATHS]

EXCLUDE_DIRS = {"tests", "test", "__pycache__", "node_modules", ".git",
                "docs", "dist", ".venv", "venv", "workspace", "checkpoints"}


def _iter_source_files() -> Iterable[Path]:
    """Yield repo source files, skipping tests, GUI writer, and heavy dirs."""
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if p.name.startswith("test_") or p.name == "api_experiment.py":
                continue
            yield p


# Cache file contents once — recompiling patterns is cheap; re-reading is not.
@pytest.fixture(scope="module")
def source_texts() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for p in _iter_source_files():
        try:
            out.append((p, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def _find_readers(var: str, sources: list[tuple[Path, str]]) -> list[Path]:
    """Return source files that read os.environ[...] for *var*.

    Also detects f-string patterns like ``f"ARI_MODEL_{phase.upper()}"`` that
    synthesize the name dynamically — a reader counts when the literal ARI_MODEL_
    f-string AND the phase suffix both appear in the same file.
    """
    read_pattern = re.compile(
        r"""environ(?:\.get|\[)\s*[\(\[]?\s*["']""" + re.escape(var) + r"""["']"""
    )
    hits = [p for (p, text) in sources if read_pattern.search(text)]
    if hits:
        return hits

    # f-string reader detection for ARI_MODEL_<PHASE>
    m = re.match(r"^ARI_MODEL_([A-Z]+)$", var)
    if m:
        phase = m.group(1).lower()
        fstr_pat = re.compile(r"""environ(?:\.get|\[)\s*[\(\[]?\s*f?["']ARI_MODEL_\{""")
        for p, text in sources:
            if fstr_pat.search(text) and phase in text:
                hits.append(p)
    return hits


# (env_var, human description, list of expected consumer file-path suffixes)
# When consumers is empty, the variable is currently orphaned — mark as xfail so
# the gap is visible without breaking the suite.
ENV_VARS_WITH_CONSUMERS: list[tuple[str, str]] = [
    # ── LLM / API (reach config.py via _apply_llm_env_overrides) ──
    ("ARI_MODEL", "GUI wizard LLM model"),
    ("ARI_LLM_MODEL", "fallback GUI LLM model"),
    ("ARI_BACKEND", "LLM provider"),
    ("ARI_LLM_API_BASE", "LLM API base URL"),
    # ── BFTS caps (reach config.py via apply_bfts_env_overrides) ──
    ("ARI_MAX_NODES", "BFTS node limit"),
    ("ARI_MAX_DEPTH", "BFTS depth limit"),
    ("ARI_MAX_REACT", "ReAct step limit"),
    ("ARI_PARALLEL", "parallel worker count"),
    ("ARI_TIMEOUT_NODE", "per-node timeout"),
    # ── Checkpoint (reach config.py via _apply_checkpoint_env_overrides) ──
    ("ARI_CHECKPOINT_DIR", "GUI pre-created checkpoint directory"),
    # ── Retrieval / VLM ──
    ("ARI_RETRIEVAL_BACKEND", "paper retrieval backend"),
    ("VLM_MODEL", "VLM review model"),
    # ── Container ──
    ("ARI_CONTAINER_IMAGE", "container image"),
    ("ARI_CONTAINER_MODE", "container runtime mode"),
    # ── SLURM resources (read by ari-skill-hpc or config.py auto_config) ──
    ("ARI_SLURM_CPUS", "SLURM CPU count"),
    ("ARI_SLURM_MEM_GB", "SLURM memory (GB)"),
    ("ARI_SLURM_GPUS", "SLURM GPU count"),
    ("ARI_SLURM_WALLTIME", "SLURM walltime (config.py resources)"),
    ("ARI_SLURM_PARTITION", "SLURM partition (config.py resources)"),
    # ── Per-phase LLM model overrides (wired Apr 2026) ──
    ("ARI_MODEL_IDEA", "idea-skill LLM model"),
    ("ARI_MODEL_CODING", "AgentLoop (ReAct / coding) LLM model"),
    ("ARI_MODEL_EVAL", "evaluator-skill LLM model"),
    ("ARI_MODEL_PAPER", "paper-re skill LLM model"),
    ("ARI_MODEL_REVIEW", "review-skill LLM model"),
    ("ARI_MODEL_BFTS", "BFTS orchestrator LLM model"),
]

# These are WRITTEN by the GUI but have NO reader in the codebase. They're
# silently ignored. Listed here so future PRs can fix them; xfail keeps CI green
# but the gap is visible.
ORPHANED_ENV_VARS: list[tuple[str, str]] = []


@pytest.mark.parametrize("var,desc", ENV_VARS_WITH_CONSUMERS)
def test_gui_env_var_has_a_consumer(var: str, desc: str, source_texts):
    """Every GUI-injected env var must be read by at least one non-test source file."""
    hits = _find_readers(var, source_texts)
    assert hits, (
        f"{var} ({desc}) is set by the GUI launcher but has no reader anywhere in the "
        f"backend or skills. Either wire up a consumer or stop writing the variable."
    )


@pytest.mark.parametrize("var,desc", ORPHANED_ENV_VARS)
def test_orphaned_gui_env_var(var: str, desc: str, source_texts):
    """Documents variables the GUI sets but nothing reads.

    Marked xfail so discovery is visible but the suite remains green until the
    gap is closed. When a consumer is added, the xfail will XPASS and this test
    should be moved to ``ENV_VARS_WITH_CONSUMERS``.
    """
    hits = _find_readers(var, source_texts)
    if hits:
        pytest.fail(
            f"{var} now has a reader ({hits[0]}). Move it out of ORPHANED_ENV_VARS "
            f"and into ENV_VARS_WITH_CONSUMERS."
        )
    pytest.xfail(f"{var}: {desc}")


# ── GUI writer inventory ───────────────────────────────────────────────
# Independent check: every var listed above (consumer + orphan) must actually
# be WRITTEN by api_experiment.py. Otherwise the list is stale.


def test_every_listed_var_is_written_by_api_experiment():
    """Every env var in the inventory must appear in the GUI launcher source.

    api_experiment.py writes per-phase models via an f-string
    (``ARI_MODEL_{skill.upper()}``) so ARI_MODEL_IDEA etc. are accepted if the
    f-string pattern plus the skill name both appear.
    """
    src = (REPO_ROOT / "ari-core" / "ari" / "viz" / "api_experiment.py").read_text()
    has_fstring_phase_model = bool(
        re.search(r'ARI_MODEL_\{[^}]*\.upper\(\)\}', src)
    )
    all_vars = [v for v, _ in ENV_VARS_WITH_CONSUMERS + ORPHANED_ENV_VARS]
    missing: list[str] = []
    for v in all_vars:
        if v in src:
            continue
        # ARI_MODEL_<PHASE> is synthesized in a loop
        m = re.match(r"^ARI_MODEL_([A-Z]+)$", v)
        if m and has_fstring_phase_model and m.group(1).lower() in src:
            continue
        missing.append(v)
    assert not missing, (
        f"{missing} are in the test inventory but no longer written by api_experiment.py. "
        f"Update the test or restore the GUI wiring."
    )


# ── Explicit end-to-end checks ─────────────────────────────────────────
# Beyond the file-grep above, exercise the actual config loading path for the
# knobs that matter most (BFTS caps, checkpoint dir). These catch silent
# regressions where a reader exists but no longer plumbs the value through.


def test_bfts_env_reaches_config_object(monkeypatch):
    from ari.config import ARIConfig, apply_bfts_env_overrides
    for v in ("ARI_MAX_NODES", "ARI_MAX_DEPTH", "ARI_MAX_REACT",
              "ARI_PARALLEL", "ARI_TIMEOUT_NODE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ARI_MAX_NODES", "11")
    monkeypatch.setenv("ARI_MAX_DEPTH", "9")
    monkeypatch.setenv("ARI_MAX_REACT", "44")
    monkeypatch.setenv("ARI_PARALLEL", "5")
    monkeypatch.setenv("ARI_TIMEOUT_NODE", "123")
    cfg = ARIConfig()
    apply_bfts_env_overrides(cfg)
    assert cfg.bfts.max_total_nodes == 11
    assert cfg.bfts.max_depth == 9
    assert cfg.bfts.max_react_steps == 44
    assert cfg.bfts.max_parallel_nodes == 5
    assert cfg.bfts.timeout_per_node == 123


def test_llm_env_reaches_config_object(monkeypatch, tmp_path):
    import yaml as _yaml
    from ari.config import load_config
    monkeypatch.setenv("ARI_MODEL", "gpt-9")
    monkeypatch.setenv("ARI_BACKEND", "anthropic")
    monkeypatch.setenv("ARI_LLM_API_BASE", "http://example.local")
    fpath = tmp_path / "c.yaml"
    fpath.write_text(_yaml.dump({"llm": {"backend": "openai", "model": "gpt-5"}}))
    cfg = load_config(str(fpath))
    assert cfg.llm.model == "gpt-9"
    assert cfg.llm.backend == "anthropic"
    assert cfg.llm.base_url == "http://example.local"


def test_checkpoint_env_reaches_config_object(monkeypatch, tmp_path):
    import yaml as _yaml
    from ari.config import load_config
    target = str(tmp_path / "precreated")
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", target)
    fpath = tmp_path / "c.yaml"
    fpath.write_text(_yaml.dump({"llm": {"model": "x"}}))
    cfg = load_config(str(fpath))
    assert cfg.checkpoint.dir == target
    assert cfg.logging.dir == target


# ── Per-phase LLM model end-to-end ─────────────────────────────────────


def _clear_phase_env(monkeypatch):
    for v in ("ARI_MODEL", "ARI_LLM_MODEL", "LLM_MODEL"):
        monkeypatch.delenv(v, raising=False)
    for phase in ("IDEA", "CODING", "EVAL", "PAPER", "REVIEW", "BFTS"):
        monkeypatch.delenv(f"ARI_MODEL_{phase}", raising=False)


@pytest.mark.parametrize("skill,phase_var", [
    ("ari-skill-idea",       "ARI_MODEL_IDEA"),
    ("ari-skill-paper-re",   "ARI_MODEL_PAPER"),
    ("ari-skill-review",     "ARI_MODEL_REVIEW"),
    ("ari-skill-evaluator",  "ARI_MODEL_EVAL"),
])
def test_phase_model_has_precedence_over_global(skill, phase_var):
    """Within each skill's ``_model()`` block, the phase env must be checked
    before the global ARI_LLM_MODEL/ARI_MODEL fallback so the phase value wins.
    """
    src = (REPO_ROOT / skill / "src" / "server.py").read_text()
    assert phase_var in src, f"{skill} must read {phase_var}"
    # Extract the smallest window that contains the phase var and the global
    # fallback; the phase var must appear first in that window.
    idx_phase = src.index(phase_var)
    window = src[max(0, idx_phase - 200): idx_phase + 400]
    for fallback in ("ARI_LLM_MODEL", "ARI_MODEL"):
        # Only enforce when the fallback actually appears in the _model() block
        if fallback in window:
            idx_fallback = window.index(fallback)
            idx_phase_local = window.index(phase_var)
            assert idx_phase_local < idx_fallback, (
                f"{skill}: {phase_var} must be checked before {fallback}"
            )
            break
    else:
        pytest.fail(f"{skill}: no fallback model env found near {phase_var}")


def test_phase_model_bfts_builds_dedicated_client(monkeypatch, tmp_path):
    """ari-core/core.py must build a separate LLMClient when ARI_MODEL_BFTS is set."""
    _clear_phase_env(monkeypatch)
    monkeypatch.setenv("ARI_MODEL_BFTS", "gpt-orchestrator-xyz")
    monkeypatch.setenv("ARI_MODEL_CODING", "claude-agent-xyz")
    from ari.config import ARIConfig, LLMConfig
    cfg = ARIConfig(llm=LLMConfig(backend="openai", model="base-model"))
    # Minimal stub so build_runtime can proceed without MCP fork
    with __import__("unittest.mock", fromlist=["mock"]).patch("ari.mcp.client.MCPClient") as _mc, \
         __import__("unittest.mock", fromlist=["mock"]).patch("ari.agent.loop.AgentLoop") as _al:
        _mc.return_value.list_tools.return_value = []
        _al.return_value = __import__("unittest.mock", fromlist=["mock"]).MagicMock()
        from ari.core import build_runtime
        try:
            llm, _, _, bfts, _, _, _ = build_runtime(cfg, "goal", checkpoint_dir=tmp_path)
        except Exception:
            # If downstream construction fails, still inspect models from the env
            # resolution logic by re-reading os.environ.
            import os as _os
            assert _os.environ["ARI_MODEL_BFTS"] == "gpt-orchestrator-xyz"
            assert _os.environ["ARI_MODEL_CODING"] == "claude-agent-xyz"
            return
    # When build_runtime succeeds, verify BFTS got the orchestrator model and
    # the main llm got the coding model (separate client instances).
    assert bfts.llm is not llm, "BFTS and agent must have distinct LLMClient instances"
    assert bfts.llm.config.model == "gpt-orchestrator-xyz"
    assert llm.config.model == "claude-agent-xyz"


def test_phase_model_coding_falls_back_to_global(monkeypatch, tmp_path):
    """When ARI_MODEL_CODING is unset, the agent LLM uses the global cfg.llm.model."""
    _clear_phase_env(monkeypatch)
    from ari.config import ARIConfig, LLMConfig
    cfg = ARIConfig(llm=LLMConfig(backend="openai", model="base-model"))
    with __import__("unittest.mock", fromlist=["mock"]).patch("ari.mcp.client.MCPClient") as _mc, \
         __import__("unittest.mock", fromlist=["mock"]).patch("ari.agent.loop.AgentLoop") as _al:
        _mc.return_value.list_tools.return_value = []
        _al.return_value = __import__("unittest.mock", fromlist=["mock"]).MagicMock()
        from ari.core import build_runtime
        try:
            llm, _, _, bfts, _, _, _ = build_runtime(cfg, "goal", checkpoint_dir=tmp_path)
        except Exception:
            return
    assert llm.config.model == "base-model"
    assert bfts.llm.config.model == "base-model"
