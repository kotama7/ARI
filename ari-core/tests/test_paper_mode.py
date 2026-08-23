"""Paper-archive Task 01 — paper execution-mode switch
(docs/guides/execution_modes.md §The paper execution axis: `paper.mode`).

Covers: config parsing (`paper.mode` / `rqgm.paper.enabled` + archive/epoch/
anchor/prompt_evolution skeletons), the four-cell `resolve_paper_mode` table
with both warning paths, `apply_paper_env_overrides`
(`ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED`), `_effective_paper_mode_str`
parity, `paper_archive_state.json` round-trip + META_FILES /
`_INTERNAL_JSON_NAMES` registration, the linear identity regression (no
ari.rqgm imports/objects/files on a default paper run), independence from the
exploration `ari.mode` (the 2x2 matrix), and the re-invocation rule (persisted
paper mode wins; a fresh rqgm_archive run starts — never inert).

No test calls a real LLM.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from ari.config import (
    ARIConfig,
    PaperConfig,
    RQGMPaperConfig,
    _effective_mode_str,
    _effective_paper_mode_str,
    apply_paper_env_overrides,
    load_config,
)
from ari.rqgm.paper_mode import PaperMode, resolve_paper_mode


@pytest.fixture(autouse=True)
def _clear_paper_env(monkeypatch):
    monkeypatch.delenv("ARI_PAPER_MODE", raising=False)
    monkeypatch.delenv("ARI_RQGM_PAPER_ENABLED", raising=False)
    yield


# ── config parsing ──────────────────────────────────────────────────────────

def test_absent_blocks_default_to_linear():
    cfg = ARIConfig()
    assert cfg.paper.mode == "linear"
    assert cfg.rqgm.paper.enabled is False
    # archive skeleton defaults (Task 01 §6.1 / Task 02 §6.2)
    arch = cfg.rqgm.paper.archive
    assert (arch.width, arch.refine_rounds, arch.max_expansions, arch.depth) == (
        4, 2, 12, 3
    )
    assert arch.compile_threshold == 0.0
    assert cfg.rqgm.paper.epoch.rounds == 2
    assert cfg.rqgm.paper.prompt_evolution.enabled is True


def test_full_blocks_parse(tmp_path):
    wf = tmp_path / "workflow.yaml"
    wf.write_text(yaml.safe_dump({
        "paper": {"mode": "rqgm_archive"},
        "rqgm": {"paper": {
            "enabled": True,
            "archive": {"width": 3, "depth": 5, "max_expansions": 20,
                        "compile_threshold": 0.5},
            "epoch": {"rounds": 3},
            "prompt_evolution": {"enabled": False},
        }},
    }))
    cfg = load_config(str(wf))
    assert cfg.paper.mode == "rqgm_archive"
    assert cfg.rqgm.paper.enabled is True
    assert cfg.rqgm.paper.archive.width == 3
    assert cfg.rqgm.paper.archive.depth == 5
    assert cfg.rqgm.paper.archive.max_expansions == 20
    assert cfg.rqgm.paper.archive.compile_threshold == 0.5
    assert cfg.rqgm.paper.epoch.rounds == 3
    assert cfg.rqgm.paper.prompt_evolution.enabled is False


def test_invalid_paper_mode_literal_rejected():
    with pytest.raises(ValidationError):
        PaperConfig(mode="bogus")
    with pytest.raises(ValidationError):
        ARIConfig(paper={"mode": "archive"})


def test_untyped_top_level_paper_block_survives_field_filter(tmp_path):
    """The typed `paper:` field is picked up by load_config's model_fields
    filter (Task 01 §5.1)."""
    wf = tmp_path / "workflow.yaml"
    wf.write_text("paper:\n  mode: rqgm_archive\n")
    cfg = load_config(str(wf))
    assert cfg.paper.mode == "rqgm_archive"


# ── resolve_paper_mode: the four-cell table (§5.2) ──────────────────────────

@pytest.mark.parametrize("mode,enabled,expected", [
    ("linear", False, PaperMode.LINEAR),
    ("linear", True, PaperMode.LINEAR),
    ("rqgm_archive", False, PaperMode.LINEAR),
    ("rqgm_archive", True, PaperMode.RQGM_ARCHIVE),
])
def test_resolve_paper_mode_table(mode, enabled, expected):
    cfg = ARIConfig()
    cfg.paper.mode = mode
    cfg.rqgm.paper.enabled = enabled
    assert resolve_paper_mode(cfg) is expected


def test_resolve_paper_mode_warns_on_disagreement(caplog):
    import logging
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.paper.enabled = False
    with caplog.at_level(logging.WARNING):
        assert resolve_paper_mode(cfg) is PaperMode.LINEAR
    assert any("falling back to linear" in r.message for r in caplog.records)
    caplog.clear()
    cfg.paper.mode = "linear"
    cfg.rqgm.paper.enabled = True
    with caplog.at_level(logging.WARNING):
        assert resolve_paper_mode(cfg) is PaperMode.LINEAR
    assert any("falling back to linear" in r.message for r in caplog.records)


def test_resolve_paper_mode_never_reads_ari_mode():
    """Independence: resolve_paper_mode ignores ari.mode / rqgm.enabled (§5.6)."""
    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    cfg.paper.mode = "linear"
    cfg.rqgm.paper.enabled = False
    assert resolve_paper_mode(cfg) is PaperMode.LINEAR


# ── env overrides ───────────────────────────────────────────────────────────

def test_env_overrides_paper_mode(monkeypatch):
    cfg = ARIConfig()
    monkeypatch.setenv("ARI_PAPER_MODE", "rqgm_archive")
    monkeypatch.setenv("ARI_RQGM_PAPER_ENABLED", "1")
    apply_paper_env_overrides(cfg)
    assert cfg.paper.mode == "rqgm_archive"
    assert cfg.rqgm.paper.enabled is True


def test_env_invalid_values_ignored_with_warning(monkeypatch, caplog):
    import logging
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.paper.enabled = True
    monkeypatch.setenv("ARI_PAPER_MODE", "sideways")
    monkeypatch.setenv("ARI_RQGM_PAPER_ENABLED", "maybe")
    with caplog.at_level(logging.WARNING):
        apply_paper_env_overrides(cfg)
    # invalid values ignored — cfg unchanged
    assert cfg.paper.mode == "rqgm_archive"
    assert cfg.rqgm.paper.enabled is True
    assert any("ARI_PAPER_MODE" in r.message for r in caplog.records)
    assert any("ARI_RQGM_PAPER_ENABLED" in r.message for r in caplog.records)


# ── _effective_paper_mode_str parity (import-free mirror) ───────────────────

@pytest.mark.parametrize("mode,enabled", [
    ("linear", False), ("linear", True),
    ("rqgm_archive", False), ("rqgm_archive", True),
])
def test_effective_paper_mode_str_parity(mode, enabled):
    cfg = ARIConfig()
    cfg.paper.mode = mode
    cfg.rqgm.paper.enabled = enabled
    want = resolve_paper_mode(cfg).value
    assert _effective_paper_mode_str(cfg) == want


# ── paper_archive_state.json round-trip + registration ──────────────────────

def test_state_roundtrip_and_absence_tolerant(tmp_path):
    from ari.rqgm.paper_runtime import (
        build_paper_run_start_state,
        persist_paper_run_start,
        read_paper_archive_state,
    )
    assert read_paper_archive_state(tmp_path) is None  # absence-tolerant
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        mode_source="config", exploration_mode="ari_rqgm", seed_node_id="node_x",
    )
    state = read_paper_archive_state(tmp_path)
    assert state["schema_version"] == 1
    assert state["paper_mode"] == "rqgm_archive"
    assert state["rqgm_paper_enabled"] is True
    assert state["mode_source"] == "config"
    assert state["exploration_mode"] == "ari_rqgm"
    assert state["seed_node_id"] == "node_x"
    assert state["switch_journal"][0]["event"] == "paper_phase_start"
    # write-once: a second call never clobbers
    persist_paper_run_start(tmp_path, paper_mode="linear",
                            rqgm_paper_enabled=False, mode_source="env")
    assert read_paper_archive_state(tmp_path)["paper_mode"] == "rqgm_archive"
    # build helper coerces unknown mode_source to 'config'
    body = build_paper_run_start_state(
        paper_mode="rqgm_archive", rqgm_paper_enabled=True, mode_source="bogus")
    assert body["mode_source"] == "config"


def test_seed_change_is_journaled_not_rewritten(tmp_path):
    """`seed_node_id` records what the FIRST paper invocation started from,
    but the live seed is recomputed every round under three mechanisms that
    exist to change it (erasure excluding it, an escalation penalty demoting
    it, the replay re-applying both). A later invocation therefore APPENDS
    rather than rewriting — the record stays true and the file tells the
    whole story instead of a silently stale first line."""
    from ari.rqgm.paper_runtime import (
        SEED_JOURNAL_FIELD,
        persist_paper_run_start,
        read_paper_archive_state,
    )

    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_a",
    )
    assert SEED_JOURNAL_FIELD not in read_paper_archive_state(tmp_path)

    # Same seed on re-invocation: nothing to say.
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_a",
    )
    assert SEED_JOURNAL_FIELD not in read_paper_archive_state(tmp_path)

    # node_a erased / demoted → the next invocation seeds from node_b.
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_b",
    )
    state = read_paper_archive_state(tmp_path)
    assert state["seed_node_id"] == "node_a"          # the record is intact
    assert state[SEED_JOURNAL_FIELD] == [
        {"event": "seed_changed", "prior_seed_node_id": "node_a",
         "seed_node_id": "node_b"},
    ]

    # A second move chains off the LATEST seed, not the original record.
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_c",
    )
    journal = read_paper_archive_state(tmp_path)[SEED_JOURNAL_FIELD]
    assert [e["prior_seed_node_id"] for e in journal] == ["node_a", "node_b"]
    assert [e["seed_node_id"] for e in journal] == ["node_b", "node_c"]

    # …and re-invoking with the latest seed stays quiet.
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_c",
    )
    assert len(read_paper_archive_state(tmp_path)[SEED_JOURNAL_FIELD]) == 2


def test_seed_journaling_never_breaks_the_paper_phase(tmp_path):
    from ari.rqgm.paper_runtime import (
        journal_seed_change,
        persist_paper_run_start,
        read_paper_archive_state,
    )

    # No state file yet, or no seed to compare: silent no-ops.
    assert journal_seed_change(tmp_path, "node_a") is False
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        seed_node_id="node_a",
    )
    assert journal_seed_change(tmp_path, None) is False
    assert journal_seed_change(tmp_path, "") is False
    # An unreadable state file degrades instead of raising.
    (tmp_path / "paper_archive_state.json").write_text("{not json")
    assert journal_seed_change(tmp_path, "node_b") is False
    assert read_paper_archive_state(tmp_path) is None


def test_defaults_yaml_matches_pydantic():
    """The rqgm.paper block in defaults.yaml mirrors the typed RQGMPaperConfig
    defaults — the two homes cannot drift (Task 01 §6.1 / §7)."""
    import yaml
    import ari
    # cwd-independent: resolve against the installed package, not the process
    # working directory (the gate runs pytest from the repo root, not ari-core/).
    raw = yaml.safe_load(
        (Path(ari.__file__).parent / "configs" / "defaults.yaml").read_text()
    )
    pd = raw["rqgm"]["paper"]
    typed = RQGMPaperConfig()
    assert pd["enabled"] == typed.enabled
    a = pd["archive"]
    assert a["width"] == typed.archive.width
    assert a["refine_rounds"] == typed.archive.refine_rounds
    assert a["max_expansions"] == typed.archive.max_expansions
    assert a["depth"] == typed.archive.depth
    assert a["compile_threshold"] == typed.archive.compile_threshold
    assert pd["epoch"]["rounds"] == typed.epoch.rounds
    assert pd["prompt_evolution"]["enabled"] == typed.prompt_evolution.enabled
    # per-epoch self-consistency: width + width*refine_rounds == max_expansions
    assert (typed.archive.width
            + typed.archive.width * typed.archive.refine_rounds
            == typed.archive.max_expansions)


def test_new_filenames_are_meta_files():
    """Pattern: test_prompt_provenance.py::test_new_filenames_are_meta_files."""
    from ari.paths import PathManager
    from ari.orchestrator.node_report.builder import _INTERNAL_JSON_NAMES
    assert "paper_archive_state.json" in PathManager.META_FILES
    assert "paper_draft_archive.jsonl" in PathManager.META_FILES
    assert "paper_archive_state.json" in _INTERNAL_JSON_NAMES


# ── linear identity regression (no ari.rqgm on the paper path) ──────────────

def test_linear_path_imports_no_rqgm_and_writes_no_state(monkeypatch):
    """Replicates the exact linear branch of projects.py:paper and asserts no
    ari.rqgm module is imported and no provenance file is written."""
    for m in list(sys.modules):
        if m.startswith("ari.rqgm.paper"):
            sys.modules.pop(m, None)
    cfg = ARIConfig()  # default linear
    tmp = Path(tempfile.mkdtemp())
    apply_paper_env_overrides(cfg)
    state_path = tmp / "paper_archive_state.json"
    existed = state_path.exists()
    if existed:  # pragma: no cover - never on a linear checkpoint
        from ari.rqgm.paper_runtime import reconcile_paper_resume_mode
        reconcile_paper_resume_mode(cfg, tmp)
    mode_str = _effective_paper_mode_str(cfg)
    rt = None
    if mode_str == "rqgm_archive":  # pragma: no cover - default is linear
        from ari.rqgm.paper_runtime import PaperArchiveRuntime
        rt = PaperArchiveRuntime(cfg, checkpoint_dir=tmp)
    assert mode_str == "linear"
    assert rt is None
    assert not state_path.exists()
    leaked = [m for m in sys.modules if m.startswith("ari.rqgm.paper")]
    assert not leaked, f"linear path imported ari.rqgm modules: {leaked}"


# ── 2x2 independence (exploration ari.mode x paper.mode) ────────────────────

@pytest.mark.parametrize("ari_mode,rqgm_en", [
    ("simple_bfts", False), ("ari_rqgm", True),
])
@pytest.mark.parametrize("paper_mode,paper_en", [
    ("linear", False), ("rqgm_archive", True),
])
def test_2x2_matrix_orthogonal(ari_mode, rqgm_en, paper_mode, paper_en):
    cfg = ARIConfig()
    cfg.ari.mode = ari_mode
    cfg.rqgm.enabled = rqgm_en
    cfg.paper.mode = paper_mode
    cfg.rqgm.paper.enabled = paper_en
    # exploration axis independent of the paper axis
    assert _effective_mode_str(cfg) == ("ari_rqgm" if rqgm_en else "simple_bfts")
    assert _effective_paper_mode_str(cfg) == (
        "rqgm_archive" if paper_en else "linear"
    )


# ── re-invocation / resume (persisted paper mode wins) ──────────────────────

def test_reconcile_persisted_mode_wins_over_env(tmp_path, monkeypatch, caplog):
    import logging
    from ari.rqgm.paper_runtime import (
        persist_paper_run_start,
        reconcile_paper_resume_mode,
    )
    persist_paper_run_start(
        tmp_path, paper_mode="rqgm_archive", rqgm_paper_enabled=True,
        mode_source="config")
    # a re-invocation that requests linear via env
    cfg = ARIConfig()
    monkeypatch.setenv("ARI_PAPER_MODE", "linear")
    apply_paper_env_overrides(cfg)
    assert cfg.paper.mode == "linear"
    with caplog.at_level(logging.WARNING):
        reconcile_paper_resume_mode(cfg, tmp_path)
    # persisted rqgm_archive wins, warning logged
    assert cfg.paper.mode == "rqgm_archive"
    assert cfg.rqgm.paper.enabled is True
    assert any("persisted paper mode wins" in r.message for r in caplog.records)


def test_reconcile_noop_when_no_state_allows_fresh_archive(tmp_path):
    """A fresh rqgm_archive run (no state file) must be able to START — reconcile
    is a no-op on absence, so the archive is never inert (§5.5 absence-is-default;
    the single-entry-point `ari paper` first invocation IS the start)."""
    from ari.rqgm.paper_runtime import reconcile_paper_resume_mode
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.paper.enabled = True
    reconcile_paper_resume_mode(cfg, tmp_path)  # no state -> unchanged
    assert _effective_paper_mode_str(cfg) == "rqgm_archive"


# ── the paper AXIS must be honoured by EVERY entry point, not just `ari paper` ──
#
# `ari run` (exploration -> paper, one pass) and `ari resume` called
# `generate_paper_section` directly and unconditionally, so a config/env asking
# for `rqgm_archive` was silently dropped there: the archive was reachable ONLY
# by invoking `ari paper` separately on a finished checkpoint. The dispatch now
# lives in `ari.cli.paper_dispatch.run_paper_phase`, shared by all three.

def _dispatch_cfg(mode, enabled):
    cfg = ARIConfig()
    cfg.paper.mode = mode
    cfg.rqgm.paper.enabled = enabled
    return cfg


def test_every_entry_point_routes_the_paper_phase_through_one_dispatch():
    """`ari run`, `ari resume` and `ari paper` must all reach the archive via
    `run_paper_phase` — no entry may call the linear pipeline unconditionally.

    The sources are read from disk, not via ``inspect.getsource`` on an imported
    name: ``ari/cli/__init__.py`` binds ``run`` to the Typer COMMAND, which
    shadows the ``ari.cli.run`` submodule, so ``import ari.cli.run`` yields the
    function and would silently scope this check to one function body."""
    from ari.cli import paper_dispatch

    cli_dir = Path(paper_dispatch.__file__).parent
    run_src = (cli_dir / "run.py").read_text(encoding="utf-8")
    projects_src = (cli_dir / "projects.py").read_text(encoding="utf-8")

    assert "run_paper_phase(" in projects_src, "`ari paper` lost the dispatch"
    # BOTH one-pass entries — `ari run` and `ari resume` — must route through it
    assert run_src.count("run_paper_phase(") >= 2, (
        "both `ari run` and `ari resume` must route the paper phase through the "
        "shared dispatch; a bare generate_paper_section call silently drops a "
        "configured rqgm_archive"
    )


def test_dispatch_runs_linear_when_the_axis_says_linear(tmp_path):
    from ari.cli.paper_dispatch import run_paper_phase

    calls = []
    mode = run_paper_phase(
        _dispatch_cfg("linear", False), [], {"goal": "g"}, tmp_path, object(), "",
        linear_paper_fn=lambda *a, **k: calls.append(a),
    )
    assert mode == "linear"
    assert len(calls) == 1                        # the linear pipeline ran
    assert not (tmp_path / "paper_archive_state.json").exists()


def test_dispatch_enters_the_archive_when_both_flags_agree(tmp_path, monkeypatch):
    """The regression this whole seam exists for: with the axis set to
    `rqgm_archive`, the dispatch must build the archive runtime — NOT fall
    through to the linear pipeline."""
    from ari.cli import paper_dispatch

    built = {}

    class _RT:
        def __init__(self, cfg, **kw):
            built["cfg"] = cfg
            built["kw"] = kw

        def persist_mode(self, ckpt, **kw):
            built["persisted"] = kw
            (Path(ckpt) / "paper_archive_state.json").write_text("{}")

        def run_archive(self, *a, **kw):
            built["ran"] = True

    monkeypatch.setattr("ari.rqgm.paper_runtime.PaperArchiveRuntime", _RT)
    linear_calls = []
    mode = paper_dispatch.run_paper_phase(
        _dispatch_cfg("rqgm_archive", True), [], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=lambda *a, **k: linear_calls.append(a),
    )
    assert mode == "rqgm_archive"
    assert built.get("ran") is True                # the archive ran
    assert linear_calls == []                      # NOT the unconditional linear call
    assert built["persisted"]["mode_source"] == "config"


def test_dispatch_honours_the_env_override(tmp_path, monkeypatch):
    from ari.cli import paper_dispatch

    ran = {}

    class _RT:
        def __init__(self, cfg, **kw):
            pass

        def persist_mode(self, ckpt, **kw):
            ran["source"] = kw.get("mode_source")

        def run_archive(self, *a, **kw):
            ran["ran"] = True

    monkeypatch.setattr("ari.rqgm.paper_runtime.PaperArchiveRuntime", _RT)
    monkeypatch.setenv("ARI_PAPER_MODE", "rqgm_archive")
    monkeypatch.setenv("ARI_RQGM_PAPER_ENABLED", "true")
    mode = paper_dispatch.run_paper_phase(
        _dispatch_cfg("linear", False), [], {"goal": "g"}, tmp_path, object(),
        "", linear_paper_fn=lambda *a, **k: None,
    )
    assert mode == "rqgm_archive"                  # env flipped a linear config
    assert ran.get("ran") is True
    assert ran["source"] == "env"


def test_dispatch_passes_the_governance_llm_seams(tmp_path, monkeypatch):
    """`llm` / `adversary_llm` are what make the paper phase's governance real.

    Production omitted both, so the paper_self_preference AdversarialRound sat
    on `AdversaryEngine`'s no-LLM floor (zero attacks) and the PromptMutator
    never minted a candidate — while `rqgm.paper.self_preference.enabled` and
    `rqgm.paper.prompt_evolution.enabled` both default to TRUE. The config
    promised behaviour that could not happen."""
    from ari.cli import paper_dispatch

    seen = {}

    class _RT:
        def __init__(self, cfg, **kw):
            seen.update(kw)

        def persist_mode(self, ckpt, **kw):
            pass

        def run_archive(self, *a, **kw):
            pass

    monkeypatch.setattr("ari.rqgm.paper_runtime.PaperArchiveRuntime", _RT)
    sentinel = object()
    paper_dispatch.run_paper_phase(
        _dispatch_cfg("rqgm_archive", True), [], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=lambda *a, **k: None,
        paper_llm=sentinel,
    )
    assert seen.get("llm") is sentinel, (
        "the inner RQGMRuntime got no LLM — the PromptMutator cannot co-evolve "
        "the governed paper_writer/paper_reviewer bytes"
    )
    assert seen.get("adversary_llm") is sentinel, (
        "the paper_self_preference round got no LLM — AdversaryEngine.attack "
        "sits on its no-LLM floor and emits zero attacks"
    )


# ── the memory enrichment must reach the stages that consume it (sweep) ─────
#
# `pipeline/driver.py` writes `nodes_tree.json` with each node's memory entries
# so "downstream stages (transform, paper, EAR) become memory-aware without
# issuing an MCP call themselves" — but every consumer in workflow.yaml was
# pointed at the BARE `tree.json`, which has no memory field. The enrichment
# was computed on every run and read by nobody, including `write_paper_iterative`.

def test_every_nodes_json_consumer_gets_the_enriched_tree():
    import yaml

    from ari.config.finder import package_config_root

    wf = yaml.safe_load(
        (package_config_root() / "workflow.yaml").read_text(encoding="utf-8")
    )
    consumers = [
        (section, st.get("tool"), (st.get("inputs") or {})["nodes_json_path"])
        for section in ("pipeline", "bfts_pipeline")
        for st in (wf.get(section) or [])
        if (st.get("inputs") or {}).get("nodes_json_path")
    ]
    assert consumers, "no stage consumes nodes_json_path — the wiring moved"
    for section, tool, path in consumers:
        assert path.endswith("nodes_tree.json"), (
            f"{section}/{tool} reads {path!r} — the bare tree has no memory "
            "field, so the per-node enrichment is silently dropped"
        )


def test_the_driver_still_writes_the_enriched_file():
    """The file those stages now point at must be the one the driver writes."""
    from pathlib import Path

    import ari.pipeline.driver as _d

    src = Path(_d.__file__).read_text(encoding="utf-8")
    assert 'checkpoint_dir / "nodes_tree.json"' in src


# ── the paper-candidate pre-flight is shared by every entry (option E) ──────

class _PreflightSpy:
    """Duck-typed RQGMRuntime stand-in recording the pre-flight calls."""

    def __init__(self):
        self.escalated: list = []
        self.replayed: list = []
        self.reideated: list = []

    def replay_utility_penalties(self, all_nodes):
        self.replayed.append(len(all_nodes or []))
        return 0

    def run_paper_candidate_escalation(self, node, all_nodes=None):
        self.escalated.append(getattr(node, "id", ""))

    def reideate(self, event, ctx):
        self.reideated.append((event, ctx.get("node_id")))


def _pf_node(nid="n1", score=0.8):
    return SimpleNamespace(id=nid, metrics={"_scientific_score": score},
                           has_real_data=True, ancestor_ids=[])


def _seed_presignal(ckpt):
    """One paper pre-signal artifact — enough to arm the pre-flight gate."""
    (ckpt / "related_refs.json").write_text('{"refs": []}')


def test_preflight_runs_before_the_mode_branch(tmp_path):
    """`ari run`/`ari resume` used to skip the paper-candidate round entirely
    (it lived privately in `ari paper`). It now rides the shared dispatch, and
    fires on the EXPLORATION axis — i.e. even when the paper axis is linear,
    preserving the documented 2x2 orthogonality."""
    from ari.cli.paper_dispatch import run_paper_phase

    _seed_presignal(tmp_path)
    spy = _PreflightSpy()
    node = _pf_node()
    ran = []
    mode = run_paper_phase(
        _dispatch_cfg("linear", False), [node], {"goal": "g"}, tmp_path,
        object(), "",
        linear_paper_fn=lambda *a, **k: ran.append(len(spy.escalated)),
        rqgm=spy,
    )
    assert mode == "linear"
    assert spy.escalated == ["n1"]          # the round ran on the linear axis
    assert spy.replayed == [1]              # penalties replayed first
    assert spy.reideated == [("paper_candidate", "n1")]
    assert ran == [1]                       # …and BEFORE the paper pipeline


def test_preflight_defers_until_the_paper_evidence_exists(tmp_path):
    """The round's marker is one-shot per node and its whole point is to
    attack the paper's real artifacts. On a checkpoint that has not produced
    a paper yet (every fresh `ari run`), firing it early would spend the
    marker on an empty bundle and permanently suppress the artifact-grounded
    round. It defers, then runs once the pipeline HAS written the evidence."""
    from ari.cli.paper_dispatch import run_paper_phase

    spy = _PreflightSpy()
    order = []

    def _linear(all_nodes, experiment_data, ckpt, mcp, cfg_str):
        order.append(("pipeline", list(spy.escalated)))
        _seed_presignal(Path(ckpt))          # the paper stages write these

    mode = run_paper_phase(
        _dispatch_cfg("linear", False), [_pf_node()], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=_linear, rqgm=spy,
    )
    assert mode == "linear"
    assert order == [("pipeline", [])]       # nothing escalated pre-flight
    assert spy.escalated == ["n1"]           # …but the round DID run, after


def test_preflight_stays_deferred_when_no_paper_was_produced(tmp_path):
    """A pipeline that writes no evidence leaves the marker unspent, so a
    later invocation can still run the real, artifact-grounded round."""
    from ari.cli.paper_dispatch import run_paper_phase

    spy = _PreflightSpy()
    run_paper_phase(
        _dispatch_cfg("linear", False), [_pf_node()], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=lambda *a, **k: None, rqgm=spy,
    )
    assert spy.escalated == [] and spy.replayed == []


def test_preflight_is_inert_without_an_rqgm_runtime(tmp_path):
    """simple_bfts passes rqgm=None: dead branch, linear pipeline unchanged."""
    from ari.cli.paper_dispatch import run_paper_phase

    calls = []
    mode = run_paper_phase(
        _dispatch_cfg("linear", False), [_pf_node()], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=lambda *a, **k: calls.append(a),
    )
    assert mode == "linear" and len(calls) == 1


def test_preflight_fails_open_and_never_blocks_the_paper_phase(tmp_path):
    from ari.cli.paper_dispatch import run_paper_phase

    class _Boom:
        def run_paper_candidate_escalation(self, node, all_nodes=None):
            raise RuntimeError("adversary exploded")

    _seed_presignal(tmp_path)
    calls = []
    mode = run_paper_phase(
        _dispatch_cfg("linear", False), [_pf_node()], {"goal": "g"}, tmp_path,
        object(), "", linear_paper_fn=lambda *a, **k: calls.append(a),
        rqgm=_Boom(),
    )
    assert mode == "linear" and len(calls) == 1   # paper still ran


def test_every_entry_point_passes_the_rqgm_handle_to_the_dispatch():
    """The pre-flight only fires when the entry hands over the runtime, so the
    three call sites must all pass it — a missing `rqgm=` silently restores the
    `ari paper`-only asymmetry this hoist removed."""
    from ari.cli import paper_dispatch

    cli_dir = Path(paper_dispatch.__file__).parent
    run_src = (cli_dir / "run.py").read_text(encoding="utf-8")
    projects_src = (cli_dir / "projects.py").read_text(encoding="utf-8")

    assert "rqgm=_rqgm_paper" in projects_src, "`ari paper` lost the handle"
    assert run_src.count('rqgm=getattr(bfts, "rqgm", None)') >= 2, (
        "both `ari run` and `ari resume` must pass the exploration runtime to "
        "run_paper_phase, or the paper-candidate round never runs there"
    )
