"""PaperBench SimpleJudge bridge.

This module re-exports the PaperBench upstream symbols used by
``grade_with_simplejudge`` and provides thin adapters for the calling
convention used inside ARI:

  - ``TaskNode``                 — paperbench.rubric.tasks.TaskNode
  - ``GradedTaskNode``           — paperbench.judge.graded_task_node.GradedTaskNode
  - ``SimpleJudge``              — paperbench.judge.simple.SimpleJudge
  - ``task_node_from_dict``      — dict → upstream TaskNode
  - ``aggregate_graded_tree``    — weighted tree score envelope
  - ``average_graded_runs``      — n-run mean over GradedTaskNode trees
  - ``rollout_submission``       — PaperBench Stage 1 (agent rollout that
                                    writes reproduce.sh); thin wrapper over
                                    :func:`_replicator_agent.run_replicator_agent`.
  - ``reproduce_submission``     — PaperBench Stage 2 (execute reproduce.sh
                                    in the chosen sandbox, capture
                                    reproduce.log); thin wrapper over
                                    :func:`server.run_reproduce`.
  - ``judge_submission``         — PaperBench Stage 3 (SimpleJudge over the
                                    executed submission).

The three Stage adapters share the same ``(paper_md, work_dir or
submission_dir, model, ...)`` calling style so a caller (e.g.
``scripts/sc_paper_dogfood.py`` or ``ari-core``'s viz worker) can
sequence ``rollout_submission → reproduce_submission → judge_submission``
without translating between independent argument vocabularies.

Resolution of the upstream package follows:
  1. ``ARI_PAPERBENCH_PATH`` (explicit override).
  2. The vendored git submodule at vendor/paperbench/project/paperbench.
     The submodule URL is github.com/openai/preparedness (a monorepo) but
     it is mounted at vendor/paperbench so the layout matches rubric.md §8.
  3. A pip-installed ``paperbench`` package on the standard sys.path.

The upstream depends on ``openai``, ``preparedness_turn_completer``,
``nanoeval``, ``alcatraz``, ``structlog``, ``tiktoken``, ``drain3``,
``blobfile``, etc. Run ``scripts/setup/install_paperbench.sh`` (invoked
automatically by ``setup.sh``) to install them. Without these packages
this module fails to import — there is **no local fallback**.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── locate upstream PaperBench ───────────────────────────────────────────
# Path injection happens in :mod:`_vendor_path` so that the agent-mode
# Replicator and the SimpleJudge bridge load from the same vendor tree.

import _vendor_path  # noqa: F401  (side-effect: sys.path injection)


# ─── re-export upstream symbols (no fallback) ────────────────────────────

from paperbench.rubric.tasks import TaskNode  # noqa: E402  type: ignore
from paperbench.judge.graded_task_node import GradedTaskNode  # noqa: E402  type: ignore
from paperbench.judge.simple import SimpleJudge  # noqa: E402  type: ignore

log.info("paperbench upstream loaded (sys.path injected by _vendor_path)")


# ─── vendor patch: orphan tool_call filter (Responses API) ────────────────
#
# Vendor ``BasicAgentSolver._execute_agent`` (solver.py:171-180) appends the
# assistant message containing N tool_calls to the conversation FIRST and
# THEN iterates each tool_call to invoke it + append its output. When one
# of the per-call ``handle_tool_call`` invocations raises (sandbox error,
# OOM in the tool subprocess, file-system race, etc.), the loop crashes
# after assistant.tool_calls is committed but before all corresponding
# ``role=tool`` outputs are appended. The next completer call replays the
# conversation verbatim, and the OpenAI Responses API rejects it with
# ``BadRequestError: No tool output found for function call call_XXX``
# (vendor converters.py:171-176 passes assistant.tool_calls through
# unchanged).
#
# Reproduced twice on the SC41406 BasicAgent dogfood
# (sandbox=local then sandbox=local-inside-ai-l40s); fixing at the
# converter layer is the minimum-blast-radius patch because every
# downstream caller (vendor solver, future ARI orchestrators) benefits
# without per-call defensive code.
#
# We do not edit vendor sources (the
# ``zero vendor changes`` invariant from the v0.7.2 docs); instead, we
# monkey-patch the converter symbol at module load. The original is
# stashed for callers who explicitly opt out via
# ``ARI_PB_DISABLE_ORPHAN_FILTER=1``.

_ORPHAN_PATCH_DISABLE_ENV = "ARI_PB_DISABLE_ORPHAN_FILTER"


def _filter_orphan_tool_calls(conversation: list) -> list:
    """Drop assistant tool_calls whose call_id has no matching role=tool
    output anywhere in the conversation.

    Preserves the assistant message itself if it has textual content or
    surviving tool_calls. Empty assistant messages (no content, no
    surviving calls) are dropped to keep the API input compact.
    """
    matched_ids: set[str] = set()
    for m in conversation:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool":
            tcid = m.get("tool_call_id")
            if tcid:
                matched_ids.add(str(tcid))

    out: list = []
    n_dropped_calls = 0
    n_dropped_msgs = 0
    for m in conversation:
        if not isinstance(m, dict):
            out.append(m)
            continue
        if m.get("role") == "assistant" and "tool_calls" in m and m["tool_calls"]:
            kept = [tc for tc in m["tool_calls"] if str(tc.get("id", "")) in matched_ids]
            n_dropped_calls += len(m["tool_calls"]) - len(kept)
            if kept:
                new_m = dict(m)
                new_m["tool_calls"] = kept
                out.append(new_m)
            else:
                # No surviving tool_calls; keep the assistant message
                # iff it still has text content.
                if m.get("content"):
                    new_m = dict(m)
                    new_m.pop("tool_calls", None)
                    out.append(new_m)
                else:
                    n_dropped_msgs += 1
        else:
            out.append(m)
    if n_dropped_calls or n_dropped_msgs:
        log.warning(
            "vendor patch: filtered %d orphan tool_call(s) and %d empty "
            "assistant message(s) from Responses API input "
            "(BasicAgentSolver loop crashed mid-tool-exec; outputs missing)",
            n_dropped_calls, n_dropped_msgs,
        )
    return out


def _install_orphan_filter_patch() -> None:
    """Monkey-patch vendor ``convert_conversation_to_response_input`` to
    pre-filter orphan tool_calls before the request hits the OpenAI
    Responses API. Idempotent. Skipped when ``ARI_PB_DISABLE_ORPHAN_FILTER=1``.
    """
    if os.environ.get(_ORPHAN_PATCH_DISABLE_ENV, "") == "1":
        log.info("vendor patch: orphan-tool-call filter disabled via %s=1",
                 _ORPHAN_PATCH_DISABLE_ENV)
        return
    try:
        from preparedness_turn_completer.oai_responses_turn_completer import (  # type: ignore
            converters as _v_conv,
            completer as _v_comp,
        )
    except Exception as e:
        log.warning("vendor patch: cannot locate vendor converter module: %s; "
                    "Responses API path is unprotected from orphan tool_calls", e)
        return
    if getattr(_v_conv.convert_conversation_to_response_input, "_ari_orphan_patched", False):
        return
    original = _v_conv.convert_conversation_to_response_input

    def patched(conversation):  # noqa: ANN001
        return original(_filter_orphan_tool_calls(list(conversation)))

    patched._ari_orphan_patched = True  # type: ignore[attr-defined]
    _v_conv.convert_conversation_to_response_input = patched
    # The completer module imports the symbol by name at import time, so
    # patch that binding too.
    if hasattr(_v_comp, "convert_conversation_to_response_input"):
        _v_comp.convert_conversation_to_response_input = patched
    log.info("vendor patch: installed orphan-tool-call filter on "
             "Responses API converter")


_install_orphan_filter_patch()


# ─── vendor patch: env-truth ADDITIONAL NOTES substitution ────────────────
#
# Vendor's BasicAgent system prompt
# (``solvers/basicagent/prompts/templates.py:additional_notes_template``)
# hardcodes "- You have root access in your environment." This is correct
# for the upstream PaperBench eval environment (an Ubuntu Docker
# container with sudo + apt-get + a baked-in CUDA toolkit), but is a LIE
# on a shared HPC cluster (SLURM-dispatched compute node where the user
# has no root and the CUDA toolchain is gated behind an Lmod ``module
# load`` command).
#
# On the SC41406 dogfood we observed the cost of this lie: the agent
# faithfully copied the template's "apt-get install" pattern into its
# reproduce.sh, hit ``apt-get: command not found`` on first invocation,
# pivoted to "pip-only CPU" without ever probing ``module avail`` or
# ``which nvcc`` — leaving the CUDA toolchain undiscovered for the full
# 30-minute rollout and forfeiting every GPU-related rubric leaf.
#
# Fix: monkey-patch vendor ``get_instructions`` at bridge import. The
# patched version detects the actual env (SLURM vs Docker vs local
# host) plus the actual availability of ``apt-get``, ``nvcc``,
# ``module``, ``sudo`` and substitutes a TRUTHFUL ADDITIONAL NOTES
# section instead of vendor's hardcoded Docker-style notes. No vendor
# source edits (preserves the ``zero vendor changes`` invariant from
# v0.7.2 docs). Opt-out via ``ARI_PB_DISABLE_ENV_PATCH=1`` for callers
# who want the verbatim vendor template (e.g., when reproducing an
# upstream leaderboard result).

_ENV_PATCH_DISABLE_ENV = "ARI_PB_DISABLE_ENV_PATCH"
_VENDOR_ROOT_ACCESS_LINE = "- You have root access in your environment."


def _detect_runtime_env() -> dict:
    """Probe the actual runtime environment so the agent prompt can be
    rewritten with TRUTH instead of vendor's Docker assumption.

    Returns a dict with:
      - ``kind``: 'slurm' | 'docker' | 'local'
      - ``has_apt``: bool, ``apt-get`` on PATH
      - ``has_sudo``: bool, ``sudo`` on PATH (root access surrogate)
      - ``has_module``: bool, Lmod/environment-modules system is usable
      - ``module_path``: str or None, current MODULEPATH if module system present
      - ``nvcc_path``: str or None, ``nvcc`` location (probed via PATH + common
        HPC SDK install locations)
      - ``slurm_partition``: str or None, current SLURM partition if any
    """
    import shutil

    env_kind = "local"
    slurm_partition = os.environ.get("SLURM_JOB_PARTITION") or None
    if os.environ.get("SLURM_JOB_ID") or slurm_partition:
        env_kind = "slurm"
    elif Path("/.dockerenv").is_file():
        env_kind = "docker"
    else:
        try:
            cg = Path("/proc/1/cgroup")
            if cg.is_file() and "docker" in cg.read_text(errors="replace").lower():
                env_kind = "docker"
        except Exception:
            pass

    nvcc = shutil.which("nvcc")
    if not nvcc:
        for cand in (
            "/opt/nvidia/hpc_sdk/Linux_x86_64/25.7/compilers/bin/nvcc",
            "/opt/nvidia/hpc_sdk/Linux_x86_64/25.5/compilers/bin/nvcc",
            "/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/compilers/bin/nvcc",
            "/usr/local/cuda/bin/nvcc",
        ):
            if Path(cand).is_file():
                nvcc = cand
                break

    return {
        "kind": env_kind,
        "has_apt": shutil.which("apt-get") is not None,
        "has_sudo": shutil.which("sudo") is not None,
        "has_module": (
            shutil.which("module") is not None
            or bool(os.environ.get("MODULEPATH"))
        ),
        "module_path": os.environ.get("MODULEPATH") or None,
        "nvcc_path": nvcc,
        "slurm_partition": slurm_partition,
    }


def _build_truthful_env_block(env: dict) -> str:
    """Compose a replacement for vendor's ``- You have root access in your
    environment.`` line. Lists the ACTUAL state of the host so the
    agent doesn't have to guess via trial-and-error.
    """
    if env["kind"] == "docker":
        # Vendor's assumption is correct for Docker; keep the original line
        # so we don't waste tokens on info the agent already has.
        return _VENDOR_ROOT_ACCESS_LINE

    # Build a multi-line replacement for non-Docker envs.
    lines: list[str] = []
    parts_root: list[str] = []
    if env["has_sudo"]:
        parts_root.append("sudo available")
    if env["has_apt"]:
        parts_root.append("apt-get available")
    if not parts_root:
        parts_root.append("NO root access (no sudo, no apt-get)")
    lines.append(f"- Host privileges: {', '.join(parts_root)}.")

    if env["kind"] == "slurm":
        slurm_note = "SHARED HPC cluster (SLURM-dispatched compute node)"
        if env["slurm_partition"]:
            slurm_note += f"; current partition={env['slurm_partition']}"
        lines.append(f"- Environment: {slurm_note}. ")

    if env["has_module"]:
        lines.append(
            "- Module system: ENABLED. Discover available compilers and "
            "runtimes via `module avail`; load with `module load <name>`."
        )

    if env["nvcc_path"]:
        nvcc = env["nvcc_path"]
        if env["has_module"] and "/opt/nvidia/hpc_sdk" in nvcc:
            lines.append(
                f"- CUDA toolchain: nvcc available at {nvcc} AFTER "
                f"`module load nvhpc` (NVIDIA HPC SDK). The `nvcc` binary "
                f"is NOT on PATH by default; you MUST `module load nvhpc` "
                f"first to compile CUDA code."
            )
        else:
            lines.append(f"- CUDA toolchain: nvcc available at {nvcc} (already on PATH).")
    elif env["has_module"]:
        lines.append(
            "- CUDA toolchain: NOT on default PATH. Try "
            "`module avail nvhpc` / `module load nvhpc` to discover."
        )
    else:
        lines.append("- CUDA toolchain: NOT detected on this host.")

    lines.append(
        "- Shared filesystem note: per-node `/tmp` is NOT shared across "
        "compute nodes; write run artifacts to the working directory "
        "(passed in via the workspace) so they survive node hops."
    )
    # Network claim: SLURM and local hosts almost always have outbound
    # HTTPS to PyPI/GitHub/HF/Zenodo. We declare this so the agent
    # doesn't waste cycles probing connectivity or assume it must
    # bundle every dependency locally. (Docker is handled in the early
    # return above so this only fires for slurm/local kinds.)
    lines.append(
        "- Network: outbound HTTPS is available — `pip install`, "
        "`git clone`, `curl`/`wget` to PyPI / GitHub / Hugging Face / "
        "Zenodo all work. Use these for fetching source code, model "
        "weights, and (small) datasets. Since `apt-get` is not "
        "available, prefer pip / source build / `module load` over "
        "system-package install paths."
    )
    # Phase 2 isolation warning — by far the most subtle failure mode
    # for HPC dogfood runs. The agent's iteration shell is NOT the
    # shell that will run reproduce.sh at grading time.
    lines.append(
        "- Phase 2 isolation: the grader will run "
        "`bash submission/reproduce.sh` in a FRESH shell on a fresh "
        "node allocation. Any `module load`, `pip install`, "
        "environment variables, or directory changes you do during "
        "your iteration WILL NOT carry over. If you need a `module "
        "load`, a `pip install`, or any other env setup to make your "
        "code run, put those lines AT THE TOP of `reproduce.sh` "
        "itself."
    )
    # Language-choice counter-priming. The standard PaperBench
    # instructions.txt uses a Python (count.py / strawberry) example
    # for illustration, which strongly primes the agent toward Python
    # regardless of the paper. On HPC papers (CUDA / MPI / OpenMP /
    # Fortran numerical libraries) this is a false positive — the
    # rubric typically has "GPU kernel verified", "C++17 build",
    # "MPI process count = N", "Fortran subroutine X exists" leaves
    # that Python proxies cannot satisfy.
    lines.append(
        "- Language choice: the reproduce.sh example in the standard "
        "instructions uses Python — that is illustration ONLY, not "
        "prescription. Match the paper's native language stack:\n"
        "    * HPC GPU compute (CUDA / cuSZ / GPU kernels) → C++/CUDA "
        "(`module load nvhpc`, then `nvcc -std=c++17 -arch=sm_XX -O3`); "
        "HIP/ROCm for AMD GPU papers; SYCL for portable.\n"
        "    * HPC CPU parallel (OpenMP / MPI / vectorisation) → "
        "C / C++ / Fortran with `mpicc` / `mpic++` / `mpifort` (`module "
        "load openmpi` or `mpich`) and `-fopenmp`.\n"
        "    * Numerical libraries (BLAS / LAPACK / FFTW / HDF5 / "
        "NetCDF) → C / C++ / Fortran linked against the system module "
        "(`module load fftw` etc); Python wrappers (numpy.linalg / "
        "h5py / netCDF4) are acceptable when the paper itself uses "
        "them.\n"
        "    * ML / deep learning (PyTorch / JAX / TensorFlow / "
        "diffusion / transformers) → Python with the appropriate "
        "framework; CUDA kernel custom ops in C++/CUDA when the paper "
        "ships them.\n"
        "    * Systems / databases / compilers / kernels → the paper's "
        "declared language (C / C++ / Rust / Go / OCaml / etc); do "
        "not re-implement in Python.\n"
        "    * Web / JS frameworks → JS/TS in Node.js or the declared "
        "runtime.\n"
        "  A Python-only proxy of a CUDA/MPI/Fortran paper will lose "
        "every kernel/build/execution rubric leaf even when the "
        "algorithm shape is correct. The rubric REWARDS reproducing "
        "the paper in its native language."
    )
    return "\n".join(lines)


def _install_env_assumption_patch() -> None:
    """Monkey-patch vendor ``get_instructions`` to substitute vendor's
    hardcoded ``- You have root access in your environment.`` line with
    a TRUTHFUL multi-line block describing the actual runtime env
    (apt/sudo/module/nvcc state) so the agent doesn't blindly trust the
    Docker-assumption template. Idempotent. Skipped when
    ``ARI_PB_DISABLE_ENV_PATCH=1`` is set.
    """
    if os.environ.get(_ENV_PATCH_DISABLE_ENV, "") == "1":
        log.info("vendor patch: env-assumption substitution disabled via %s=1",
                 _ENV_PATCH_DISABLE_ENV)
        return
    try:
        from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    except Exception as e:
        log.warning("vendor patch: cannot locate basicagent.utils for env "
                    "substitution: %s; agent will see vendor's Docker "
                    "assumption verbatim", e)
        return
    if getattr(_v_utils.get_instructions, "_ari_env_patched", False):
        return
    original = _v_utils.get_instructions

    async def patched(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        out = await original(*args, **kwargs)
        # Re-detect at call time (env state could change between import and
        # rollout, e.g., SLURM_JOB_ID materialises only inside sbatch).
        env = _detect_runtime_env()
        replacement = _build_truthful_env_block(env)
        if replacement != _VENDOR_ROOT_ACCESS_LINE and _VENDOR_ROOT_ACCESS_LINE in out:
            out = out.replace(_VENDOR_ROOT_ACCESS_LINE, replacement)
            log.info(
                "vendor patch: substituted env-assumption line with %d-line "
                "truthful block (kind=%s nvcc=%s has_module=%s has_apt=%s)",
                replacement.count("\n") + 1,
                env["kind"], bool(env["nvcc_path"]),
                env["has_module"], env["has_apt"],
            )
        return out

    patched._ari_env_patched = True  # type: ignore[attr-defined]
    _v_utils.get_instructions = patched
    log.info("vendor patch: installed env-assumption substitution on "
             "BasicAgent get_instructions")


_install_env_assumption_patch()


# ─── vendor patch: blacklist lift (ARI lifts vendor leaderboard rules) ────
#
# Vendor instructions.txt:19 contains:
#
#   "You are allowed to browse and use resources you can find online,
#    however you must not look at or use the paper's codebase or any
#    other resources listed in `blacklist.txt`, as this is considered
#    cheating."
#
# This rule exists because PaperBench's purpose is "can an LLM
# blind-reproduce a paper from text alone?" — using the author's own
# code is leaderboard cheating. ARI's purpose is different (LLM-driven
# reproduction-quality audit with LLM-generated rubrics, not
# leaderboard rank — see project memory `project_ari_rubric_design`).
# For ARI an agent that consults the author's official artifact repo
# to clarify ambiguous paper passages produces a HIGHER-quality
# reproduction, which is the actual goal. The vendor blacklist rule
# is therefore counter-productive for ARI dogfood.
#
# Fix: monkey-patch ``paperbench.solvers.basicagent.utils.get_instructions``
# to substitute the cheating-claim line with an explicit ARI override
# saying the agent MAY consult the paper's official codebase. No
# vendor source edits (preserves ``zero vendor changes`` invariant).
# Opt-out via ``ARI_PB_KEEP_BLACKLIST=1`` for callers reproducing
# upstream leaderboard runs.
#
# Note: this DOES NOT delete the bridge's separate ``blacklist_urls``
# parameter on ``rollout_submission`` — callers can still pass
# explicit URL lists they want gated (e.g., a competitor's proprietary
# dataset they don't want fetched). It only removes the default
# blanket "cheating" claim on the paper's own repo.

_BLACKLIST_PATCH_DISABLE_ENV = "ARI_PB_KEEP_BLACKLIST"
_VENDOR_BLACKLIST_LINE = (
    "You are allowed to browse and use resources you can find online, "
    "however you must not look at or use the paper's codebase or any "
    "other resources listed in `blacklist.txt`, as this is considered "
    "cheating."
)
_ARI_BLACKLIST_OVERRIDE = (
    "You may freely browse and use any online resources, including the "
    "paper's official codebase, supplementary materials, author "
    "repositories, and data archives. ARI's reproduction goal is "
    "audit-quality fidelity (LLM-rubric-graded), not blind-replication "
    "leaderboard rank — consulting the paper's own implementation as "
    "reference is encouraged when it clarifies ambiguous passages. "
    "(Caller may still pass explicit URL gates via "
    "`blacklist_urls`; absent that, no automatic blacklist applies.)"
)


def _install_blacklist_lift_patch() -> None:
    """Monkey-patch vendor ``get_instructions`` to replace the
    cheating-claim sentence with an ARI override allowing the agent
    to consult the paper's own codebase. Idempotent. Skipped when
    ``ARI_PB_KEEP_BLACKLIST=1`` is set (for vendor-leaderboard parity).
    """
    if os.environ.get(_BLACKLIST_PATCH_DISABLE_ENV, "") == "1":
        log.info("vendor patch: blacklist lift disabled via %s=1",
                 _BLACKLIST_PATCH_DISABLE_ENV)
        return
    try:
        from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    except Exception as e:
        log.warning("vendor patch: cannot locate basicagent.utils for "
                    "blacklist lift: %s; vendor cheating claim will reach "
                    "the agent verbatim", e)
        return
    if getattr(_v_utils.get_instructions, "_ari_blacklist_lifted", False):
        return
    # If env-assumption patch already wrapped get_instructions, our
    # blacklist wrap stacks on top (both substitutions fire per call).
    inner = _v_utils.get_instructions

    async def patched(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        out = await inner(*args, **kwargs)
        if _VENDOR_BLACKLIST_LINE in out:
            out = out.replace(_VENDOR_BLACKLIST_LINE, _ARI_BLACKLIST_OVERRIDE)
            log.info("vendor patch: lifted paper-codebase blacklist "
                     "(agent may consult author's repository)")
        return out

    patched._ari_blacklist_lifted = True  # type: ignore[attr-defined]
    # Preserve env-assumption patch sentinel so its idempotency check
    # still passes.
    if getattr(inner, "_ari_env_patched", False):
        patched._ari_env_patched = True  # type: ignore[attr-defined]
    _v_utils.get_instructions = patched
    log.info("vendor patch: installed blacklist lift on "
             "BasicAgent get_instructions")


_install_blacklist_lift_patch()


# ─── helpers ──────────────────────────────────────────────────────────────


def task_node_from_dict(d: dict) -> TaskNode:
    """Construct an upstream TaskNode from our PaperBench-format dict."""
    return TaskNode(
        id=str(d.get("id") or uuid.uuid4()),
        requirements=str(d.get("requirements", "")),
        weight=int(d.get("weight", 1)),
        sub_tasks=tuple(task_node_from_dict(c) for c in (d.get("sub_tasks") or [])),
        task_category=d.get("task_category"),
        finegrained_task_category=d.get("finegrained_task_category"),
    )


def aggregate_graded_tree(graded: GradedTaskNode) -> dict:
    """Reproduce PaperBench's weighted aggregation (and the unweighted score).

    weighted: sum(child.weight * child.score) / sum(child.weight) recursively.
    unweighted: mean of leaf 0/1 scores.
    """
    leaves: list[GradedTaskNode] = []

    def _walk(n: GradedTaskNode) -> None:
        children = list(n.sub_tasks) if n.sub_tasks else []
        if not children:
            leaves.append(n)
            return
        for c in children:
            _walk(c)

    _walk(graded)
    raw = (sum(1.0 if g.score >= 0.5 else 0.0 for g in leaves) / max(1, len(leaves)))

    return {
        "ors_score": float(graded.score),
        "raw_score": float(raw),
        "leaf_grades": [
            {
                "id": g.id,
                "requirements": g.requirements,
                "weight": int(g.weight),
                "task_category": g.task_category,
                "passed_runs": int(g.score >= 0.5),
                "n_runs": 1,
                "mean_score": float(g.score),
                "explanation": g.explanation,
            }
            for g in leaves
        ],
    }


def average_graded_runs(runs: list[GradedTaskNode]) -> dict:
    """Average leaf scores across multiple SimpleJudge runs."""
    if not runs:
        return {"ors_score": 0.0, "raw_score": 0.0, "leaf_grades": []}
    if len(runs) == 1:
        return aggregate_graded_tree(runs[0])

    leaf_runs: dict[str, list[GradedTaskNode]] = {}

    def _collect(n: GradedTaskNode) -> None:
        if not n.sub_tasks:
            leaf_runs.setdefault(n.id, []).append(n)
            return
        for c in n.sub_tasks:
            _collect(c)

    for r in runs:
        _collect(r)

    template = runs[0]
    n_runs = len(runs)

    def _rebuild(n: GradedTaskNode) -> GradedTaskNode:
        if not n.sub_tasks:
            scores = [g.score for g in leaf_runs.get(n.id, [n])]
            mean = sum(scores) / max(1, len(scores))
            kwargs = dict(
                id=n.id, requirements=n.requirements, weight=int(n.weight),
                sub_tasks=(), score=mean, explanation=n.explanation,
                task_category=n.task_category,
                valid_score=getattr(n, "valid_score", True),
                judge_metadata=getattr(n, "judge_metadata", None),
            )
            return GradedTaskNode(**kwargs)
        children = tuple(_rebuild(c) for c in n.sub_tasks)
        total_w = sum(c.weight for c in children) or 1
        score = sum(c.weight * c.score for c in children) / total_w
        kwargs = dict(
            id=n.id, requirements=n.requirements, weight=int(n.weight),
            sub_tasks=children, score=score, explanation=n.explanation,
            task_category=n.task_category,
            valid_score=getattr(n, "valid_score", True),
            judge_metadata=getattr(n, "judge_metadata", None),
        )
        return GradedTaskNode(**kwargs)

    averaged = _rebuild(template)
    agg = aggregate_graded_tree(averaged)
    for lg in agg["leaf_grades"]:
        runs_for = leaf_runs.get(lg["id"], [])
        passed = sum(1 for g in runs_for if g.score >= 0.5)
        lg["passed_runs"] = passed
        lg["n_runs"] = n_runs
    return agg


# ─── async adapter: our calling convention → upstream SimpleJudge ─────────


_PAPER_AUDIT_QUESTIONS = {
    "Code Development": (
        "Does the paper or its AD/AE Appendix describe this implementation "
        "detail with concrete, reconstructable specificity — concrete "
        "versions, parameters, configuration, file paths, or code "
        "fragments? Mere mentions or vague descriptions are NOT sufficient. "
        "Note: a submission may not exist; in paper_audit mode you are "
        "scoring the paper's self-description, not whether a submission "
        "reproduces it."
    ),
    "Code Execution": (
        "Does the paper or its AD/AE Appendix document the execution "
        "procedure for this (commands, scripts, sbatch parameters, "
        "environment variables, hardware setup) with enough detail that "
        "an HPC practitioner could reproduce it without consulting the "
        "authors? Note: a submission may not exist; in paper_audit mode "
        "you are scoring the paper's self-description, not whether a "
        "submission reproduces it."
    ),
    "Result Analysis": (
        "Is the paper's claim INTERNALLY CONSISTENT with the experimental "
        "evidence presented elsewhere in the paper (figures, tables, "
        "body text, AD/AE Appendix)? Cross-check the textual claim "
        "against the numerical or visual evidence — both the magnitude "
        "and the scaling trend must match within reasonable tolerance. "
        "Note: a submission may not exist; in paper_audit mode you are "
        "checking the paper's own internal consistency, not whether a "
        "submission reproduced the result."
    ),
    "Subtree": "What is the weighted score of all the criteria in the subtree?",
}


def _patch_task_category_questions(replacement: dict[str, str] | None = None):
    """Context manager: swap PaperBench's ``TASK_CATEGORY_QUESTIONS`` so
    SimpleJudge's grading prompt asks paper-audit-flavored questions
    instead of submission-flavored ones.

    The vendor ``simple.py`` imports the constant into its module
    namespace at module load time, so both
    ``paperbench.rubric.tasks.TASK_CATEGORY_QUESTIONS`` AND
    ``paperbench.judge.simple.TASK_CATEGORY_QUESTIONS`` must be patched
    to make the override take effect. Always restored on exit so the
    agent-benchmark code path is unaffected by a paper_audit call.
    """
    import contextlib
    import paperbench.judge.simple as ps_simple  # type: ignore
    import paperbench.rubric.tasks as ps_tasks   # type: ignore

    if replacement is None:
        replacement = _PAPER_AUDIT_QUESTIONS

    @contextlib.contextmanager
    def _patch():
        orig_simple = ps_simple.TASK_CATEGORY_QUESTIONS
        orig_tasks = ps_tasks.TASK_CATEGORY_QUESTIONS
        ps_simple.TASK_CATEGORY_QUESTIONS = replacement
        ps_tasks.TASK_CATEGORY_QUESTIONS = replacement
        try:
            yield
        finally:
            ps_simple.TASK_CATEGORY_QUESTIONS = orig_simple
            ps_tasks.TASK_CATEGORY_QUESTIONS = orig_tasks
    return _patch()


async def judge_submission(
    *,
    paper_md: str,
    rubric: TaskNode,
    submission_dir: Path,
    reproduce_log: str = "",
    judge_model: str,
    addendum: str | None = None,
    judge_addendum: str | None = None,
    paper_audit_mode: bool = False,
    code_only: bool = False,
) -> GradedTaskNode:
    """Run upstream SimpleJudge against the given submission.

    The upstream constructor wants ``paper_path`` and ``paper_md`` as
    ``Path`` objects and reads ``reproduce.sh`` / ``reproduce.log`` from
    ``submission_dir``. This wrapper writes ``paper_md`` to a temp file and,
    if the caller provided an inline ``reproduce_log`` string, persists it
    into ``submission_dir/reproduce.log`` so the judge can find it.

    ``paper_audit_mode``: when True, the vendor's
    ``TASK_CATEGORY_QUESTIONS`` (which asks about a submission's code /
    reproduce.sh / produced evidence) is monkey-patched to paper-audit
    questions (about the paper's own self-description and internal
    consistency) for the duration of the call. This breaks the structural
    ceiling where ``Result Analysis`` leaves always score 0 with an empty
    submission. The override is scoped to this call only; agent-benchmark
    callers see the original vendor prompt.

    ``code_only``: when True, the rubric tree is pruned via vendor
    :meth:`paperbench.rubric.tasks.TaskNode.code_only` so that ONLY
    ``Code Development`` leaves are graded. This mirrors vendor
    :mod:`paperbench.grade.run_judge` (``grade.py:109-112``) which
    applies the same reduction when ``judge.code_only=True`` is set on
    the upstream task config. Use this when Stage 2 (executed
    submission) was skipped — the agent was told to "only write code"
    and grading Code Execution / Result Analysis leaves against an
    empty submission would systematically zero them via the vendor's
    ``reproduce.sh failed to modify or create any files`` safeguard
    (judge/simple.py:557-560). Pairing rollout-only with this flag
    keeps the agent's instructions consistent with the grader's
    scope. Mutually exclusive with ``paper_audit_mode`` (paper-audit
    targets paper text, code-only targets a Stage 1 submission).
    """
    if code_only and paper_audit_mode:
        raise ValueError(
            "code_only and paper_audit_mode are mutually exclusive: "
            "code_only grades a Stage 1 submission against the Code "
            "Development subtree; paper_audit_mode grades the paper "
            "itself for describability. Pick one."
        )

    # Main per-leaf grading completer routes through LiteLLM so any provider
    # works (OpenAI snapshots not in PaperBench's CONTEXT_WINDOW_LENGTHS,
    # Anthropic, Gemini, Ollama, …). The int/float structured completers
    # SimpleJudge constructs internally still default to gpt-4o-2024-08-06
    # via OpenAI direct — that is fine because that model IS in the registry
    # and the parse step is small.
    from _litellm_completer import LiteLLMTurnCompleter

    submission_dir = Path(submission_dir)
    submission_dir.mkdir(parents=True, exist_ok=True)
    if reproduce_log:
        log_path = submission_dir / "reproduce.log"
        if not log_path.is_file():
            log_path.write_text(reproduce_log)

    # Apply vendor's code-only reduction BEFORE constructing the judge so
    # ``judge.grade(rubric, ...)`` walks the pruned tree. Mirror of
    # ``paperbench/grade.py:109-112``: if ``rubric.code_only()`` returns
    # None (e.g. the tree had no Code Development leaves at all), fall
    # back to a single-node Code Development tree so SimpleJudge still
    # has something to grade.
    if code_only:
        pruned = rubric.code_only()
        if pruned is None:
            pruned = rubric.set_task_category("Code Development").set_sub_tasks([])
        rubric = pruned

    with tempfile.TemporaryDirectory() as tmp:
        paper_md_path = Path(tmp) / "paper.md"
        paper_md_path.write_text(paper_md or "")
        cfg = LiteLLMTurnCompleter.Config(model=judge_model)
        judge = SimpleJudge(
            paper_path=paper_md_path,
            rubric=rubric,
            addendum=addendum,
            judge_addendum=judge_addendum,
            submission_dir=submission_dir,
            paper_md=paper_md_path,
            completer_config=cfg,
        )
        if paper_audit_mode:
            with _patch_task_category_questions():
                await judge.before_grading()
                return await judge.grade(rubric, judge.grade_leaf)
        else:
            await judge.before_grading()
            return await judge.grade(rubric, judge.grade_leaf)


# ─── Stage 1: agent rollout ──────────────────────────────────────────────


async def rollout_submission(
    *,
    paper_md: str,
    work_dir: Path | str,
    agent_model: str,
    time_limit_sec: int = 12 * 3600,
    iterative_agent: bool = False,
    max_steps: int | None = None,
    sandbox_kind: str = "auto",
    container_image: str = "",
    env: dict[str, str] | None = None,
    agent_env_path: Path | str | None = None,
    expected_artifacts: list[str] | None = None,
    execution_profile: dict | None = None,
    paper_id: str = "ari-local",
    run_id: str | None = None,
    forbid_host_filesystem: bool = False,
    blacklist_urls: list[str] | None = None,
) -> dict:
    """PaperBench Stage 1 — drive a BasicAgent / IterativeAgent rollout
    that writes a ``reproduce.sh`` (plus supporting code) into ``work_dir``.

    Public companion to :func:`judge_submission`: paper_md is written to
    ``work_dir/_input_paper.md`` and the existing
    :func:`_replicator_agent.run_replicator_agent` is invoked. The chosen
    completer mirrors :func:`server.build_reproduce_sh`: vanilla OpenAI
    Responses for ``gpt-*`` / ``o[1-5]-*`` model ids, LiteLLM-routed
    otherwise (Anthropic / Gemini / Ollama / ...).

    ``container_image`` honours the same priority chain as
    :func:`server.build_reproduce_sh`: explicit value wins, else legacy
    ``ARI_PHASE1_APPTAINER_IMAGE`` / ``ARI_PHASE1_SINGULARITY_IMAGE`` env.
    Only the Apptainer / Singularity sandbox kinds consume the image at
    Stage 1; ``sandbox_kind=slurm`` / ``local`` runs the agent on the
    host filesystem (see :func:`_compute.make_computer`).

    ``env`` is the in-memory env dict passed straight to the agent's
    subprocess. ``agent_env_path`` (path to a vendor-style ``agent.env``
    file with one ``KEY=VALUE`` pair per line) is loaded and merged
    INTO ``env`` with explicit ``env`` keys winning. Mirrors vendor
    ``nano/task.py:117 agent_env_path = get_agents_dir() / "agent.env"``
    so per-paper credentials (e.g. ``HF_TOKEN``, ``OPENAI_API_KEY``
    overrides) reach the agent inside its sandbox. Required for any
    paper that needs huggingface access during rollout.

    ``forbid_host_filesystem`` (default False): when True, refuse to
    start the rollout if ``sandbox_kind`` resolves to ``local`` or
    ``slurm`` (both run the agent's bash/python on the host filesystem
    with no isolation — see ``_compute/computer.py:LocalComputer``).
    Use this for benchmark-mode runs where source-leak fairness
    matters; the operator must then supply ``sandbox_kind=apptainer``
    or ``singularity`` with a real ``container_image``.

    ``blacklist_urls`` (default None): list of URLs / domains the
    agent must not fetch during rollout. Mirrors vendor PaperBench's
    per-paper ``data/papers/<id>/blacklist.txt`` mechanism for keeping
    the agent from short-circuiting reproduction by cloning the
    original paper's codebase. ARI does not have a per-paper registry
    (LLM-generated rubrics; one-paper-at-a-time), so the caller
    supplies blacklist URLs explicitly. Enforcement is two-layer:
    (1) the entries are prepended verbatim to the agent's instruction
    prompt under a ``FORBIDDEN URLS`` heading so the LLM knows the
    rule; (2) they are also exported as ``ARI_BLACKLIST_URLS`` env
    var (newline-joined) so downstream tools / wrappers can refuse.
    This is best-effort — a determined agent can still encode URLs
    obliquely; running with sandbox_kind=apptainer and no_network
    is the only hard guarantee.

    Returns the standard ``build_reproduce_sh`` envelope
    (``{populated, output_dir, files, expected_artifacts,
    max_runtime_sec, model, agent_runtime_sec, notes, warnings}``).
    Pass ``output_dir`` directly to :func:`reproduce_submission` as
    ``submission_dir`` to chain into Stage 2.
    """
    # Resolve effective sandbox_kind for the host-filesystem guard.
    # ``auto`` + container_image set → apptainer; ``auto`` + no image
    # → local. Match :func:`_compute.make_computer`'s resolution.
    effective_sandbox = (sandbox_kind or "auto").lower()
    explicit = os.environ.get("ARI_PHASE1_SANDBOX", "").strip().lower()
    if explicit:
        effective_sandbox = explicit
    if effective_sandbox == "auto":
        effective_sandbox = "apptainer" if container_image else "local"
    if forbid_host_filesystem and effective_sandbox in ("local", "slurm"):
        raise RuntimeError(
            f"forbid_host_filesystem=True but the effective sandbox_kind "
            f"resolves to {effective_sandbox!r}, which runs the agent's "
            f"bash/python tools directly on the host filesystem (no "
            f"container isolation; see _compute/computer.py LocalComputer). "
            f"For benchmark-fair runs where the agent must not see the host "
            f"workspace, pass sandbox_kind='apptainer' (or 'singularity') "
            f"with a real container_image. Pass forbid_host_filesystem=False "
            f"to opt back into host-FS execution (the default for development "
            f"workflows where the agent is expected to be able to read the "
            f"paper's repo)."
        )

    # Merge agent_env_path → env (in-memory env wins). When
    # agent_env_path is unset, fall back to the operator-configured
    # default (``ARI_AGENT_ENV_PATH`` env) and then to ``~/.ari/agent.env``
    # if either is present. This is the auto-load path so wizard users
    # don't have to thread the file location explicitly.
    if agent_env_path is None:
        for candidate in (
            os.environ.get("ARI_AGENT_ENV_PATH", "").strip(),
            str(Path.home() / ".ari" / "agent.env"),
        ):
            if candidate and Path(candidate).is_file():
                agent_env_path = candidate
                log.info("rollout_submission: auto-loading agent.env from %s", candidate)
                break

    # Lift HF_TOKEN from the calling process env into the agent's env
    # by default (mirrors vendor's nano/eval.py:172-179 pattern of
    # forwarding well-known credential names). This keeps the
    # "setup.sh asked me to register HF_TOKEN" → "the agent sees it"
    # contract working without requiring an agent.env file at all.
    merged_env: dict[str, str] | None = None
    if env or agent_env_path or any(os.environ.get(k) for k in ("HF_TOKEN",)):
        merged_env = {}
        if agent_env_path:
            for k, v in _load_dotenv_file(Path(agent_env_path)).items():
                merged_env[k] = v
        for k in ("HF_TOKEN",):
            v = os.environ.get(k)
            if v and k not in merged_env:
                merged_env[k] = v
        if env:
            merged_env.update(env)

    # blacklist_urls enforcement: export as env (for downstream tool
    # wrappers) AND prepend a FORBIDDEN URLS section to paper_md so
    # the agent's instruction prompt carries it. The prepended block
    # is plain Markdown so vendor's prompt-building code reads it
    # verbatim; mirrors vendor PaperBench's per-paper blacklist.txt.
    bl_entries = [str(u).strip() for u in (blacklist_urls or []) if str(u).strip()]
    if bl_entries:
        if merged_env is None:
            merged_env = {}
        merged_env["ARI_BLACKLIST_URLS"] = "\n".join(bl_entries)
        prelude = (
            "# FORBIDDEN URLS / RESOURCES\n\n"
            "You MUST NOT fetch, clone, curl, wget, pip-install-from, or\n"
            "otherwise access any of the URLs / domains listed below at any\n"
            "point during this rollout. They are the paper's own codebase\n"
            "(or other reference sources whose use would short-circuit the\n"
            "reproduction). Producing reproduce.sh that references them is\n"
            "also forbidden. If a tool call would touch one of these, abort\n"
            "the call and explain in your reasoning.\n\n"
        )
        prelude += "\n".join(f"  - {u}" for u in bl_entries) + "\n\n---\n\n"
        paper_md = prelude + (paper_md or "")

    container_image = _resolve_container_image_alias(container_image)

    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    paper_md_path = work / "_input_paper.md"
    paper_md_path.write_text(paper_md or "", encoding="utf-8")

    is_openai_responses = (
        agent_model.startswith(("gpt-", "o1-", "o3-", "o4-", "o5-"))
        and "/" not in agent_model
    )
    if is_openai_responses:
        from paperbench.solvers.basicagent.completer import (  # type: ignore
            OpenAIResponsesTurnCompleterConfig,
        )
        # Preserve the vendor BasicAgentSolver default_factory's
        # ``tools=[WebSearchToolParam(type="web_search_preview")]``. We
        # construct a fresh completer_config (so the caller's agent_model
        # wins over the vendor's hardcoded "gpt-4.1-mini"), and the
        # vendor's default web search tool would otherwise be lost.
        # Without this, IterativeAgent mode degrades to bash + read-file
        # only (no web search, no PythonTool, no SearchFile) — the agent
        # cannot look up library versions or check baselines.
        from openai.types.responses.web_search_tool_param import (  # type: ignore
            WebSearchToolParam,
        )
        completer_config: Any = OpenAIResponsesTurnCompleterConfig(
            model=agent_model,
            tools=[WebSearchToolParam(type="web_search_preview")],
        )
    else:
        from _litellm_completer import get_litellm_basicagent_completer_config
        completer_config = get_litellm_basicagent_completer_config()(model=agent_model)

    from _replicator_agent import run_replicator_agent

    return await run_replicator_agent(
        paper_md_path=str(paper_md_path),
        output_dir=str(work),
        expected_artifacts=list(expected_artifacts or []),
        execution_profile=dict(execution_profile or {}),
        time_limit_sec=int(time_limit_sec),
        iterative_agent=bool(iterative_agent),
        max_steps=max_steps,
        completer_config=completer_config,
        sandbox_kind=sandbox_kind,
        apptainer_image=container_image or None,
        env=merged_env if merged_env is not None else env,
        paper_id=paper_id,
        run_id=run_id,
    )


def _load_dotenv_file(path: Path) -> dict[str, str]:
    """Minimal ``.env`` parser for agent.env-style files.

    Format: ``KEY=VALUE`` per line; ``#`` starts a comment; surrounding
    quotes on the value are stripped. No expansion, no multi-line
    values — matches the vendor ``agent.env`` shape (one secret per
    line, plain strings).
    """
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip("\"").strip("'")
    return out


# Short aliases for the vendor PaperBench Docker images that
# ``scripts/build_pb_images.sh`` produces. Operators can pass
# ``container_image="pb-env"`` / ``"pb-reproducer"`` to the bridge and
# the call resolves to the canonical ``image:latest`` tag at runtime,
# making wizard / CLI presets short and human-friendly without
# hardcoding the tag string at every call site.
_PB_IMAGE_ALIASES: dict[str, str] = {
    "pb-env": "pb-env:latest",
    "pb-reproducer": "pb-reproducer:latest",
}


def _resolve_container_image_alias(value: str) -> str:
    """Resolve short PaperBench image aliases to their canonical tag.

    Accepts the bare alias (``pb-env``) or any string that already
    contains a tag separator (``:``), an absolute path (``/``), or a
    URI scheme (``docker://``, ``library://``, ``shub://``). Anything
    not matching an alias is returned verbatim so user-supplied SIF
    paths and arbitrary image tags continue to work.
    """
    v = (value or "").strip()
    if not v:
        return v
    if v in _PB_IMAGE_ALIASES:
        return _PB_IMAGE_ALIASES[v]
    return v


# ─── Stage 2: reproduce.sh execution ────────────────────────────────────


async def reproduce_submission(
    *,
    submission_dir: Path | str,
    sandbox_kind: str = "auto",
    container_image: str = "",
    time_limit_sec: int = 6 * 3600,
    partition: str = "",
    gpus_per_task: int = 0,
    gpu_type: str = "",
    memory_gb_per_node: int = 0,
    exclusive: bool = False,
    extra_sbatch_args: list[str] | None = None,
    capture_tarball: bool = True,
    tarball_dir: Path | str | None = None,
    salvage_retries: int = 0,
    retry_threshold_sec: int = 60,
) -> dict:
    """PaperBench Stage 2 — execute ``submission_dir/reproduce.sh`` in the
    chosen sandbox, capture stdout/stderr into ``reproduce.log``.

    Public companion to :func:`rollout_submission` and
    :func:`judge_submission`. Wraps :func:`server.run_reproduce` so callers
    using the bridge can drive Stage 2 without speaking the MCP tool's
    full 23-arg signature. The submission directory is reused in-place as
    the executed-submission output (matching the vendor reproducer
    container behaviour where reproduce.log is written back to the
    bind-mounted submission dir).

    Infrastructure preconditions are enforced loudly: a missing docker
    daemon / apptainer binary / sbatch / partition raises
    ``RuntimeError`` unless ``ARI_PHASE1_ALLOW_FALLBACK=1`` is set, and a
    GRES-less cluster with GPU request raises unless
    ``ARI_SLURM_ALLOW_NO_GRES=1``. The returned dict adds
    ``executed_submission_dir`` and ``reproduce_log_path`` keys so
    downstream :func:`judge_submission` can wire its ``submission_dir`` /
    ``reproduce_log`` arguments directly.

    ``capture_tarball`` (default True) packages the executed submission
    dir into ``submission_executed.tar.gz`` alongside the submission
    (timestamped to avoid clobbering prior runs). Mirrors vendor
    ``reproduce.py:230-244`` which writes per-attempt tarballs for
    re-grading and provenance. ``tarball_dir`` overrides the destination
    directory (default: ``submission_dir.parent``). The path is returned
    as ``executed_tarball``.

    ``salvage_retries`` (default 0 = no retry) controls vendor-style
    salvage retries: if the first attempt exits non-zero AND finishes
    under ``retry_threshold_sec``, retry up to N more times with a
    Python 3.11 + fresh venv wrapper around reproduce.sh. Mirrors
    vendor ``reproduce.py:252 reproduce_on_computer_with_salvaging``
    (which uses a Cartesian ``{use_py3_11, make_venv}`` retry matrix).
    The attempts log lives in the returned ``salvage_attempts`` list.
    """
    from server import run_reproduce  # lazy: server imports this module

    container_image = _resolve_container_image_alias(container_image)
    sub = Path(submission_dir).resolve()

    # Wall-clock budget shared by ALL attempts (initial + salvage
    # retries). Vendor's reproduce.py:timeout is per-attempt, but
    # ARI's contract is "time_limit_sec is the user's total budget" —
    # retry-time exclusion (a la BasicAgent's use_real_time_limit at
    # Stage 1) lets us spend that budget across multiple attempts
    # without overshooting. Each attempt's per-call timeout is the
    # REMAINING budget capped to the original time_limit_sec.
    import time as _time
    overall_start = _time.time()
    overall_budget_sec = int(time_limit_sec)

    def _remaining_budget() -> int:
        spent = int(_time.time() - overall_start)
        return max(0, overall_budget_sec - spent)

    async def _attempt(use_salvage_wrapper: bool) -> dict:
        if use_salvage_wrapper:
            _install_salvage_wrapper(sub)
        try:
            return await run_reproduce(
                rubric_path="",
                repo_dir=str(sub),
                sandbox_kind=sandbox_kind,
                container_image=container_image,
                timeout_global_sec=_remaining_budget(),
                partition=partition,
                gpus_per_task=int(gpus_per_task),
                gpu_type=gpu_type,
                memory_gb_per_node=int(memory_gb_per_node),
                exclusive=bool(exclusive),
                extra_sbatch_args=list(extra_sbatch_args or []),
            )
        finally:
            if use_salvage_wrapper:
                _restore_salvage_wrapper(sub)

    attempts: list[dict] = []
    res = await _attempt(use_salvage_wrapper=False)
    attempts.append({"attempt": 1, "salvage": False, **_attempt_summary(res)})

    # Salvage retry condition: caller opted in AND first attempt failed
    # AND finished fast (likely an environment issue, not a slow run)
    # AND there is still budget remaining for another attempt.
    n = 0
    while (
        salvage_retries > 0
        and n < int(salvage_retries)
        and isinstance(res, dict)
        and res.get("exit_code") not in (0, None)
        and float(res.get("elapsed_sec") or 0) < float(retry_threshold_sec)
        and _remaining_budget() > 0
    ):
        n += 1
        log.info(
            "[salvage] attempt %d/%d (exit=%s elapsed=%.1fs<threshold=%ds remaining=%ds)",
            n, salvage_retries,
            res.get("exit_code"), res.get("elapsed_sec") or 0.0,
            retry_threshold_sec, _remaining_budget(),
        )
        res = await _attempt(use_salvage_wrapper=True)
        attempts.append({"attempt": n + 1, "salvage": True, **_attempt_summary(res)})

    if isinstance(res, dict):
        res.setdefault("executed_submission_dir", str(sub))
        res.setdefault("reproduce_log_path", str(sub / "reproduce.log"))
        if len(attempts) > 1:
            res["salvage_attempts"] = attempts
        if capture_tarball:
            try:
                tar_path = _write_executed_tarball(sub, tarball_dir)
                res["executed_tarball"] = str(tar_path)
            except Exception as e:
                log.warning("submission_executed.tar.gz capture failed: %s", e)
                res.setdefault("warnings", []).append(
                    f"submission_executed.tar.gz capture failed: {e}"
                )
    return res


def _attempt_summary(res: dict) -> dict:
    """Extract the fields the caller cares about from a single
    run_reproduce return — used to populate salvage_attempts list."""
    if not isinstance(res, dict):
        return {"executed": False, "error": "non-dict run_reproduce return"}
    return {
        "executed": res.get("executed"),
        "exit_code": res.get("exit_code"),
        "elapsed_sec": res.get("elapsed_sec"),
        "error": res.get("error"),
    }


def _write_executed_tarball(
    submission_dir: Path,
    tarball_dir: Path | str | None,
) -> Path:
    """Write a timestamped ``submission_executed.tar.gz`` next to the
    submission (or into ``tarball_dir`` when supplied). Returns the
    path of the written tarball. Mirrors vendor
    ``reproduce.py:tar_and_extract_from_computer`` semantics —
    timestamp distinguishes per-attempt artefacts so a salvage retry
    doesn't clobber the previous attempt's record.
    """
    import tarfile
    import time as _time

    out_dir = Path(tarball_dir).resolve() if tarball_dir else submission_dir.parent.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _time.strftime("%Y%m%dT%H%M%S", _time.gmtime())
    tar_path = out_dir / f"submission_executed_{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(submission_dir, arcname=submission_dir.name)
    return tar_path


_SALVAGE_WRAPPER_SUFFIX = ".pre_salvage"


def _install_salvage_wrapper(submission_dir: Path) -> None:
    """Wrap submission_dir/reproduce.sh with a vendor-style salvage
    prelude that creates a fresh Python 3.11 venv and uses it for the
    duration of the rerun. Mirrors the rationale of
    ``vendor/.../reproduce.py:252 reproduce_on_computer_with_salvaging``
    (use_py3_11=True, make_venv=True). The original script is moved to
    ``reproduce.sh.pre_salvage`` so :func:`_restore_salvage_wrapper`
    can put it back regardless of outcome.
    """
    orig = submission_dir / "reproduce.sh"
    if not orig.is_file():
        return
    backup = orig.with_suffix(orig.suffix + _SALVAGE_WRAPPER_SUFFIX)
    if not backup.is_file():
        backup.write_bytes(orig.read_bytes())
    body = orig.read_text()
    wrapped = (
        "#!/usr/bin/env bash\n"
        "# AUTO-INSERTED BY ari-skill-paper-re salvage retry. The original\n"
        "# reproduce.sh body follows the venv prelude. Original is\n"
        "# preserved as reproduce.sh.pre_salvage.\n"
        "set -e\n"
        "PY311=$(command -v python3.11 || true)\n"
        "if [ -n \"${PY311}\" ]; then\n"
        "  if [ ! -d .salvage_venv ]; then\n"
        "    \"${PY311}\" -m venv .salvage_venv\n"
        "  fi\n"
        "  # shellcheck disable=SC1091\n"
        "  . .salvage_venv/bin/activate\n"
        "fi\n"
        "set +e\n"
        "# ─── original reproduce.sh body ───────────────────────────\n"
    ) + body
    orig.write_text(wrapped)
    try:
        orig.chmod(0o755)
    except OSError:
        pass


def _restore_salvage_wrapper(submission_dir: Path) -> None:
    """Reverse :func:`_install_salvage_wrapper`."""
    orig = submission_dir / "reproduce.sh"
    backup = orig.with_suffix(orig.suffix + _SALVAGE_WRAPPER_SUFFIX)
    if backup.is_file():
        orig.write_bytes(backup.read_bytes())
        try:
            orig.chmod(0o755)
        except OSError:
            pass
        try:
            backup.unlink()
        except OSError:
            pass
