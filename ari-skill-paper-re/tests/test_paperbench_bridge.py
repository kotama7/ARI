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
    for k in ("kind", "has_apt", "has_sudo", "has_module", "nvcc_path",
              "slurm_partition", "module_path"):
        assert k in env, f"missing key {k} in detected env"
    assert env["kind"] in ("slurm", "docker", "local"), env["kind"]


def test_env_block_for_docker_keeps_vendor_line():
    """In a Docker env vendor's 'You have root access in your environment.'
    line is correct — patch must NOT alter the line so we don't waste
    tokens telling the agent things it already knows."""
    env = {
        "kind": "docker",
        "has_apt": True, "has_sudo": True, "has_module": False,
        "nvcc_path": "/usr/local/cuda/bin/nvcc",
        "slurm_partition": None, "module_path": None,
    }
    assert B._build_truthful_env_block(env) == B._VENDOR_ROOT_ACCESS_LINE


def test_env_block_for_slurm_describes_module_load_path():
    """SLURM HPC cluster: agent must learn that root access is NOT
    available, module system IS available, and nvcc lives behind a
    `module load nvhpc` gate. Without this the agent blindly tries
    `apt-get install nvidia-cuda-toolkit` and gives up."""
    env = {
        "kind": "slurm",
        "has_apt": False, "has_sudo": False, "has_module": True,
        "nvcc_path": "/opt/nvidia/hpc_sdk/Linux_x86_64/25.7/compilers/bin/nvcc",
        "slurm_partition": "ai-l40s",
        "module_path": "/cloud_opt/modulefiles/ai-l40s:...",
    }
    block = B._build_truthful_env_block(env)
    assert "NO root access" in block
    assert "SLURM" in block or "HPC" in block
    assert "ai-l40s" in block  # partition surfaced
    assert "module load nvhpc" in block  # the discovery instruction
    assert "module avail" in block  # the exploration instruction
    assert "/opt/nvidia/hpc_sdk" in block  # exact nvcc path
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
    # Language-choice counter-priming. The vendor instructions.txt
    # uses a Python (count.py / strawberry) example which strongly
    # primes the agent toward Python regardless of the paper. The
    # env block must explicitly tell the agent the example is
    # illustration only and to MATCH THE PAPER'S NATIVE LANGUAGE.
    # The block must enumerate the major HPC / ML / systems / web
    # language tracks so the agent has a concrete reference.
    assert "Language choice" in block
    assert "illustration ONLY" in block
    assert "native language" in block
    # Specific stacks the env block must enumerate so the agent can
    # match its choice to the paper's domain.
    for lang_or_tool in (
        "C++/CUDA", "HIP", "SYCL",       # GPU compute
        "OpenMP", "MPI",                  # CPU parallel
        "Fortran",                        # legacy numerical
        "PyTorch", "JAX",                 # ML frameworks
        "Rust", "Go",                     # systems
    ):
        assert lang_or_tool in block, f"language addendum missing: {lang_or_tool!r}"


def test_env_block_for_local_host_without_cuda():
    """Bare-metal local with no module system and no nvcc: agent must
    learn nvcc is not detected so it doesn't waste cycles searching."""
    env = {
        "kind": "local",
        "has_apt": True, "has_sudo": False, "has_module": False,
        "nvcc_path": None, "slurm_partition": None, "module_path": None,
    }
    block = B._build_truthful_env_block(env)
    assert "apt-get available" in block
    assert "NOT detected" in block  # nvcc honesty
    # Even on bare-metal local hosts the network + Phase 2 isolation
    # notes apply — these are not SLURM-specific.
    assert "Network" in block
    assert "FRESH shell" in block
    # Language counter-priming applies on local hosts too — the LLM
    # bias toward Python isn't kind-dependent.
    assert "Language choice" in block
    assert "native language" in block
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
    """The vendor get_instructions symbol must have the blacklist-lift
    sentinel set at bridge import. Stacks on top of env-assumption
    patch — both substitutions must fire per call."""
    from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    fn = _v_utils.get_instructions
    assert getattr(fn, "_ari_blacklist_lifted", False) is True, (
        "blacklist lift patch not installed; agent will see vendor's "
        "cheating claim and self-police away from paper's codebase even "
        "though ARI's reproduction goal does not require it"
    )
    # Both env-assumption and blacklist lift patches must coexist:
    # the latter wraps the former.
    assert getattr(fn, "_ari_env_patched", False) is True, (
        "env-assumption patch sentinel lost when blacklist lift was "
        "installed; both must be visible on the final wrapper"
    )


def test_env_patch_is_installed_on_vendor_get_instructions():
    """The vendor get_instructions symbol must be patched at bridge
    import. Idempotent: importing the bridge twice leaves only one
    patch layer (verified by the ._ari_env_patched sentinel)."""
    from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    assert getattr(_v_utils.get_instructions, "_ari_env_patched", False) is True, (
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
