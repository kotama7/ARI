"""``GET /state`` legacy-facade freeze — frozen top-level key set (gui_refresh G2 tail).

Plan 04 §Caching and polling policy: "`/state` は legacy facade として凍結し、
新 feature を追加して肥大化させない". This suite pins the EXACT top-level key
set ``services.state_service.build_app_state`` emits, as frozen literals, for
the two boundary scenarios:

* no active checkpoint (minimal payload — process/status skeleton only), and
* a fully-populated checkpoint fixture that trips every conditional injection
  branch (tree + idea.json + science_data.json + results.json + paper/review/
  repro markers + cost artifacts + launch_config.json), i.e. the maximal
  payload the facade can produce today.

If either assertion fails with ADDED keys, someone grew the frozen facade —
put the new data on a run-explicit ``/api/v1`` endpoint (``ari/viz/v1/``)
instead (plan 04 §API principles; MN-10 run identity). REMOVED keys break the
legacy dashboard pages still polling ``/state`` (parity invariant) — also
forbidden until the facade itself is deleted at the G6 legacy-removal gate
(plan 04 §Compatibility and migration step 7; RR-P0-8 disposition in
docs/plans/gui_refresh/baseline/risk_register.md).

Captured faithfully from the live builder on 2026-07-26 (35 keys maximal /
7 keys minimal). The per-key VALUE contracts are covered elsewhere
(test_contract_snapshots.py, tree_view byte-parity, test_server.py literal
pins); this suite freezes only the additive-growth seam.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import state as _st
from ari.viz.services import state_service

_FREEZE_POINTER = (
    "/state is a FROZEN legacy facade (plan 04 §Caching and polling policy, "
    "G2 tail): do NOT add top-level keys here — serve new data from a "
    "run-explicit /api/v1 endpoint (ari/viz/v1/) instead."
)

# Frozen literal — the exact top-level key set of GET /state with NO active
# checkpoint (process/status skeleton the legacy pages always receive).
FROZEN_KEYS_NO_CHECKPOINT = frozenset({
    "exit_code",
    "is_running",
    "llm_model",
    "pid",
    "running",
    "running_pid",
    "status_label",
})

# Frozen literal — the exact top-level key set with a fully-populated
# checkpoint (every conditional branch of build_app_state active). "nodes"
# is the tree-file passthrough (the fixture tree carries only "nodes"; the
# tree payload itself is frozen byte-for-byte by viz/tree_view.py).
FROZEN_KEYS_FULL_CHECKPOINT = FROZEN_KEYS_NO_CHECKPOINT | frozenset({
    "actual_models",
    "all_metric_keys",
    "best_nodes",
    "checkpoint_id",
    "checkpoint_path",
    "cost",
    "current_phase",
    "experiment_config",
    "experiment_context",
    "experiment_goal",
    "experiment_md_content",
    "experiment_md_path",
    "experiment_text",
    "gap_analysis",
    "has_paper",
    "has_pdf",
    "has_repro",
    "has_review",
    "idea_metric_rationale",
    "idea_primary_metric",
    "ideas",
    "llm_model_actual",
    "node_count",
    "nodes",
    "phase_flags",
    "summary_stats",
    "typed_split_sources",
    "workflow_yaml",
})


@pytest.fixture()
def clean_state(monkeypatch):
    """Neutral module-global ``_st`` state (no proc, no launch, no settings)."""
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_last_experiment_md", None)
    monkeypatch.setattr(_st, "_launch_config", None)
    monkeypatch.setattr(_st, "_launch_llm_model", None)
    monkeypatch.setattr(_st, "_launch_llm_provider", None)
    monkeypatch.setattr(_st, "_settings_path", None)


def _full_checkpoint(tmp_path: Path) -> Path:
    """Materialize a checkpoint dir that activates every /state branch."""
    d = tmp_path / "ckpt_full"
    d.mkdir()
    (d / "nodes_tree.json").write_text(json.dumps(
        {"nodes": [{"id": "node-0", "status": "success", "metrics": {}}]}
    ))
    (d / "idea.json").write_text(json.dumps({
        "ideas": [{"title": "t"}],
        "gap_analysis": "gap",
        "primary_metric": "accuracy",
        "metric_rationale": "why",
    }))
    (d / "science_data.json").write_text(json.dumps({
        "experiment_context": {"domain": "x"},
        "configurations": [{"metrics": {"accuracy": 1.0}}],
        "summary_stats": {},
    }))
    (d / "results.json").write_text(json.dumps({
        "experiment_goal": "goal",
        "config_path": str(d / "experiment.md"),
    }))
    (d / "experiment.md").write_text("# Goal\ntext\n")
    (d / "workflow.yaml").write_text("bfts:\n  max_total_nodes: 4\n")
    (d / "full_paper.tex").write_text("x")
    (d / "full_paper.pdf").write_bytes(b"x")
    (d / "review_report.json").write_text("{}")
    (d / "cost_summary.json").write_text('{"total": 0.0}')
    (d / "launch_config.json").write_text(json.dumps(
        {"llm_model": "m", "llm_provider": "p"}
    ))
    (d / "cost_trace.jsonl").write_text('{"skill": "coder", "model": "m1"}\n')
    (d / "reproducibility_report.json").write_text("{}")
    return d


def _assert_frozen(actual: set, frozen: frozenset, scenario: str) -> None:
    added = sorted(actual - frozen)
    removed = sorted(frozen - actual)
    assert not added, (
        f"NEW top-level /state keys in the {scenario} payload: {added}. "
        + _FREEZE_POINTER
    )
    assert not removed, (
        f"top-level /state keys DROPPED from the {scenario} payload: "
        f"{removed}. Legacy pages still poll /state (parity invariant); the "
        "facade may only disappear wholesale at the G6 legacy-removal gate."
    )


def test_no_checkpoint_key_set_is_frozen(clean_state):
    data = state_service.build_app_state()
    _assert_frozen(set(data), FROZEN_KEYS_NO_CHECKPOINT, "no-checkpoint")


def test_full_checkpoint_key_set_is_frozen(clean_state, monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_checkpoint_dir", _full_checkpoint(tmp_path))
    data = state_service.build_app_state()
    _assert_frozen(set(data), FROZEN_KEYS_FULL_CHECKPOINT, "full-checkpoint")


def test_freeze_marker_present_in_source():
    """The FROZEN declaration must stay on the builder (plan 04 freeze)."""
    src = Path(state_service.__file__).read_text(encoding="utf-8")
    assert "FROZEN" in src and "legacy facade" in src, (
        "services/state_service.py lost its FROZEN legacy-facade header — "
        "restore it (plan 04 §Caching and polling policy; G2 tail)."
    )
