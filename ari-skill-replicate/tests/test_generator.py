"""Tests for generator.py — uses an injected mock LLM."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

import generator as G
import manifest as M

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _leaf(text: str, cat: str = "Code Development",
          quote: str = "the mask network outputs 0 for critical steps") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": 2,
        "sub_tasks": [],
        "task_category": cat,
        "finegrained_task_category": "Method Implementation",
        "rationale_from_paper": {"section": "§2", "quote": quote},
    }


def _envelope_partial(leaves: int = 60) -> dict:
    children = []
    for i in range(leaves):
        cat = ["Code Development", "Code Execution", "Result Analysis"][i % 3]
        children.append(_leaf(
            text=f"Leaf #{i}: a definite verifiable claim about implementation step {i}.",
            cat=cat,
        ))
    return {
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 7200,
            "expected_artifacts": ["reproduce.log", "results/summary.json"],
        },
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "Replicate the paper's main contribution.",
            "weight": 1,
            "sub_tasks": children,
        },
    }


def test_compute_target_leaf_count_short():
    text = " ".join(["word"] * 5400)
    assert G.compute_target_leaf_count(text) == 72


def test_compute_target_leaf_count_capped_max():
    text = " ".join(["word"] * 100_000)
    assert G.compute_target_leaf_count(text) == 400


def test_compute_target_leaf_count_capped_min():
    text = " ".join(["word"] * 100)
    assert G.compute_target_leaf_count(text) == 50


def test_extract_json_object_handles_fences():
    raw = "```json\n{\"a\": 1}\n```"
    assert G._extract_json_object(raw) == {"a": 1}


def test_extract_json_object_handles_thinking_tags():
    raw = "<think>reasoning</think>\n{\"a\": 2}"
    assert G._extract_json_object(raw) == {"a": 2}


def test_extract_json_object_extracts_outermost_braces():
    raw = "Some preamble text {\"x\": {\"y\": 3}} trailing"
    assert G._extract_json_object(raw) == {"x": {"y": 3}}


def test_extract_json_object_sanitizes_latex_backslash_escapes():
    """LLMs copying LaTeX-rich quotes verbatim produce ``\\(x\\)`` etc. that
    json.loads rejects as ``Invalid \\escape``. The sanitizer fallback drops
    these illegal backslashes so the rubric still loads."""
    raw = (
        '{"quote": "where \\(A\\in\\mathbb{R}^{m\\times n}\\) is stored '
        'in CSR with \\\\texttt{rowptr}"}'
    )
    obj = G._extract_json_object(raw)
    assert obj is not None
    # Backslashes that aren't valid JSON escapes have been dropped; the
    # plain-text content survives.
    assert "rowptr" in obj["quote"]
    assert "CSR" in obj["quote"]


def test_sanitize_only_strips_invalid_escapes():
    """Valid JSON escapes (``\\\"`` ``\\\\`` ``\\n`` etc.) must be preserved."""
    raw = '{"a": "ok\\nfine", "b": "quoted: \\"yes\\""}'
    obj = G._extract_json_object(raw)
    assert obj == {"a": "ok\nfine", "b": 'quoted: "yes"'}


def test_ensure_uuid_replaces_invalid():
    n = {"id": "not-a-uuid", "weight": "5", "sub_tasks": [{"id": "x"}]}
    G._ensure_uuid(n)
    uuid.UUID(n["id"])
    assert n["weight"] == 5
    uuid.UUID(n["sub_tasks"][0]["id"])


# ─── _collapse_single_child_chains ───────────────────────────────────────


def test_collapse_single_leaf_child_merges_into_parent_as_leaf():
    """Parent + single leaf child → one merged leaf carrying both texts."""
    n = {
        "id": "p", "weight": 2, "requirements": "Parent claim",
        "sub_tasks": [{
            "id": "c", "weight": 1, "requirements": "Logged",
            "sub_tasks": [], "task_category": "Code Execution",
            "finegrained_task_category": "Method Implementation",
            "rationale_from_paper": {"section": "§2", "quote": "x"},
        }],
    }
    G._collapse_single_child_chains(n)
    assert n["id"] == "p", "parent id retained"
    assert n["weight"] == 2, "parent weight retained"
    assert n["sub_tasks"] == [], "becomes leaf"
    assert "Parent claim" in n["requirements"]
    assert "Logged" in n["requirements"]
    # leaf metadata adopted because the merged node IS a leaf
    assert n["task_category"] == "Code Execution"
    assert n["finegrained_task_category"] == "Method Implementation"
    assert n["rationale_from_paper"] == {"section": "§2", "quote": "x"}


def test_collapse_single_child_with_grandchildren_strips_leaf_fields():
    """When parent's only child has 2+ grandchildren AND a task_category,
    the merged parent is NON-leaf; task_category MUST be stripped, otherwise
    PaperBench's grader rejects the rubric ('Non-leaf cannot have a task
    category').
    """
    n = {
        "id": "p", "weight": 2, "requirements": "Parent",
        "sub_tasks": [{
            "id": "c", "weight": 1, "requirements": "Middle",
            # The child carries leaf fields it shouldn't (e.g. LLM mistake).
            "task_category": "Code Development",
            "finegrained_task_category": "Method Implementation",
            "rationale_from_paper": {"section": "§3", "quote": "y"},
            "sub_tasks": [
                {"id": "g1", "weight": 1, "requirements": "leaf 1", "sub_tasks": []},
                {"id": "g2", "weight": 1, "requirements": "leaf 2", "sub_tasks": []},
            ],
        }],
    }
    G._collapse_single_child_chains(n)
    assert n["id"] == "p"
    assert "Parent" in n["requirements"] and "Middle" in n["requirements"]
    assert len(n["sub_tasks"]) == 2, "grandchildren promoted"
    # CRITICAL: leaf-only fields must NOT survive on the now-non-leaf parent
    assert "task_category" not in n
    assert "finegrained_task_category" not in n
    assert "rationale_from_paper" not in n


def test_collapse_two_child_node_unchanged():
    n = {
        "id": "p", "weight": 2, "requirements": "Parent",
        "sub_tasks": [
            {"id": "c1", "weight": 1, "requirements": "A", "sub_tasks": []},
            {"id": "c2", "weight": 1, "requirements": "B", "sub_tasks": []},
        ],
    }
    G._collapse_single_child_chains(n)
    assert n["requirements"] == "Parent", "no concatenation"
    assert len(n["sub_tasks"]) == 2


def test_collapse_deep_chain_fully_flattens():
    """4-deep single-child chain collapses to a single leaf."""
    n = {
        "id": "a", "weight": 1, "requirements": "A",
        "sub_tasks": [{
            "id": "b", "weight": 1, "requirements": "B",
            "sub_tasks": [{
                "id": "c", "weight": 1, "requirements": "C",
                "sub_tasks": [{
                    "id": "d", "weight": 1, "requirements": "D",
                    "sub_tasks": [], "task_category": "Code Execution",
                }],
            }],
        }],
    }
    G._collapse_single_child_chains(n)
    assert n["id"] == "a"
    assert all(s in n["requirements"] for s in ("A", "B", "C", "D"))
    assert n["sub_tasks"] == [], "fully flattened to leaf"
    assert n["task_category"] == "Code Execution", "leaf-only field kept on final leaf"


# ─── _strip_leaf_fields_from_non_leaves ──────────────────────────────────


def test_strip_removes_leaf_fields_from_non_leaf():
    """LLM sometimes attaches task_category to internal nodes — grader rejects."""
    n = {
        "id": "p", "weight": 1, "requirements": "Parent",
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
        "rationale_from_paper": {"section": "§1", "quote": "z"},
        "sub_tasks": [
            {"id": "c1", "weight": 1, "requirements": "A", "sub_tasks": []},
            {"id": "c2", "weight": 1, "requirements": "B", "sub_tasks": []},
        ],
    }
    stripped = G._strip_leaf_fields_from_non_leaves(n)
    assert stripped == 3
    for k in ("task_category", "finegrained_task_category", "rationale_from_paper"):
        assert k not in n, f"{k} should be stripped from non-leaf"


def test_strip_preserves_leaf_fields_on_leaves():
    n = {
        "id": "p", "weight": 1, "requirements": "Parent",
        "sub_tasks": [{
            "id": "c", "weight": 1, "requirements": "leaf",
            "sub_tasks": [],
            "task_category": "Code Development",
            "finegrained_task_category": "Method Implementation",
            "rationale_from_paper": {"section": "§1", "quote": "z"},
        }],
    }
    stripped = G._strip_leaf_fields_from_non_leaves(n)
    assert stripped == 0
    leaf = n["sub_tasks"][0]
    assert leaf["task_category"] == "Code Development"
    assert leaf["finegrained_task_category"] == "Method Implementation"
    assert leaf["rationale_from_paper"]["section"] == "§1"


def test_strip_recurses_through_tree():
    """Multiple non-leaves at different depths each get cleaned."""
    n = {
        "id": "root", "weight": 1, "requirements": "R",
        "task_category": "Code Development",  # ← on root non-leaf
        "sub_tasks": [{
            "id": "mid", "weight": 1, "requirements": "M",
            "finegrained_task_category": "Method Implementation",  # ← on mid non-leaf
            "sub_tasks": [
                {"id": "l1", "weight": 1, "requirements": "x", "sub_tasks": [],
                 "task_category": "Code Execution"},
                {"id": "l2", "weight": 1, "requirements": "y", "sub_tasks": [],
                 "task_category": "Result Analysis"},
            ],
        }],
    }
    stripped = G._strip_leaf_fields_from_non_leaves(n)
    assert stripped == 2, "one field on root + one on mid"
    assert "task_category" not in n
    assert "finegrained_task_category" not in n["sub_tasks"][0]
    # leaves still have their fields
    assert n["sub_tasks"][0]["sub_tasks"][0]["task_category"] == "Code Execution"
    assert n["sub_tasks"][0]["sub_tasks"][1]["task_category"] == "Result Analysis"


@pytest.mark.asyncio
async def test_generate_rubric_round_trip(tmp_path):
    paper_text = (FIXTURES / "paper_simple.tex").read_text()
    env = _envelope_partial(leaves=60)
    out_path = tmp_path / "rubric.json"

    async def fake_llm(prompt: str) -> str:
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=60,
        model="test/mock",
        llm_call=fake_llm,
    )
    assert "error" not in res, res
    assert res["leaves_count"] == 60
    assert res["model"] == "test/mock"
    written = json.loads(out_path.read_text())
    assert written["version"] == "3"
    assert M.verify(written) is True
    pb = M.to_paperbench_format(written)
    assert "paper_sha256" not in pb


@pytest.mark.asyncio
async def test_generate_rubric_retries_on_bad_json(tmp_path):
    paper_text = "tiny paper text " * 50
    env = _envelope_partial(leaves=50)
    out_path = tmp_path / "rubric.json"

    calls = {"n": 0}

    async def fake_llm(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "not JSON at all"
        if calls["n"] == 2:
            return "{ broken json"
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=50,
        model="test/mock",
        llm_call=fake_llm,
    )
    assert "error" not in res, res
    assert calls["n"] == 3
    assert res["leaves_count"] == 50


@pytest.mark.asyncio
async def test_generate_rubric_fails_after_retry_limit(tmp_path):
    out_path = tmp_path / "rubric.json"

    async def always_bad(prompt: str) -> str:
        return "garbage"

    res = await G.generate_rubric_async(
        paper_text="x" * 200,
        output_path=str(out_path),
        target_leaf_count=50,
        model="test/mock",
        llm_call=always_bad,
    )
    assert "error" in res
    assert len(res["warnings"]) == G.JSON_RETRY_LIMIT


@pytest.mark.asyncio
async def test_generate_rubric_clamps_invalid_finegrained(tmp_path):
    """LLM emits the two captured-in-the-wild bogus categories; saved rubric must be clean.

    Reproduces the production failure: ``Result Visualization`` and
    ``Result Analysis Implementation`` crash PaperBench's ``TaskNode.__post_init__``.
    The generator must clamp them before write/freeze and surface what was changed.
    """
    out_path = tmp_path / "rubric.json"
    env = _envelope_partial(leaves=50)
    # Stomp three leaves with the two real failure modes + a novel string.
    env["rubric"]["sub_tasks"][0]["finegrained_task_category"] = "Result Visualization"
    env["rubric"]["sub_tasks"][1]["finegrained_task_category"] = "Result Analysis Implementation"
    env["rubric"]["sub_tasks"][2]["finegrained_task_category"] = "Quantum Foo Bar Baz"
    env["rubric"]["sub_tasks"][3]["task_category"] = "Result Analysis"
    env["rubric"]["sub_tasks"][3]["finegrained_task_category"] = "results visualization"  # case-fix path

    async def fake_llm(prompt: str) -> str:
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text="paper " * 200,
        output_path=str(out_path),
        target_leaf_count=50,
        model="test/mock",
        llm_call=fake_llm,
    )
    assert "error" not in res, res

    written = json.loads(out_path.read_text())
    # Every leaf in the saved envelope is now in PaperBench's allow-list.
    from categories import VALID_FINEGRAINED_TASK_CATEGORIES, VALID_TASK_CATEGORIES

    def _walk(n):
        fg = n.get("finegrained_task_category")
        tc = n.get("task_category")
        if fg is not None:
            assert fg in VALID_FINEGRAINED_TASK_CATEGORIES, fg
        if tc is not None:
            assert tc in VALID_TASK_CATEGORIES, tc
        for c in n.get("sub_tasks", []):
            _walk(c)

    _walk(written["rubric"])
    # Each clamp produced a warning describing the substitution.
    msgs = "\n".join(res["warnings"])
    assert "Result Visualization" in msgs
    assert "Result Analysis Implementation" in msgs
    assert "Quantum Foo Bar Baz" in msgs
    # rubric_sha256 must match the post-normalization tree.
    assert M.verify(written) is True


@pytest.mark.asyncio
async def test_generate_rubric_auto_target(tmp_path):
    paper_text = " ".join(["word"] * 5400)
    env = _envelope_partial(leaves=72)
    out_path = tmp_path / "rubric.json"

    async def fake_llm(prompt: str) -> str:
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=0,  # auto
        model="test/mock",
        llm_call=fake_llm,
    )
    assert res["target_leaf_count"] == 72
    assert res["auto_computed_target"] is True


def _skeleton_envelope(parent_reqs: list[str]) -> dict:
    """Skeleton-pass response: root + N direct children, each empty."""
    children = []
    for i, req in enumerate(parent_reqs):
        children.append({
            "id": str(uuid.uuid4()),
            "requirements": req,
            "weight": 2,
            "target_subtree_leaves": 8,
            "sub_tasks": [],
        })
    return {
        "version": "3",
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 7200,
            "expected_artifacts": ["results.csv"],
        },
        "rubric": {
            "id": str(uuid.uuid4()),
            "requirements": "The core contributions of the paper have been reproduced.",
            "weight": 1,
            "sub_tasks": children,
        },
    }


def _subtree_node(parent_req: str, n_leaves: int = 4) -> dict:
    """Subtree-pass response: parent populated with two internal subgroups + leaves.

    Two subgroups (rather than one) keeps the depth-3 hierarchy visible
    after _collapse_single_child_chains runs — single-child internals get
    folded into their parent and would otherwise flatten this fixture.
    """
    half = max(1, n_leaves // 2)
    def _leaves(prefix: str, count: int) -> list[dict]:
        return [
            _leaf(
                text=f"For {parent_req[:20]} / {prefix}: a definite verifiable claim {i}.",
                cat=["Code Development", "Code Execution", "Result Analysis"][i % 3],
            )
            for i in range(count)
        ]
    internal_a = {
        "id": str(uuid.uuid4()),
        "requirements": f"Subgroup A under {parent_req[:30]}",
        "weight": 1,
        "sub_tasks": _leaves("A", half),
    }
    internal_b = {
        "id": str(uuid.uuid4()),
        "requirements": f"Subgroup B under {parent_req[:30]}",
        "weight": 1,
        "sub_tasks": _leaves("B", n_leaves - half),
    }
    return {
        "id": str(uuid.uuid4()),
        "requirements": parent_req,
        "weight": 2,
        "sub_tasks": [internal_a, internal_b],
    }


@pytest.mark.asyncio
async def test_two_stage_generates_skeleton_then_subtrees(tmp_path):
    """Two-stage generation issues 1+N calls, merges subtrees, and the
    resulting rubric is deeper than what one call produced."""
    paper_text = (FIXTURES / "paper_simple.tex").read_text()
    out_path = tmp_path / "rubric.json"
    parents = [
        "Reproduce Contribution A: the core method implementation.",
        "Reproduce Contribution B: the benchmark experiments.",
    ]
    skeleton = _skeleton_envelope(parents)
    subtrees = {req: _subtree_node(req, n_leaves=5) for req in parents}

    seen_prompts: list[str] = []

    async def fake_llm(prompt: str) -> str:
        seen_prompts.append(prompt)
        if "SKELETON" in prompt:
            return json.dumps(skeleton)
        for req, sub in subtrees.items():
            if req in prompt:
                return json.dumps(sub)
        raise AssertionError(f"unexpected prompt:\n{prompt[:200]}")

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=20,
        model="test/mock",
        llm_call=fake_llm,
        two_stage=True,
    )
    assert "error" not in res, res
    # 1 skeleton + 2 subtree calls
    assert len(seen_prompts) == 3
    # Tree should be deeper than the skeleton-only output (root → d2 → d3 → d4 leaves)
    assert res["depth"] >= 3
    # Total leaves equals sum across subtrees
    assert res["leaves_count"] == 10
    written = json.loads(out_path.read_text())
    assert M.verify(written) is True
    # ``target_subtree_leaves`` is a generator-internal hint — must NOT
    # leak into the persisted envelope (not in the schema's allow-list).
    def _no_budget_leakage(n):
        assert "target_subtree_leaves" not in n
        for c in n.get("sub_tasks", []):
            _no_budget_leakage(c)
    _no_budget_leakage(written["rubric"])


@pytest.mark.asyncio
async def test_two_stage_drops_invalid_leaves_instead_of_failing(tmp_path):
    """If a subtree call returns a leaf with too-short quote (<10 chars),
    the prune pass should drop it and the rubric should still validate."""
    paper_text = (FIXTURES / "paper_simple.tex").read_text()
    out_path = tmp_path / "rubric.json"
    parents = ["Contribution X: deep verifiable check coverage."]
    skeleton = _skeleton_envelope(parents)
    sub = _subtree_node(parents[0], n_leaves=4)
    # Stomp two leaves with quotes shorter than the schema's minLength=10.
    sub["sub_tasks"][0]["sub_tasks"][0]["rationale_from_paper"]["quote"] = "x<y"
    sub["sub_tasks"][0]["sub_tasks"][1]["requirements"] = "tiny"

    async def fake_llm(prompt: str) -> str:
        if "SKELETON" in prompt:
            return json.dumps(skeleton)
        return json.dumps(sub)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=20,
        model="test/mock",
        llm_call=fake_llm,
        two_stage=True,
    )
    assert "error" not in res, res
    # 4 leaves emitted, 2 were invalid → 2 should remain
    assert res["leaves_count"] == 2
    msgs = "\n".join(res["warnings"])
    assert "pruned" in msgs


@pytest.mark.asyncio
async def test_generate_rubric_preserves_execution_profile(tmp_path):
    """A rubric envelope carrying execution_profile must round-trip through
    generate_rubric_async and survive freeze + schema validation. This is the
    P1 acceptance criterion for HPC-aware rubrics (cf. PLAN_MPI_EXIT.md §5).
    """
    paper_text = "We ran TS-SpGEMM on 4 nodes with 8 MPI ranks per node. " * 80
    env = _envelope_partial(leaves=20)
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi_gpu",
        "paper_max_ranks": 32,
        "paper_max_nodes": 4,
        "min_ranks": 4,
        "min_nodes": 1,
        "result_aggregation": "rank0_csv",
        "metric_columns": ["nodes", "ranks", "runtime_sec", "gflops"],
        "accepts_reduced_scale": True,
        "requested_nodes": 4,
        "ntasks_per_node": 8,
        "exclusive": True,
        "requested_gpus_per_task": 1,
        "gpu_type": "v100",
        "memory_gb_per_node": 256,
        "constraint": "skylake",
        "module_loads": ["cuda/12.4", "openmpi/4.1"],
        "extra_sbatch_args": ["--account=projX"],
    }
    out_path = tmp_path / "rubric.json"

    async def fake_llm(prompt: str) -> str:
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=20,
        model="test/mock",
        llm_call=fake_llm,
    )
    assert "error" not in res, res
    written = json.loads(out_path.read_text())
    prof = written["reproduce_contract"]["execution_profile"]
    assert prof["kind"] == "mpi_gpu"
    assert prof["paper_max_ranks"] == 32
    assert prof["requested_nodes"] == 4
    assert prof["exclusive"] is True
    assert prof["gpu_type"] == "v100"
    assert prof["module_loads"] == ["cuda/12.4", "openmpi/4.1"]
    assert prof["extra_sbatch_args"] == ["--account=projX"]
    # sha256 covers the full envelope including execution_profile.
    assert M.verify(written) is True


@pytest.mark.asyncio
async def test_generate_rubric_without_execution_profile_unchanged(tmp_path):
    """Backward compat: legacy single-node paper rubric without
    execution_profile still generates + validates."""
    paper_text = "A small CPU-only paper. " * 80
    env = _envelope_partial(leaves=15)
    assert "execution_profile" not in env["reproduce_contract"]
    out_path = tmp_path / "rubric.json"

    async def fake_llm(prompt: str) -> str:
        return json.dumps(env)

    res = await G.generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=15,
        model="test/mock",
        llm_call=fake_llm,
    )
    assert "error" not in res, res
    written = json.loads(out_path.read_text())
    assert "execution_profile" not in written["reproduce_contract"]
    assert M.verify(written) is True


def test_skeleton_prompt_includes_execution_profile_guidance():
    """The skeleton template must explicitly instruct the LLM about
    execution_profile so HPC paper structure gets captured at generation
    time (P1 acceptance criterion)."""
    rendered = G._render_skeleton_prompt(paper_text="X" * 100, target_leaves=50)
    assert "execution_profile" in rendered
    assert "kind" in rendered
    assert "mpi" in rendered
    assert "gpu_single" in rendered
    assert "module_loads" in rendered


def test_single_call_prompt_also_includes_execution_profile_guidance():
    """The single-call ``adversarial_reviewer.md`` template (used when
    `two_stage=False`) must carry the same execution_profile guidance.
    Without it, users who opt into single-call mode silently lose the
    HPC pathway — discovered during the v0.7.2 real-LLM smoke against
    sc24-00052, which returned ``execution_profile: null`` when
    `two_stage=False` despite the paper being MPI."""
    rendered = G._render_prompt(paper_text="X" * 100, target_leaves=50)
    assert "execution_profile" in rendered
    assert "kind" in rendered
    assert "mpi" in rendered
    assert "gpu_single" in rendered
    assert "module_loads" in rendered
    assert "OMIT" in rendered  # explicit instruction for non-HPC papers


def test_prompt_includes_expected_artifacts_discipline():
    """A2: rubric prompt must explicitly tell the LLM how to populate
    expected_artifacts — over-specifying it (especially with figure paths
    the experiment program doesn't emit) tanks reproducibility scoring."""
    rendered = G._render_prompt(paper_text="X" * 100, target_leaves=50)
    # The dedicated section must appear.
    assert "EXPECTED_ARTIFACTS DISCIPLINE" in rendered
    # Concrete rules the LLM must follow.
    assert "post-hoc plotting" in rendered
    assert "results.csv" in rendered
    assert "fig_1.pdf" in rendered
    # The final schema block should reference the new "RULES above" hint
    # rather than the old "<relative paths produced by reproduce.sh>".
    assert "see RULES above" in rendered
