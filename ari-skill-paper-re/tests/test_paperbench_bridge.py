"""Tests for the PaperBench bridge (Step 3 / 5.1 DoD).

These tests exercise the bridge's structural surface — TaskNode construction
from dicts, weighted aggregation, and run averaging. They use the upstream
GradedTaskNode/TaskNode (no local fallback exists). The LLM-driven
SimpleJudge.judge() path is exercised separately in
test_paperbench_bridge_upstream.py — those tests need a real OpenAI key and
are skipped on CI by default.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location("paper_re_bridge", SRC / "_paperbench_bridge.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_bridge"] = B
_spec.loader.exec_module(B)


def _leaf(text: str, weight: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": text,
        "weight": weight,
        "sub_tasks": [],
        "task_category": "Code Development",
        "finegrained_task_category": "Method Implementation",
    }


def _root_pb_dict(leaves: list[dict]) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": "Replicate the paper's main contribution.",
        "weight": 1,
        "sub_tasks": leaves,
        "task_category": None,
    }


def _graded_leaf(id_: str, *, score: float, weight: int = 1, category: str = "Code Development") -> "B.GradedTaskNode":
    return B.GradedTaskNode(
        id=id_, requirements="x", weight=weight, sub_tasks=(), score=score,
        valid_score=True, explanation="", task_category=category,
        judge_metadata=None,
    )


def _graded_internal(id_: str, children, *, score: float, weight: int = 1) -> "B.GradedTaskNode":
    return B.GradedTaskNode(
        id=id_, requirements="root", weight=weight, sub_tasks=tuple(children),
        score=score, valid_score=True, explanation="", task_category=None,
        judge_metadata=None,
    )


def test_task_node_from_dict_round_trip():
    pb = _root_pb_dict([_leaf("Implement MaskNetwork outputs zero for critical states.")])
    node = B.task_node_from_dict(pb)
    assert node.requirements.startswith("Replicate the paper")
    assert len(node.sub_tasks) == 1
    leaf = node.sub_tasks[0]
    assert leaf.weight == 1
    assert leaf.task_category == "Code Development"


def test_aggregate_graded_tree_unweighted_and_weighted():
    g_pass = _graded_leaf("l1", score=1.0, weight=2)
    g_fail = _graded_leaf("l2", score=0.0, weight=2, category="Code Execution")
    expected = (2 * 1.0 + 2 * 0.0) / (2 + 2)
    g_root = _graded_internal("r", [g_pass, g_fail], score=expected)
    agg = B.aggregate_graded_tree(g_root)
    assert agg["ors_score"] == pytest.approx(0.5)
    assert agg["raw_score"] == pytest.approx(0.5)
    assert len(agg["leaf_grades"]) == 2


def test_average_graded_runs_passed_runs_count():
    g_root_pass = _graded_internal("r", [_graded_leaf("l1", score=1.0)], score=1.0)
    g_root_fail = _graded_internal("r", [_graded_leaf("l1", score=0.0)], score=0.0)
    agg = B.average_graded_runs([g_root_pass, g_root_fail, g_root_pass])
    assert agg["leaf_grades"][0]["passed_runs"] == 2
    assert agg["leaf_grades"][0]["n_runs"] == 3
    assert agg["leaf_grades"][0]["mean_score"] == pytest.approx(2 / 3)


def test_average_graded_runs_single_run_is_aggregate():
    """Single-run case is equivalent to aggregate_graded_tree for scoring."""
    g = _graded_internal("r", [_graded_leaf("l1", score=1.0), _graded_leaf("l2", score=0.0)], score=0.5)
    agg = B.average_graded_runs([g])
    assert agg["ors_score"] == pytest.approx(0.5)


def test_average_graded_runs_empty_list_is_zero():
    agg = B.average_graded_runs([])
    assert agg["ors_score"] == 0.0
    assert agg["leaf_grades"] == []


def test_judge_submission_is_async_callable():
    """The async LLM-driven adapter exists. Real LLM calls are exercised in
    test_paperbench_bridge_upstream.py (skipped without OPENAI_API_KEY)."""
    import inspect
    assert inspect.iscoroutinefunction(B.judge_submission)


def test_three_stage_adapters_share_calling_style():
    """Stage 1 (rollout_submission), Stage 2 (reproduce_submission), and
    Stage 3 (judge_submission) are exposed as keyword-only async callables
    so a caller can sequence them with explicit field names. This is the
    public surface the dogfood script and the viz worker consume.
    """
    import inspect
    for fn_name in ("rollout_submission", "reproduce_submission", "judge_submission"):
        fn = getattr(B, fn_name)
        assert inspect.iscoroutinefunction(fn), f"{fn_name} must be async"
        sig = inspect.signature(fn)
        # All params keyword-only (no positional surprises).
        kinds = {p.kind for p in sig.parameters.values()}
        assert kinds == {inspect.Parameter.KEYWORD_ONLY}, (
            f"{fn_name} parameters must all be keyword-only; got kinds={kinds}"
        )


def test_rollout_submission_signature_includes_container_image_and_sandbox():
    """Regression for the container_image / sandbox_kind pipeline: the
    Stage 1 adapter must expose both so a caller can opt into Apptainer
    isolation (the only Stage 1 sandbox with real container isolation).
    """
    import inspect
    sig = inspect.signature(B.rollout_submission)
    params = set(sig.parameters)
    for required in (
        "paper_md", "work_dir", "agent_model",
        "container_image", "sandbox_kind",
        "iterative_agent", "time_limit_sec",
    ):
        assert required in params, f"rollout_submission missing {required!r}"


def test_reproduce_submission_signature_honors_sandbox_and_slurm_flags():
    """Regression for the Stage 2 wiring: the adapter must expose
    container_image plus the SLURM resource flags so a wizard request
    flows through verbatim.
    """
    import inspect
    sig = inspect.signature(B.reproduce_submission)
    params = set(sig.parameters)
    for required in (
        "submission_dir", "sandbox_kind", "container_image",
        "time_limit_sec", "partition",
        "gpus_per_task", "gpu_type", "memory_gb_per_node",
        "exclusive", "extra_sbatch_args",
    ):
        assert required in params, f"reproduce_submission missing {required!r}"


def test_judge_submission_code_only_prunes_rubric_tree():
    """Mirror of vendor ``paperbench/grade.py:109-112``: when
    ``code_only=True`` is passed, the rubric tree is reduced to
    Code Development leaves only (per ``TaskNode.code_only`` in
    ``rubric/tasks.py:338-344``) BEFORE SimpleJudge is constructed.

    This is the structural test (the reducer call is what matters; the
    actual LLM-driven grade_leaf is exercised in the upstream test).
    We exercise reduce-then-aggregate which gives an apples-to-apples
    comparison: graded.score over a pruned tree counts only Code Dev.
    """
    import uuid
    rubric_dict = {
        "id": str(uuid.uuid4()),
        "requirements": "root",
        "weight": 1,
        "sub_tasks": [
            {"id": str(uuid.uuid4()), "requirements": "implement X",
             "weight": 1, "task_category": "Code Development"},
            {"id": str(uuid.uuid4()), "requirements": "run Y",
             "weight": 1, "task_category": "Code Execution"},
            {"id": str(uuid.uuid4()), "requirements": "analyze Z",
             "weight": 1, "task_category": "Result Analysis"},
        ],
    }
    root = B.task_node_from_dict(rubric_dict)

    # Pre-reduction: 3 leaves spanning all three categories.
    leaves_before = []
    def _walk(n):
        if not n.sub_tasks:
            leaves_before.append(n)
        for c in n.sub_tasks:
            _walk(c)
    _walk(root)
    assert len(leaves_before) == 3
    assert {l.task_category for l in leaves_before} == {
        "Code Development", "Code Execution", "Result Analysis"
    }

    # Post-reduction (the vendor method used inside judge_submission).
    pruned = root.code_only()
    assert pruned is not None
    leaves_after = []
    def _walk2(n):
        if not n.sub_tasks:
            leaves_after.append(n)
        for c in n.sub_tasks:
            _walk2(c)
    _walk2(pruned)
    assert len(leaves_after) == 1
    assert leaves_after[0].task_category == "Code Development"
    assert leaves_after[0].requirements == "implement X"


def test_rollout_submission_forbid_host_filesystem_raises_for_local_slurm():
    """``forbid_host_filesystem=True`` + sandbox_kind in {local, slurm}
    must raise RuntimeError BEFORE any agent rollout starts. The error
    message must point the user at sandbox_kind=apptainer.
    """
    import asyncio
    for sandbox in ("local", "slurm"):
        with pytest.raises(RuntimeError, match="forbid_host_filesystem"):
            asyncio.run(B.rollout_submission(
                paper_md="x", work_dir="/tmp/.does-not-matter",
                agent_model="gpt-5-mini",
                sandbox_kind=sandbox,
                forbid_host_filesystem=True,
            ))


def test_rollout_submission_forbid_host_filesystem_allows_apptainer():
    """The guard must NOT fire for sandbox_kind=apptainer/singularity —
    those have real container isolation.
    """
    import inspect
    sig = inspect.signature(B.rollout_submission)
    assert "forbid_host_filesystem" in sig.parameters
    assert "agent_env_path" in sig.parameters
    # Default is permissive so existing dogfood / dev workflows are not
    # broken — caller must opt in.
    assert sig.parameters["forbid_host_filesystem"].default is False
    assert sig.parameters["agent_env_path"].default is None


def test_load_dotenv_file_handles_comments_quotes_and_empty():
    """The agent.env / .env loader must skip comments, strip quotes,
    and accept empty values."""
    import tempfile
    from pathlib import Path as _P
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write(
            "# leading comment\n"
            "\n"
            "FOO=bar\n"
            "QUOTED=\"baz qux\"\n"
            "SINGLE='hi'\n"
            "EMPTY=\n"
            "HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
            "  # indented comment\n"
            "no_equals_sign_ignored\n"
        )
        path = _P(f.name)
    try:
        got = B._load_dotenv_file(path)
        assert got["FOO"] == "bar"
        assert got["QUOTED"] == "baz qux"
        assert got["SINGLE"] == "hi"
        assert got["EMPTY"] == ""
        assert got["HF_TOKEN"].startswith("hf_")
        assert "no_equals_sign_ignored" not in got
    finally:
        path.unlink()


def test_reproduce_submission_signature_includes_tarball_and_salvage():
    """Regression for the (b) tarball capture and (a) salvage retries
    Stage 2 fixes: both flags must be on the bridge surface so a
    caller (wizard / CLI / external orchestrator) can opt in/out.
    """
    import inspect
    sig = inspect.signature(B.reproduce_submission)
    params = set(sig.parameters)
    for required in (
        "capture_tarball", "tarball_dir",
        "salvage_retries", "retry_threshold_sec",
    ):
        assert required in params, f"reproduce_submission missing {required!r}"
    # Defaults: tarball ON, salvage OFF (preserves existing dogfood
    # behaviour and only adds work when caller asks).
    assert sig.parameters["capture_tarball"].default is True
    assert sig.parameters["salvage_retries"].default == 0


def test_install_and_restore_salvage_wrapper_roundtrip(tmp_path):
    """The salvage wrapper must wrap reproduce.sh with a venv prelude
    AND restore the original byte-for-byte on cleanup."""
    sub = tmp_path / "sub"
    sub.mkdir()
    repro = sub / "reproduce.sh"
    original_body = "#!/usr/bin/env bash\necho original\n"
    repro.write_text(original_body)
    repro.chmod(0o755)

    B._install_salvage_wrapper(sub)
    wrapped = repro.read_text()
    assert "ari-skill-paper-re salvage retry" in wrapped
    assert ".salvage_venv" in wrapped
    assert "original reproduce.sh body" in wrapped
    assert wrapped.endswith(original_body)
    # Backup preserved exactly
    backup = repro.with_suffix(repro.suffix + B._SALVAGE_WRAPPER_SUFFIX)
    assert backup.is_file()
    assert backup.read_text() == original_body

    B._restore_salvage_wrapper(sub)
    assert repro.read_text() == original_body
    assert not backup.is_file()


def test_write_executed_tarball_round_trip(tmp_path):
    """(b) Tarball capture writes a gzip tarball alongside the
    submission and contains every file from the executed dir."""
    import tarfile
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "reproduce.sh").write_text("#!/bin/bash\necho ok\n")
    (sub / "reproduce.log").write_text("ok\n")
    (sub / "results").mkdir()
    (sub / "results" / "metric.txt").write_text("0.42\n")

    tar = B._write_executed_tarball(sub, None)
    assert tar.is_file()
    assert tar.name.startswith("submission_executed_") and tar.suffix == ".gz"
    with tarfile.open(tar, "r:gz") as tf:
        names = sorted(tf.getnames())
    # Includes the submission dir + its members (arcname=submission_dir.name)
    assert any(n.endswith("/reproduce.sh") for n in names), names
    assert any(n.endswith("/results/metric.txt") for n in names), names


def test_filter_orphan_tool_calls_drops_unmatched():
    """Regression for the SC41406 vendor bug: when vendor solver loop
    crashes after appending assistant.tool_calls but before all matching
    role=tool outputs are added, the next API call sees orphan tool_calls
    and the Responses API returns BadRequestError. The bridge's
    _filter_orphan_tool_calls drops the orphans before the converter sees
    them.
    """
    convo = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [
            {"id": "A", "function": {"name": "foo", "arguments": "{}"}, "type": "function"},
            {"id": "B", "function": {"name": "bar", "arguments": "{}"}, "type": "function"},
        ]},
        {"role": "tool", "tool_call_id": "A", "content": "A-out"},
        # B has no matching output → orphan
        {"role": "user", "content": "continue"},
    ]
    filtered = B._filter_orphan_tool_calls(convo)
    assert len(filtered) == 4
    asst = filtered[1]
    assert asst["role"] == "assistant"
    assert [tc["id"] for tc in asst["tool_calls"]] == ["A"], \
        "orphan tool_call B must be dropped, matched A kept"


def test_filter_orphan_tool_calls_drops_empty_assistant_when_all_orphan():
    """When every tool_call on an assistant message is orphan AND the
    message has no text content, drop the entire assistant message to
    keep the API input compact.
    """
    convo = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [
            {"id": "X", "function": {"name": "foo", "arguments": "{}"}, "type": "function"},
        ]},
        {"role": "user", "content": "next"},
    ]
    filtered = B._filter_orphan_tool_calls(convo)
    # The orphan-only assistant must be dropped entirely.
    assert all(m.get("role") != "assistant" for m in filtered), filtered
    assert len(filtered) == 2


def test_filter_orphan_tool_calls_keeps_assistant_with_text_after_orphan_strip():
    """When an assistant message has BOTH text content AND tool_calls,
    and only the tool_calls are orphan, keep the assistant message
    (text preserved) but drop the orphan call list.
    """
    convo = [
        {"role": "assistant", "content": "I will call foo",
         "tool_calls": [{"id": "X", "function": {"name": "foo", "arguments": "{}"}, "type": "function"}]},
    ]
    filtered = B._filter_orphan_tool_calls(convo)
    assert len(filtered) == 1
    assert filtered[0]["content"] == "I will call foo"
    assert "tool_calls" not in filtered[0]


def test_filter_orphan_tool_calls_idempotent_on_clean_conversation():
    """Conversations without orphans must pass through unchanged."""
    convo = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [
            {"id": "A", "function": {"name": "foo", "arguments": "{}"}, "type": "function"},
        ]},
        {"role": "tool", "tool_call_id": "A", "content": "ok"},
    ]
    filtered = B._filter_orphan_tool_calls(convo)
    assert filtered == convo, "clean conversations must round-trip unchanged"


def test_orphan_filter_patch_is_installed_on_vendor_converter():
    """The patch must be active on the vendor converter symbol so the
    Responses API call path is protected. Idempotency: importing the
    bridge twice (re-loading the module) should leave only one patch
    layer (verified by the ._ari_orphan_patched sentinel)."""
    from preparedness_turn_completer.oai_responses_turn_completer import (  # type: ignore
        converters as _v_conv,
    )
    fn = _v_conv.convert_conversation_to_response_input
    assert getattr(fn, "_ari_orphan_patched", False) is True, (
        "vendor converter not patched; orphan tool_calls will reach the "
        "Responses API and trigger BadRequestError"
    )


def test_env_detect_returns_required_keys():
    env = B._detect_runtime_env()
    # Since v0.7.5 the env detect dict no longer carries compiler-
    # specific fields (nvcc_path was removed for cluster-agnosticism;
    # paper-conditional language guidance flows via the addendum hint
    # instead — see _build_paper_kind_addendum).
    for k in ("kind", "has_apt", "has_sudo", "has_module",
              "slurm_partition", "module_path"):
        assert k in env, f"missing key {k} in detected env"
    assert env["kind"] in ("slurm", "docker", "local"), env["kind"]
    # Regression guard: nvcc-specific keys MUST NOT reappear (would
    # be a philosophy violation — bridge inspecting/exposing a
    # specific toolchain).
    assert "nvcc_path" not in env, (
        "nvcc_path is a compiler-specific privilege that violates the "
        "cluster-agnostic bridge philosophy; use `module avail` probe + "
        "paper-kind addendum instead"
    )


def test_env_block_for_docker_keeps_vendor_line():
    """In a Docker env vendor's 'You have root access in your environment.'
    line is correct — patch must NOT alter the line so we don't waste
    tokens telling the agent things it already knows."""
    env = {
        "kind": "docker",
        "has_apt": True, "has_sudo": True, "has_module": False,
        "slurm_partition": None, "module_path": None,
    }
    assert B._build_truthful_env_block(env) == B._VENDOR_ROOT_ACCESS_LINE


def test_env_block_for_slurm_describes_module_load_path():
    """SLURM HPC cluster: agent must learn root access is NOT
    available, module system IS available, and the cluster catalog
    is dumped via `module avail` for the agent to inspect. Bridge
    must NOT name specific compilers (nvcc / mpicc / gcc) — that
    knowledge belongs in the per-paper addendum, not the env block."""
    env = {
        "kind": "slurm",
        "has_apt": False, "has_sudo": False, "has_module": True,
        "slurm_partition": "ai-l40s",
        "module_path": "/cloud_opt/modulefiles/ai-l40s:...",
    }
    block = B._build_truthful_env_block(env)
    assert "NO root access" in block
    assert "SLURM" in block or "HPC" in block
    assert "ai-l40s" in block  # partition surfaced
    assert "module avail" in block  # the exploration instruction
    assert "module load" in block  # generic load command
    # The vendor's misleading line MUST be entirely replaced (we are
    # not on Docker — sudo lie would mislead the agent again).
    assert B._VENDOR_ROOT_ACCESS_LINE not in block
    # Network claim must be present so the agent doesn't waste cycles
    # probing connectivity or try to bundle every dep locally.
    assert "Network" in block
    assert "pip install" in block
    assert "git clone" in block
    # Phase 2 fresh-shell warning is the most subtle failure mode for
    # HPC dogfood — must be explicit so the agent puts module load /
    # pip install AT THE TOP of reproduce.sh.
    assert "FRESH shell" in block
    assert "reproduce.sh" in block
    # Verify-first principle: counters the observed agent bias of
    # writing CUDA / MPI / numba scaffolding without actually
    # probing whether the toolchain is reachable in the iteration
    # shell. Must mention probe + zero-cost experimentation.
    assert "Verify-first" in block
    assert "module load" in block  # named example for cluster envs
    assert "ZERO Code Execution" in block
    # Native-language guidance is NOT in the env block anymore — it moved
    # to the paper-kind addendum's Cautionary note (paper-specific +
    # imperative). The env block stays focused on the ENVIRONMENT.
    assert "Language choice" not in block


def test_env_block_for_local_host_without_module():
    """Bare-metal local with no module system: agent should be told
    module is unavailable so it doesn't waste tool calls trying."""
    env = {
        "kind": "local",
        "has_apt": True, "has_sudo": False, "has_module": False,
        "slurm_partition": None, "module_path": None,
    }
    block = B._build_truthful_env_block(env)
    assert "apt-get available" in block
    assert "not detected" in block  # module honesty
    # Even on bare-metal local hosts the network + Phase 2 isolation
    # notes apply — these are not SLURM-specific.
    assert "Network" in block
    assert "FRESH shell" in block
    # Native-language guidance moved to the addendum; env block no longer
    # carries it.
    assert "Language choice" not in block
    # Verify-first principle must also fire on local — it counters a
    # generic agent bias (write code before checking toolchain works)
    # that is not slurm-specific.
    assert "Verify-first" in block
    assert "PROBE" in block
    assert "ZERO Code Execution" in block


def test_blacklist_lift_constants_disagree_with_vendor():
    """Sanity: the ARI override text must NOT be a substring of the
    vendor cheating-claim line, otherwise the substitution would
    loop or no-op."""
    assert B._ARI_BLACKLIST_OVERRIDE != B._VENDOR_BLACKLIST_LINE
    # Override must mention the lift mechanism so the agent understands
    # the override is intentional, not a leak.
    assert "paper's official codebase" in B._ARI_BLACKLIST_OVERRIDE
    assert "blacklist_urls" in B._ARI_BLACKLIST_OVERRIDE
    # Original cheating wording must NOT be in the override.
    assert "cheating" not in B._ARI_BLACKLIST_OVERRIDE


def test_blacklist_patch_is_installed_on_vendor_get_instructions():
    """The vendor get_instructions symbol must carry the consolidated
    rewrite sentinel at bridge import. Env-truth + blacklist-lift now live
    in ONE wrapper (both fire per call)."""
    from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    fn = _v_utils.get_instructions
    assert getattr(fn, "_ari_instr_rewritten", False) is True, (
        "consolidated instruction-rewrite wrapper not installed; agent will "
        "see vendor's env/cheating claims verbatim"
    )


def test_paper_kind_addendum_format_cpp_cuda():
    """For a CUDA paper the addendum must surface the C++/CUDA
    reproduce.sh skeleton (`nvcc -std=c++17`) so the agent has a
    concrete template to follow, plus the cautionary past-dogfood
    data block.

    Regression: the skeleton must NOT contain a hardcoded cluster
    module name (e.g., `nvhpc`) — bridge stays cluster-agnostic by
    using `module load <NAME>` placeholders that the agent resolves
    against the env-truth `module avail` catalog.
    """
    out = B._format_paper_kind_addendum(
        native="cpp+cuda",
        rationale="paper mentions GPU kernels, nvcc, sm_*",
        secondary=["CUDA SDK >= 11", "single-GPU A100"],
        env={"has_module": True, "has_apt": False, "has_sudo": False},
    )
    assert "native_stack: **cpp+cuda**" in out
    assert "nvcc -std=c++17" in out  # concrete build line
    assert "CUDA SDK >= 11" in out  # secondary hint surfaced
    # For a non-Python native stack the cautionary note must be
    # IMPERATIVE (no "where possible" soft out) and must neutralise the
    # vendor Python toy example, which otherwise primes a Python proxy
    # (v3-A9: agent declared "minimal Python-based reproduction" for a
    # CUDA paper).
    assert "Cautionary note" in out
    assert "You MUST implement" in out
    # The old soft-out phrasing ("match it where possible") must be gone;
    # the note now explicitly negates it ("This is NOT 'where possible'").
    assert "match it where possible" not in out
    assert "it is required" in out  # imperative
    assert "count.py" in out  # toy example explicitly neutralised
    assert "IGNORE THE LANGUAGE OF THE VENDOR TOY EXAMPLE" in out
    # Cluster-agnosticism regression: NO cluster-specific module name.
    assert "nvhpc" not in out, "cluster-specific module name must not leak"
    assert "openmpi" not in out
    assert "module load <NAME>" in out  # placeholder must be present
    # Runbook STEP 1 must reference the activation mechanism.
    assert "STEP 1" in out
    assert "module avail" in out  # discovery path
    # STEP 2 must require the FULL module chain in reproduce.sh (Phase 2
    # isolation): v3-A8 agent loaded entry+tier-2 in its iteration shell
    # but wrote only the entry module into reproduce.sh, so nvcc was
    # absent at grade time. The runbook must say copy EVERY activation
    # command (entry AND tier-2), not a single line.
    assert "STEP 2" in out
    assert "FULL chain" in out or "EVERY activation" in out
    assert "TIER-2" in out or "tier-2 module" in out
    assert "entry-module load alone" in out or "does NOT add the tool" in out
    # STEP 4 must be present, MANDATORY-flagged, with concrete final
    # check + git clean caveat. This is the imperative reinforcement
    # of vendor instructions.txt L25/L27 which use weaker verbs
    # ("very important", "advised"). It must enforce ALL THREE of:
    # git-clean + reproduce.sh exit 0 + impl-complete (the last is
    # the anti-early-submit guard).
    assert "STEP 4" in out
    assert "MANDATORY" in out
    assert "bash reproduce.sh" in out
    assert "git status --porcelain" in out  # git-clean guard
    assert "git clean -fd" in out
    # Anti-early-submit guard: agent must not submit a thin scaffold.
    assert "thin scaffold" in out or "scaffold" in out
    # Anti-philosophy-leak regression: addendum must NOT carry
    # paper-specific dogfood score tables (e.g., "SC41406 v1 14.45%").
    # Past commit e780fa5 added such a table; commit (this fix)
    # removed it. The rule itself stands on its own without per-paper
    # dogfood numbers.
    assert "SC41406" not in out
    assert "14.45%" not in out


def test_paper_kind_addendum_lists_paper_datasets_with_search_hint():
    """When the classifier returns paper-cited datasets, the addendum
    must include a STEP 1.5 dataset-acquisition block listing each
    dataset by name + domain + url_hint, plus the tactic list (web_search →
    wget / huggingface-cli / git clone), plus a paper-agnostic note on
    why skipping dataset download zeros the Result Analysis leaves.
    """
    out = B._format_paper_kind_addendum(
        native="cpp+cuda",
        rationale="GPU compression paper",
        secondary=[],
        env={"has_module": True, "has_apt": False, "has_sudo": False},
        datasets=[
            {"name": "Miranda", "domain": "hydrodynamics simulation",
             "url_hint": "SDRBench Zenodo Miranda"},
            {"name": "Nyx", "domain": "cosmological hydrodynamics",
             "url_hint": "SDRBench Zenodo Nyx"},
        ],
    )
    assert "STEP 1.5" in out
    assert "Miranda" in out
    assert "hydrodynamics simulation" in out
    assert "SDRBench Zenodo Miranda" in out  # search hint surfaced
    assert "Nyx" in out
    # Acquisition tactics must mention all major channels.
    assert "web_search" in out
    assert "wget" in out
    assert "huggingface-cli" in out or "huggingface" in out
    assert "git clone" in out
    # Registry-first guidance: find the official download/registry PAGE,
    # do NOT fabricate file URLs (v3-A7 agent guessed zenodo/HF URLs that
    # 404/401'd). Must tell the agent to confirm with a HEAD before use.
    assert "registry" in out.lower() or "official download" in out.lower()
    assert "fabricate" in out.lower() or "guess" in out.lower()
    assert "curl -sI" in out  # HEAD-confirm before download (curl -sIL ⊇ curl -sI)
    # Concrete search→fetch-index→parse-links workflow so the agent does
    # not give up after one web_search and fall back to a guessed URL
    # (v3-A8: web_search 1x, never reached the official registry).
    assert "official data" in out.lower()  # search query framing
    assert "grep -oE" in out  # extract real file links from the page
    assert "do NOT skip to synthetic" in out  # persist, don't bail to synthetic
    # reproduce.sh must carry the EXACT confirmed URL and be tested from a
    # clean state (v3-A9: agent got real data once but wrote a 404 URL into
    # reproduce.sh → grader got no data).
    assert "EXACT confirmed URL" in out
    assert "rm -rf data && bash reproduce.sh" in out
    # CHECKSUMS guidance for graders' verification.
    assert "sha256sum" in out
    # WHY THIS MATTERS — explain the cost of skipping dataset download,
    # paper-agnostically (no per-paper dogfood names/scores).
    assert "WHY THIS MATTERS" in out
    assert "SC41406" not in out  # no paper-specific leak in dataset block
    assert "Result Analysis" in out  # rubric impact named


def test_paper_kind_addendum_lists_required_libraries():
    """When the classifier returns libraries, the addendum must surface a
    STEP 1.4 'Required libraries' block (name + acquisition channel) and
    tell the agent to install ALL deps inside reproduce.sh for
    from-scratch reproduction."""
    out = B._format_paper_kind_addendum(
        native="cpp+cuda", rationale="GPU compressor", secondary=[],
        env={"has_module": True, "has_apt": False, "has_sudo": False},
        libraries=[
            {"name": "CUDA Toolkit", "how": "module"},
            {"name": "zstd", "how": "source-build"},
            {"name": "HDF5", "how": "module"},
        ],
    )
    assert "STEP 1.4" in out
    assert "Required libraries" in out
    assert "CUDA Toolkit" in out and "zstd" in out and "HDF5" in out
    assert "via module" in out and "via source-build" in out
    assert "from scratch" in out  # install all deps in reproduce.sh


def test_paper_kind_addendum_omits_library_block_when_empty():
    """Theoretical / pure-synthetic papers: no libraries → no STEP 1.4."""
    out = B._format_paper_kind_addendum(
        native="python+numpy", rationale="theory", secondary=[],
        env={"has_module": False, "has_apt": True, "has_sudo": True},
        libraries=[],
    )
    assert "STEP 1.4" not in out
    assert "Required libraries" not in out


def test_reproduce_sh_from_scratch_and_pip_user_caveat():
    """STEP 3 must require from-scratch self-containment (install ALL deps
    in reproduce.sh) and warn against `pip install --user` (fails in a
    venv — recurring v3-A5/A6/A9 failure)."""
    out = B._format_paper_kind_addendum(
        native="cpp+cuda", rationale="x", secondary=[],
        env={"has_module": True, "has_apt": False, "has_sudo": False},
    )
    assert "FROM-SCRATCH" in out or "from-scratch" in out.lower()
    assert "do NOT use `--user`" in out
    assert "env -i" in out  # clean-room verification recipe


def test_cautionary_note_soft_for_python_native_stack():
    """Generality: for a python+* paper, Python IS correct — the
    cautionary note must NOT issue the imperative 'you MUST implement in
    <native>' nor neutralise the toy example (nothing to override)."""
    out = B._format_paper_kind_addendum(
        native="python+pytorch",
        rationale="deep learning training paper",
        secondary=[],
        env={"has_module": False, "has_apt": True, "has_sudo": True},
    )
    assert "Cautionary note" in out
    assert "You MUST implement" not in out  # no imperative for python paper
    assert "IGNORE THE LANGUAGE OF THE VENDOR TOY EXAMPLE" not in out


def test_paper_kind_addendum_omits_dataset_block_when_no_datasets():
    """Theoretical-only / synthetic papers: empty datasets list →
    no STEP 1.5 block, no false alarms about missing data."""
    out = B._format_paper_kind_addendum(
        native="python+numpy",
        rationale="numerical experiments on synthetic fields",
        secondary=[],
        env={"has_module": False, "has_apt": True, "has_sudo": True},
        datasets=[],
    )
    assert "STEP 1.5" not in out
    assert "WHY THIS MATTERS" not in out  # only in the dataset block


def test_classifier_paper_window_reaches_evaluation_section():
    """Regression for the empty-datasets bug (v3-A6): the classifier is
    fed a truncated prefix of the paper. Dataset names live in the
    Evaluation section — e.g. SC41406's six datasets (JHTDB / Miranda /
    Nyx / QMCPACK / RTM / S3D) first appear at char ~34000-48000, well
    past the old 16000-char window — so the classifier returned an empty
    datasets list and STEP 1.5 never fired. The window must reach far
    enough into the paper to cover a typical evaluation section.
    """
    assert B._CLASSIFIER_PAPER_MAX_CHARS >= 50000, (
        "classifier paper window must reach the evaluation section where "
        "datasets are introduced (SC41406 datasets start at char ~34000)"
    )


def test_paper_kind_addendum_carries_agent_only_marker():
    """The addendum is generated for the Stage 1 agent (via
    paper/addendum.md) and MUST NOT be reused as Stage 3
    judge_addendum (would bias grading with past-dogfood scores +
    runbook nudges). The bridge-generated addendum always carries
    a marker so callers can defensively reject it from the judge
    path."""
    out = B._format_paper_kind_addendum(
        native="cpp+cuda",
        rationale="GPU paper",
        secondary=[],
        env={"has_module": True, "has_apt": False, "has_sudo": False},
    )
    assert B._ARI_AGENT_ONLY_MARKER in out
    # The marker must be in the very first lines so file readers /
    # diff tools surface it immediately.
    head = "\n".join(out.split("\n")[:5])
    assert B._ARI_AGENT_ONLY_MARKER in head


def test_paper_kind_addendum_format_unknown_omits_skeleton():
    """When classifier returns unknown, the build skeleton SECTION
    must be omitted (no `_REPRODUCE_SH_SHAPES["unknown"]` entry to
    inject). Compiler names may still appear in the runbook STEP 1
    "BUILD_TOOL" example list — that's pedagogical, not a CUDA skeleton.
    """
    out = B._format_paper_kind_addendum(
        native="unknown",
        rationale="purely theoretical paper, no implementation language",
        secondary=[],
        env={"has_module": False, "has_apt": False, "has_sudo": False},
    )
    assert "native_stack: **unknown**" in out
    # No language-specific BUILD SKELETON section.
    assert "Recommended `reproduce.sh` skeleton" not in out
    # No skeleton-specific build commands (these only appear via the
    # _REPRODUCE_SH_SHAPES dict, which has no "unknown" entry).
    assert "nvcc -std=c++17" not in out  # the skeleton CUDA build line
    assert "mpic++ -O3" not in out         # the skeleton MPI build line
    assert "cargo build --release" not in out  # the skeleton Rust build line
    # Cautionary is still useful even for unknown — the agent still
    # benefits from learning past dogfood failure modes.
    assert "Cautionary" in out


def test_paper_kind_addendum_covers_major_stacks():
    """Each major HPC / ML / systems stack must have a reproduce.sh
    skeleton template so the classifier output is actionable."""
    for stack in (
        "cpp+cuda", "cpp+mpi", "cpp+openmp",
        "fortran+mpi", "fortran+openmp",
        "python+pytorch", "python+jax", "python+tensorflow", "python+numpy",
        "rust", "go", "c", "cpp",
    ):
        assert stack in B._REPRODUCE_SH_SHAPES, f"missing skeleton for {stack!r}"


def test_reproduce_shape_skeletons_have_no_hardcoded_module_names():
    """Regression guard for the cluster-agnostic invariant: skeleton
    templates must NOT name specific cluster modules (nvhpc, openmpi,
    mpich, fftw, gcc, etc) because those vary across HPC sites. The
    activation line is rendered separately by _render_activation_block
    and uses a `<NAME>` placeholder."""
    for stack, skeleton in B._REPRODUCE_SH_SHAPES.items():
        for bad_name in ("nvhpc", "module load nvhpc", "module load openmpi",
                         "module load mpich", "module load fftw",
                         "module load gcc"):
            assert bad_name not in skeleton, (
                f"skeleton for {stack!r} contains hardcoded module name "
                f"{bad_name!r}; use placeholder instead"
            )


def test_render_activation_block_module_env():
    """On Lmod-enabled hosts the activation block must instruct
    `module load <NAME>` (placeholder, never a specific module name)
    and reference the env-truth catalog as the discovery source."""
    block = B._render_activation_block({"has_module": True})
    assert "module load <NAME>" in block
    assert "module avail" in block
    # No cluster-specific names allowed.
    for bad in ("nvhpc", "openmpi", "mpich", "fftw", "gcc/"):
        assert bad not in block, f"cluster-specific name {bad!r} leaked"


def test_render_activation_block_apt_env():
    """On Docker/root hosts with apt-get, the activation block must
    instruct `apt-get install -y <PACKAGE>` (placeholder)."""
    block = B._render_activation_block({
        "has_module": False, "has_apt": True, "has_sudo": True,
    })
    assert "apt-get install -y <PACKAGE>" in block
    assert "apt search" in block


def test_probe_module_avail_returns_string_or_empty():
    """Probe must return either a non-empty catalog string or empty
    (never raise). Hosts without module return empty so the caller
    skips the section."""
    out = B._probe_module_avail()
    assert isinstance(out, str)


def test_probe_module_avail_silences_spider_unsupported_marker():
    """Pre-Lmod Environment Modules returns
    ``ERROR: Invalid command 'spider'`` which would otherwise leak
    into the agent prompt. Verify the marker is filtered: if probe
    returns content, it must NOT contain the error string."""
    out = B._probe_module_avail()
    if out:
        assert "Invalid command 'spider'" not in out, (
            "spider-unsupported error leaked into probe output"
        )
        assert "Unrecognized subcommand 'spider'" not in out


def test_parse_module_names_keeps_namespaced_skips_builtins():
    """Only namespaced (``ns/name``) entries are MODULEPATH-switch
    candidates; path headers, separators and bare builtins are dropped."""
    avail = (
        "------------------------ /usr/share/Modules/modulefiles ------------------------\n"
        "dot  module-git  module-info  modules  null  use.own\n"
        "------------------------- /cloud_opt/misc/modulefiles --------------------------\n"
        "system/a100  system/ai-l40s <L>  system/qc-a100  mpi/mpich-x86_64\n"
    )
    names = B._parse_module_names(avail)
    assert "system/ai-l40s" in names  # <L> marker stripped
    assert "system/a100" in names
    assert "mpi/mpich-x86_64" in names
    assert "dot" not in names and "null" not in names  # builtins skipped
    assert all("/" in n for n in names)


def test_expand_modulepath_tier2_reveals_hidden_modules_read_only():
    """Tcl 2-tier breakthrough: `module show <entry>` exposes the
    MODULEPATH it would prepend; `module avail <dir>` lists tier-2.
    The expansion must use ONLY `module show` / `module avail` — never
    `module load` (read-only philosophy)."""
    avail = (
        "---- /cloud_opt/misc/modulefiles ----\n"
        "system/ai-l40s\n"
    )
    calls: list[str] = []

    def fake_run(cmd: str) -> str:
        calls.append(cmd)
        if cmd.startswith("module show system/ai-l40s"):
            return (
                "/cloud_opt/misc/modulefiles/system/ai-l40s:\n"
                "conflict\tsystem\n"
                "prepend-path\tMODULEPATH /opt/nvidia/hpc_sdk/modulefiles\n"
            )
        # Enumeration overrides MODULEPATH (read-only) rather than passing
        # the dir as a filter arg.
        if "MODULEPATH=/opt/nvidia/hpc_sdk/modulefiles" in cmd and "module avail" in cmd:
            return (
                "---- /opt/nvidia/hpc_sdk/modulefiles ----\n"
                "nvhpc/25.7  nvhpc-byo-compiler/25.7\n"
            )
        return ""

    out = B._expand_modulepath_tier2(fake_run, avail)
    assert "nvhpc/25.7" in out  # tier-2 module surfaced
    assert "module load system/ai-l40s" in out  # tells agent the entry
    # Read-only invariant: NO `module load` was ever issued.
    assert not any("module load" in c for c in calls), \
        "tier-2 expansion must be read-only (no module load)"


def test_expand_modulepath_tier2_shared_dir_lists_all_entries_with_conflict_note():
    """Regression for v3-A7 failure: a tier-2 dir (NVIDIA HPC SDK) is
    shared by several `system/<gpu>` entries. Attributing it to a single
    arbitrary entry misled the agent into loading multiple conflicting
    entries (which unloaded everything). The output must list ALL entries
    that reach the shared dir AND warn they are mutually exclusive."""
    avail = "---- /cloud_opt/misc/modulefiles ----\nsystem/a100  system/ai-l40s\n"

    def fake_run(cmd: str) -> str:
        # Both entries prepend the SAME shared hpc_sdk MODULEPATH.
        if cmd.startswith("module show system/a100") or cmd.startswith("module show system/ai-l40s"):
            return "x:\nprepend-path\tMODULEPATH /opt/nvidia/hpc_sdk/modulefiles\n"
        if "MODULEPATH=/opt/nvidia/hpc_sdk/modulefiles" in cmd and "module avail" in cmd:
            return "---- /opt/nvidia/hpc_sdk/modulefiles ----\nnvhpc/25.7\n"
        return ""

    out = B._expand_modulepath_tier2(fake_run, avail)
    assert "nvhpc/25.7" in out
    # Both reaching entries listed, not just the first.
    assert "system/a100" in out and "system/ai-l40s" in out
    # Mutual-exclusion guidance present so the agent loads only ONE.
    assert "MUTUALLY EXCLUSIVE" in out or "load exactly\n  ONE" in out or "load exactly ONE" in out
    # The shared dir is enumerated only once (not duplicated per entry).
    assert out.count("/opt/nvidia/hpc_sdk/modulefiles ----") == 1


def test_expand_modulepath_tier2_matches_module_use_and_append_styles():
    """Portability across Tcl clusters: entry modules switch MODULEPATH
    via `prepend-path`, `append-path`, OR `module use` — all three must
    be recognised, not just R-CCS's `prepend-path` style."""
    for directive, dir_ in (
        ("append-path\tMODULEPATH /opt/compilers/modulefiles", "/opt/compilers/modulefiles"),
        ("module use --append /opt/compilers/modulefiles", "/opt/compilers/modulefiles"),
        ("module use /opt/compilers/modulefiles", "/opt/compilers/modulefiles"),
    ):
        def fake_run(cmd, _d=directive, _dir=dir_):
            if cmd.startswith("module show"):
                return f"/x/compiler/gcc:\n{_d}\n"
            if f"MODULEPATH={_dir}" in cmd and "module avail" in cmd:
                return f"---- {_dir} ----\ngcc/13.2  gcc/12.3\n"
            return ""
        out = B._expand_modulepath_tier2(fake_run, "---- /x ----\ncompiler/gcc\n")
        assert "gcc/13.2" in out, f"directive not recognised: {directive!r}"


def test_expand_modulepath_tier2_empty_when_flat():
    """Flat clusters / laptops: entries reveal no MODULEPATH prepend, or
    the revealed dir is empty (off-node) → expansion returns ""."""
    avail = "---- /usr/share/modulefiles ----\nmpi/mpich-x86_64\n"

    def fake_run(cmd: str) -> str:
        if cmd.startswith("module show"):
            return "mpi/mpich-x86_64:\nprepend-path\tPATH /usr/lib64/mpich/bin\n"
        return ""  # no MODULEPATH prepend, nothing to expand

    assert B._expand_modulepath_tier2(fake_run, avail) == ""


def test_render_activation_block_neither_falls_back_to_manual():
    """On bare-metal dev hosts the activation block must fall back to
    `conda activate` / manual install / SDK setup — no module / no apt."""
    block = B._render_activation_block({
        "has_module": False, "has_apt": False, "has_sudo": False,
    })
    assert "conda activate" in block or "manual" in block.lower()
    assert "module load" not in block
    assert "apt-get install" not in block




def test_env_patch_is_installed_on_vendor_get_instructions():
    """The vendor get_instructions symbol must carry the consolidated
    rewrite wrapper at bridge import (single ._ari_instr_rewritten sentinel;
    env-truth + blacklist-lift in one wrapper)."""
    from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    assert getattr(_v_utils.get_instructions, "_ari_instr_rewritten", False) is True, (
        "vendor get_instructions not patched; agent will see Docker-style "
        "root-access claim even on SLURM HPC clusters"
    )


def test_resolve_container_image_alias():
    """``pb-env`` / ``pb-reproducer`` short aliases must resolve to the
    canonical ``image:latest`` tags that ``scripts/build_pb_images.sh``
    produces. Anything else (URIs, paths, arbitrary tags, empty) must
    pass through verbatim — operators rely on supplying their own
    images for non-vendor workflows.
    """
    assert B._resolve_container_image_alias("pb-env") == "pb-env:latest"
    assert B._resolve_container_image_alias("pb-reproducer") == "pb-reproducer:latest"
    assert B._resolve_container_image_alias("") == ""
    assert B._resolve_container_image_alias("ubuntu:24.04") == "ubuntu:24.04"
    assert B._resolve_container_image_alias("docker://nvcr.io/nvidia/pytorch:24.05-py3") == \
        "docker://nvcr.io/nvidia/pytorch:24.05-py3"
    assert B._resolve_container_image_alias("/scratch/img.sif") == "/scratch/img.sif"
    # Whitespace tolerance (operators pasting wizard input):
    assert B._resolve_container_image_alias("  pb-env  ") == "pb-env:latest"


def test_rollout_submission_signature_includes_blacklist_urls():
    """(g) regression: bridge surface exposes blacklist_urls so the
    wizard / CLI can forbid the agent from accessing the paper's own
    codebase URL during rollout.
    """
    import inspect
    sig = inspect.signature(B.rollout_submission)
    assert "blacklist_urls" in sig.parameters
    assert sig.parameters["blacklist_urls"].default is None


def test_blacklist_urls_prepend_into_paper_md_smoke(tmp_path, monkeypatch):
    """Smoke that the blacklist enforcement path:
      (a) prepends a FORBIDDEN URLS section into the agent's paper_md.
      (b) exports ARI_BLACKLIST_URLS as env.

    We mock run_replicator_agent to capture the values it received.
    """
    import asyncio
    captured: dict = {}

    async def fake_run_replicator_agent(**kwargs):
        # Snapshot the values the bridge handed off.
        captured["env"] = dict(kwargs.get("env") or {})
        captured["paper_md_path"] = kwargs.get("paper_md_path")
        return {"populated": False, "warnings": [], "files": []}

    # _replicator_agent is imported lazily inside rollout_submission.
    import importlib, sys as _sys
    fake_mod = type(_sys)("_replicator_agent")
    fake_mod.run_replicator_agent = fake_run_replicator_agent  # type: ignore
    monkeypatch.setitem(_sys.modules, "_replicator_agent", fake_mod)

    # Stub out the OpenAI Responses completer + LiteLLM completer so
    # the bridge does not try to import them for a non-OpenAI fake
    # model.
    asyncio.run(B.rollout_submission(
        paper_md="hello paper body",
        work_dir=tmp_path / "wd",
        agent_model="anthropic/test",  # routes through LiteLLM branch
        sandbox_kind="local",
        blacklist_urls=[
            "https://github.com/author/original-repo",
            "https://huggingface.co/author/original-model",
        ],
    ))

    # Env carries newline-joined entries
    env = captured.get("env") or {}
    assert "ARI_BLACKLIST_URLS" in env, env
    assert "github.com/author/original-repo" in env["ARI_BLACKLIST_URLS"]
    assert "huggingface.co/author/original-model" in env["ARI_BLACKLIST_URLS"]

    # paper_md on disk has the FORBIDDEN URLS prelude
    pm = Path(captured["paper_md_path"]).read_text()
    assert "# FORBIDDEN URLS" in pm
    assert "github.com/author/original-repo" in pm
    assert pm.rstrip().endswith("hello paper body"), \
        "original paper body must follow the prelude"


def test_judge_submission_rejects_code_only_with_paper_audit_mode():
    """code_only (grade a Stage 1 submission against Code Dev subtree)
    and paper_audit_mode (grade the paper itself for describability)
    are conceptually orthogonal targets. Combining them would feed an
    executed-or-not submission to a judge asking 'is the paper specific
    enough?' — meaningless. The bridge MUST refuse loudly.
    """
    import asyncio, uuid
    rubric_dict = {
        "id": str(uuid.uuid4()),
        "requirements": "root",
        "weight": 1,
        "task_category": "Code Development",
    }
    root = B.task_node_from_dict(rubric_dict)
    with pytest.raises(ValueError, match="mutually exclusive"):
        asyncio.run(B.judge_submission(
            paper_md="x", rubric=root, submission_dir=Path("/tmp"),
            judge_model="test/m",
            paper_audit_mode=True, code_only=True,
        ))


# ─── dynamic computer-side env detection (node→GPU→module auto-probe) ───────

class _FakeComputer:
    """Minimal ComputerInterface stand-in: maps shell commands to canned
    (exit_code, output) so the async probe pipeline can be tested without a
    real cluster."""
    def __init__(self, responses):
        self._responses = responses  # list of (substr, exit_code, output)

    async def send_shell_command(self, cmd):
        # Pick the most specific (longest) matching substring so that
        # e.g. "sudo -n true" wins over a bare "true" liveness probe.
        best = None
        for substr, rc, out in self._responses:
            if substr in cmd and (best is None or len(substr) > len(best[0])):
                best = (substr, rc, out)
        if best is not None:
            return _FakeExecResult(best[1], best[2])
        return _FakeExecResult(127, "")


class _FakeExecResult:
    def __init__(self, rc, out):
        self.exit_code = rc
        self._out = out

    @property
    def unicode_output_best_effort(self):
        return self._out


def test_probe_gpu_stage1_nvidia_smi_with_compute_cap():
    """Stage 1: nvidia-smi yields name + compute_cap → sm for -arch."""
    import asyncio
    comp = _FakeComputer([
        ("nvidia-smi --query-gpu=name,compute_cap", 0, "NVIDIA L40S, 8.9, 1, 46068 MiB\n"),
    ])
    g = asyncio.run(B._probe_gpu_on_computer(comp))
    assert g["present"] and g["name"] == "NVIDIA L40S"
    assert g["compute_cap"] == "8.9" and g["sm"] == "89"
    assert g["count"] == "1"


def test_probe_gpu_fallback_when_nvidia_smi_absent():
    """Regression: nvidia-smi missing must NOT be read as 'no GPU' (that
    suppresses CUDA). Device-file fallback must report present."""
    import asyncio
    comp = _FakeComputer([
        ("nvidia-smi", 127, ""),                  # not on PATH
        ("ls /dev/nvidia0", 0, "PRESENT\n"),      # but device exists
    ])
    g = asyncio.run(B._probe_gpu_on_computer(comp))
    assert g["present"] is True
    assert "/dev/nvidia" in g["via"]  # surfaced via fallback, not false-negative


def test_probe_env_on_computer_sudo_password_required_is_not_available():
    """has_sudo must reflect USABILITY: `sudo -n true` failing (password
    required) → has_sudo False, even though the binary exists."""
    import asyncio
    comp = _FakeComputer([
        ("true", 0, ""),
        ("command -v apt-get", 127, ""),          # no apt
        ("sudo -n true", 1, "sudo: a password is required\n"),  # unusable
        ("command -v docker", 127, ""),           # no docker
        ("command -v module", 0, "HASMOD\nMP=/cloud_opt/x"),
        ("SLURM_JOB_ID", 0, "JID=123|PART=ai-l40s"),
        ("/.dockerenv", 1, ""),
        ("nvidia-smi --query-gpu=name,compute_cap", 0, "NVIDIA L40S, 8.9, 1, 46068 MiB\n"),
    ])
    env = asyncio.run(B._probe_env_on_computer(comp))
    assert env is not None
    assert env["has_sudo"] is False          # password-required → not usable
    assert env["has_apt"] is False
    assert env["kind"] == "slurm"
    assert env["has_module"] is True
    assert env["gpu"]["sm"] == "89"


def test_reconcile_gated_off_for_real_docker():
    """In a real Docker container (kind=docker) the vendor body is true →
    leave it untouched (vanilla PaperBench compatibility)."""
    body = ("copy your submission to a fresh Ubuntu 24.04 LTS Docker container "
            "and run `bash reproduce.sh` from the submission directory. The "
            "container will have access to an NVIDIA A10 GPU, with the NVIDIA "
            "container toolkit already installed.")
    env = {"kind": "docker", "has_docker": True, "gpu": {"present": True, "name": "A10"}}
    assert B._reconcile_vendor_env_claims(body, env) == body



def test_expand_modulepath_tier2_scopes_to_allocated_partition():
    """Now that the partition is auto-detected, the tier-2 expansion must
    scope to the allocated entry (system/<partition>) instead of dumping
    every GPU's stack (A100/H100/MI250/...) — that was prompt noise."""
    avail = ("---- /cloud_opt/misc/modulefiles ----\n"
             "system/a100  system/ai-l40s  system/qc-mi250  system/qc-gh200\n")

    def fake_run(cmd):
        if cmd.startswith("module show system/ai-l40s"):
            return "x:\nprepend-path\tMODULEPATH /opt/nvidia/hpc_sdk/modulefiles\n"
        if cmd.startswith("module show "):
            # other entries also prepend a (different) dir — should be skipped
            return "x:\nprepend-path\tMODULEPATH /cloud_opt/modulefiles/other\n"
        if "MODULEPATH=/opt/nvidia/hpc_sdk/modulefiles" in cmd and "module avail" in cmd:
            return "---- /opt/nvidia/hpc_sdk/modulefiles ----\nnvhpc/25.7\n"
        if "MODULEPATH=/cloud_opt/modulefiles/other" in cmd and "module avail" in cmd:
            return "---- other ----\nshould_not_appear/1.0\n"
        return ""

    out = B._expand_modulepath_tier2(fake_run, avail, partition="ai-l40s")
    assert "nvhpc/25.7" in out                     # the allocated entry's stack
    assert "system/ai-l40s" in out
    assert "should_not_appear" not in out          # other partitions skipped
    assert "system/a100" not in out and "system/qc-mi250" not in out


def test_expand_modulepath_tier2_falls_back_when_partition_unmatched():
    """If no entry name matches the partition (naming mismatch), keep all
    entries rather than silently dropping everything."""
    avail = "---- x ----\nsystem/a100\n"

    def fake_run(cmd):
        if cmd.startswith("module show system/a100"):
            return "x:\nprepend-path\tMODULEPATH /opt/nvidia/hpc_sdk/modulefiles\n"
        if "MODULEPATH=/opt/nvidia/hpc_sdk/modulefiles" in cmd and "module avail" in cmd:
            return "---- d ----\nnvhpc/25.7\n"
        return ""

    out = B._expand_modulepath_tier2(fake_run, avail, partition="some-unknown-part")
    assert "nvhpc/25.7" in out  # fallback: not dropped
