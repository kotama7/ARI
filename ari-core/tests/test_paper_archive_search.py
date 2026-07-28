"""Paper-archive Task 02 — draft archive search substrate
(docs/plans/ari_rqgm_paper/02, §9).

Covers: the best-first draft-TREE topology and its `bfts.py` cutoff reuse
(total cap before depth cap), the REAL deterministic `select_best_to_expand`
frontier selection (not a root-return), the REAL framing-keyed
`diversity_bonus`, the per-epoch `max_expansions` budget cap and its
depth-independence, `PaperDraftExecutor` (one generative call per node,
write_paper_iterative seeds + paper_refine child nodes), best-belief reuse of
`select_best_node`, lazy compile, the `paper_draft_archive.jsonl` schema +
registration, Protocol conformance, and determinism (P2). Plus the runnable
`rqgm_archive` startup smoke over `PaperArchiveRuntime.run_archive` with a
stubbed skill + stub reviewer, and the resume test.

No test calls a real LLM: the skill is a scripted double and the reviewer is a
stub scoring oracle.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ari.config import ARIConfig
from ari.orchestrator.node import Node, NodeLabel
from ari.pipeline.verified_context import select_best_node
from ari.protocols.search import NodeExecutor, SearchStrategy
from ari.rqgm.paper_archive import (
    PaperArchiveStrategy,
    read_paper_draft_archive,
    write_paper_draft_record,
)
# BOTH names must come from ONE import: `test_paper_mode.py` purges
# `ari.rqgm.paper*` from sys.modules (its :255-257 import-isolation check), so an
# in-test re-import would bind a DIFFERENT `PaperSkillCallError` object than the
# executor instance raises and `pytest.raises` would miss it — an
# order-dependent false failure.
from ari.rqgm.paper_draft_executor import (
    PaperDraftExecutor,
    PaperSkillCallError,
)
from ari.rqgm.paper_runtime import PaperArchiveRuntime


# ── scripted doubles ─────────────────────────────────────────────────────────

class ScriptedPaperMCP:
    """Scripted ari-skill-paper double: growing LaTeX so refine 'improves'."""

    def __init__(self):
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "write_paper_iterative":
            body = (
                "\\documentclass{article}\\begin{document}\n"
                "\\section{Intro}\n% CLAIM:C1:NC1\n" + ("s" * 600)
                + "\n\\end{document}"
            )
            return {"latex": body}
        if name == "paper_refine":
            try:
                cur = Path(args["tex_path"]).read_text(encoding="utf-8")
            except OSError:
                cur = "\\end{document}"
            body = cur.replace(
                "\\end{document}",
                "\\section{More}\n% CLAIM:C2:NC2\n" + ("r" * 300)
                + "\n\\end{document}",
            )
            return {"latex": body, "refined": True, "anchors_preserved": True}
        if name == "compile_paper":
            return {"success": True,
                    "pdf_path": str(Path(args["tex_dir"]) / "full_paper.pdf")}
        return {}


class LengthReviewer:
    """Deterministic (P2) stub scorer: longer .tex scores higher (so a refine
    child outscores its seed), no LLM."""

    prompt_hash = "stub_reviewer_v0"

    def review(self, tex_path):
        return SimpleNamespace(
            suggested_revisions_json='[{"instruction":"tighten"}]')

    def score(self, tex_path):
        try:
            return round(min(1.0, len(Path(tex_path).read_text()) / 3000.0), 6)
        except OSError:
            return 0.0


def _archive_cfg(**over):
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.paper.enabled = True
    for k, v in over.items():
        setattr(cfg.rqgm.paper.archive, k, v)
    return cfg


def _root():
    r = Node(id="paper_root", parent_id=None, depth=0, label=NodeLabel.DRAFT)
    r.original_direction = "root"
    return r


# ── Protocol conformance (duck-typed, never isinstance of a concrete) ───────

def test_protocol_conformance():
    strat = PaperArchiveStrategy(ARIConfig().rqgm.paper.archive, root_task=_root())
    execu = PaperDraftExecutor(ScriptedPaperMCP(), reviewer=LengthReviewer(),
                               checkpoint_dir="/tmp")
    assert isinstance(strat, SearchStrategy)
    assert isinstance(execu, NodeExecutor)


# ── topology: seeds-first, one child per expand, depth cap ──────────────────

def test_seeds_first_then_refine_children():
    knobs = ARIConfig().rqgm.paper.archive  # width 4, refine 2, depth 3, exp 12
    root = _root()
    strat = PaperArchiveStrategy(knobs, root_task=root)
    # width seed drafts appear at depth 1 before any refine child
    seeds = []
    for _ in range(knobs.width):
        picked = strat.select_best_to_expand([root] + seeds, "g", None)
        assert picked is root, "root must be picked until width framings exist"
        children = strat.expand(root, existing_children=seeds)
        assert len(children) == 1  # one child per expand (bfts.py:643 invariant)
        c = children[0]
        assert c.depth == 1 and c.original_direction == "seed"
        # give it a score so the frontier can rank later
        c.metrics = {"_scientific_score": 0.1 * (len(seeds) + 1),
                     "_framing_key": f"f{len(seeds)}"}
        strat.record_run(c)
        seeds.append(c)
    # root fan-out is now spent -> should_prune retires it
    assert strat.should_prune(root, current_total=1 + len(seeds)) is True
    # next selection is a real DRAFT, never the root
    nxt = strat.select_best_to_expand(seeds, "g", None)
    assert nxt is not root and nxt.original_direction == "seed"


def test_expand_reaches_depth_three():
    knobs = ARIConfig().rqgm.paper.archive
    root = _root()
    strat = PaperArchiveStrategy(knobs, root_task=root)
    seed = strat.expand(root, existing_children=[])[0]
    assert seed.depth == 1
    r1 = strat.expand(seed, existing_children=[])[0]
    assert r1.depth == 2 and r1.original_direction == "refine"
    r2 = strat.expand(r1, existing_children=[])[0]
    assert r2.depth == 3
    # depth cap: no child past archive.depth
    assert strat.expand(r2, existing_children=[]) == []
    assert strat.should_prune(r2, current_total=4) is True  # depth >= depth


def test_fanout_cap_and_erasure_clause():
    knobs = _archive_cfg(width=2, refine_rounds=1).rqgm.paper.archive
    root = _root()
    strat = PaperArchiveStrategy(knobs, root_task=root)
    a = strat.expand(root, existing_children=[])[0]
    b = strat.expand(root, existing_children=[])[0]
    # root fan-out (width=2) is spent
    assert strat.expand(root, existing_children=[a, b]) == []
    # a draft's fan-out cap is refine_rounds=1
    strat.expand(a, existing_children=[])
    assert strat.expand(a, existing_children=[]) == []
    # selective-erasure clause retires an erased draft
    b.metrics = {"_valid_for_frontier": False}
    assert strat.should_prune(b, current_total=3) is True


# ── the best-first frontier is REAL, not a constant of the root ─────────────

def test_select_best_to_expand_is_real_not_root_return():
    knobs = _archive_cfg(width=3).rqgm.paper.archive
    root = _root()
    strat = PaperArchiveStrategy(knobs, root_task=root)
    d0 = strat.expand(root, existing_children=[])[0]
    d1 = strat.expand(root, existing_children=[])[0]
    d2 = strat.expand(root, existing_children=[])[0]
    for d, s in ((d0, 0.2), (d1, 0.4), (d2, 0.9)):
        d.metrics = {"_scientific_score": s, "_framing_key": d.id}
        strat.record_run(d)
    # width framings exist -> the frontier picks the MAX-scoring draft, not root
    picked = strat.select_best_to_expand([root, d0, d1, d2], "g", None)
    assert picked is d2
    # regression: not a constant function of the root
    assert picked is not root
    # deterministic ties resolve to creation order
    d1.metrics["_scientific_score"] = 0.9
    d2.metrics["_scientific_score"] = 0.9
    twice = [strat.select_best_to_expand([root, d0, d1, d2], "g", None)
             for _ in range(2)]
    assert twice[0] is twice[1] is d1  # first maximal == creation order


def test_diversity_bonus_is_real_not_zero():
    knobs = ARIConfig().rqgm.paper.archive
    strat = PaperArchiveStrategy(knobs, root_task=_root())
    # recent history dominated by framing 'A'
    for _ in range(4):
        strat.record_run(Node(id="x", parent_id=None, depth=1,
                              metrics={"_framing_key": "A"}))
    strat.record_run(Node(id="y", parent_id=None, depth=1,
                          metrics={"_framing_key": "B"}))
    under = Node(id="u", parent_id=None, depth=1, metrics={"_framing_key": "B"})
    over = Node(id="o", parent_id=None, depth=1, metrics={"_framing_key": "A"})
    assert strat.diversity_bonus(under) == 0.05  # under-sampled framing rewarded
    assert strat.diversity_bonus(over) == 0.0
    # it flips a tie in select_best_to_expand toward the under-sampled framing
    under.metrics["_scientific_score"] = 0.5
    over.metrics["_scientific_score"] = 0.5
    # need width framings so the root is not returned
    s2 = PaperArchiveStrategy(_archive_cfg(width=1).rqgm.paper.archive,
                              root_task=_root())
    s2._framings = ["A", "A", "A", "A", "B"]
    s2._fanout[s2._root.id] = 1  # width satisfied
    assert s2.select_best_to_expand([under, over], "g", None) is under


# ── budget cap + depth-independence (§5.1 / §9) ─────────────────────────────

def _run_full_archive(tmp_path, cfg, mcp=None, reviewer=None):
    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    mcp = mcp or ScriptedPaperMCP()
    rt = PaperArchiveRuntime(cfg, checkpoint_dir=tmp_path, mcp=mcp,
                             reviewer=reviewer or LengthReviewer())
    nodes = [Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                  metrics={"_scientific_score": 0.9})]
    called = {}
    rt.run_archive(nodes, {"goal": "g"}, tmp_path, mcp, "wf.yaml",
                   # **kw: the handoff passes `disable_stages` when a winner was
                   # materialised (07 §5.4/R5 — see test_rqgm_paper_eval.py).
                   linear_fallback=lambda *a, **kw: called.setdefault(
                       "linear", True))
    return mcp, called


def test_budget_cap_bounds_skill_calls(tmp_path):
    cfg = _archive_cfg(width=4, refine_rounds=2, max_expansions=12, depth=3)
    mcp, _ = _run_full_archive(tmp_path, cfg)
    gen_calls = [c for c in mcp.calls
                 if c[0] in ("write_paper_iterative", "paper_refine")]
    assert len(gen_calls) <= 12  # per-epoch budget cap
    recs = read_paper_draft_archive(tmp_path)
    assert len(recs) <= 12


def test_cost_is_depth_independent(tmp_path):
    """Same config with depth=5 issues the SAME <=12 calls and node count —
    the total cap binds before the depth cap (bfts.py:501-503)."""
    a = tmp_path / "d3"
    b = tmp_path / "d5"
    a.mkdir(); b.mkdir()
    mcp3, _ = _run_full_archive(a, _archive_cfg(depth=3))
    mcp5, _ = _run_full_archive(b, _archive_cfg(depth=5))
    n3 = len([c for c in mcp3.calls
              if c[0] in ("write_paper_iterative", "paper_refine")])
    n5 = len([c for c in mcp5.calls
              if c[0] in ("write_paper_iterative", "paper_refine")])
    assert n3 == n5 <= 12


# ── executor: one call per node, refine child, framing inheritance ──────────

def test_executor_seed_then_refine_child(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    mcp = ScriptedPaperMCP()
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path)
    seed = Node(id="draft_0", parent_id="paper_root", depth=1,
                ancestor_ids=["paper_root"])
    seed.original_direction = "seed"
    execu.run(seed, {"writer_prompt_hashes": ["wh0"]})
    assert seed.metrics["_scientific_score"] > 0
    assert seed.metrics["_framing_key"] == "wh0"
    assert mcp.calls[0][0] == "write_paper_iterative"
    # a refine CHILD makes exactly one paper_refine and inherits the framing
    child = Node(id="draft_0.r1", parent_id="draft_0", depth=2,
                 ancestor_ids=["paper_root", "draft_0"])
    child.original_direction = "refine"
    execu.run(child, {})
    assert child.metrics["_framing_key"] == "wh0"  # inherits parent framing
    refine_calls = [c for c in mcp.calls if c[0] == "paper_refine"]
    assert len(refine_calls) == 1
    assert "compile_paper" not in [c[0] for c in mcp.calls]  # never compiles
    # records: seed (refine_pass 0) + refine child (refine_pass 1)
    recs = read_paper_draft_archive(tmp_path)
    assert [r["kind"] for r in recs] == ["seed", "refine"]
    assert recs[1]["parent_draft_id"] == "draft_0"
    assert recs[1]["refine_pass"] == 1
    assert recs[0]["tex_sha256"] != recs[1]["tex_sha256"]  # versioned, not overwritten


_EMPTY_TEX_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


class EnvelopePaperMCP(ScriptedPaperMCP):
    """The SHIPPED ``MCPClient.call_tool`` surface: the tool payload comes back
    serialised and wrapped as ``{"result": "<json-string>"}``
    (ari/mcp/client.py:237), NOT as the raw payload dict the other doubles
    return. Reproduces the production envelope so the executor's unwrap is
    exercised end-to-end."""

    def call_tool(self, name, args):
        payload = super().call_tool(name, args)
        return {"result": json.dumps(payload, ensure_ascii=False)}


def test_executor_unwraps_shipped_call_tool_envelope(tmp_path):
    """Regression: with the REAL ``{"result": "<json>"}`` envelope the seed draft
    must carry the tool's LaTeX — not collapse to the empty-string ``.tex``.

    Before the unwrap fix (2026-07-19) the executor read ``latex`` off the
    envelope dict, got ``""``, and EVERY draft hashed to the empty-string sha256
    (e3b0c44…) — the archive degraded to K empty copies and fell back to linear.
    The other scripted doubles returned the raw payload dict, so they never
    reproduced the envelope and the bug slipped past the suite."""
    mcp = EnvelopePaperMCP()
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path)
    seed = Node(id="draft_0", parent_id="paper_root", depth=1,
                ancestor_ids=["paper_root"])
    seed.original_direction = "seed"
    execu.run(seed, {"writer_prompt_hashes": ["wh0"]})

    recs = read_paper_draft_archive(tmp_path)
    assert len(recs) == 1
    assert recs[0]["tex_sha256"] != _EMPTY_TEX_SHA256      # NOT the empty draft
    # the tool's real LaTeX reached disk (non-empty, contains the seed section)
    tex_on_disk = Path(recs[0]["tex_path"])
    if not tex_on_disk.is_absolute():
        tex_on_disk = tmp_path / recs[0]["tex_path"]
    body = tex_on_disk.read_text(encoding="utf-8")
    assert "\\section{Intro}" in body and len(body) > 100
    assert seed.metrics["_scientific_score"] > 0          # reviewer saw real text


# ── the PRODUCTION failure shapes must never become a silent empty draft ─────
#
# `MCPClient.call_tool` NEVER raises on tool failure (ari/mcp/client.py:227-239):
# it RETURNS `{"error": ...}`, or wraps a raising tool's error text as
# `{"result": "<non-JSON text>"}`. Both were read as "no latex" and written as a
# 0-byte draft (tex_sha256 e3b0c44…) — the very bug the unwrap fix targeted, one
# layer down. They must reach the SAME contract `InterruptingPaperMCP` already
# pins: raise, so nothing is recorded and `run_archive` fail-opens loudly.

class _FailingPaperMCP(ScriptedPaperMCP):
    """Returns one of the shipped FAILURE envelopes instead of a payload."""

    def __init__(self, envelope):
        super().__init__()
        self._envelope = envelope

    def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return self._envelope


def _seed_node():
    n = Node(id="draft_0", parent_id="paper_root", depth=1,
             ancestor_ids=["paper_root"])
    n.original_direction = "seed"
    return n


@pytest.mark.parametrize("envelope", [
    {"error": "Tool 'write_paper_iterative' returned empty response — "
              "the tool may have crashed or timed out."},
    {"result": "=== write_paper_iterative TRACEBACK ===\nRuntimeError: boom"},
    {"result": json.dumps({"latex": ""})},          # payload with empty body
    {"result": json.dumps({"sections": []})},       # payload with NO latex key
])
def test_production_failure_envelopes_raise_instead_of_writing_empty_draft(
    tmp_path, envelope,
):
    mcp = _FailingPaperMCP(envelope)
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path)
    with pytest.raises(PaperSkillCallError):
        execu.run(_seed_node(), {"writer_prompt_hashes": ["wh0"]})
    # NOTHING is recorded: no 0-byte draft, no fabricated anchors_preserved
    assert read_paper_draft_archive(tmp_path) == []
    tex = tmp_path / "archive/epoch_000/draft_0/full_paper.tex"
    assert not tex.exists() or tex.read_text(encoding="utf-8") == ""


# ── §6.1 / Q-49: drafts are versioned across EPOCHS, never overwritten ──────

class VaryingPaperMCP(ScriptedPaperMCP):
    """Like ScriptedPaperMCP but every call yields DIFFERENT bytes — i.e. any
    real writer. ScriptedPaperMCP returns a CONSTANT seed body, which makes a
    cross-epoch overwrite invisible (the clobbering bytes are byte-identical to
    the clobbered ones), so it structurally cannot see that class of bug.

    Bodies are FIXED-WIDTH (`u%03d`), so every draft's length — and therefore
    `LengthReviewer`'s score and the resulting tree topology — is identical
    regardless of which call index produced it. That keeps the node set
    deterministic while the bytes still differ, which is what lets a resumed run
    be compared against an uninterrupted one (P2).
    """

    def __init__(self):
        super().__init__()
        self.n = 0

    def call_tool(self, name, args):
        if name == "write_paper_iterative":
            self.calls.append((name, dict(args)))
            self.n += 1
            return {"latex": "\\documentclass{article}\\begin{document}\n"
                             "\\section{Intro}\n% CLAIM:C1:NC1\n"
                             + ("u%03d" % (self.n % 1000)) * 150
                             + "\n\\end{document}"}
        if name == "paper_refine":
            self.calls.append((name, dict(args)))
            self.n += 1
            try:
                cur = Path(args["tex_path"]).read_text(encoding="utf-8")
            except OSError:
                cur = "\\end{document}"
            return {"latex": cur.replace(
                "\\end{document}",
                "\\section{More}\n% CLAIM:C2:NC2\n"
                + ("v%03d" % (self.n % 1000)) * 75
                + "\n\\end{document}"), "anchors_preserved": True}
        return super().call_tool(name, args)


class InterruptingPaperMCP(VaryingPaperMCP):
    """A writer that dies partway — the §9 "archive interrupted" condition. The
    records already appended survive; no winner is finalised, so nothing is
    materialised to the canonical path."""

    def __init__(self, fail_after: int):
        super().__init__()
        self.fail_after = fail_after
        self.gen = 0

    def call_tool(self, name, args):
        if name in ("write_paper_iterative", "paper_refine"):
            if self.gen >= self.fail_after:
                raise RuntimeError("archive interrupted")
            self.gen += 1
        return super().call_tool(name, args)


def test_drafts_from_different_epochs_do_not_overwrite_each_other(tmp_path):
    """§6.1: "every draft is a content-hashed record, never an in-place
    overwrite of `full_paper.tex`"; `tex_sha256` = "drafts are versioned, not
    overwritten".

    Node ids are re-minted every round by a fresh `PaperArchiveStrategy`, and the
    tex path used to key off `node.id` alone — so epoch_001's `draft_0`
    `write_text`-overwrote epoch_000's, and every epoch_000 record's `tex_sha256`
    went stale against the bytes at its OWN `tex_path`. That is the per-epoch
    draft-versioning half of Q-49 — the thing this schema exists to resolve.

    Drives the SHIPPED default (co-evolution, `rounds: 2`, no injected reviewer),
    which is the only path that mints ids twice.
    """
    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    mcp = VaryingPaperMCP()
    cfg = _archive_cfg()
    rt = PaperArchiveRuntime(cfg, checkpoint_dir=tmp_path, mcp=mcp)
    nodes = [Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                  metrics={"_scientific_score": 0.9})]
    rt.run_archive(nodes, {"goal": "g"}, tmp_path, mcp, "wf.yaml")

    recs = read_paper_draft_archive(tmp_path)
    assert len({r["epoch_id"] for r in recs}) > 1, "need >1 epoch to see this"
    # (a) every record owns its own file — no two drafts share a tex_path
    assert len({r["tex_path"] for r in recs}) == len(recs)
    # (b) every record's bytes still hash to its recorded tex_sha256
    import hashlib
    for r in recs:
        got = hashlib.sha256(
            (tmp_path / r["tex_path"]).read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        assert got == r["tex_sha256"], f"stale hash for {r['node_id']}"
    # (c) §6.1: exactly one record is the best belief, for exactly one compile
    assert sum(1 for r in recs if r.get("is_best_belief")) == 1
    compiles = [c for c in mcp.calls if c[0] == "compile_paper"]
    assert sum(1 for r in recs if r.get("compiled")) == len(compiles)
    # node ids DO still repeat across epochs — the fix scopes the filesystem, not
    # the ids (§6.1 pins draft_0 / draft_0.r1), so mark_paper_draft_flags'
    # clear-others rule stays load-bearing rather than degrading to a no-op.
    assert len({r["node_id"] for r in recs}) < len(recs)


# ── best-belief reuse of select_best_node ───────────────────────────────────

def test_best_belief_reuses_select_best_node():
    archive = [
        Node(id="a", parent_id=None, depth=1, has_real_data=True,
             metrics={"_scientific_score": 0.3}),
        Node(id="b", parent_id=None, depth=2, has_real_data=True,
             metrics={"_scientific_score": 0.8}),
        Node(id="c", parent_id=None, depth=1, has_real_data=True,
             metrics={"_scientific_score": 0.5}),
    ]
    assert select_best_node(archive).id == "b"


# ── lazy compile ────────────────────────────────────────────────────────────

def test_lazy_compile_fires_once_for_winner(tmp_path):
    cfg = _archive_cfg()
    mcp, _ = _run_full_archive(tmp_path, cfg)
    compiles = [c for c in mcp.calls if c[0] == "compile_paper"]
    assert len(compiles) == 1  # exactly one, only the best-belief draft
    assert (tmp_path / "full_paper.tex").exists()  # winner at canonical path
    recs = read_paper_draft_archive(tmp_path)
    best = [r for r in recs if r.get("is_best_belief")]
    assert len(best) == 1 and best[0]["compiled"] is True


def test_high_threshold_skips_compile_but_still_copies(tmp_path):
    cfg = _archive_cfg(compile_threshold=2.0)  # unreachable
    mcp, _ = _run_full_archive(tmp_path, cfg)
    compiles = [c for c in mcp.calls if c[0] == "compile_paper"]
    assert len(compiles) == 0  # below threshold -> no compile
    assert (tmp_path / "full_paper.tex").exists()  # still reaches the canonical path
    recs = read_paper_draft_archive(tmp_path)
    best = [r for r in recs if r.get("is_best_belief")]
    assert len(best) == 1 and best[0]["compiled"] is False


def test_exactly_one_record_carries_a_flag_across_duplicate_node_ids(tmp_path):
    """§6.1: exactly one record carries `is_best_belief` / `compiled`.

    Node ids are re-minted every round by a fresh `PaperArchiveStrategy`, so
    several records share a `node_id`. `mark_paper_draft_flags` marked EVERY
    match and cleared nothing, so ONE compile stamped `compiled: true` on two
    records. The LAST match wins (append-only => the last write is that node's
    current state) and the flag is CLEARED elsewhere."""
    from ari.rqgm.paper_archive import mark_paper_draft_flags

    # two rounds mint `draft_0` twice, both epoch_000 (so an epoch filter is a
    # no-op here — the reason #12 must NOT be fixed by epoch-scoping)
    for i, sha in enumerate(("aaa", "bbb")):
        write_paper_draft_record(tmp_path, {
            "node_id": "draft_0", "kind": "seed", "epoch_id": "epoch_000",
            "tex_sha256": sha, "decode_seed": 1000 + i})
    write_paper_draft_record(tmp_path, {
        "node_id": "draft_1", "kind": "seed", "epoch_id": "epoch_000",
        "tex_sha256": "ccc"})

    mark_paper_draft_flags(tmp_path, "draft_0", is_best_belief=True,
                           compiled=True)
    recs = read_paper_draft_archive(tmp_path)
    best = [r for r in recs if r.get("is_best_belief")]
    assert len(best) == 1, "one compile must not flag two records"
    assert best[0]["tex_sha256"] == "bbb"      # the LAST write of that node
    assert sum(1 for r in recs if r.get("compiled")) == 1

    # a later winner MOVES the flag rather than adding a second one
    mark_paper_draft_flags(tmp_path, "draft_1", is_best_belief=True)
    recs2 = read_paper_draft_archive(tmp_path)
    best2 = [r for r in recs2 if r.get("is_best_belief")]
    assert len(best2) == 1 and best2[0]["node_id"] == "draft_1"
    # ...and a flag this call does not own is untouched
    assert sum(1 for r in recs2 if r.get("compiled")) == 1


def test_seed_collapse_is_warned_not_silent(tmp_path, caplog):
    """Plan 02 R1's collapse detector. `decode_seed` is the only diversity lever
    at `n == 1` writer prompts, and litellm `seed` is provider-dependent — a
    backend that ignores it collapses the archive to K copies while every record
    still advertises a distinct seed. The collapse is now visible."""
    write_paper_draft_record(tmp_path, {
        "node_id": "draft_0", "kind": "seed", "tex_sha256": "same",
        "decode_seed": 1000})
    with caplog.at_level("WARNING"):
        write_paper_draft_record(tmp_path, {
            "node_id": "draft_1", "kind": "seed", "tex_sha256": "same",
            "decode_seed": 1001})
    assert any("seed collapse" in r.message for r in caplog.records)
    assert len(read_paper_draft_archive(tmp_path)) == 2  # never blocks a write

    # a DISTINCT draft is silent, and a refine record is not a seed
    caplog.clear()
    with caplog.at_level("WARNING"):
        write_paper_draft_record(tmp_path, {
            "node_id": "draft_2", "kind": "seed", "tex_sha256": "other",
            "decode_seed": 1002})
        write_paper_draft_record(tmp_path, {
            "node_id": "draft_0.r1", "kind": "refine", "tex_sha256": "same"})
    assert not any("seed collapse" in r.message for r in caplog.records)


def test_same_seed_reproducing_the_same_bytes_is_not_a_collapse(tmp_path, caplog):
    """R1's claim is about candidates that differ ONLY by seed producing
    identical bytes. The SAME seed reproducing the same text is determinism
    working as designed — a resume, or a node id re-minted across rounds (a
    fresh `PaperArchiveStrategy` per round restarts the ids). Warning on it
    would fire on every round of a normal run and bury the real signal."""
    rec = {"node_id": "draft_0", "kind": "seed", "tex_sha256": "abc",
           "decode_seed": 1000}
    write_paper_draft_record(tmp_path, dict(rec))
    caplog.clear()
    with caplog.at_level("WARNING"):
        write_paper_draft_record(tmp_path, dict(rec))   # identical seed re-record
    assert not any("seed collapse" in r.message for r in caplog.records)

    # ...but a DIFFERENT seed landing on those same bytes still warns
    with caplog.at_level("WARNING"):
        write_paper_draft_record(tmp_path, dict(rec, node_id="draft_1",
                                                decode_seed=1001))
    assert any("seed collapse" in r.message for r in caplog.records)


# ── archive schema round-trip + registration ────────────────────────────────

def test_archive_jsonl_roundtrip_and_absence(tmp_path):
    assert read_paper_draft_archive(tmp_path) == []  # absence-tolerant
    write_paper_draft_record(tmp_path, {"node_id": "draft_0", "kind": "seed"})
    write_paper_draft_record(tmp_path, {"node_id": "draft_0.r1", "kind": "refine"})
    recs = read_paper_draft_archive(tmp_path)
    assert [r["node_id"] for r in recs] == ["draft_0", "draft_0.r1"]


# ── determinism (P2): two runs produce identical archives ───────────────────

def test_determinism_two_runs_identical(tmp_path):
    a = tmp_path / "run_a"
    b = tmp_path / "run_b"
    a.mkdir(); b.mkdir()
    _run_full_archive(a, _archive_cfg())
    _run_full_archive(b, _archive_cfg())

    def _key(recs):
        return [(r["node_id"], r["kind"], r["refine_pass"], r["tex_sha256"],
                 r["decode_seed"]) for r in recs]

    assert _key(read_paper_draft_archive(a)) == _key(read_paper_draft_archive(b))


# ── runnable rqgm_archive startup smoke (the anti-inertness proof) ──────────

def test_startup_smoke_seeds_and_reaches_depth(tmp_path):
    cfg = _archive_cfg(width=2, refine_rounds=1, depth=3, max_expansions=4)
    mcp, called = _run_full_archive(tmp_path, cfg)
    recs = read_paper_draft_archive(tmp_path)
    seeds = [r for r in recs if r["kind"] == "seed"]
    assert len(seeds) == 2  # K=width seeds
    assert len(recs) == 4  # 2 seeds + 2 refine expansions (best-first)
    tree_depth = 1 + max(r["refine_pass"] for r in recs)
    assert tree_depth > 1  # the tree reaches depth > 1 via refine children
    assert sum(1 for r in recs if r["is_best_belief"]) == 1  # a winner
    assert (tmp_path / "full_paper.tex").exists()
    assert called.get("linear")  # linear claim-gate handoff still runs


def test_degraded_on_ramp_single_framing(tmp_path):
    """prompt_evolution.enabled=false -> best-of-N, single framing across all
    seed records; the strategy/executor code path is unchanged (§5.6)."""
    cfg = _archive_cfg()
    cfg.rqgm.paper.prompt_evolution.enabled = False
    _run_full_archive(tmp_path, cfg)
    recs = read_paper_draft_archive(tmp_path)
    seed_framings = {r["writer_prompt_hash"] for r in recs if r["kind"] == "seed"}
    assert len(seed_framings) == 1  # single frozen framing


# ── resume: recorded nodes are not re-issued; tree rebuilt ──────────────────

def test_cli_paper_entry_boots_archive(tmp_path, monkeypatch):
    """The REAL projects.py:paper CLI dispatch boots PaperArchiveRuntime and
    drives run_archive when the effective paper mode is rqgm_archive — the
    anti-inertness proof that the production entry actually runs the archive.
    """
    import ari.cli as cli
    from ari.orchestrator.node import NodeStatus

    (tmp_path / "experiment.md").write_text("# Goal\n")
    (tmp_path / "tree.json").write_text(json.dumps({
        "run_id": "r",
        "nodes": [{"id": "n1", "parent_id": None, "depth": 0, "status": "success",
                   "has_real_data": True, "metrics": {"_scientific_score": 0.9},
                   "children": [], "ancestor_ids": []}],
    }))
    cfg = _archive_cfg()
    mcp = ScriptedPaperMCP()
    linear_called = {}

    monkeypatch.setattr(cli, "_resolve_cfg", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "_setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "build_runtime",
        lambda *a, **k: (None, None, mcp, SimpleNamespace(), None, None),
    )
    monkeypatch.setattr(
        cli, "generate_paper_section",
        lambda *a, **k: linear_called.setdefault("yes", True),
    )
    # inject the deterministic stub reviewer into the runtime
    import ari.rqgm.paper_runtime as prt
    monkeypatch.setattr(prt, "_DefaultPaperReviewer", LengthReviewer)

    from ari.cli.projects import paper
    paper(tmp_path, experiment=None, config=None, rubric=None,
          fewshot_mode=None, num_reviews_ensemble=None, num_reflections=None)

    # provenance written, archive populated, winner materialized, linear tail ran
    state = json.loads((tmp_path / "paper_archive_state.json").read_text())
    assert state["paper_mode"] == "rqgm_archive"
    assert state["seed_node_id"] == "n1"
    recs = read_paper_draft_archive(tmp_path)
    # Task 03 §5.9 makes run_archive multi-round (co-evolution): each round
    # seeds `width` drafts, so the CLI-booted archive carries >= width seeds.
    assert len([r for r in recs if r["kind"] == "seed"]) >= cfg.rqgm.paper.archive.width
    assert sum(1 for r in recs if r["is_best_belief"]) >= 1  # a winner materialized
    assert (tmp_path / "full_paper.tex").exists()
    assert linear_called.get("yes")  # claim-gate handoff still runs


def test_boundary_fires_once_at_stock_defaults(tmp_path, monkeypatch):
    """docs/plans/ari_rqgm_paper/01 §9 (§5.7 falsifiable claim): a stock-default
    `rqgm_archive` run closes `rounds - 1 == 1` epoch boundary — round 1 runs
    under `epoch_000`, `_run_epoch_boundary` is entered exactly once at round end,
    and round 2's drafts are built under `epoch_001`. Pins the boundary EVENT
    (not a reviewer-hash change, which needs ~5 boundaries per doc 04) so a
    regression to the E=1-style inert boundary ships red, not silent."""
    import ari.rqgm.paper_runtime as prt
    import ari.rqgm.runtime as rtm

    monkeypatch.setattr(prt, "_DefaultPaperReviewer", LengthReviewer)
    entries = []
    orig = rtm.RQGMRuntime._run_epoch_boundary
    monkeypatch.setattr(
        rtm.RQGMRuntime, "_run_epoch_boundary",
        lambda self, ckpt, **kw: (entries.append(kw.get("node_count")),
                                  orig(self, ckpt, **kw))[1],
    )
    cfg = _archive_cfg()                          # STOCK rqgm.paper.epoch.rounds
    assert cfg.rqgm.paper.epoch.rounds == 2       # the E=2 default under test

    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    node = Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                metrics={"_scientific_score": 0.9})
    mcp = ScriptedPaperMCP()
    rt = PaperArchiveRuntime(cfg, checkpoint_dir=tmp_path, mcp=mcp)
    rt.run_archive([node], {"goal": "g"}, tmp_path, mcp, "")

    # rounds-1 == 1 boundary, entered exactly once at round end
    assert len(entries) == 1, f"boundary entered {len(entries)}x, expected 1"
    assert json.loads(
        (tmp_path / "epoch_state.json").read_text())["epoch_id"] == "epoch_001"
    # round 1 ran under epoch_000; round 2's drafts under epoch_001
    recs = read_paper_draft_archive(tmp_path)
    assert {r["epoch_id"] for r in recs} == {"epoch_000", "epoch_001"}
    # one active reviewer hash per round (adoption needs ~5 boundaries — doc 04)
    assert len(rt.reviewer_prompt_hash_sequence) == 2


@pytest.mark.parametrize("ari_mode,rqgm_en", [("simple_bfts", False), ("ari_rqgm", True)])
@pytest.mark.parametrize("paper_mode,paper_en", [("linear", False), ("rqgm_archive", True)])
def test_cli_2x2_matrix_no_cross_leak(tmp_path, monkeypatch, ari_mode, rqgm_en,
                                      paper_mode, paper_en):
    """docs/plans/ari_rqgm_paper/01 §9 (§5.6 / R5): all four cells at the REAL
    production entry — escalation fires iff exploration `ari_rqgm`, the archive
    runtime is built iff paper `rqgm_archive`, and the two are orthogonal. The
    (`ari_rqgm` × `rqgm_archive`) cell — R5's "two runtimes present at once" —
    is exercised end-to-end for the first time here."""
    import ari.cli as cli
    import ari.rqgm.paper_runtime as prt

    monkeypatch.delenv("ARI_PAPER_MODE", raising=False)
    monkeypatch.delenv("ARI_RQGM_PAPER_ENABLED", raising=False)

    (tmp_path / "experiment.md").write_text("# Goal\n")
    (tmp_path / "tree.json").write_text(json.dumps({
        "run_id": "r",
        "nodes": [{"id": "n1", "parent_id": None, "depth": 0, "status": "success",
                   "has_real_data": True, "metrics": {"_scientific_score": 0.9},
                   "children": [], "ancestor_ids": []}],
    }))
    cfg = ARIConfig()
    cfg.ari.mode, cfg.rqgm.enabled = ari_mode, rqgm_en
    cfg.paper.mode, cfg.rqgm.paper.enabled = paper_mode, paper_en

    escalated = []

    class _EscSpy:
        def run_paper_candidate_escalation(self, node, all_nodes=None):
            escalated.append(node.id)

    mcp = ScriptedPaperMCP()
    bfts = SimpleNamespace(rqgm=_EscSpy()) if rqgm_en else SimpleNamespace()
    monkeypatch.setattr(cli, "_resolve_cfg", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "_setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "build_runtime",
        lambda *a, **k: (None, None, mcp, bfts, None, None),
    )
    linear_called = {}
    monkeypatch.setattr(
        cli, "generate_paper_section",
        lambda *a, **k: linear_called.setdefault("yes", True),
    )
    monkeypatch.setattr(prt, "_DefaultPaperReviewer", LengthReviewer)

    from ari.cli.projects import paper
    paper(tmp_path, experiment=None, config=None, rubric=None,
          fewshot_mode=None, num_reviews_ensemble=None, num_reflections=None)

    # escalation fires IFF exploration ari_rqgm (independent of paper.mode)
    assert bool(escalated) == (ari_mode == "ari_rqgm")
    # archive runtime built IFF paper rqgm_archive (independent of ari.mode)
    assert (tmp_path / "paper_archive_state.json").exists() == paper_en
    if paper_en:
        state = json.loads((tmp_path / "paper_archive_state.json").read_text())
        assert state["paper_mode"] == "rqgm_archive"
        # exploration mode is recorded for provenance only, never behavioural
        assert state["exploration_mode"] == ari_mode


def test_archive_output_invariant_to_exploration_mode(tmp_path, monkeypatch):
    """docs/plans/ari_rqgm_paper/01 R5: the two state files stay owned by their
    own writers and exploration mode does not perturb the archive. The same
    `rqgm_archive` cfg under both exploration rows produces the SAME paper draft
    archive, and the archive never emits `rqgm_state.json`."""
    import ari.cli as cli
    import ari.rqgm.paper_runtime as prt

    monkeypatch.delenv("ARI_PAPER_MODE", raising=False)
    monkeypatch.delenv("ARI_RQGM_PAPER_ENABLED", raising=False)
    monkeypatch.setattr(cli, "_setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(prt, "_DefaultPaperReviewer", LengthReviewer)
    monkeypatch.setattr(
        cli, "generate_paper_section", lambda *a, **k: None)

    def _drive(ckpt, ari_mode, rqgm_en):
        ckpt.mkdir()
        (ckpt / "experiment.md").write_text("# Goal\n")
        (ckpt / "tree.json").write_text(json.dumps({
            "run_id": "r",
            "nodes": [{"id": "n1", "parent_id": None, "depth": 0,
                       "status": "success", "has_real_data": True,
                       "metrics": {"_scientific_score": 0.9},
                       "children": [], "ancestor_ids": []}],
        }))
        cfg = ARIConfig()
        cfg.ari.mode, cfg.rqgm.enabled = ari_mode, rqgm_en
        cfg.paper.mode, cfg.rqgm.paper.enabled = "rqgm_archive", True
        bfts = SimpleNamespace(rqgm=SimpleNamespace(
            run_paper_candidate_escalation=lambda *a, **k: None)) if rqgm_en \
            else SimpleNamespace()
        monkeypatch.setattr(cli, "_resolve_cfg", lambda *a, **k: cfg)
        monkeypatch.setattr(
            cli, "build_runtime",
            lambda *a, **k: (None, None, ScriptedPaperMCP(), bfts, None, None))
        from ari.cli.projects import paper
        paper(ckpt, experiment=None, config=None, rubric=None,
              fewshot_mode=None, num_reviews_ensemble=None, num_reflections=None)

    a, b = tmp_path / "a", tmp_path / "b"
    _drive(a, "simple_bfts", False)
    _drive(b, "ari_rqgm", True)

    key = lambda recs: [(r["node_id"], r["kind"], r["refine_pass"], r["tex_sha256"])
                        for r in recs]
    assert key(read_paper_draft_archive(a)) == key(read_paper_draft_archive(b))
    # each state file is written only by its owner: the archive never emits
    # rqgm_state.json (that is the exploration runtime's file)
    assert not (a / "rqgm_state.json").exists()
    assert not (b / "rqgm_state.json").exists()


def test_cli_paper_entry_linear_is_byte_identical(tmp_path, monkeypatch):
    """paper.mode=linear (default) calls generate_paper_section directly, writes
    no archive files, and imports no ari.rqgm.paper module on the paper path."""
    import sys
    import ari.cli as cli

    for m in list(sys.modules):
        if m.startswith("ari.rqgm.paper"):
            sys.modules.pop(m, None)

    (tmp_path / "experiment.md").write_text("# Goal\n")
    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    cfg = ARIConfig()  # default linear
    linear_called = {}
    monkeypatch.setattr(cli, "_resolve_cfg", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "_setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "build_runtime",
        lambda *a, **k: (None, None, ScriptedPaperMCP(), SimpleNamespace(),
                         None, None),
    )
    monkeypatch.setattr(
        cli, "generate_paper_section",
        lambda *a, **k: linear_called.setdefault("yes", True),
    )
    from ari.cli.projects import paper
    paper(tmp_path, experiment=None, config=None, rubric=None,
          fewshot_mode=None, num_reviews_ensemble=None, num_reflections=None)

    assert linear_called.get("yes")
    assert not (tmp_path / "paper_archive_state.json").exists()
    assert not (tmp_path / "paper_draft_archive.jsonl").exists()
    leaked = [m for m in sys.modules if m.startswith("ari.rqgm.paper")]
    assert not leaked, f"linear paper path imported ari.rqgm modules: {leaked}"


def test_resume_does_not_reissue_recorded_seed(tmp_path):
    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    # pre-seed a recorded parent draft so a refine child resolves it
    parent_tex = tmp_path / "archive" / "draft_0" / "full_paper.tex"
    parent_tex.parent.mkdir(parents=True)
    parent_tex.write_text("\\documentclass{article}\\begin{document}\n"
                          "% CLAIM:C1:NC1\nbody\n\\end{document}")
    write_paper_draft_record(tmp_path, {
        "schema_version": 1, "node_id": "draft_0", "draft_id": "draft_0",
        "kind": "seed", "parent_draft_id": None, "refine_pass": 0,
        "tex_path": "archive/draft_0/full_paper.tex",
        "writer_prompt_hash": "wh0", "decode_seed": 1000,
        # Every record `PaperDraftExecutor.run` writes carries its epoch, and the
        # resume lookup is epoch-scoped (a re-minted node id must not resolve a
        # PRIOR epoch's homonym as this refine's parent). "epoch_000" is the
        # executor's default, i.e. this executor's own epoch.
        "epoch_id": "epoch_000",
    })
    mcp = ScriptedPaperMCP()
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path)
    child = Node(id="draft_0.r1", parent_id="draft_0", depth=2,
                 ancestor_ids=["paper_root", "draft_0"])
    child.original_direction = "refine"
    execu.run(child, {})
    # the recorded seed is resolved from the archive (no write_paper_iterative)
    assert "write_paper_iterative" not in [c[0] for c in mcp.calls]
    assert mcp.calls[0][0] == "paper_refine"
    assert child.metrics["_framing_key"] == "wh0"  # rebuilt from the record


def _drive_archive(ck, mcp, cfg=None):
    """One `run_archive` over the single-round path (an injected reviewer pins
    `_coevolution_enabled()` False => exactly one round / one epoch), returning
    the generative calls issued."""
    ck.mkdir(parents=True, exist_ok=True)
    (ck / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    rt = PaperArchiveRuntime(cfg or _archive_cfg(), checkpoint_dir=ck, mcp=mcp,
                             reviewer=LengthReviewer())
    nodes = [Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                  metrics={"_scientific_score": 0.9})]
    rt.run_archive(nodes, {"goal": "g"}, ck, mcp, "wf.yaml")
    return [c[0] for c in mcp.calls
            if c[0] in ("write_paper_iterative", "paper_refine")]


def test_resume_rebuilds_an_interrupted_round_instead_of_re_running_it(tmp_path):
    """§8.6 "Resume is content-hash safe" + §9 Resume ("producing the same node
    set as the uninterrupted run (P2)"); Task 06 §8.5/§9.11 "a resume must not
    re-fund the round".

    `_run_one_round` used to start from `archive = []` / `frontier = [root]`
    unconditionally and never read the persisted archive, so resuming an
    interrupted round re-issued every generative call and appended a duplicate
    record for every node_id. The sibling executor-level test cannot see this: it
    never calls `run_archive`.

    The archive is INTERRUPTED (not completed) on purpose — a completed run is
    short-circuited earlier by the 07 §8.6 already-materialised guard, which
    would never reach the restore path and would make this test vacuous.
    """
    # (1) uninterrupted reference run
    cold = tmp_path / "cold"
    cold_calls = _drive_archive(cold, VaryingPaperMCP())
    cold_ids = [r["node_id"] for r in read_paper_draft_archive(cold)]
    assert len(cold_calls) > 3, "need a multi-node round to interrupt"

    # (2) same config, interrupted after 3 generative calls
    ck = tmp_path / "ck"
    _drive_archive(ck, InterruptingPaperMCP(fail_after=3))
    partial = read_paper_draft_archive(ck)
    assert len(partial) == 3, "the completed nodes' records must survive"
    assert not (ck / "full_paper.tex").exists(), \
        "an interrupted archive finalises no winner (else the §8.6 guard fires)"

    # (3) resume: the 3 recorded nodes restore; only the REST is generated
    resumed_calls = _drive_archive(ck, VaryingPaperMCP())
    recs = read_paper_draft_archive(ck)
    assert len(resumed_calls) == len(cold_calls) - 3, \
        "a resume must not re-issue a recorded node's skill call"
    assert len(recs) == len(cold_ids), "resume must not re-fund the round"
    assert len(recs) == len({r["node_id"] for r in recs}), \
        "resume must not duplicate records"
    assert {r["node_id"] for r in recs} == set(cold_ids), \
        "resume must reproduce the uninterrupted node set (P2)"
    assert sum(1 for r in recs if r.get("is_best_belief")) == 1


def test_resume_regenerates_a_node_whose_bytes_no_longer_match(tmp_path):
    """§8.6's content-hash gate: restore is keyed on `tex_sha256`, not on the
    record existing. A record whose .tex is gone or edited is DROPPED so the node
    regenerates — otherwise resume would restore a node whose artifact is stale,
    silently scoring a draft nobody wrote."""
    from ari.rqgm.paper_archive import epoch_draft_records

    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    mcp = VaryingPaperMCP()
    rt = PaperArchiveRuntime(_archive_cfg(), checkpoint_dir=tmp_path, mcp=mcp)
    rt.run_archive([Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                         metrics={"_scientific_score": 0.9})],
                   {"goal": "g"}, tmp_path, mcp, "wf.yaml")
    recs = read_paper_draft_archive(tmp_path)
    e0 = [r for r in recs if r["epoch_id"] == "epoch_000"]
    assert len(epoch_draft_records(tmp_path, "epoch_000")) == len(e0)

    # tamper with one draft's bytes -> that record no longer restores
    (tmp_path / e0[0]["tex_path"]).write_text("EDITED", encoding="utf-8")
    kept = epoch_draft_records(tmp_path, "epoch_000")
    assert len(kept) == len(e0) - 1
    assert e0[0]["node_id"] not in {r["node_id"] for r in kept}

    # a deleted artifact drops its record too
    (tmp_path / e0[1]["tex_path"]).unlink()
    kept2 = epoch_draft_records(tmp_path, "epoch_000")
    assert len(kept2) == len(e0) - 2


def test_restore_is_epoch_scoped_and_primes_the_next_index(tmp_path):
    """A prior epoch's records must not restore into this round (each round
    rebuilds under freshly adopted prompts), and the strategy must be primed so
    `expand` mints the NEXT id rather than re-minting one that exists."""
    from ari.rqgm.paper_archive import restore_archive_round

    (tmp_path / "tree.json").write_text(json.dumps({"run_id": "r", "nodes": []}))
    mcp = VaryingPaperMCP()
    rt = PaperArchiveRuntime(_archive_cfg(), checkpoint_dir=tmp_path, mcp=mcp)
    rt.run_archive([Node(id="n1", parent_id=None, depth=0, has_real_data=True,
                         metrics={"_scientific_score": 0.9})],
                   {"goal": "g"}, tmp_path, mcp, "wf.yaml")

    root = _root()
    strat = PaperArchiveStrategy(_archive_cfg().rqgm.paper.archive, root_task=root)
    restored = restore_archive_round(tmp_path, strat, root, "epoch_000")
    recs0 = [r for r in read_paper_draft_archive(tmp_path)
             if r["epoch_id"] == "epoch_000"]
    assert {n.id for n in restored} == {r["node_id"] for r in recs0}
    # epoch_001's records are NOT in this round's restore
    assert strat._expansions == len(recs0)
    # scores/framings restore from the records (§8.6 edge/score/framing restore)
    seed = next(n for n in restored if n.original_direction == "seed")
    rec = next(r for r in recs0 if r["node_id"] == seed.id)
    assert seed.metrics["_scientific_score"] == rec["review_score"]
    assert seed.metrics["_framing_key"] == rec["writer_prompt_hash"]
    assert seed.artifacts == [str(tmp_path / rec["tex_path"])]
    # the root's fan-out is primed, so a further expand does not re-mint draft_0
    minted = strat.expand(root)
    assert minted == [] or minted[0].id not in {n.id for n in restored}

    # an unknown epoch restores nothing (absence-tolerant)
    root2 = _root()
    strat2 = PaperArchiveStrategy(_archive_cfg().rqgm.paper.archive,
                                  root_task=root2)
    assert restore_archive_round(tmp_path, strat2, root2, "epoch_999") == []


# ── §5.4 decision 5: the decode seed is SENT, not just recorded ──────────────

class SeedHonouringPaperMCP(ScriptedPaperMCP):
    """A writer double that SAMPLES under the seed it is given — the stand-in
    for any backend that honours litellm `seed`. ScriptedPaperMCP ignores it, so
    it cannot tell "the seed was sent" from "the seed was dropped"; that is
    exactly why the shipped collapse (8 seeds -> 1 tex_sha256) went unseen."""

    def call_tool(self, name, args):
        out = super().call_tool(name, args)
        if name in ("write_paper_iterative", "paper_refine"):
            out["latex"] = f"% sampled under seed {args.get('decode_seed')}\n" + out["latex"]
        return out


def test_each_seed_draft_is_generated_under_its_own_decode_seed(tmp_path):
    """The seed reaches the SKILL. It was computed and written into the archive
    record but never passed to `write_paper_iterative`, so every record
    advertised a decode identity nothing honoured."""
    mcp = SeedHonouringPaperMCP()
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path, base_seed=1000)
    strat = PaperArchiveStrategy(_archive_cfg(width=4).rqgm.paper.archive,
                                 root_task=_root())
    root = _root()
    seeds = []
    for _ in range(4):
        node = strat.expand(root, existing_children=seeds)[0]
        execu.run(node, {"writer_prompt_hashes": ["wh0"]})
        seeds.append(node)

    sent = [a["decode_seed"] for n, a in mcp.calls if n == "write_paper_iterative"]
    assert sent == [1000, 1001, 1002, 1003], "each seed decodes under its own seed"

    recs = read_paper_draft_archive(tmp_path)
    # The record's advertised seed is the one that was actually used...
    assert [r["decode_seed"] for r in recs] == sent
    # ...and N distinct seeds now yield N distinct drafts (R1's anti-collapse
    # mitigation): with n == 1 writer prompt this is the ONLY diversity lever.
    assert len({r["tex_sha256"] for r in recs}) == len(recs)


def test_a_refine_child_decodes_under_its_parents_seed(tmp_path):
    """A refine keeps its parent's decode identity, as it keeps its framing —
    and the seed it advertises is the one the call used."""
    mcp = SeedHonouringPaperMCP()
    execu = PaperDraftExecutor(mcp, reviewer=LengthReviewer(),
                               checkpoint_dir=tmp_path, base_seed=7000)
    strat = PaperArchiveStrategy(_archive_cfg(width=1).rqgm.paper.archive,
                                 root_task=_root())
    root = _root()
    seed_node = strat.expand(root, existing_children=[])[0]
    execu.run(seed_node, {"writer_prompt_hashes": ["wh0"]})
    child = strat.expand(seed_node, existing_children=[])[0]
    execu.run(child, {"writer_prompt_hashes": ["wh0"]})

    refine = [a for n, a in mcp.calls if n == "paper_refine"]
    assert refine and refine[0]["decode_seed"] == 7000
    recs = read_paper_draft_archive(tmp_path)
    assert [r["decode_seed"] for r in recs] == [7000, 7000]
