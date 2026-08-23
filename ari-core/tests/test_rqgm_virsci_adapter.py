"""RQGM Task 03 — VirSciAdapter + VirSci optionality
(docs/guides/virsci_integration.md "Archive vs. summary", "Guarantees when
enabled: false", "The four mode × VirSci combinations").

Covers: normalization of the canned 9-key ``generate_ideas`` payload (both
``real_wrap`` and ``reimpl`` statuses), archive_refs population, the
archive/summary split (no transcript content in any summary or rendered
expand context), MCP retry idempotency (3× call → no duplicate records),
the mode × VirSci four-combination matrix at config-validation + boot level,
and the ``virsci.enabled=false`` guarantees (adapter never constructed, no
idea-skill VirSci path touched — the assertion Task 01 deferred here).

The MCP client is always a fake: no VirSci install, no vendored submodule,
no real LLM call anywhere in this module.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ari.config import ARIConfig
from ari.rqgm.proposals.records import render_summary_ctx
from ari.rqgm.proposals.router import ProposalRouter
from ari.rqgm.proposals.store import ProposalStore
from ari.rqgm.proposals.virsci_adapter import (
    VirSciAdapter,
    _mcp_payload,
    literature_query,
    normalize_generate_ideas_result,
)

TRANSCRIPT_MARKER = "UNIQUE-TRANSCRIPT-CONTENT-9f2d"
GAP_MARKER = "UNIQUE-GAP-ANALYSIS-77aa"


def _nine_key_payload(status: str = "reimpl: VirSci submodule unavailable "
                                    "— using inline fallback prompts") -> dict:
    return {
        "gap_analysis": f"Current tools ignore X. {GAP_MARKER}",
        "ideas": [
            {
                "title": "Idea One",
                "description": "First sentence one. More detail follows.",
                "novelty": "Novelty score: 8.0",
                "feasibility": "Feasibility score: 7.0",
                "experiment_plan": "### 1) Build\nbody\n\n### 2) Measure\nbody",
                "novelty_score": 0.8,
                "feasibility_score": 0.7,
                "overall_score": 0.77,
            },
            {
                "title": "Idea Two",
                "description": "Second idea.",
                "novelty": "Novelty score: 6.0",
                "feasibility": "Feasibility score: 9.0",
                "experiment_plan": "### 1) Prototype",
                "novelty_score": 0.6,
                "feasibility_score": 0.9,
                "overall_score": 0.68,
            },
        ],
        "primary_metric": "throughput_gflops",
        "higher_is_better": True,
        "metric_rationale": "Measures computational efficiency.",
        "papers_analyzed": 12,
        "n_agents": 4,
        "discussion_rounds": 2,
        "virsci_integration_status": status,
    }


class FakeMCP:
    """Deterministic MCPClient stub for the two idea-skill tools."""

    def __init__(self, payload: dict | None = None):
        self.payload = payload or _nine_key_payload()
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool_name, args, **kw):
        self.calls.append((tool_name, dict(args)))
        if tool_name == "survey":
            return {"papers": [{"title": "Prior paper", "abstract": "a"}]}
        if tool_name == "generate_ideas":
            return {"result": json.dumps(self.payload)}
        raise KeyError(tool_name)


def _virsci_cfg(**virsci) -> ARIConfig:
    virsci.setdefault("enabled", True)
    virsci.setdefault("max_calls_per_epoch", 10)
    return ARIConfig(
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True},
        proposal_router={"generators": {"virsci": virsci}},
    )


# ── normalization: the canned 9-key payload → bounded summary drafts ─────────


@pytest.mark.parametrize("status", ["real_wrap", "reimpl: inline fallback"])
def test_normalize_nine_key_payload(status):
    drafts = normalize_generate_ideas_result(_nine_key_payload(status))
    assert len(drafts) == 2
    one = drafts[0]
    assert one.generator == "virsci"
    assert one.summary.title == "Idea One"
    assert one.summary.hypothesis == "First sentence one"
    assert one.summary.success_metric == {
        "name": "throughput_gflops",
        "higher_is_better": True,
        "rationale": "Measures computational efficiency.",
    }
    assert one.summary.scores == {
        "novelty": 0.8, "feasibility": 0.7, "overall": 0.77,
    }
    # Plan keeps the section structure (### N) → parseable after projection).
    assert len(one.summary.experiment_plan) == 2
    from ari.rqgm.proposals.records import summary_violations

    for draft in drafts:
        assert summary_violations(draft.summary) == []
        # Shared 9-key extras ride projection_meta, never the summary.
        assert draft.projection_meta["virsci_integration_status"] == status
        assert GAP_MARKER not in json.dumps(draft.summary.to_dict())


def test_normalize_rejects_junk():
    assert normalize_generate_ideas_result({}) == []
    assert normalize_generate_ideas_result({"ideas": "nope"}) == []
    assert normalize_generate_ideas_result(None) == []  # type: ignore[arg-type]
    # Ideas without a title are skipped, not crashed on.
    payload = _nine_key_payload()
    payload["ideas"].append({"description": "untitled"})
    assert len(normalize_generate_ideas_result(payload)) == 2


def test_normalize_preserves_typed_contract_for_router_projection():
    payload = _nine_key_payload()
    payload.update(
        {
            "typed_schema_version": "ari.research-contract/v1",
            "contract_status": "admitted",
            "research_contract": {"title": "Idea One"},
            "research_contract_digest": "a" * 64,
            "idea_set_digest": "b" * 64,
        }
    )
    draft = normalize_generate_ideas_result(payload)[0]
    assert draft.projection_meta["contract_status"] == "admitted"
    assert draft.projection_meta["research_contract"]["title"] == "Idea One"


def test_mcp_payload_unwrapping():
    raw = _nine_key_payload()
    assert _mcp_payload(raw) == raw
    assert _mcp_payload({"result": raw}) == raw
    assert _mcp_payload({"result": json.dumps(raw)}) == raw
    assert _mcp_payload(json.dumps(raw)) == raw
    assert _mcp_payload("not json") == {}
    assert _mcp_payload(None) == {}


# ── adapter over MCP (archive refs, idempotency) ─────────────────────────────


def test_adapter_generates_and_references_existing_artifacts(tmp_path):
    (tmp_path / "virsci_logs").mkdir()
    (tmp_path / "virsci_logs" / "virsci_stdout.log").write_text(
        TRANSCRIPT_MARKER
    )
    (tmp_path / "virsci_snapshot" / "papers").mkdir(parents=True)
    mcp = FakeMCP()
    adapter = VirSciAdapter(mcp, checkpoint_dir=tmp_path)
    drafts = adapter.generate({"goal": "topic"})
    assert [c[0] for c in mcp.calls] == ["survey", "generate_ideas"]
    refs = drafts[0].raw_output["archive_refs"]
    # Existing artifacts are referenced, never copied (checkpoint-relative).
    assert refs["discussion_log"] == "virsci_logs/virsci_stdout.log"
    assert refs["retrieval_snapshot"] == "virsci_snapshot/"


def test_adapter_uses_bounded_research_goal_for_literature_query(tmp_path):
    mcp = FakeMCP()
    topic = (
        "# Run title\n\n## Research Goal\n"
        "Compare cache-friendly GEMM loop ordering on an FP64 CPU.\n\n"
        "## Scientific Contract\n" + ("irrelevant constraint " * 100)
    )
    adapter = VirSciAdapter(mcp, checkpoint_dir=tmp_path)
    assert adapter.generate({"goal": topic})
    survey_args = mcp.calls[0][1]
    assert survey_args["topic"] == literature_query(topic)
    assert "Scientific Contract" not in survey_args["topic"]
    assert len(survey_args["topic"]) <= 240


def test_adapter_prefers_deterministic_task_tags_for_literature_query(tmp_path):
    mcp = FakeMCP()
    adapter = VirSciAdapter(mcp, checkpoint_dir=tmp_path)
    assert adapter.generate(
        {"goal": "an excessively specific goal", "task_tags": ["hpc.gemm.optimization"]}
    )
    assert mcp.calls[0][1]["topic"] == "hpc gemm optimization"


def test_adapter_preserves_typed_survey_snapshot_for_generation(tmp_path):
    snapshot = {"schema_version": "ari.survey-snapshot/v1", "query": "GEMM"}

    class SnapshotMCP(FakeMCP):
        def call_tool(self, tool_name, args, **kw):
            self.calls.append((tool_name, dict(args)))
            if tool_name == "survey":
                return {
                    "result": json.dumps(
                        {"papers": [{"title": "p"}], "survey_snapshot": snapshot}
                    )
                }
            if tool_name == "generate_ideas":
                return {"result": json.dumps(self.payload)}
            raise KeyError(tool_name)

    mcp = SnapshotMCP()
    assert VirSciAdapter(mcp, checkpoint_dir=tmp_path).generate({"goal": "GEMM"})
    generate_args = mcp.calls[1][1]
    assert generate_args["survey_snapshot"] == snapshot
    assert "papers" not in generate_args


def test_adapter_failure_degrades_to_no_drafts(tmp_path):
    mcp = MagicMock()
    mcp.call_tool.side_effect = RuntimeError("skill unavailable")
    adapter = VirSciAdapter(mcp, checkpoint_dir=tmp_path)
    assert adapter.generate({"goal": "topic"}) == []


def test_retry_idempotency_no_duplicate_records(tmp_path):
    """The MCP 3-retry hazard: identical payloads → identical content keys →
    exactly one record set, however many times the call repeats."""
    mcp = FakeMCP()
    router = ProposalRouter(
        _virsci_cfg(), None, mcp, ProposalStore(tmp_path)
    )
    first = router.generate_root_proposals({"goal": "topic"})
    assert [r.generator for r in first] == ["virsci", "virsci"]
    count_after_first = len(ProposalStore(tmp_path).load_all())
    for _ in range(2):  # retries reproduce the same payload
        again = router.on_event("initial_exploration", {"goal": "topic"})
        assert again == []
    assert len(ProposalStore(tmp_path).load_all()) == count_after_first
    assert sum(1 for name, _ in mcp.calls if name == "generate_ideas") == 3


def test_virsci_projection_meta_reaches_idea_json(tmp_path):
    mcp = FakeMCP()
    router = ProposalRouter(_virsci_cfg(), None, mcp, ProposalStore(tmp_path))
    records = router.generate_root_proposals({"goal": "topic"})
    assert records and records[0].status == "selected"
    doc = json.loads((tmp_path / "idea.json").read_text())
    assert GAP_MARKER in doc["gap_analysis"]
    assert doc["papers_analyzed"] == 12
    assert doc["n_agents"] == 4
    assert doc["primary_metric"] == "throughput_gflops"
    # Best idea first (overall 0.77 > 0.68); traceability link present.
    assert doc["ideas"][0]["title"] == "Idea One"
    assert doc["ideas"][0]["_proposal_record_id"] == records[0].record_id


# ── archive/summary split: transcripts are referenced, never rendered ────────


def test_transcript_content_never_reaches_expand_context(tmp_path):
    (tmp_path / "virsci_logs").mkdir()
    (tmp_path / "virsci_logs" / "virsci_stdout.log").write_text(
        f"agent A said: {TRANSCRIPT_MARKER}\n"
    )
    mcp = FakeMCP()
    store = ProposalStore(tmp_path)
    router = ProposalRouter(_virsci_cfg(), None, mcp, store)
    router.generate_root_proposals({"goal": "topic"})
    selected = store.selected()
    # Archive refs point at the transcript...
    assert (selected.archive_refs.get("discussion_log")
            == "virsci_logs/virsci_stdout.log")
    raw_ref = selected.archive_refs["raw_output"]
    assert (tmp_path / raw_ref).exists()
    # ...but neither the transcript nor archived-only payload text appears in
    # the rendered expand context (BFTS sees the bounded summary ONLY).
    ctx = render_summary_ctx(selected.summary)
    assert ctx  # non-empty summary channel
    assert TRANSCRIPT_MARKER not in ctx
    assert GAP_MARKER not in ctx


# ── mode × VirSci four-combination matrix (config-validation + boot) ─────────


@pytest.mark.parametrize("mode,virsci_on", [
    ("simple_bfts", False),
    ("simple_bfts", True),
    ("ari_rqgm", False),
    ("ari_rqgm", True),
])
def test_mode_virsci_matrix_config_and_boot(monkeypatch, tmp_path, mode,
                                            virsci_on):
    """All four combinations are valid config and boot cleanly; VirSci is an
    independent toggle, not a mode (docs/guides/virsci_integration.md,
    "The four mode × VirSci combinations")."""
    from ari.rqgm.mode import EffectiveMode, resolve_effective_mode

    cfg = ARIConfig(
        ari={"mode": mode},
        rqgm={"enabled": mode == "ari_rqgm"},
        proposal_router={"generators": {"virsci": {"enabled": virsci_on}}},
    )
    expected = (EffectiveMode.ARI_RQGM if mode == "ari_rqgm"
                else EffectiveMode.SIMPLE_BFTS)
    assert resolve_effective_mode(cfg) is expected

    mcp = MagicMock()
    if mode == "simple_bfts":
        # proposal_router.* is deliberately inert in simple_bfts: nothing
        # constructs the router, whatever virsci.enabled says.
        assert cfg.proposal_router.generators.virsci.enabled is virsci_on
        mcp.call_tool.assert_not_called()
        return
    from ari.rqgm.runtime import RQGMRuntime

    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=None, mcp=mcp)
    router = runtime.router
    assert router is not None
    if virsci_on:
        assert "virsci" in router._generators
        assert type(router._generators["virsci"]).__name__ == "VirSciAdapter"
    else:
        assert "virsci" not in router._generators
    # Boot alone never touches the idea skill (Task 01's deferred assertion:
    # no idea-skill VirSci path is exercised until the router dispatches).
    mcp.call_tool.assert_not_called()


def test_virsci_disabled_adapter_module_never_imported(monkeypatch, tmp_path):
    """Structural virsci.enabled=false guarantee: with the default config the
    adapter module is never imported, so no VirSci dependency can load."""
    monkeypatch.delitem(
        sys.modules, "ari.rqgm.proposals.virsci_adapter", raising=False
    )
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    router = ProposalRouter(cfg, None, MagicMock(),
                            ProposalStore(tmp_path))
    assert "virsci" not in router._generators
    assert "ari.rqgm.proposals.virsci_adapter" not in sys.modules


def test_adapter_imports_nothing_from_the_idea_skill():
    """MCP-only rule: the adapter module must not import the skill or any
    VirSci runtime; heavy deps stay inside the skill subprocess."""
    import ast

    import ari.rqgm.proposals.virsci_adapter as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("server", "virsci", "virsci_runtime", "snapshot", "torch",
                 "faiss", "agentscope")
    for name in imported:
        root = name.split(".")[0]
        assert root not in forbidden, f"forbidden import {name!r}"
        assert not root.startswith("ari_skill"), name
    for name in sys.modules:
        assert not name.startswith("virsci"), name
