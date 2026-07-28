"""RQGM Task 03 — ProposalRecord / ProposalStore / ProposalRouter
(docs/plans/ari_rqgm/03, §9).

Covers: schema round-trip + jsonschema validation (over-budget rejection),
``render_summary_ctx`` purity and budget, the idea.json projection golden
(9-key contract, sort invariant, pinned-in-front merge, marker preservation,
``_extract_plan_sections`` parseability), the deterministic routing policy
table (budget exhaustion, disabled generators never selected), Stage-1
record-only dual-write, the ``simple_bfts`` identity regression (no
``proposals/`` dir, no ``ari.rqgm`` import), META_FILES / blocklist
registration, and the ``ari_rqgm`` + ``virsci.enabled=false`` boot
integration over ``_run_loop``.

No test calls a real LLM: generators receive deterministic fakes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from ari.config import ARIConfig
from ari.rqgm.proposals.records import (
    RENDERED_CTX_BUDGET,
    ProposalRecord,
    ProposalSummaryView,
    clamp_summary,
    content_key,
    record_from_dict,
    render_summary_ctx,
    summary_from_dict,
    summary_violations,
)
from ari.rqgm.proposals.router import ProposalRouter, route
from ari.rqgm.proposals.store import (
    IDEA_JSON_KEYS,
    ProposalStore,
    import_idea_json_records,
)


# ── fixtures / fakes ─────────────────────────────────────────────────────────


def _payload(title: str = "Adaptive tiling GEMM", overall: float = 0.77) -> dict:
    return {
        "title": title,
        "short_description": f"{title}: tune tile sizes online.",
        "hypothesis": "Online tile tuning beats static tiling.",
        "experiment_plan": ["### 1) Implement baseline", "### 2) Add tuner"],
        "success_metric": {
            "name": "gflops",
            "higher_is_better": True,
            "rationale": "throughput",
        },
        "novelty_risks": ["close to autotuners"],
        "expected_artifacts": ["bench.csv"],
        "dissent_summary": "",
        "scores": {"novelty": 0.8, "feasibility": 0.7, "overall": overall},
    }


class FakeLLM:
    """Deterministic LLM stub returning canned JSON payloads in order."""

    def __init__(self, payloads=None):
        self._payloads = list(payloads or [_payload()])
        self.calls = 0

    def complete(self, messages, tools=None, require_tool=True, **kw):
        payload = self._payloads[min(self.calls, len(self._payloads) - 1)]
        self.calls += 1
        return SimpleNamespace(content=json.dumps(payload))


def _summary(**kw) -> ProposalSummaryView:
    base = dict(
        proposal_record_id="prop_000000",
        title="T",
        short_description="D",
        hypothesis="H",
        experiment_plan=("### 1) step",),
        success_metric={"name": "m", "higher_is_better": True, "rationale": "r"},
        novelty_risks=("risk",),
        expected_artifacts=("a.csv",),
        dissent_summary="",
        scores={"novelty": 0.5, "feasibility": 0.5, "overall": 0.5},
    )
    base.update(kw)
    return ProposalSummaryView(**base)


def _record(record_id="prop_000000", **kw) -> ProposalRecord:
    base = dict(
        record_id=record_id,
        generator="cheap",
        status="candidate",
        epoch_id="epoch_000",
        component_id="proposal_router_v1",
        prompt_hash="a" * 12,
        created_at="2026-07-05T00:00:00Z",
        summary=_summary(proposal_record_id=record_id),
        idea_projection={"projected": True},
    )
    base.update(kw)
    return ProposalRecord(**base)


def _rqgm_cfg(**pr_kwargs) -> ARIConfig:
    return ARIConfig(
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True},
        proposal_router=pr_kwargs or {},
    )


# ── schema round-trip + validation (§9 unit 1) ──────────────────────────────


def test_record_dict_roundtrip():
    rec = _record()
    assert record_from_dict(rec.to_dict()).to_dict() == rec.to_dict()
    view = _summary()
    assert summary_from_dict(view.to_dict()).to_dict() == view.to_dict()


def test_record_schema_validates_and_rejects():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    record_schema = schemas.load("proposal_record.schema")
    jsonschema.validate(_record().to_dict(), record_schema)
    # simple_bfts record-only nullability: epoch_id/prompt_hash null is legal.
    jsonschema.validate(
        _record(epoch_id=None, prompt_hash=None, generator="legacy_idea_json"
                ).to_dict(),
        record_schema,
    )
    # Missing mandatory envelope field is rejected.
    broken = _record().to_dict()
    del broken["prompt_hash"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, record_schema)
    # Unknown generator is rejected (closed vocabulary).
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_record(generator="llm_magic").to_dict(),
                            record_schema)


def test_summary_schema_rejects_over_budget():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    summary_schema = schemas.load("proposal_summary_view.schema")
    jsonschema.validate(_summary().to_dict(), summary_schema)
    over = _summary(title="t" * 201).to_dict()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(over, summary_schema)
    over = _summary(experiment_plan=tuple(f"### {i})" for i in range(7))).to_dict()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(over, summary_schema)


def test_summary_violations_and_clamp():
    over = ProposalSummaryView(
        title="t" * 300,
        short_description="d" * 700,
        hypothesis="h" * 500,
        experiment_plan=tuple("### %d) %s" % (i, "x" * 500) for i in range(8)),
        novelty_risks=tuple("r" * 300 for _ in range(5)),
        expected_artifacts=tuple("a" * 200 for _ in range(7)),
        dissent_summary="s" * 500,
    )
    assert summary_violations(over)  # rejected as over-budget
    clamped = clamp_summary(over)
    assert summary_violations(clamped) == []
    assert len(clamped.title) == 200
    assert len(clamped.experiment_plan) == 6


def test_render_summary_ctx_pure_and_budgeted():
    view = clamp_summary(
        _summary(short_description="d" * 600, hypothesis="h" * 400)
    )
    a = render_summary_ctx(view)
    b = render_summary_ctx(view)
    assert a == b  # byte-identical for identical input (P2)
    assert len(a) <= RENDERED_CTX_BUDGET
    big = clamp_summary(
        ProposalSummaryView(
            title="t" * 200,
            short_description="d" * 600,
            hypothesis="h" * 400,
            experiment_plan=tuple("### %d) %s" % (i, "x" * 400) for i in range(6)),
            novelty_risks=tuple("r" * 200 for _ in range(3)),
            expected_artifacts=tuple("a" * 120 for _ in range(5)),
            dissent_summary="s" * 400,
        )
    )
    assert len(render_summary_ctx(big)) <= RENDERED_CTX_BUDGET
    assert len(render_summary_ctx(big, budget=500)) <= 500


def test_content_key_ignores_id_status_and_wallclock():
    a = _record(record_id="prop_000001", status="candidate",
                created_at="2026-01-01T00:00:00Z")
    b = _record(record_id="prop_000042", status="selected",
                created_at="2027-12-31T23:59:59Z")
    assert content_key(a) == content_key(b)


# ── ProposalStore (append/dedup/selected) ────────────────────────────────────


def test_store_append_dedup_and_selected(tmp_path):
    store = ProposalStore(tmp_path)
    assert store.load_all() == []
    rec = _record(status="selected")
    assert store.append(rec) is True
    # Retry with a fresh id but identical content: deduplicated.
    assert store.append(_record(record_id="prop_000001",
                                status="candidate")) is False
    assert len(store.load_all()) == 1
    assert store.selected().record_id == "prop_000000"
    index = json.loads(store.index_path.read_text())
    assert index["records"]["prop_000000"]["generator"] == "cheap"


def test_store_satisfies_protocol(tmp_path):
    from ari.protocols import ProposalStore as ProposalStoreProtocol

    assert isinstance(ProposalStore(tmp_path), ProposalStoreProtocol)


# ── idea.json projection (§9 unit 2) ─────────────────────────────────────────


def test_projection_nine_key_contract_and_plan_parse(tmp_path):
    cfg = _rqgm_cfg()
    router = ProposalRouter(cfg, FakeLLM(), None, ProposalStore(tmp_path))
    records = router.generate_root_proposals({"goal": "Fast GEMM"})
    assert records and records[0].status == "selected"
    doc = json.loads((tmp_path / "idea.json").read_text())
    assert set(IDEA_JSON_KEYS) <= set(doc.keys())
    assert doc["primary_metric"] == "gflops"
    assert doc["higher_is_better"] is True
    assert doc["virsci_integration_status"] == "router:cheap"
    idea = doc["ideas"][0]
    assert idea["_proposal_record_id"] == records[0].record_id
    for key in ("title", "description", "novelty", "feasibility",
                "experiment_plan", "novelty_score", "feasibility_score",
                "overall_score"):
        assert key in idea
    from ari.pipeline.experiment_md import _extract_plan_sections

    sections = _extract_plan_sections(idea["experiment_plan"])
    assert len(sections) == 2  # the "### N)" format survived projection


def test_projection_sort_invariant(tmp_path):
    store = ProposalStore(tmp_path)
    store.append(_record(record_id="prop_000000", status="selected",
                         summary=_summary(proposal_record_id="prop_000000",
                                          title="Directive",
                                          scores={"overall": 0.1})))
    store.append(_record(record_id="prop_000001",
                         summary=_summary(proposal_record_id="prop_000001",
                                          title="Low",
                                          scores={"overall": 0.2})))
    store.append(_record(record_id="prop_000002",
                         summary=_summary(proposal_record_id="prop_000002",
                                          title="High",
                                          scores={"overall": 0.9})))
    assert store.write_idea_projection() is True
    doc = json.loads((tmp_path / "idea.json").read_text())
    titles = [i["title"] for i in doc["ideas"]]
    # ideas[0] is the directive; alternatives sorted by overall desc.
    assert titles == ["Directive", "High", "Low"]


def test_projection_pinned_in_front_and_marker_preservation(tmp_path):
    pinned_idea = {
        "title": "Inherited direction",
        "description": "Parent's chosen idea.",
        "novelty": "Novelty score: 8.0",
        "feasibility": "Feasibility score: 7.0",
        "experiment_plan": "### 1) Run inherited plan",
        "novelty_score": 0.8,
        "feasibility_score": 0.7,
        "overall_score": 0.77,
        "_pinned": True,
    }
    seed = {
        "gap_analysis": "seed gap",
        "ideas": [pinned_idea],
        "primary_metric": "latency_ms",
        "higher_is_better": False,
        "metric_rationale": "seed",
        "papers_analyzed": 3,
        "n_agents": 2,
        "discussion_rounds": 1,
        "virsci_integration_status": "reimpl",
        "_inherited_from": {"run_id": "parent-run", "idea_index": 0},
    }
    (tmp_path / "idea.json").write_text(json.dumps(seed))
    cfg = _rqgm_cfg()
    router = ProposalRouter(cfg, FakeLLM(), None, ProposalStore(tmp_path))
    router.generate_root_proposals({"goal": "Fast GEMM"})
    store = ProposalStore(tmp_path)
    # The inherited pinned idea was imported as a legacy_idea_json record.
    generators = [r.generator for r in store.load_all()]
    assert "legacy_idea_json" in generators
    doc = json.loads((tmp_path / "idea.json").read_text())
    # Pinned entry stays in front, verbatim; markers preserved.
    assert doc["ideas"][0] == pinned_idea
    assert doc["_inherited_from"] == seed["_inherited_from"]
    # Newly generated proposals become alternatives behind the pinned idea.
    assert any(i.get("_proposal_record_id") for i in doc["ideas"][1:])


def test_projection_respects_root_choice_marker(tmp_path):
    store = ProposalStore(tmp_path)
    store.append(_record(record_id="prop_000000", status="selected",
                         summary=_summary(proposal_record_id="prop_000000",
                                          title="Original",
                                          scores={"overall": 0.9})))
    store.append(_record(record_id="prop_000001",
                         summary=_summary(proposal_record_id="prop_000001",
                                          title="Runner-up",
                                          scores={"overall": 0.4})))
    store.write_idea_projection()
    # Simulate apply_root_choice: swap + one-shot marker.
    doc = json.loads((tmp_path / "idea.json").read_text())
    doc["ideas"] = [doc["ideas"][1], doc["ideas"][0]]
    doc["_root_choice"] = {"chosen_index": 1, "rationale": "better fit"}
    (tmp_path / "idea.json").write_text(json.dumps(doc))
    # Re-emitting the projection must respect the marker, not undo the swap.
    store.write_idea_projection()
    doc2 = json.loads((tmp_path / "idea.json").read_text())
    assert doc2["ideas"][0]["title"] == "Runner-up"
    assert doc2["_root_choice"]["rationale"] == "better fit"


# ── routing policy (§9 unit 3) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "event,available,budgets,expected",
    [
        ("initial_exploration", {"cheap"}, {}, "cheap"),
        ("initial_exploration", {"virsci", "cheap"}, {"virsci": 2}, "virsci"),
        ("initial_exploration", {"virsci", "cheap"}, {"virsci": 0}, "cheap"),
        ("frontier_stagnation", {"mutation", "cheap"}, {"mutation": 2},
         "mutation"),
        ("frontier_stagnation", {"mutation", "cheap"}, {"mutation": 0},
         "cheap"),
        ("major_pivot", {"prior_art", "cheap"}, {"prior_art": 1}, "prior_art"),
        ("paper_candidate", {"prior_art", "mutation", "cheap"},
         {"prior_art": 1, "mutation": 2}, "prior_art"),
        ("paper_candidate", {"mutation", "cheap"}, {"mutation": 1},
         "mutation"),
        ("paper_candidate", {"cheap"}, {}, "cheap"),
        # Disabled generators (absent from available) are never selected.
        ("frontier_stagnation", {"cheap"}, {"mutation": 2}, "cheap"),
        ("unknown_event", {"cheap"}, {}, "cheap"),
        ("initial_exploration", set(), {}, None),
    ],
)
def test_route_policy_table(event, available, budgets, expected):
    assert route(event, budgets, available) == expected
    # Deterministic: same inputs, same output.
    assert route(event, budgets, available) == expected


def test_router_budget_exhaustion_falls_back(tmp_path):
    """mutation cap=1: the second stagnation event falls through to cheap."""
    cfg = _rqgm_cfg(generators={"mutation": {"enabled": True,
                                             "max_calls_per_epoch": 1}})
    llm = FakeLLM([_payload("First"), _payload("Second"), _payload("Third")])
    store = ProposalStore(tmp_path)
    router = ProposalRouter(cfg, llm, None, store)
    router.generate_root_proposals({"goal": "g"})  # cheap, selected
    first = router.on_event("frontier_stagnation", {"goal": "g"})
    assert [r.generator for r in first] == ["mutation"]
    second = router.on_event("frontier_stagnation", {"goal": "g"})
    assert [r.generator for r in second] == ["cheap"]


def test_router_disabled_generator_never_selected(tmp_path):
    cfg = _rqgm_cfg(generators={"prior_art": {"enabled": False},
                                "mutation": {"enabled": True,
                                             "max_calls_per_epoch": 2}})
    llm = FakeLLM([_payload("Root"), _payload("Mut")])
    router = ProposalRouter(cfg, llm, None, ProposalStore(tmp_path))
    router.generate_root_proposals({"goal": "g"})
    records = router.on_event("paper_candidate", {"goal": "g"})
    assert records and records[0].generator == "mutation"


def test_router_failure_degrades_to_status_quo(tmp_path):
    """A raising generator must never propagate out of the router."""

    class Boom:
        name = "cheap"

        def generate(self, ctx):
            raise RuntimeError("boom")

    cfg = _rqgm_cfg()
    router = ProposalRouter(cfg, None, None, ProposalStore(tmp_path),
                            generators={"cheap": Boom()})
    assert router.generate_root_proposals({"goal": "g"}) == []
    assert router.on_event("frontier_stagnation", {"goal": "g"}) == []
    assert not (tmp_path / "idea.json").exists()


def test_mutation_generator_sets_parent_ref(tmp_path):
    cfg = _rqgm_cfg()
    llm = FakeLLM([_payload("Root"), _payload("Mutated")])
    store = ProposalStore(tmp_path)
    router = ProposalRouter(cfg, llm, None, store)
    root = router.generate_root_proposals({"goal": "g"})
    records = router.on_event("frontier_stagnation", {"goal": "g"})
    assert records[0].generator == "mutation"
    assert (records[0].source_refs["parent_proposal_id"]
            == root[0].record_id)
    # The parent record itself is never mutated in place (append-only truth).
    stored = {r.record_id: r for r in store.load_all()}
    assert stored[root[0].record_id].summary.title == "Root"


# ── Stage-1 record-only dual-write (§8 Stage 1) ──────────────────────────────


def _legacy_idea_json() -> dict:
    return {
        "gap_analysis": "gap",
        "ideas": [
            {"title": "Legacy A", "description": "a", "novelty": "n",
             "feasibility": "f",
             "experiment_plan": "### 1) do A\n\n### 2) measure A",
             "novelty_score": 0.9, "feasibility_score": 0.8,
             "overall_score": 0.85},
            {"title": "Legacy B", "description": "b", "novelty": "n",
             "feasibility": "f", "experiment_plan": "### 1) do B",
             "novelty_score": 0.4, "feasibility_score": 0.4,
             "overall_score": 0.4},
        ],
        "primary_metric": "throughput",
        "higher_is_better": True,
        "metric_rationale": "r",
        "papers_analyzed": 2,
        "n_agents": 2,
        "discussion_rounds": 1,
        "virsci_integration_status": "reimpl",
    }


def test_import_idea_json_records_is_idempotent(tmp_path):
    (tmp_path / "idea.json").write_text(json.dumps(_legacy_idea_json()))
    before = (tmp_path / "idea.json").read_bytes()
    assert import_idea_json_records(tmp_path) == 2
    assert import_idea_json_records(tmp_path) == 0  # content-key dedup
    records = ProposalStore(tmp_path).load_all()
    assert [r.generator for r in records] == ["legacy_idea_json"] * 2
    assert [r.status for r in records] == ["selected", "candidate"]
    assert records[0].epoch_id is None and records[0].prompt_hash is None
    # Zero behavior change: idea.json bytes untouched (single writer kept).
    assert (tmp_path / "idea.json").read_bytes() == before


# ── simple_bfts identity + registration regressions (§9 regression) ──────────


def _forget_rqgm_modules(monkeypatch):
    for name in [n for n in list(sys.modules)
                 if n == "ari.rqgm" or n.startswith("ari.rqgm.")]:
        monkeypatch.delitem(sys.modules, name)


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


def _make_strategy(expand_kwargs_log=None):
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    # A plain (non-governed) strategy: without this, MagicMock's auto-attr
    # would make _run_loop's duck-typed `getattr(bfts, "rqgm", None)` truthy.
    bfts.rqgm = None
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        if expand_kwargs_log is not None:
            expand_kwargs_log.append(dict(kwargs))
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        child.original_direction = f"direction {counter['n']}"
        child.name = f"child name {counter['n']}"
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda f, goal, mem: f[0]
    bfts.select_next_node.side_effect = lambda p, goal, mem: p[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    return bfts


def _run_short_loop(tmp_path, strategy, cfg, agent=None):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    all_nodes = [root]
    agent = agent or _make_agent()
    _run_loop(
        cfg, strategy, agent, [root], all_nodes,
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="rqgm-proposals",
    )
    return agent, all_nodes


def test_simple_bfts_default_creates_no_proposals_dir(monkeypatch, tmp_path):
    """Default run: no proposals/ dir, idea.json byte-identical, and no
    ari.rqgm module import at all."""
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    (tmp_path / "idea.json").write_text(json.dumps(_legacy_idea_json()))
    before = (tmp_path / "idea.json").read_bytes()
    _forget_rqgm_modules(monkeypatch)
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    assert cfg.proposal_router.record_only is False  # shipped default
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    assert not (tmp_path / "proposals").exists()
    assert (tmp_path / "idea.json").read_bytes() == before
    assert not any(n == "ari.rqgm" or n.startswith("ari.rqgm.")
                   for n in sys.modules), \
        "default simple_bfts run must not import ari.rqgm"


def test_simple_bfts_record_only_dual_writes(monkeypatch, tmp_path):
    """Ablation B1: record_only=true imports idea.json into the record store
    with zero behavior change (idea.json bytes untouched)."""
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    (tmp_path / "idea.json").write_text(json.dumps(_legacy_idea_json()))
    before = (tmp_path / "idea.json").read_bytes()
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60},
                    proposal_router={"record_only": True})
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    records = ProposalStore(tmp_path).load_all()
    assert [r.generator for r in records] == ["legacy_idea_json"] * 2
    assert (tmp_path / "idea.json").read_bytes() == before


def test_proposal_filenames_registered():
    """META_FILES / _TRACE_FILES / node-report blocklists (§6.3)."""
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_DIRS,
        _FILES_CHANGED_BLOCKLIST_NAMES,
        _INTERNAL_JSON_NAMES,
        classify_artifact_role,
    )
    from ari.paths import PathManager, RuntimePathResolver

    assert "proposal_records.jsonl" in PathManager.META_FILES
    assert "proposal_index.json" in PathManager.META_FILES
    assert PathManager.is_meta_file("proposal_records.jsonl")
    assert PathManager.is_meta_file("proposal_index.json")
    assert RuntimePathResolver.bucket_for("proposal_records.jsonl") == "traces"
    assert "proposal_records.jsonl" in _FILES_CHANGED_BLOCKLIST_NAMES
    assert "proposal_index.json" in _FILES_CHANGED_BLOCKLIST_NAMES
    assert "proposals" in _FILES_CHANGED_BLOCKLIST_DIRS
    assert "proposal_index.json" in _INTERNAL_JSON_NAMES
    assert classify_artifact_role("proposal_index.json") == "unknown"


def test_proposals_never_in_files_changed(tmp_path):
    from ari.orchestrator.node_report.builder import compute_files_changed

    work = tmp_path / "work"
    (work / "proposals" / "archive" / "prop_000000").mkdir(parents=True)
    (work / "proposals" / "proposal_records.jsonl").write_text("{}\n")
    (work / "proposals" / "archive" / "prop_000000" / "raw_output.json"
     ).write_text("{}")
    (work / "result.csv").write_text("a,b\n")
    changed = compute_files_changed(None, work)
    paths = [f["path"] for f in changed["added"]]
    assert paths == ["result.csv"]


# ── ari_rqgm boot integration (§9 integration) ───────────────────────────────


def test_ari_rqgm_boot_virsci_off(monkeypatch, tmp_path):
    """ari_rqgm + virsci.enabled=false over a short _run_loop:

    CheapGenerator proposals flow, the VirSciAdapter module is never even
    imported (construction impossible), no virsci_snapshot/ build is
    attempted, the expand context renders from the ProposalSummaryView, and
    expansion directions are recorded as observations.
    """
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delitem(
        sys.modules, "ari.rqgm.proposals.virsci_adapter", raising=False
    )
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60},
                    ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    assert cfg.proposal_router.generators.virsci.enabled is False
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=FakeLLM())
    expand_kwargs: list[dict] = []
    governed = runtime.wrap_search_strategy(_make_strategy(expand_kwargs))
    agent, _ = _run_short_loop(tmp_path, governed, cfg)

    store = ProposalStore(tmp_path)
    records = store.load_all()
    assert any(r.generator == "cheap" and r.status == "selected"
               for r in records)
    # Root ideation replaced the agent-initiated generate_ideas call.
    assert agent._ideas_generated is True
    assert agent._suppress_tools == {"generate_ideas"}
    # idea.json is the router's projection.
    doc = json.loads((tmp_path / "idea.json").read_text())
    assert doc["ideas"][0]["_proposal_record_id"] == store.selected().record_id
    # Expand received the summary-rendered context, not the idea.json one.
    assert expand_kwargs, "expand was never reached"
    expected_ctx = render_summary_ctx(store.selected().summary)
    assert all(k["idea_context"] == expected_ctx for k in expand_kwargs)
    # Expansion directions were recorded as observations (never projected).
    observed = [r for r in records if r.status == "expanded"]
    assert observed and all(
        r.idea_projection == {"projected": False} for r in observed
    )
    titles = {i["title"] for i in doc["ideas"]}
    assert not any(r.summary.title in titles for r in observed)
    # VirSci fully absent: adapter module never imported, no snapshot built.
    assert "ari.rqgm.proposals.virsci_adapter" not in sys.modules
    assert not (tmp_path / "virsci_snapshot").exists()


def test_expansion_recording_never_breaks_expand(tmp_path):
    """Recording failures degrade: expand still returns the children."""
    from ari.rqgm.runtime import RQGMRuntime

    cfg = _rqgm_cfg()
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=FakeLLM())
    governed = runtime.wrap_search_strategy(_make_strategy())

    def _boom(node, direction):
        raise RuntimeError("recording broke")

    runtime.record_expansion_proposal = _boom  # type: ignore[assignment]
    from ari.orchestrator.node import Node

    parent = Node(id="p", parent_id=None, depth=0)
    children = governed.expand(parent, idea_context="ctx")
    assert len(children) == 1


# ── config (§6.5) ────────────────────────────────────────────────────────────


def test_defaults_yaml_matches_typed_proposal_router_defaults():
    """defaults.yaml proposal_router block == pydantic defaults (parity)."""
    from ari.config import ProposalRouterConfig

    defaults_path = (
        Path(__file__).resolve().parents[1] / "ari" / "configs" / "defaults.yaml"
    )
    raw = yaml.safe_load(defaults_path.read_text())["proposal_router"]
    typed = ProposalRouterConfig().model_dump()
    assert raw == typed


def test_proposal_router_cfg_survives_load_config(tmp_path):
    """The typed field keeps the block through load_config's key filter."""
    from ari.config import load_config

    p = tmp_path / "workflow.yaml"
    p.write_text(yaml.safe_dump({
        "skills": [],
        "proposal_router": {
            "record_only": True,
            "generators": {"virsci": {"enabled": True,
                                      "max_calls_per_epoch": 1}},
        },
    }))
    cfg = load_config(str(p))
    assert cfg.proposal_router.record_only is True
    assert cfg.proposal_router.generators.virsci.enabled is True
    assert cfg.proposal_router.generators.virsci.max_calls_per_epoch == 1
    assert cfg.proposal_router.generators.cheap.enabled is True  # defaults


# ── the three non-root trigger events must actually dispatch (sweep) ─────────
#
# `ProposalRouter.on_event` — documented as "the re-ideation surface" — had NO
# production caller. Only `initial_exploration` (row: virsci, cheap) ever
# dispatched, so 3 of the 4 rows of `_EVENT_PRIORITY` were dead and the
# MutationGenerator / PriorArtDifferentiationGenerator were unreachable in
# production despite being enabled by default with real per-epoch budgets.

class _ProposalLLM:
    def complete(self, messages, **kw):
        class _R:
            content = '{"title":"T","hypothesis":"H","method":"M"}'
        return _R()


def _rqgm_for_reideation(tmp_path):
    from ari.config import ARIConfig
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=_ProposalLLM())
    rt.ensure_epoch(0, checkpoint_dir=tmp_path, run_id="reideate-test")
    # a root record so `mutation` has a parent to mutate
    rt.generate_root_proposals({"goal": "g", "checkpoint_dir": str(tmp_path)})
    return rt


def test_frontier_stagnation_reaches_the_mutation_generator(tmp_path):
    rt = _rqgm_for_reideation(tmp_path)
    out = rt.reideate("frontier_stagnation",
                      {"goal": "g", "checkpoint_dir": str(tmp_path)})
    assert out, "frontier_stagnation produced no proposal"
    assert [getattr(r, "generator", None) for r in out] == ["mutation"]


def test_major_pivot_reaches_the_prior_art_generator(tmp_path):
    rt = _rqgm_for_reideation(tmp_path)
    out = rt.reideate("major_pivot", {
        "goal": "g", "checkpoint_dir": str(tmp_path),
        "survey_refs": ["Prior Art X"],
    })
    assert out, "major_pivot produced no proposal"
    assert [getattr(r, "generator", None) for r in out] == ["prior_art"]


def test_paper_candidate_dispatches(tmp_path):
    rt = _rqgm_for_reideation(tmp_path)
    out = rt.reideate("paper_candidate", {
        "goal": "g", "checkpoint_dir": str(tmp_path),
        "survey_refs": ["Prior Art X"],
    })
    assert out, "paper_candidate produced no proposal"


def test_reideation_respects_the_per_epoch_budget(tmp_path):
    """prior_art has max_calls_per_epoch=1 — the second event must not reuse it."""
    rt = _rqgm_for_reideation(tmp_path)
    ctx = {"goal": "g", "checkpoint_dir": str(tmp_path),
           "survey_refs": ["Prior Art X"]}
    first = rt.reideate("major_pivot", ctx)
    assert [getattr(r, "generator", None) for r in first] == ["prior_art"]
    second = rt.reideate("major_pivot", ctx)
    assert [getattr(r, "generator", None) for r in second] != ["prior_art"]


def test_every_declared_trigger_event_is_wired_at_a_production_hook():
    """All four rows of the routing table must have a caller."""
    from pathlib import Path

    import ari.rqgm.runtime as _rt
    from ari.rqgm.proposals.router import _EVENT_PRIORITY

    cli = Path(_rt.__file__).parents[1] / "cli"
    sources = "\n".join(
        (cli / f).read_text(encoding="utf-8")
        for f in ("bfts_loop.py", "projects.py")
    )
    for event in _EVENT_PRIORITY:
        if event == "initial_exploration":
            assert "generate_root_proposals" in sources
        else:
            assert f'"{event}"' in sources, (
                f"trigger event {event!r} has no production hook — its row of "
                "_EVENT_PRIORITY is dead"
            )


# ── root-ideation prior-art grounding ───────────────────────────────────────

def test_initial_exploration_can_reach_prior_art():
    """The FIRST idea — the one every later node descends from — had no
    literature-grounded path: `initial_exploration` listed only
    (virsci, cheap), and virsci is default-OFF, so every run fell through to
    `cheap` with papers_analyzed=0 and a novelty claim that was pure LLM
    self-assessment."""
    from ari.rqgm.proposals.router import route

    avail = {"cheap", "prior_art", "mutation"}          # virsci off
    assert route("initial_exploration", {"prior_art": 3}, avail) == "prior_art"
    # …and it is still safe when prior_art has no budget.
    assert route("initial_exploration", {"prior_art": 0}, avail) == "cheap"


def test_prior_art_degrades_when_no_refs_are_supplied():
    """The addition must not change behaviour where grounding is unavailable:
    the generator returns [] on empty survey_refs and the router falls through
    to cheap exactly as before."""
    from ari.rqgm.proposals.generators import PriorArtDifferentiationGenerator

    gen = PriorArtDifferentiationGenerator.__new__(PriorArtDifferentiationGenerator)
    assert gen.generate({"goal": "g", "survey_refs": []}) == []
    assert gen.generate({"goal": "g"}) == []


def test_root_survey_refs_supplies_the_previously_dead_input(caplog):
    """`ctx["survey_refs"]` was READ in exactly one place (the prior-art
    generator) and WRITTEN in none, so that generator was reachable from the
    router table yet structurally unable to ever produce anything."""
    import json as _json
    from types import SimpleNamespace

    from ari.cli.bfts_loop import _root_survey_refs

    class _MCP:
        def call_tool(self, name, args):
            assert name == "survey"
            return {"result": _json.dumps({"papers": [
                {"title": "Wavefront diamond blocking", "year": 2014},
                {"title": "Polyhedral stencils on FPGAs", "year": 2024},
            ]})}

    refs = _root_survey_refs(SimpleNamespace(mcp=_MCP()), "stencil cache blocking")
    assert refs == ["Wavefront diamond blocking (2014)",
                    "Polyhedral stencils on FPGAs (2024)"]


def test_root_survey_refs_is_fail_open_and_says_so(caplog):
    """A hook on the _run_loop main thread must never kill the run — but the
    absence of grounding must be VISIBLE, not silent: an ungrounded novelty
    claim that nobody flags is exactly what shipped before."""
    from types import SimpleNamespace

    from ari.cli.bfts_loop import _root_survey_refs

    assert _root_survey_refs(SimpleNamespace(mcp=None), "goal") == []
    # MCPClient RETURNS {"error": ...}; it does not raise.
    err = SimpleNamespace(call_tool=lambda n, a: {"error": "provider down"})
    assert _root_survey_refs(SimpleNamespace(mcp=err), "goal") == []

    with caplog.at_level("WARNING"):
        empty = SimpleNamespace(
            call_tool=lambda n, a: {"result": '{"papers": []}'})
        assert _root_survey_refs(SimpleNamespace(mcp=empty), "goal") == []
    assert any("ungrounded" in r.message or "NO prior-art" in r.message
               for r in caplog.records), [r.message for r in caplog.records]
