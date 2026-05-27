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
import re
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

    return {
        "kind": env_kind,
        "has_apt": shutil.which("apt-get") is not None,
        "has_sudo": shutil.which("sudo") is not None,
        "has_module": (
            shutil.which("module") is not None
            or bool(os.environ.get("MODULEPATH"))
        ),
        "module_path": os.environ.get("MODULEPATH") or None,
        "slurm_partition": slurm_partition,
    }


def _parse_module_names(avail_output: str) -> list[str]:
    """Extract namespaced module names (those containing ``/``, e.g.
    ``system/ai-l40s``, ``mpi/mpich-x86_64``) from ``module avail``
    output. Path headers (``--- /some/dir ---``) and bare builtins
    (``dot``, ``null``, ``modules``) are skipped — only namespaced
    entries are candidate MODULEPATH-switch entry modules. Order is
    preserved, duplicates removed.
    """
    names: list[str] = []
    seen: set[str] = set()
    for raw in avail_output.splitlines():
        line = raw.strip()
        if not line or line.startswith("/") or set(line) <= set("- "):
            continue  # path header or separator rule
        for tok in line.split():
            # strip trailing markers: (default), <L>, trailing slash
            name = tok.split("(")[0].rstrip("/").strip()
            if "/" in name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _expand_modulepath_tier2(run_module, avail_output: str,
                             max_entries: int = 40,
                             partition: str | None = None) -> str:
    """Read-only tier-2 expansion for Tcl Environment Modules (no Lmod
    ``spider``). For each namespaced entry module in ``avail_output``,
    run ``module show`` (read-only — never ``module load``) to find any
    ``prepend-path MODULEPATH <dir>`` it would add, then list that dir by
    OVERRIDING ``MODULEPATH`` for a single ``module avail`` (read-only env
    scope, still no ``module load``). Returns a catalog section, or "" when
    nothing is hidden behind entry modules (flat clusters / laptops).

    Note: ``module avail <dir>`` cannot be used to enumerate ``<dir>`` —
    classic Tcl Modules treats the argument as a FILTER over the active
    MODULEPATH, so a dir not already on MODULEPATH lists nothing. Setting
    ``MODULEPATH=<dir>`` for the one command lists exactly that dir.

    Each revealed MODULEPATH dir is enumerated once. A dir is often shared
    by several entry modules (e.g. every ``system/<gpu>`` entry prepends
    the same NVIDIA HPC SDK modulefiles path). We therefore record ALL
    entries that expose each dir and present them together with an
    explicit "load ONE of these (they are mutually exclusive)" note —
    attributing a shared dir to a single arbitrary entry mislead a past
    dogfood agent into loading several conflicting entries, which (via the
    modulefiles' ``conflict`` directive) unloaded everything and left the
    toolchain unreachable. Dirs absent on the probing host (tier-2
    modulefiles mounted only on compute nodes) yield empty listings and
    are dropped, so this degrades gracefully when run off-node.
    """
    import re
    import shlex

    # A hierarchical entry module switches MODULEPATH in one of three
    # portable ways across Tcl Environment Modules deployments:
    #   prepend-path MODULEPATH <dir>   (most common)
    #   append-path  MODULEPATH <dir>
    #   module use [--append] <dir>     (sugar that also edits MODULEPATH)
    # Match all three so the breakthrough is not tied to R-CCS's style.
    _modulepath_patterns = (
        r"(?:prepend|append)-path\s+(?:--\S+\s+)?MODULEPATH\s+(\S+)",
        r"module\s+use\s+(?:--\S+\s+)?(\S+)",
    )
    entries = _parse_module_names(avail_output)[:max_entries]
    # Scope to the allocated partition's entry when known. The other
    # `system/<gpu>` entries (A100/H100/GH200/MI250/...) are irrelevant to a
    # job allocated on, say, ai-l40s — expanding all of them is noise that
    # dilutes the prompt. Keep entries whose name contains the partition
    # token; fall back to all entries if none match (heuristic-safe).
    if partition:
        ptok = partition.strip().lower()
        matched = [e for e in entries if ptok in e.lower()]
        if matched:
            entries = matched
    # Pass 1 (read-only `module show`): map each revealed MODULEPATH dir to
    # the ordered list of entry modules that expose it.
    dir_to_entries: dict[str, list[str]] = {}
    dir_order: list[str] = []
    for ent in entries:
        show = run_module(f"module show {ent} 2>&1")
        if not show:
            continue
        for pat in _modulepath_patterns:
            for m in re.finditer(pat, show):
                mp = m.group(1)
                if mp not in dir_to_entries:
                    dir_to_entries[mp] = []
                    dir_order.append(mp)
                if ent not in dir_to_entries[mp]:
                    dir_to_entries[mp].append(ent)
    # Pass 2 (read-only MODULEPATH-override `module avail`): enumerate each
    # dir once, listing every entry that reaches it.
    sections: list[str] = []
    for mp in dir_order:
        listing = run_module(
            f"export MODULEPATH={shlex.quote(mp)}; module avail 2>&1"
        )
        # Keep only listings that name at least one real module
        # (a non-header, non-separator line).
        has_module = any(
            ln.strip() and not ln.strip().startswith("/")
            and set(ln.strip()) > set("- ")
            for ln in listing.splitlines()
        )
        if not (listing and has_module):
            continue
        ents = dir_to_entries[mp]
        if len(ents) == 1:
            head = f"--- behind `module load {ents[0]}` (MODULEPATH {mp}) ---"
        else:
            head = (
                f"--- behind `module load <ONE of: {', '.join(ents)}>` "
                f"— these entry modules are MUTUALLY EXCLUSIVE, load exactly "
                f"ONE (the one matching your allocated hardware/partition); "
                f"loading several unloads them all (MODULEPATH {mp}) ---"
            )
        sections.append(head + "\n" + listing)
    if not sections:
        return ""
    return (
        "=== tier-2 modules behind entry modules (revealed read-only via "
        "`module show`; to use, `module load <entry>` THEN `module load "
        "<tier-2 name>`) ===\n" + "\n\n".join(sections)
    )


def _probe_module_avail(max_chars: int = 12000,
                        partition: str | None = None) -> str:
    """Run ``module spider`` AND ``module avail`` and return their
    combined raw output, capped at ``max_chars`` to keep the prompt
    budget bounded. ``partition`` scopes the tier-2 expansion to the
    allocated partition's entry module (avoids dumping every GPU's stack).

    Why both:

      - ``module avail`` lists modules visible at the current
        MODULEPATH. On 2-step-entry clusters (R-CCS, LUMI, TGCC, ...)
        this only shows the entry modules (``system/ai-l40s``,
        ``LUMI/24.03``, etc) — the actual compilers (nvhpc, openmpi,
        cuda) are hidden behind those entries until the entry is
        loaded.
      - ``module spider`` (Lmod standard, read-only) RECURSIVELY
        enumerates EVERY module discoverable across all known
        modulepaths INCLUDING child catalogs behind entry modules.
        Same philosophy as ``module avail`` (read-only inspection,
        no state mutation, no bridge-side compiler knowledge) but
        better data for the agent.
      - When ``module spider`` is unsupported (classic Tcl Environment
        Modules, e.g. R-CCS), we recover the same tier-2 visibility
        WITHOUT loading anything: ``module show <entry>`` (read-only)
        reveals the ``prepend-path MODULEPATH <dir>`` an entry module
        would add, and ``module avail <dir>`` lists what lives there.
        This is the Tcl equivalent of Lmod's read-only ``spider`` — no
        ``module load``, no state mutation, no bridge-side compiler
        knowledge.

    Cluster-agnostic: bridge does NOT name specific modules. It just
    runs standard read-only module verbs and dumps their output as
    data; the agent inspects the catalog and decides what to load.

    SC41406 v3-A2/v3-A6 surfaced this requirement: the agent ran
    ``module avail`` correctly, saw only ``system/ai-l40s`` (the entry
    module), but stopped there — it loaded the entry and expected nvcc
    on PATH, not realising the entry only switches MODULEPATH and a
    SECOND ``module load nvhpc`` is needed. Surfacing tier-2 lets the
    agent write the correct ``module load system/ai-l40s && module
    load nvhpc`` chain.
    """
    import subprocess
    import shlex

    # Tier-2 expansion may issue many `module show` / `module avail`
    # calls. Re-sourcing the full login profile (`bash -lc`) on each is
    # multi-second on some clusters (measured 2.5s/call on R-CCS). Detect
    # the module system's lightweight init once and `source` only that on
    # subsequent calls (~0.05s/call); fall back to a login shell if the
    # init script can't be located.
    _prelude = ""
    _bash_flag = "-lc"
    try:
        _r = subprocess.run(
            ["bash", "-lc", 'printf %s "$MODULESHOME"'],
            capture_output=True, timeout=30, check=False,
        )
        _home = (_r.stdout or b"").decode("utf-8", errors="replace").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _home = ""
    _init = os.path.join(_home, "init", "bash") if _home else ""
    if _init and os.path.isfile(_init):
        _prelude = f"source {shlex.quote(_init)} 2>/dev/null; "
        _bash_flag = "-c"

    def _run_module(cmd: str) -> str:
        try:
            r = subprocess.run(
                ["bash", _bash_flag, _prelude + cmd],
                capture_output=True, timeout=60, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("module probe failed (%s): %s", cmd, e)
            return ""
        out = (r.stdout or b"") + (r.stderr or b"")
        return out.decode("utf-8", errors="replace").strip()

    spider = _run_module("module spider 2>&1")
    avail = _run_module("module avail 2>&1")
    # Old Environment Modules (pre-Lmod) returns "Invalid command 'spider'"
    # — treat that as "spider unsupported" and skip the section so the
    # agent prompt doesn't carry a misleading error message.
    spider_unsupported_markers = (
        "Invalid command 'spider'",
        "Unrecognized subcommand 'spider'",
        "spider: command not found",
    )
    if any(m in spider for m in spider_unsupported_markers):
        spider = ""
    parts: list[str] = []
    if spider:
        parts.append("=== `module spider` (recursive enumeration; "
                     "shows child catalogs behind entry modules on "
                     "2-step-entry clusters) ===\n" + spider)
    if avail:
        parts.append("=== `module avail` (modules at current MODULEPATH) ===\n"
                     + avail)
    # Tcl Environment Modules has no `spider`. Recover tier-2 visibility
    # read-only: for each namespaced entry module, `module show` reveals
    # the MODULEPATH it would prepend; `module avail <dir>` lists modules
    # there. No `module load`, no mutation.
    if not spider:
        tier2 = _expand_modulepath_tier2(_run_module, avail, partition=partition)
        if tier2:
            parts.append(tier2)
    if not parts:
        return ""
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated at {max_chars} chars]"
    return text


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

    # Module system + cluster catalog. We deliberately do NOT name
    # nvcc, mpicc, gcc, or any specific compiler here — the bridge
    # MUST stay cluster-agnostic (no hardcoded toolchain knowledge).
    # Instead we dump the raw `module avail` output as data and let the
    # agent inspect the cluster catalog to decide which modules apply
    # to the paper. (CUDA-specific guidance now flows through the
    # paper-kind addendum, which is paper-conditional rather than
    # cluster-conditional.)
    if env["has_module"]:
        lines.append(
            "- Module system: ENABLED. Use `module avail` to see the "
            "cluster catalog and `module load <name>` to activate any "
            "toolchain the paper requires (compilers, MPI, libraries, "
            "etc). The available-modules list is included below."
        )
        avail = _probe_module_avail(partition=env.get("slurm_partition"))
        if avail:
            lines.append("")
            lines.append("Available modules on this host (probed at rollout start):")
            lines.append("```")
            lines.append(avail)
            lines.append("```")
            lines.append("")
    else:
        lines.append(
            "- Module system: not detected on this host. Use `which "
            "<binary>` / package-manager status to discover compilers."
        )

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
    # Verify-first principle — toolchain-agnostic counter to the
    # observed agent pattern of writing scaffolding (kernel.cu,
    # build.sh) WITHOUT ever actually compiling or running it. On
    # SC41406 the agent wrote a CUDA kernel stub + build.sh, ran
    # build.sh once, hit `nvcc not found` (because it never
    # `module load nvhpc`-ed in its own iteration shell), and just
    # documented "requires nvcc/NVHPC" in the README instead of
    # trying `module load nvhpc` itself. The rubric grades real
    # execution, not documentation.
    lines.append(
        "- Verify-first principle: BEFORE writing toolchain-dependent "
        "code, PROBE the toolchain in YOUR shell. Use whichever "
        "discovery mechanism your env supports — `module avail` / "
        "`module load <name>` on Lmod clusters, `conda activate` / "
        "`pip list` in conda/venv, `which <bin>` / `pkg-config <name>` "
        "otherwise. If the probe succeeds, copy the activation "
        "command(s) to the TOP of reproduce.sh so Phase 2 (the "
        "grader's fresh shell) inherits the same env. Scaffolding "
        "(writing source files, build scripts, READMEs) WITHOUT ever "
        "compiling or running anything earns ZERO Code Execution "
        "rubric credit — probe aggressively early; iterative shell "
        "experimentation has zero cost."
    )
    lines.append(
        "- Language choice: the reproduce.sh example in the standard "
        "instructions uses Python — that is illustration ONLY, not "
        "prescription. Match the paper's native language stack:\n"
        "    * HPC GPU compute (CUDA / GPU kernels) → C++/CUDA "
        "(load the cluster's CUDA module via `module load <NAME>`, "
        "then `nvcc -std=c++17 -arch=sm_XX -O3 ...`); HIP/ROCm for AMD "
        "GPU papers; SYCL for portable.\n"
        "    * HPC CPU parallel (OpenMP / MPI / vectorisation) → "
        "C / C++ / Fortran with `mpicc` / `mpic++` / `mpifort` (load "
        "the cluster's MPI module first) and `-fopenmp`.\n"
        "    * Numerical libraries (BLAS / LAPACK / FFTW / HDF5 / "
        "NetCDF) → C / C++ / Fortran linked against the system "
        "module (`module load <library-name>`); Python wrappers "
        "(numpy.linalg / h5py / netCDF4) are acceptable when the "
        "paper itself uses them.\n"
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


async def _run_on_computer(computer, cmd: str):
    """Run ``cmd`` INSIDE the agent's actual execution environment via the
    vendor ComputerInterface (not the solver host). Returns
    ``(exit_code|None, output_str)``; (None, "") on failure."""
    try:
        r = await computer.send_shell_command(cmd)
        return r.exit_code, r.unicode_output_best_effort
    except Exception as e:  # noqa: BLE001
        log.debug("computer probe failed (%s): %s", cmd[:40], e)
        return None, ""


async def _probe_gpu_on_computer(computer) -> dict:
    """Multi-stage GPU detection ON the computer. nvidia-smi may be absent
    from PATH (needs ``module load`` on some clusters) yet a GPU still be
    present — so a single failed nvidia-smi must NOT be read as 'no GPU'
    (that would wrongly tell the agent CPU-only and suppress CUDA). Fall
    back through device files / lspci / SLURM allocation env."""
    g = {"present": False, "name": "", "compute_cap": "", "sm": "",
         "count": "", "mem": "", "via": ""}
    # Stage 1: nvidia-smi (name + compute capability + count + memory)
    rc, out = await _run_on_computer(
        computer,
        "nvidia-smi --query-gpu=name,compute_cap,count,memory.total "
        "--format=csv,noheader 2>/dev/null")
    if rc == 0 and out.strip():
        p = [x.strip() for x in out.strip().splitlines()[0].split(",")]
        if p and p[0]:
            g.update(present=True, via="nvidia-smi", name=p[0])
            if len(p) > 1 and p[1]:
                g["compute_cap"] = p[1]
                g["sm"] = p[1].replace(".", "")
            if len(p) > 2:
                g["count"] = p[2]
            if len(p) > 3:
                g["mem"] = p[3]
            return g
    # Stage 2: NVIDIA device files (GPU present even if nvidia-smi absent)
    rc, out = await _run_on_computer(
        computer, "ls /dev/nvidia0 >/dev/null 2>&1 && echo PRESENT")
    if "PRESENT" in out:
        g.update(present=True, via="/dev/nvidia* (nvidia-smi not on PATH — "
                 "load the CUDA module, then `nvidia-smi --query-gpu=compute_cap` "
                 "to get the -arch=sm_XX value)")
        return g
    # Stage 3: lspci
    rc, out = await _run_on_computer(
        computer, "lspci 2>/dev/null | grep -i nvidia | head -1")
    if out.strip():
        g.update(present=True, via="lspci", name=out.strip())
        return g
    # Stage 4: SLURM GPU allocation env
    rc, out = await _run_on_computer(
        computer,
        'echo "CVD=${CUDA_VISIBLE_DEVICES}|GRES=${SLURM_JOB_GRES}|'
        'ORD=${GPU_DEVICE_ORDINAL}"')
    cvd = ""
    m = re.search(r"CVD=([^|]*)", out or "")
    if m:
        cvd = m.group(1).strip()
    if (cvd and cvd not in ("", "NoDevFiles")) or "gpu" in (out or "").lower():
        g.update(present=True, via="SLURM allocation env (CUDA_VISIBLE_DEVICES)")
    return g


async def _probe_env_on_computer(computer):
    """Detect the runtime env INSIDE the computer (container/node), not the
    solver host. Correct for docker/apptainer/slurm sandboxes where the
    solver process and the agent's computer differ. Returns an env dict in
    the same shape as :func:`_detect_runtime_env` plus a ``gpu`` sub-dict,
    or ``None`` on failure (caller falls back to host-side detection)."""
    if computer is None:
        return None
    rc, _ = await _run_on_computer(computer, "true")
    if rc is None:
        return None  # computer not reachable → fall back to host detection
    import re as _re  # noqa: F401  (re used below; ensure available)
    _, apt = await _run_on_computer(computer, "command -v apt-get >/dev/null 2>&1 && echo Y")
    rc_sudo, _ = await _run_on_computer(computer, "sudo -n true 2>/dev/null")
    _, dk = await _run_on_computer(computer, "command -v docker >/dev/null 2>&1 && echo Y")
    _, mod = await _run_on_computer(
        computer, 'bash -lc "command -v module >/dev/null 2>&1 && echo HASMOD; '
        'printf MP=%s \\"$MODULEPATH\\"" 2>/dev/null')
    _, slurm = await _run_on_computer(
        computer, 'echo "JID=${SLURM_JOB_ID}|PART=${SLURM_JOB_PARTITION}"')
    _, dockerenv = await _run_on_computer(computer, "test -f /.dockerenv && echo DOCKER")
    part = ""
    m = re.search(r"PART=([^|]*)", slurm or "")
    if m:
        part = m.group(1).strip()
    jid = ""
    m = re.search(r"JID=([^|]*)", slurm or "")
    if m:
        jid = m.group(1).strip()
    mp = ""
    m = re.search(r"MP=(\S+)", mod or "")
    if m and m.group(1) not in ("", "MP="):
        mp = m.group(1).strip()
    if jid or part:
        kind = "slurm"
    elif "DOCKER" in (dockerenv or ""):
        kind = "docker"
    else:
        kind = "local"
    return {
        "kind": kind,
        "has_apt": "Y" in (apt or ""),
        "has_sudo": rc_sudo == 0,
        "has_module": "HASMOD" in (mod or "") or bool(mp),
        "has_docker": "Y" in (dk or ""),
        "module_path": mp or None,
        "slurm_partition": part or None,
        "gpu": await _probe_gpu_on_computer(computer),
        "_via": "computer",
    }


def _reconcile_vendor_env_claims(out: str, env: dict) -> str:
    """Rewrite the STATIC vendor instructions.txt body claims (fresh Ubuntu
    Docker container / NVIDIA A10 / 'container toolkit already installed' /
    'Docker has been installed') so they match the ACTUAL runtime env. Only
    applied when the real env is NOT a Docker container (kind != docker) —
    in vanilla PaperBench Docker grading the vendor body is true and is left
    untouched. Each substitution no-ops if the anchor text is absent (robust
    to vendor wording drift)."""
    if env.get("kind") == "docker":
        return out
    gpu = env.get("gpu") or {}
    if gpu.get("present") and gpu.get("name"):
        if gpu.get("sm"):
            gpu_phrase = (
                f"{gpu['name']} (compute capability {gpu.get('compute_cap','?')} "
                f"→ build with `nvcc -arch=sm_{gpu['sm']}`; see ADDITIONAL "
                f"NOTES). The CUDA toolkit is NOT pre-installed — `module "
                f"load` it (see the module catalog below)")
        else:
            gpu_phrase = (
                f"{gpu['name']} (detected via {gpu.get('via','probe')}; run "
                f"`nvidia-smi --query-gpu=compute_cap` after loading the CUDA "
                f"module to get the -arch value). The CUDA toolkit is NOT "
                f"pre-installed — `module load` it")
    else:
        gpu_phrase = ("the GPU described in ADDITIONAL NOTES. The CUDA toolkit "
                      "is NOT pre-installed — `module load` it if a GPU is present")
    subs = [
        (r"copy your\s+submission to a fresh Ubuntu 24\.04 LTS Docker container "
         r"and run\s+`bash reproduce\.sh`\s+from the submission directory",
         "run `bash reproduce.sh` in a FRESH SHELL on the same cluster (NOT a "
         "Docker container; see ADDITIONAL NOTES for the real environment — "
         "no apt-get, module system enabled), from the submission directory"),
        (r"The container will have access to an NVIDIA A10 GPU, with the NVIDIA\s+"
         r"container toolkit already installed\.",
         f"Your environment provides {gpu_phrase}."),
        (r"\s*Docker has been installed in your environment, should you wish to "
         r"use it\.",
         "" if not env.get("has_docker") else
         " Docker has been installed in your environment, should you wish to use it."),
    ]
    # NOTE: we deliberately do NOT edit the strawberry toy example's
    # `apt-get install` line. The toy is a pedagogical FORMAT example for a
    # different task; injecting an env note into its code block is incoherent
    # and redundant — the ADDITIONAL NOTES already state authoritatively that
    # apt-get is unavailable (prefer pip / module / source-build).
    for pat, repl in subs:
        out = re.sub(pat, repl, out)
    # Enrich the ADDITIONAL NOTES Compute line with compute-capability / arch.
    if gpu.get("present") and gpu.get("sm"):
        out = re.sub(
            r"- \*\*Compute\*\*:[^\n]*",
            (f"- **Compute**: {gpu['name']} ×{gpu.get('count','?')}, "
             f"{gpu.get('mem','?')}, compute capability {gpu.get('compute_cap','?')} "
             f"→ compile with `nvcc -arch=sm_{gpu['sm']}` (detected via "
             f"{gpu.get('via','nvidia-smi')}). The CUDA toolkit/nvcc is NOT "
             f"pre-installed — `module load` the CUDA module shown in the "
             f"catalog below."),
            out, count=1)
    return out


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
        # Detect the env INSIDE the agent's computer (correct for
        # docker/apptainer/slurm). Fall back to host-side detection if the
        # computer can't be probed (preserves prior local-sandbox behaviour).
        computer = args[0] if args else kwargs.get("computer")
        env = None
        if computer is not None:
            try:
                env = await _probe_env_on_computer(computer)
            except Exception as e:  # noqa: BLE001
                log.warning("vendor patch: computer-side env probe failed "
                            "(%s); falling back to host detection", e)
        if env is None:
            env = _detect_runtime_env()
        replacement = _build_truthful_env_block(env)
        if replacement != _VENDOR_ROOT_ACCESS_LINE and _VENDOR_ROOT_ACCESS_LINE in out:
            out = out.replace(_VENDOR_ROOT_ACCESS_LINE, replacement)
        # Reconcile the static vendor body env claims (Docker/A10/toolkit/
        # 7-day) with the detected truth so the agent isn't fed a
        # contradictory environment description.
        out = _reconcile_vendor_env_claims(out, env)
        log.info(
            "vendor patch: env-truth applied (via=%s kind=%s has_module=%s "
            "has_apt=%s has_sudo=%s gpu=%s)",
            env.get("_via", "host"), env.get("kind"), env.get("has_module"),
            env.get("has_apt"), env.get("has_sudo"),
            (env.get("gpu") or {}).get("name") or (env.get("gpu") or {}).get("present"),
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


# ─── vendor patch: multi-language counter-example ─────────────────────────
#
# Vendor instructions.txt L39-93 contains a CONCRETE EXAMPLE — counting
# letter 'r' in "strawberry" via a Python count.py script with a
# `python3 count.py` reproduce.sh. This is the ONLY concrete example
# the agent sees. LLMs anchor heavily on concrete examples (much more
# than on abstract "use any language" advice elsewhere in the prompt),
# so the strawberry-in-Python example primes the agent toward Python
# for ALL reproductions, including HPC papers about CUDA / MPI /
# Fortran where Python would never be the native choice.
#
# SC41406 dogfood v2 (job 179341): 49 bash calls, 48 invoke python3
# despite the env-truth + language-choice prompts saying "Python is
# illustration only". The bias is rooted in the strawberry example
# example, not in our env-truth abstract text.
#
# Fix: append a COUNTER-EXAMPLE block AFTER vendor's strawberry case,
# showing the same trivial-reproducer pattern in C++/CUDA, Fortran +
# OpenMP/MPI, and Rust. The agent now sees that reproduce.sh is
# fundamentally language-agnostic — the format (bash → invoke
# native-language binary → produce output.csv) stays the same; only
# the implementation language changes per paper. Opt-out via
# ``ARI_PB_DISABLE_MULTILANG_EXAMPLE=1`` for vendor-leaderboard parity.

_MULTILANG_DISABLE_ENV = "ARI_PB_DISABLE_MULTILANG_EXAMPLE"
_STRAWBERRY_EXAMPLE_END_MARKER = (
    "the python script for counting"
)
_MULTILANG_COUNTER_EXAMPLE = """

OTHER LANGUAGES — same pattern, different stack
------------------------------------------------
The strawberry example uses Python because it is the smallest possible
illustration. The REPRODUCE.SH PATTERN — `bash` script that invokes a
native-language binary and produces a deterministic output artifact —
is language-agnostic. Match the paper's native language stack:

# HPC GPU paper (CUDA kernel) — reproduce.sh:
#   module load <cluster's CUDA module>   # see env-truth catalog above
#   nvcc -std=c++17 -arch=sm_XX -O3 count.cu -o count
#   ./count strawberry > output.csv

# HPC CPU paper (MPI + OpenMP) — reproduce.sh:
#   module load <cluster's MPI module>    # e.g., from `module avail`
#   mpicc -fopenmp -O3 count.c -o count
#   mpirun -np 4 ./count strawberry > output.csv

# Numerical paper (Fortran + BLAS) — reproduce.sh:
#   module load <cluster's Fortran + BLAS modules>
#   gfortran -fopenmp -O3 count.f90 -lopenblas -o count
#   ./count strawberry > output.csv

# Systems paper (Rust) — reproduce.sh:
#   cargo build --release
#   ./target/release/count strawberry > output.csv

# ML paper (PyTorch) — reproduce.sh:
#   pip install torch
#   python3 count.py --word strawberry --output output.csv

You are NOT required to use Python. Pick whichever language reproduces
the paper's actual artifacts (CUDA kernels for GPU papers, MPI
processes for HPC papers, Rust binaries for systems papers, etc).
A Python proxy of a CUDA / MPI / Fortran paper will fail the
"build / execution / kernel verified" rubric leaves even when the
algorithm shape is correct.

When the example shows `module load <...>` with a placeholder, look up
the actual module name on YOUR cluster via the `Available modules on
this host` catalog (in env-truth ADDITIONAL NOTES) or `module avail`.
Cluster module names are not hardcoded into this template because they
vary across HPC sites.
"""


def _install_multilang_example_patch() -> None:
    """Monkey-patch vendor ``get_instructions`` to APPEND a multi-language
    counter-example after vendor's strawberry-in-Python case. Idempotent.
    Stacks on top of the env-assumption + blacklist-lift patches.
    Skipped when ``ARI_PB_DISABLE_MULTILANG_EXAMPLE=1``.
    """
    if os.environ.get(_MULTILANG_DISABLE_ENV, "") == "1":
        log.info("vendor patch: multi-lang counter-example disabled via %s=1",
                 _MULTILANG_DISABLE_ENV)
        return
    try:
        from paperbench.solvers.basicagent import utils as _v_utils  # type: ignore
    except Exception as e:
        log.warning("vendor patch: cannot locate basicagent.utils for "
                    "multi-lang counter-example: %s; agent will see only "
                    "vendor's Python example", e)
        return
    if getattr(_v_utils.get_instructions, "_ari_multilang_example", False):
        return
    inner = _v_utils.get_instructions

    async def patched(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        out = await inner(*args, **kwargs)
        # Append at end of full instructions (after vendor's strawberry
        # case + ADDITIONAL NOTES). The counter-example needs to be AFTER
        # the strawberry example to function as counter-prime, not before.
        if _STRAWBERRY_EXAMPLE_END_MARKER in out:
            out = out + _MULTILANG_COUNTER_EXAMPLE
            log.info("vendor patch: appended multi-language counter-example "
                     "after strawberry case")
        return out

    patched._ari_multilang_example = True  # type: ignore[attr-defined]
    # Preserve prior sentinels.
    for attr in ("_ari_env_patched", "_ari_blacklist_lifted"):
        if getattr(inner, attr, False):
            setattr(patched, attr, True)
    _v_utils.get_instructions = patched
    log.info("vendor patch: installed multi-language counter-example on "
             "BasicAgent get_instructions")


_install_multilang_example_patch()


# ─── helpers ──────────────────────────────────────────────────────────────


_PAPER_KIND_CLASSIFIER_PROMPT = """\
You are classifying a research paper to advise an LLM agent on which
implementation language stack to use AND which datasets to acquire when
reproducing the paper. Read the paper text below and output a STRICT
JSON object with these fields:

  {
    "native_stack": "<one of: cpp+cuda | cpp+mpi | cpp+openmp | "
                    "fortran+mpi | fortran+openmp | python+pytorch | "
                    "python+jax | python+tensorflow | python+numpy | "
                    "rust | go | c | cpp | js | unknown>",
    "rationale": "<one sentence citing concrete paper evidence>",
    "secondary_hints": ["<optional extra hints like 'CUDA SDK >= 12', "
                        "'MPI process count = 64', 'PyTorch nightly'>"],
    "datasets": [
      {
        "name": "<dataset name as cited in the paper, e.g., 'Miranda'>",
        "domain": "<short description: 'hydrodynamics simulation', "
                  "'ImageNet image classification', etc>",
        "url_hint": "<a search hint the agent can use to find it, e.g., "
                    "'SDRBench Zenodo Miranda', 'HuggingFace squad', "
                    "'github.com/foo/dataset-bar' — leave empty string "
                    "if the paper gives no acquisition pointer>"
      }
    ],
    "libraries": [
      {
        "name": "<software dependency the artifact needs, e.g., "
                "'CUDA Toolkit', 'zstd', 'HDF5', 'cuSZ', 'OpenMPI', "
                "'PyTorch'>",
        "how": "<acquisition channel: 'module' (HPC module system) | "
               "'pip' | 'conda' | 'source-build' (clone+compile) | "
               "'system' (already present) — best guess from the paper>"
      }
    ]
  }

For native_stack pick "unknown" if the paper has no clear computational
stack (e.g., a purely theoretical paper or a mathematical proof). Be
DECISIVE — pick the language stack the paper's AUTHORS would have used
to build the artifact, not the easiest one for an LLM to write.

For datasets, list ALL benchmark datasets the paper evaluates on
(typically named in "Datasets" / "Benchmarks" / "Evaluation Setup"
sections, or in evaluation tables). If the paper uses no external
dataset (e.g., theoretical only / synthetic), return an empty list.
url_hint should be a search hint, not a literal URL — the agent will
use `web_search` / `wget` / `huggingface-cli` to fetch.

For libraries, list the SOFTWARE DEPENDENCIES the paper's artifact needs
to build and run (compilers, CUDA/MPI, compression/IO libs, the paper's
own released codebase if any). Pick the most likely acquisition channel
for each. If the paper is theoretical / pure-synthetic with no real
dependencies, return an empty list.

Output ONLY the JSON object, no prose, no markdown fences.

--- PAPER (may be truncated) ---
"""

# Char budget for the paper text fed to the classifier. Must be large
# enough to reach the Evaluation/Experiments section: native_stack is
# decidable from the intro/method (early), but the dataset list lives in
# the evaluation tables (often past char ~30k). 16k truncation silently
# starved dataset extraction — every paper that introduces its datasets
# late returned an empty list. 60k covers the evaluation section of a
# typical single paper while keeping the one classifier call cheap.
_CLASSIFIER_PAPER_MAX_CHARS = 60000


async def _build_paper_kind_addendum(
    *,
    paper_md: str,
    classifier_model: str,
    env: dict | None = None,
) -> str:
    """Run a 1-call LLM classifier on the paper, return the addendum.md
    text the agent will see (or empty string on classifier failure).

    The addendum is written to vendor's canonical
    ``/home/paper/addendum.md`` extension point; vendor's
    instructions.txt:17 already tells the agent to read it. No
    monkey-patching, no template replacement — pure data injection
    through a vendor-supported channel.

    The addendum text contains:
      - the classifier's ``native_stack`` decision + rationale
      - a recommended reproduce.sh shape for that stack
      - a brief cautionary note grounded in past dogfood data
        (SC41406 v1 = 14.45%, v2 = 0.8%, with Python proxy for a CUDA
        paper — the agent should learn from this)

    ``classifier_model`` reuses the same model id as the agent (so we
    only pay for one model setup); we send a small completion request
    and parse the JSON. On failure (rate limit, malformed JSON, no
    API key) returns empty string and the caller continues without
    addendum.
    """
    import json
    try:
        from openai import AsyncOpenAI
    except Exception as e:
        log.warning("paper-kind classifier: openai SDK unavailable (%s)", e)
        return ""
    # Use OpenAI Responses or Chat depending on model id (mirror the
    # same model-id heuristic the rollout uses).
    is_openai_responses = (
        classifier_model.startswith(("gpt-", "o1-", "o3-", "o4-", "o5-"))
        and "/" not in classifier_model
    )
    if not is_openai_responses:
        # LiteLLM-routed models — bridge does not yet wire this for the
        # classifier (LiteLLM completer is async but has more setup
        # cost; skip for v0.7.5).
        return ""
    client = AsyncOpenAI()
    prompt = _PAPER_KIND_CLASSIFIER_PROMPT + (paper_md or "")[:_CLASSIFIER_PAPER_MAX_CHARS]
    # gpt-5 / o-series models only accept the default temperature (1)
    # and reject explicit temperature=0. gpt-4* / gpt-3.5 / older
    # models accept 0 and we'd prefer the determinism. Probe via the
    # model id to pick the right call signature; on rejection during
    # the call, fall back to the default-temperature signature.
    is_default_temp_only = classifier_model.startswith(("gpt-5", "o1-", "o3-", "o4-", "o5-"))
    chat_kwargs: dict[str, Any] = {
        "model": classifier_model,
        "messages": [
            {"role": "system", "content": "You are a careful "
                                          "research-paper classifier."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    if not is_default_temp_only:
        chat_kwargs["temperature"] = 0
    try:
        # Chat Completions is the simplest single-turn JSON-mode call;
        # Responses API would also work but is overkill for one shot.
        resp = await client.chat.completions.create(**chat_kwargs)
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:
        log.warning("paper-kind classifier LLM call failed: %s", e)
        return ""

    native = str(data.get("native_stack", "unknown")).strip().lower()
    rationale = str(data.get("rationale", "")).strip()
    secondary = data.get("secondary_hints") or []
    if not isinstance(secondary, list):
        secondary = []
    datasets = data.get("datasets") or []
    if not isinstance(datasets, list):
        datasets = []
    # Defensive: ensure each dataset entry is a dict with the expected
    # keys (LLM may emit malformed entries). Drop anything else.
    sanitized: list[dict] = []
    for d in datasets:
        if not isinstance(d, dict):
            continue
        sanitized.append({
            "name": str(d.get("name", "")).strip(),
            "domain": str(d.get("domain", "")).strip(),
            "url_hint": str(d.get("url_hint", "")).strip(),
        })
    libraries = data.get("libraries") or []
    if not isinstance(libraries, list):
        libraries = []
    sanitized_libs: list[dict] = []
    for lib in libraries:
        if not isinstance(lib, dict):
            continue
        sanitized_libs.append({
            "name": str(lib.get("name", "")).strip(),
            "how": str(lib.get("how", "")).strip(),
        })
    return _format_paper_kind_addendum(
        native=native, rationale=rationale, secondary=secondary,
        env=env, datasets=sanitized, libraries=sanitized_libs,
    )


_REPRODUCE_SH_SHAPES: dict[str, str] = {
    # Each value is the BUILD + RUN portion only (no activation line —
    # activation is rendered separately by `_render_activation_block`
    # based on the host's available mechanisms, so cluster-specific
    # module names are NOT baked in here).
    "cpp+cuda": (
        "# Native language: C++/CUDA\n"
        "nvcc -std=c++17 -arch=sm_XX -O3 src/*.cu -o reproduce_binary\n"
        "./reproduce_binary <args> > output.csv\n"
    ),
    "cpp+mpi": (
        "# Native language: C++ with MPI\n"
        "mpic++ -O3 -std=c++17 src/*.cpp -o reproduce_binary\n"
        "mpirun -np <N> ./reproduce_binary <args> > output.csv\n"
    ),
    "cpp+openmp": (
        "# Native language: C++ with OpenMP\n"
        "g++ -fopenmp -O3 -std=c++17 src/*.cpp -o reproduce_binary\n"
        "OMP_NUM_THREADS=<N> ./reproduce_binary <args> > output.csv\n"
    ),
    "fortran+mpi": (
        "# Native language: Fortran with MPI\n"
        "mpifort -O3 src/*.f90 -o reproduce_binary\n"
        "mpirun -np <N> ./reproduce_binary <args> > output.csv\n"
    ),
    "fortran+openmp": (
        "# Native language: Fortran with OpenMP\n"
        "gfortran -fopenmp -O3 src/*.f90 -o reproduce_binary\n"
        "OMP_NUM_THREADS=<N> ./reproduce_binary <args> > output.csv\n"
    ),
    "python+pytorch": (
        "# Native language: Python + PyTorch\n"
        "pip install torch  # match the version table in the paper\n"
        "python3 train.py <args>\n"
    ),
    "python+jax": (
        "# Native language: Python + JAX\n"
        "pip install jax jaxlib\n"
        "python3 main.py <args>\n"
    ),
    "python+tensorflow": (
        "# Native language: Python + TensorFlow\n"
        "pip install tensorflow\n"
        "python3 main.py <args>\n"
    ),
    "python+numpy": (
        "# Native language: Python with NumPy / SciPy\n"
        "pip install numpy scipy\n"
        "python3 main.py <args>\n"
    ),
    "rust": (
        "# Native language: Rust\n"
        "cargo build --release\n"
        "./target/release/reproduce_binary <args> > output.csv\n"
    ),
    "go": (
        "# Native language: Go\n"
        "go build -o reproduce_binary ./cmd/...\n"
        "./reproduce_binary <args> > output.csv\n"
    ),
    "c": (
        "# Native language: C\n"
        "gcc -O3 -std=c17 src/*.c -o reproduce_binary\n"
        "./reproduce_binary <args> > output.csv\n"
    ),
    "cpp": (
        "# Native language: C++\n"
        "g++ -O3 -std=c++17 src/*.cpp -o reproduce_binary\n"
        "./reproduce_binary <args> > output.csv\n"
    ),
}


def _render_activation_block(env: dict) -> str:
    """Render a one-line toolchain-activation hint based on the host's
    available mechanisms. Bridge does NOT name specific compilers,
    modules, or packages — only the MECHANISM (Lmod / apt / manual)
    and a placeholder for the agent to fill in by inspecting the
    cluster catalog (in env-truth notes) or asking the package manager.
    """
    if env.get("has_module"):
        return (
            "module load <NAME>  "
            "# inspect env-truth `module avail` catalog above; "
            "load the module that provides the build tool you need"
        )
    if env.get("has_apt") and env.get("has_sudo"):
        return (
            "apt-get install -y <PACKAGE>  "
            "# discover the right package via `apt search <keyword>`"
        )
    return (
        "# Activate the required toolchain via YOUR install method "
        "(conda activate, manual SDK install, vendor PATH setup, ...)"
    )


_ARI_AGENT_ONLY_MARKER = (
    "<!-- ARI bridge: agent-only addendum; do NOT pass to judge_addendum -->"
)


def _format_paper_kind_addendum(
    *, native: str, rationale: str, secondary: list,
    env: dict | None = None, datasets: list | None = None,
    libraries: list | None = None,
) -> str:
    """Render the addendum.md text for the agent to consume.

    Includes:
      - paper-kind classifier verdict + rationale
      - a recommended reproduce.sh skeleton for that stack (build line
        only; activation rendered separately based on host env)
      - an env-conditional activation hint (module / apt / manual)
      - a per-paper dataset acquisition table + STEP 1.5 in the runbook
      - a cautionary block on native-stack vs. proxy reproduction

    The activation block is env-conditional so the runbook STEP 1 does
    not push `module load X` on a laptop without Lmod, or
    `apt-get install` on a host without apt. Bridge does NOT name
    specific compilers / modules / packages — the agent matches the
    activation mechanism to the classifier-derived toolchain by
    inspecting the env-truth catalog.
    """
    shape = _REPRODUCE_SH_SHAPES.get(native, "")
    sec_lines = "\n".join(f"  - {s}" for s in secondary if s) if secondary else ""
    activation = _render_activation_block(env or {})
    _native_l = (native or "").lower()
    _native_known = bool(_native_l) and _native_l != "unknown"
    if _native_known and not _native_l.startswith("python"):
        # Native stack is non-Python (CUDA / MPI / Fortran / ...). Make the
        # language requirement IMPERATIVE and neutralise the vendor toy
        # example, whose Python `count.py` otherwise primes the agent to
        # write a Python proxy (observed: agent declared "minimal
        # Python-based reproduction" despite native_stack being CUDA).
        cautionary = (
            "## Cautionary note — IMPLEMENT IN THE NATIVE STACK (mandatory)\n\n"
            f"This paper's native stack is **{native}**. You MUST implement\n"
            "the core artifact in that stack. A Python (or other-language)\n"
            "proxy earns ONLY Code Development credit; EVERY Code Execution\n"
            "and Result Analysis leaf that checks the native build, GPU\n"
            "kernels, kernel launch grid, MPI process count, or\n"
            "native-produced numbers scores 0. This is NOT 'where possible'\n"
            "— for this paper it is required.\n\n"
            "IGNORE THE LANGUAGE OF THE VENDOR TOY EXAMPLE: the\n"
            "strawberry / `count.py` Python script in the standard\n"
            "instructions illustrates submission FORMAT only. It does NOT\n"
            "mean 'write Python'. Do not infer a Python implementation from\n"
            "it. (You MAY use Python for glue / I/O — e.g. h5py to load a\n"
            f"dataset — but the compute kernels themselves must be {native}.)\n"
        )
    else:
        # Python-native or unknown stack: a soft note (Python is correct
        # for python+* papers; nothing to override).
        cautionary = (
            "## Cautionary note (native-stack reproduction)\n\n"
            "Match the paper's native language stack — a proxy\n"
            "reimplementation in a different language scores a small\n"
            "fraction of what a faithful native build earns.\n"
        )
    # Dataset acquisition: list paper-cited datasets and tell the agent
    # to fetch them (web_search → wget / huggingface-cli / git clone).
    # When the classifier returns an empty datasets list (synthetic-only
    # or theoretical paper), the STEP 1.5 block is omitted entirely.
    ds_list = [d for d in (datasets or []) if d.get("name")]
    ds_block = ""
    if ds_list:
        rows = "\n".join(
            f"  - **{d['name']}**" +
            (f" — {d['domain']}" if d.get("domain") else "") +
            (f"  (search hint: `{d['url_hint']}`)" if d.get("url_hint") else "")
            for d in ds_list
        )
        ds_block = (
            "STEP 1.5 — Acquire the paper's evaluation datasets BEFORE\n"
            "  writing reproduce.sh. Paper-cited datasets:\n"
            f"{rows}\n\n"
            "  Acquisition tactics, in order:\n"
            "    1. Resolve the REAL download URL — do NOT skip to synthetic\n"
            "       after one try, and do NOT hand-construct a file URL (a\n"
            "       guessed `zenodo.org/record/<id>/...` or\n"
            "       `huggingface.co/datasets/<name>/...` path almost always\n"
            "       404/401s). Instead:\n"
            "         a. `web_search` the hint above + \"official data\n"
            "            download\" to find the dataset's OFFICIAL project /\n"
            "            registry page (the benchmark's own site, e.g. a\n"
            "            `*.github.io` index, its Zenodo/HuggingFace record).\n"
            "         b. FETCH that page and extract the real file links:\n"
            "            `curl -sL <page> | grep -oE 'https?://[^\"'\\'' ]+\\.(tar\\.gz|tgz|h5|hdf5|f32|bin|dat|nc|zip)'`\n"
            "         c. Pick the link and confirm it with `curl -sIL <url>`\n"
            "            (expect `HTTP .* 200` + a real Content-Length) BEFORE\n"
            "            downloading. If 404/401, go back to (a) — try the\n"
            "            project page again, not a fresh guess.\n"
            "    2. Fetch the confirmed URL via `wget` / `curl` /\n"
            "       `huggingface-cli download` / `git clone` into\n"
            "       `submission/data/`. Network is available — see env-truth\n"
            "       Network claim. Put the EXACT confirmed URL (the one your\n"
            "       `curl -sIL` returned 200 for) into reproduce.sh — NOT a\n"
            "       simplified or guessed variant. Then TEST reproducibility\n"
            "       from a clean state: `rm -rf data && bash reproduce.sh`\n"
            "       and confirm the file re-downloads at full size. The\n"
            "       grader runs reproduce.sh in a fresh shell; a URL that\n"
            "       worked once interactively but 404s in reproduce.sh means\n"
            "       the grader gets no real data (→ 0 Result Analysis).\n"
            "    3. Commit checksums (`sha256sum data/<file> > data/CHECKSUMS`)\n"
            "       so the grader can verify acquisition. Do NOT commit the\n"
            "       data blobs themselves if they exceed 1GB (vendor\n"
            "       instructions.txt L23).\n"
            "    4. If acquisition truly fails (404, paywall, gated), document\n"
            "       the attempt in `submission/data/NOTES.md` and fall back to\n"
            "       synthetic data — but record that this caps the Result\n"
            "       Analysis rubric score because the numbers cannot match\n"
            "       the paper's tables.\n\n"
            "  WHY THIS MATTERS: if you skip dataset acquisition and fall\n"
            "  back to synthetic data, every Result Analysis rubric leaf\n"
            "  that compares against the paper's reported numbers scores\n"
            "  0 — synthetic outputs never match the paper's tables. The\n"
            "  rubric REWARDS real-data evaluations; fetch the real\n"
            "  datasets whenever they are publicly reachable.\n\n"
        )
    # Required-libraries block: the classifier's best guess at the paper's
    # software dependencies + acquisition channel. Omitted when empty
    # (theoretical / pure-synthetic papers). These are HINTS — the agent
    # confirms/augments them; install ALL of them inside reproduce.sh so
    # the grader's fresh shell can build from scratch.
    lib_list = [l for l in (libraries or []) if l.get("name")]
    lib_block = ""
    if lib_list:
        rows = "\n".join(
            f"  - **{l['name']}**" + (f" — via {l['how']}" if l.get("how") else "")
            for l in lib_list
        )
        lib_block = (
            "STEP 1.4 — Required libraries (paper-cited; confirm + augment):\n"
            f"{rows}\n"
            "  Install/load EVERY dependency your code needs INSIDE\n"
            "  reproduce.sh (module load / pip / conda / source-build), so the\n"
            "  grader's fresh shell builds from scratch — do not assume any\n"
            "  are pre-installed beyond what env-truth states.\n\n"
        )
    runbook = (
        "## Recommended first steps (in this order)\n\n"
        "STEP 1 — Verify the toolchain your code needs is reachable in YOUR\n"
        "  iteration shell BEFORE writing any reproduction code:\n"
        f"  ```bash\n  {activation}\n  <BUILD_TOOL> --version  # e.g., nvcc / mpicc / gfortran\n  ```\n"
        "  If the build tool prints a version: ok. If not: try a different\n"
        "  module/package name from the catalog, or ask the package manager.\n\n"
        f"{lib_block}"
        f"{ds_block}"
        "STEP 2 — Copy EVERY activation command you ran in STEP 1 — the\n"
        "  FULL chain, in order — to the TOP of `reproduce.sh`. The grader\n"
        "  runs reproduce.sh in a FRESH shell that inherits NONE of your\n"
        "  interactive module state (Phase 2 isolation note in env-truth\n"
        "  above). On a 2-tier module cluster that means BOTH the entry\n"
        "  module AND the tier-2 module that actually put the build tool on\n"
        "  PATH — e.g.\n"
        "  ```bash\n"
        "  module load <ENTRY>        # switches MODULEPATH; does NOT add the tool yet\n"
        "  module load <TIER-2 NAME>  # this is what puts nvcc/mpicc/... on PATH\n"
        "  ```\n"
        "  A single entry-module load alone usually leaves the toolchain\n"
        "  UNREACHABLE. Confirm by running `<BUILD_TOOL> --version` as the\n"
        "  FIRST lines of reproduce.sh and checking it succeeds — if it\n"
        "  prints 'not found', your chain is incomplete.\n\n"
        "STEP 3 — Write your reproduction code; compile with the verified\n"
        "  toolchain; run end-to-end. reproduce.sh MUST be self-contained\n"
        "  for FROM-SCRATCH reproduction in a fresh shell: (a) module loads\n"
        "  (full chain), (b) install ALL deps it needs — `pip install <pkgs>`\n"
        "  (do NOT use `--user`: it fails inside a venv with 'Can not perform\n"
        "  a --user install'; plain `pip install` or `pip install --prefix`\n"
        "  works), conda, or source-build, (c) fetch data, (d) build, (e) run.\n"
        "  Verify from-scratch by running it in a CLEAN environment, e.g.\n"
        "  `env -i HOME=$HOME bash -lc 'cd submission && bash reproduce.sh'`\n"
        "  (approximates the grader's fresh shell) and confirm it exits 0.\n\n"
        "STEP 4 — MANDATORY FINAL CHECK before calling submit. Run this\n"
        "  sequence in `submission/` and verify ALL THREE conditions:\n"
        "  ```bash\n"
        "  cd submission\n"
        "  git status --porcelain   # MUST print nothing (no untracked / modified)\n"
        "  bash reproduce.sh        # MUST exit 0\n"
        "  echo '[ok] reproduce.sh exits 0'\n"
        "  ```\n"
        "  Call submit ONLY when all three hold:\n"
        "    (a) `git status --porcelain` produced empty output — every file\n"
        "        referenced by reproduce.sh is committed. The grader runs\n"
        "        `git clean -fd` first, so untracked files DO NOT survive\n"
        "        (vendor instructions.txt L84).\n"
        "    (b) reproduce.sh exited 0.\n"
        "    (c) You have implemented the paper's core artifact as\n"
        "        completely as the time budget allows. Do NOT submit a\n"
        "        thin scaffold just because it exits 0 — the rubric\n"
        "        rewards real reproduction of the paper's claims, not\n"
        "        a script that prints \"hello\".\n\n"
        "  TOOL NAME CLARIFICATION: vendor templates.py refers to this as\n"
        "  \"end_task\" but the actual tool in your tool list is named\n"
        "  **`submit`**. Call it as `submit(end_message=\"reproduce.sh\n"
        "  passed; git clean; impl complete\")`. Do NOT just write text\n"
        "  saying \"I'm finished\" — the vendor solver loop only exits\n"
        "  when you call the submit tool (see solver.py:176-177).\n"
    )
    parts = [
        # AGENT-ONLY MARKER: this file is consumed by the Stage 1 agent
        # via the vendor instructions.txt:17 reference to
        # `/home/paper/addendum.md`. It MUST NOT be passed to the
        # Stage 3 SimpleJudge as `judge_addendum=` — past-dogfood
        # data and runbook strings would bias the grader's scoring
        # (the addendum cites prior scores and explicit failure
        # modes, which are inappropriate for the judge to see).
        # bridge.judge_submission's `judge_addendum` param defaults
        # to None and ARI's dogfood scripts never set it; the
        # _ARI_AGENT_ONLY_MARKER regression test enforces this.
        _ARI_AGENT_ONLY_MARKER,
        "",
        "# Paper-kind hint (auto-generated by ARI bridge)",
        "",
        f"native_stack: **{native}**",
    ]
    if rationale:
        parts.append(f"rationale: {rationale}")
    if sec_lines:
        parts.append("secondary_hints:")
        parts.append(sec_lines)
    parts.append("")
    parts.append(runbook)
    if shape:
        parts.append("")
        parts.append("## Recommended `reproduce.sh` skeleton (build + run)\n")
        parts.append("```bash")
        parts.append("# Prepend the activation line you verified in STEP 1:")
        parts.append(f"{activation}")
        parts.append(shape.rstrip())
        parts.append("```")
    parts.append("")
    parts.append(cautionary)
    return "\n".join(parts) + "\n"


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

    .. important::
       ``addendum`` and ``judge_addendum`` are vendor concepts (vendor
       ``simple.py:113`` joins both into ``self.joined_addendum`` which
       is then injected into the judge's prompt). They are intended for
       paper-specific scientific clarifications the original author may
       have added, NOT for ARI's auto-generated paper-kind hint.

       **ARI INVARIANT**: never pass the agent-facing addendum produced
       by ``_format_paper_kind_addendum`` (and lives at
       ``paper/addendum.md`` for the Stage 1 agent only) into either of
       these params. That file contains past-dogfood scores +
       failure-mode tables intended to nudge the agent — exposing it to
       the judge would bias grading. The string
       ``_ARI_AGENT_ONLY_MARKER`` at the top of every bridge-generated
       addendum serves as a guard: callers SHOULD reject inputs that
       contain this marker; the
       ``test_bridge_generated_addendum_carries_agent_only_marker`` test
       enforces the bridge side of the contract.

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

    # GIT isolation: prevent the agent's bash tool from accidentally
    # `git commit`-ing into the outer ARI repo when its iteration shell
    # ends up there (observed in SC41406 v3-A2 — agent did
    # `cd submission/submission && git ... && cd -`, then a later
    # `git status` / `git add .` from the parent dir captured the
    # outer-repo WIP and committed it under a misleading message).
    #
    # Mechanism: GIT_CEILING_DIRECTORIES is a standard git env var that
    # tells `.git` discovery to STOP walking up the directory tree at
    # the listed paths. Setting it to the ARI repo root prevents git
    # from finding ARI/.git when the agent operates from any subdir of
    # ARI — but the agent's OWN submission/.git (inside the workspace,
    # found bottom-up first) still works for its own commits. We
    # detect the outer repo by walking up from work_dir looking for
    # the closest .git that is NOT inside work_dir itself; that's the
    # repo we want to gate.
    if merged_env is None:
        merged_env = {}
    if "GIT_CEILING_DIRECTORIES" not in merged_env:
        outer_repo_root: Path | None = None
        probe = work.parent
        while probe != probe.parent:
            if (probe / ".git").exists():
                outer_repo_root = probe
                break
            probe = probe.parent
        if outer_repo_root is not None:
            merged_env["GIT_CEILING_DIRECTORIES"] = str(outer_repo_root)
            log.info("git isolation: set GIT_CEILING_DIRECTORIES=%s to "
                     "prevent agent from committing into the outer repo",
                     outer_repo_root)

    paper_md_path = work / "_input_paper.md"
    paper_md_path.write_text(paper_md or "", encoding="utf-8")

    # Paper-kind classifier → addendum.md hint (philosophy-pure: bridge
    # inspects the paper via 1 LLM call, writes the result to the vendor's
    # canonical addendum extension point — instructions.txt:17 already
    # tells the agent to read /home/paper/addendum.md, so this lands in
    # the prompt path without any vendor template patching). The agent
    # retains full decision authority; the addendum is informational.
    # Skipped if disabled via ARI_PB_DISABLE_PAPER_KIND_HINT=1.
    addendum_path: Path | None = None
    if (paper_md or "").strip() and not os.environ.get(
        "ARI_PB_DISABLE_PAPER_KIND_HINT", "") == "1":
        try:
            addendum_text = await _build_paper_kind_addendum(
                paper_md=paper_md or "",
                classifier_model=agent_model,
                env=_detect_runtime_env(),
            )
            if addendum_text:
                addendum_path = work / "_input_addendum.md"
                addendum_path.write_text(addendum_text, encoding="utf-8")
                log.info("paper-kind addendum written: %s (%d chars)",
                         addendum_path, len(addendum_text))
        except Exception as e:
            log.warning("paper-kind classifier failed (%s); rollout "
                        "proceeds without addendum hint", e)

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
        paper_addendum_md_path=str(addendum_path) if addendum_path else "",
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
