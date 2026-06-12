"""ReAct agent loop for executing research within a single node.

Design principles:
- AgentLoop is a pure ReAct loop with no domain-specific knowledge
- Experiment-specific settings are injected via WorkflowHints
- Domain-specific terms do not appear in this file
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ari.agent.workflow import WorkflowHints
from ari.llm.client import LLMClient, LLMMessage
from ari.mcp.client import MCPClient
from ari.memory.client import MemoryClient
from ari.orchestrator.node import Node

logger = logging.getLogger(__name__)

MAX_REACT_STEPS = 80  # default; overridden per-instance via AgentLoop(max_react_steps=...)
MIN_TOOL_CALLS = 2

# MCP tools that the parent (ari-core) drives itself and must never be
# exposed to the LLM — otherwise the model could set an arbitrary node
# id and bypass the memory skill's CoW check.
_INTERNAL_MCP_TOOLS = frozenset({"_set_current_node"})

# Clearly placeholder strings (used to detect LLM-fabricated values)
_FAKE_PATTERNS = [
    "found n papers", "[title1]", "[title2]",
    "x.xx speedup", "serial baseline x",
    "actual papers", "actual code", "actual stdout",
    "what was actually done",
]

# Phase PC3 (PROMPTS_AND_CONFIG.md §3-1): the system prompt body lives
# in ``ari/prompts/agent/system.md``.  ``__getattr__`` below exposes the
# legacy ``SYSTEM_PROMPT`` module attribute so external callers and the
# Phase-0 smoke tests keep working without code changes.

_SYSTEM_PROMPT_KEY = "agent/system"


def _system_prompt_template() -> str:
    """Load the agent system prompt template from disk."""
    from ari.prompts import FilesystemPromptLoader
    return FilesystemPromptLoader().load(_SYSTEM_PROMPT_KEY)


def __getattr__(name: str):  # PEP 562 — keep ``SYSTEM_PROMPT`` source-compatible.
    if name == "SYSTEM_PROMPT":
        return _system_prompt_template()
    raise AttributeError(name)

_MEMORY_RULES_PER_NODE = """
- MEMORY: your descendants automatically inherit ONLY this node's final result_summary; \
everything else is lost to them unless you save it. At decision points call \
`add_memory(node_id=\"{node_id}\", text=..., metadata={{\"type\": \"finding\"}})` — a measured \
number that settles a question, a failed approach WITH its root cause, a design choice and why. \
One line each; skip chatter (the raw step log is auto-saved but unstructured and NOT inherited).
- The injected context shows ancestor CONCLUSIONS only. Before re-deriving or re-measuring \
anything an ancestor likely did, call `search_memory(query=..., ancestor_ids=[...], limit=5)` \
to pull their details instead of repeating the work."""

# Global memory tools were removed in v0.6.0 — this block is kept empty
# so the existing call-site conditional can stay.
_MEMORY_RULES_GLOBAL = ""


def _mcp_payload(raw: object) -> dict:
    """Unwrap ``MCPClient.call_tool``'s ``{"result": "<json>"}`` envelope into a dict.

    ``call_tool`` returns ``{"result": "<serialized tool output>"}`` (and may
    return a bare dict or JSON string in tests/fakes). Returns ``{}`` on any
    shape we cannot decode so callers can treat "no data" uniformly.
    """
    import json as _jp
    v: object = raw
    if isinstance(v, dict) and isinstance(v.get("result"), str):
        try:
            v = _jp.loads(v["result"])
        except Exception:
            return {}
    if isinstance(v, str):
        try:
            v = _jp.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


# Working-context injection caps (PLAN_memory_inheritance.md §8 token budget).
# Tunable: validated depth-4 chains injected ~7.5 KB with uncapped core fields
# (verbose primary_metric / metric_rationale). Caps keep per-node memory bounded.
_CORE_FIELD_CAP = 400        # per experiment-core field (1a)
_IDEA_FIELD_CAP = 1500       # selected_idea (design intent) — larger than a scalar
                             # core field: it carries the planned mechanism + target
                             # workloads that descendant nodes must inherit.
_ANCESTOR_SUMMARY_CAP = 600  # per ancestor conclusion (1b)
_SUPPLEMENT_CAP = 400        # per detail-supplement entry (2)

# Run-level invariant USER messages that must survive the react context window
# (matched against the message head). The obligation marker is the first line
# build_contract_obligation emits; the context marker is the (1a) header above.
_PINNED_USER_MARKERS = ("METRIC-CORRECTNESS CONTRACT", "[Experiment context")


def repair_tool_message_order(msgs: list) -> list:
    """Make every assistant-with-tool_calls be followed by its COMPLETE, CONTIGUOUS
    block of tool responses (the API contract).

    Two real failure shapes this repairs (defense-in-depth behind the injection
    deferral): a non-tool message interleaved between an assistant's tool responses
    is MOVED to after the block; an assistant whose responses are not all present
    (e.g. a window cut) is DROPPED together with its orphaned responses instead of
    being sent broken ("tool_call_ids did not have response messages" killed the
    root node on 3 of 5 real runs). Order is otherwise preserved.
    """
    out: list = []
    i, n = 0, len(msgs)
    while i < n:
        m = msgs[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {tc.get("id") for tc in m["tool_calls"]}
            block: list = []
            displaced: list = []
            j = i + 1
            while j < n and need:
                mj = msgs[j]
                if mj.get("role") == "tool" and mj.get("tool_call_id") in need:
                    block.append(mj)
                    need.discard(mj["tool_call_id"])
                elif mj.get("role") == "assistant":
                    break  # responses cannot legally appear past the next assistant
                else:
                    displaced.append(mj)
                j += 1
            if need:
                # incomplete pairing -> drop the assistant + its partial responses;
                # keep the innocent displaced messages in order.
                out.extend(displaced)
            else:
                out.append(m)
                out.extend(block)
                out.extend(displaced)
            i = j
        else:
            out.append(m)
            i += 1
    return out


def _cap(s: str, n: int) -> str:
    """Truncate to n chars with an ellipsis marker when cut."""
    s = s.strip()
    return s if len(s) <= n else s[:n] + " …[truncated]"


def build_working_context_messages(
    call_tool,
    *,
    depth: int,
    ancestor_ids: list[str],
    eval_summary: str | None,
    experiment_goal: str | None,
    work_dir: str = "",
) -> list[dict]:
    """Build the deterministic Tier 1/2 working-context messages for a node.

    See ``PLAN_memory_inheritance.md`` §4-5 (Phase 0). Replaces the prior
    one-shot semantic pre-seed (which truncated up to 5 joined entries to an
    aggregate 800 chars and never injected the experiment core). Parent *code*
    already inherits via work_dir copy and parent *report* via the BFTS planner;
    this injects the bounded, always-relevant working set:

      (1a) experiment core   — applies to every node, previously NOT injected.
      (1b) ancestor core     — each ancestor's conclusions (``result_summary``),
                               deterministic + full (no aggregate truncation).
      (2)  detail supplement — a small per-entry-capped semantic recall, deduped
                               against (1b).

    ``call_tool(name, args) -> dict`` is ``MCPClient.call_tool``. Read-only:
    never writes memory. Returns a (possibly empty) list of
    ``{"role": "user", "content": ...}`` messages to append to the node prompt.
    """
    out: list[dict] = []

    # (1a) Experiment core — stable experiment-level facts (metric, hardware …).
    try:
        ctx = _mcp_payload(call_tool("get_experiment_context", {}))
        ctx_lines = [
            f"  {k}: {_cap(str(ctx.get(k)), _CORE_FIELD_CAP)}"
            for k in ("primary_metric", "higher_is_better", "metric_rationale", "hardware_spec")
            if ctx.get(k) not in (None, "", {}, [])
        ]
        # The selected research idea + plan is the run-level design intent seeded
        # into core memory at the root. Injecting it for EVERY node (not just the
        # root, which alone re-runs generate_ideas) lets a DESCENDANT inherit the
        # planned mechanism and target workloads robustly — instead of only via
        # the inherited source file, which it might never open. Top-down from the
        # common ancestor (root), so it does NOT leak across sibling branches.
        _idea = ctx.get("selected_idea")
        if _idea:
            ctx_lines.append(f"  selected_idea: {_cap(str(_idea), _IDEA_FIELD_CAP)}")
        if ctx_lines:
            out.append({
                "role": "user",
                "content": "[Experiment context (stable across all nodes):]\n" + "\n".join(ctx_lines),
            })
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("experiment-core injection failed: %s", e)

    # (1c) Metric-correctness contract obligation — run-level, idea-owned. The
    # obligation was previously injected ONLY into the node that called
    # make_metric_spec (the root), so the DESCENDANTS that do the bulk of the
    # execution ran BLIND to the declared claims / evidence names / correctness
    # requirement — and the final gate then (correctly) blocked the paper for
    # evidence the executing node was never told to produce. Read the persisted
    # run-level contract (written by make_metric_spec next to idea.json) and put
    # the obligation in EVERY node's context. No-op for the root (the file does
    # not exist yet at root context-build time; the make_metric_spec result
    # handler injects it there mid-loop), so there is no double injection.
    try:
        import os as _os_mc
        from pathlib import Path as _P_mc
        _ck_mc = _os_mc.environ.get("ARI_CHECKPOINT_DIR", "")
        _mc_path = _P_mc(_ck_mc) / "metric_contract.json" if _ck_mc else None
        if _mc_path is not None and _mc_path.is_file():
            import json as _json_mc
            _mc_obj = _json_mc.loads(_mc_path.read_text())
            if isinstance(_mc_obj, dict) and _mc_obj:
                from ari.agent.metric_contract import (
                    build_contract_obligation,
                    build_coverage_status,
                    build_inherited_data_note,
                    collect_run_measurement_names,
                )
                _obl = build_contract_obligation(_mc_obj)
                if _obl:
                    # Run-level claim coverage: tell THIS node what siblings already
                    # evidenced (names only — no sibling conclusions leak) and which
                    # claims still need a dedicated experiment, so a multi-node tree
                    # divides the claims instead of re-running the headline ten times.
                    # Appended INTO the obligation message so the window pin keeps it.
                    _covst = build_coverage_status(
                        _mc_obj, collect_run_measurement_names(_ck_mc))
                    if _covst:
                        _obl = _obl + "\n\n" + _covst
                    # Lineage chaining (child side): a node whose inherited work_dir
                    # already holds lineage measurements is told so, with the
                    # contract names present — claims computed FROM existing data
                    # (fits, validations, selections) become a visible local option
                    # instead of regressing to a fresh probe. Names/files only.
                    _inh = build_inherited_data_note(_mc_obj, work_dir)
                    if _inh:
                        _obl = _obl + "\n\n" + _inh
                    # Platform-capability facts (probed on the compute partition,
                    # P2c). Without this the contract was platform-safe but the
                    # AGENT was not told: the plan still says e.g. "measure MPKI
                    # via perf", so the node would attempt the missing tool and
                    # burn react steps discovering `command not found`. Data only
                    # (relays the probe's measurements); rides the pinned message.
                    try:
                        _cap_p = _P_mc(_ck_mc) / "platform_capabilities.json"
                        if _cap_p.is_file():
                            _capdata = _json_mc.loads(_cap_p.read_text())
                            _missing = sorted(
                                t for t, ok in (_capdata.get("available") or {}).items()
                                if not ok)
                            if _missing:
                                _obl += (
                                    "\n\nPLATFORM NOTE (verified by probe on "
                                    f"partition {_capdata.get('partition', '?')}): the "
                                    "following tools are NOT available on the compute "
                                    f"nodes: {', '.join(_missing)}. Do not attempt "
                                    "them; use measurements your own code computes.")
                    except Exception:
                        pass
                    out.append({"role": "user", "content": _obl})
                    logger.info(
                        "contract obligation injected into node context (claims=%d)",
                        len(_mc_obj.get("claims") or []),
                    )
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("contract-obligation injection failed: %s", e)

    if not (depth > 0 and ancestor_ids):
        return out

    # (1b) Ancestor core — deterministic, full handoff of each ancestor's
    # conclusions. Fetched per-ancestor via get_node_memory (read-only, scoped)
    # and filtered to result_summary entries; bounded by tree depth so injected
    # whole. Order follows ancestor_ids (root → parent).
    tier1_keys: set[str] = set()
    summaries: list[str] = []
    for aid in ancestor_ids:
        try:
            nm = _mcp_payload(call_tool("get_node_memory", {"node_id": aid}))
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("get_node_memory(%s) failed: %s", aid, e)
            continue
        for ent in nm.get("entries", []) or []:
            md = ent.get("metadata", {}) or {}
            if md.get("type") != "result_summary":
                continue
            txt = (ent.get("text") or "").strip()
            if not txt:
                continue
            key = txt[:120]
            if key in tier1_keys:
                continue
            tier1_keys.add(key)
            summaries.append(_cap(txt, _ANCESTOR_SUMMARY_CAP))  # per-entry cap, NOT an aggregate cut
    if summaries:
        out.append({
            "role": "user",
            "content": (
                f"[Established conclusions from ancestor nodes ({len(summaries)}):]\n"
                + "\n".join(f"- {s}" for s in summaries)
            ),
        })

    # (2) Detail supplement — small semantic recall of ancestor detail beyond the
    # conclusions, per-entry capped and deduped against Tier 1(b). Replaces the
    # prior aggregate [:800] dump. eval_summary is used only as the search query.
    try:
        query = (eval_summary or experiment_goal or "experiment result")[:200]
        supp_raw = _mcp_payload(call_tool("search_memory", {
            "query": query,
            "ancestor_ids": ancestor_ids,
            "limit": 5,
        }))
        supp: list[str] = []
        for ent in supp_raw.get("results", []) or []:
            txt = (ent.get("text") or "").strip()
            if not txt or txt[:120] in tier1_keys:
                continue
            supp.append(_cap(txt, _SUPPLEMENT_CAP))  # per-entry cap
        if supp:
            out.append({
                "role": "user",
                "content": (
                    f"[Related prior findings from ancestors ({len(supp)}):]\n"
                    + "\n".join(f"- {s}" for s in supp)
                ),
            })
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("ancestor-detail supplement failed: %s", e)

    return out


# Phase 3D — message-history helpers extracted to
# ``ari.agent.message_utils``.  Re-imported under the same names so
# any caller (incl. the Phase-0 smoke tests) that did
# ``from ari.agent.loop import _extract_job_ids, _tool_was_called``
# keeps working byte-for-byte.
from ari.agent.message_utils import _extract_job_ids, _tool_was_called  # noqa: F401


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryClient,
        mcp: MCPClient,
        evaluator: object | None = None,
        workflow_hints: WorkflowHints | None = None,
        max_react_steps: int = MAX_REACT_STEPS,
        timeout_per_node: int = 7200,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.mcp = mcp
        self.evaluator = evaluator
        self._slurm_real_stdout: str = ""
        self.hints = workflow_hints or WorkflowHints()
        self.max_react_steps = max_react_steps
        self.timeout_per_node = timeout_per_node
        self._idea_injected = False
        self._idea_context = ""

    # ------------------------------------------------------------------
    # Tool filtering (Phase 3D — bodies in ari.agent.tool_manager)
    # ------------------------------------------------------------------

    def _available_tools_openai(self, suppress: set | None = None, phase: str | None = None) -> list[dict]:
        from ari.agent.tool_manager import available_tools_openai as _at
        return _at(self.mcp, suppress=suppress, phase=phase)

    def _execute_tool_calls(
        self, tool_calls: list[dict], node_id: str | None = None,
    ) -> list[dict]:
        from ari.agent.tool_manager import execute_tool_calls as _et
        return _et(self.mcp, tool_calls, node_id=node_id)

    def _active_tools(
        self,
        all_tools: list[dict],
        messages: list[dict],
        job_ids: list[str],
        exec_called: bool,
        force_all: bool,
    ) -> list[dict] | None:
        from ari.agent.tool_manager import active_tools as _act
        return _act(self.hints, all_tools, messages, job_ids, exec_called, force_all)

    # ------------------------------------------------------------------
    # Step guidance + metrics validation
    # ------------------------------------------------------------------
    #
    # Phase 3D: bodies live in ``ari.agent.guidance``; methods stay as
    # 1-line delegators so subclass overrides + monkeypatches keep
    # working untouched.

    def _guidance(
        self,
        last_tool: str,
        job_ids: list[str],
        tool_outputs: list[str],
        messages: list[dict] | None = None,
    ) -> str | None:
        from ari.agent.guidance import guidance as _guidance_fn
        return _guidance_fn(self.hints, last_tool, job_ids, tool_outputs, messages)

    def _validate_metrics(self, result_str: str, job_ids: list[str], node: Node) -> bool:
        from ari.agent.guidance import validate_metrics as _vm
        return _vm(self.hints, result_str, job_ids, node)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _notify_progress(self, *, force: bool = False) -> None:
        """Flush current node state to tree.json via orchestrator callback.

        The callback is attached by cli.py (``agent._progress_cb``) so the GUI
        Tree view can animate RUNNING transitions and trace_log growth without
        waiting for the entire batch to finish.
        """
        cb = getattr(self, "_progress_cb", None)
        if cb is None:
            return
        try:
            cb(force=force) if force else cb()
        except TypeError:
            try:
                cb()
            except Exception:
                pass
        except Exception:
            pass

    def run(self, node: Node, experiment: dict) -> Node:
        node.mark_running()
        # Notify the orchestrator so tree.json picks up the RUNNING state
        # immediately (before the first LLM round-trip, which can take >30 s).
        self._notify_progress(force=True)
        # NB: ARI_CURRENT_NODE_ID synchronization is now done per-call via
        # MCPClient.call_tool(..., cow_node_id=node.id), which locks the
        # (_set_current_node, write) pair so concurrent BFTS nodes don't
        # race on the shared memory-skill env var. The previous once-per-
        # run _set_current_node was unsafe at max_parallel_nodes > 1.
        # Inject work_dir BEFORE forking MCP servers (env snapshot taken at fork time).
        # Directory creation is handled by PathManager in cli.py; this only sets the env var.
        _work_dir_early = experiment.get("work_dir", "") if isinstance(experiment, dict) else ""
        if _work_dir_early:
            import os as _os_early
            _os_early.environ["ARI_WORK_DIR"] = _work_dir_early
            _os_early.makedirs(_work_dir_early, exist_ok=True)  # idempotent safety net
        # Expose the checkpoint dir to skill subprocesses (same pre-fork timing as
        # ARI_WORK_DIR) so make_metric_spec/survey can read the idea-stage
        # primary_metric (evaluation_criteria.json/idea.json) and the frozen VirSci
        # snapshot instead of re-deriving from the seed line / re-querying S2.
        _ckpt_early = getattr(self, "checkpoint_dir", None)
        if _ckpt_early:
            import os as _os_ckpt
            _os_ckpt.environ["ARI_CHECKPOINT_DIR"] = str(_ckpt_early)
        tools = self._available_tools_openai(suppress=getattr(self, "_suppress_tools", set()), phase="bfts")
        tool_names = [t["function"]["name"] for t in tools] if tools else []
        tool_desc = ", ".join(tool_names) if tool_names else "none"
        has_exec = any(n in ("run_bash", "run_code") for n in tool_names)

        label_hint = node.label.system_hint() if hasattr(node, "label") else ""
        # work_dir: per-node experiment directory (passed via experiment dict)
        work_dir = experiment.get("work_dir", "") if isinstance(experiment, dict) else ""
        slurm_partition = experiment.get("slurm_partition", "") if isinstance(experiment, dict) else ""
        slurm_max_cpus = experiment.get("slurm_max_cpus", 0) if isinstance(experiment, dict) else 0
        hpc_hint = ""
        if slurm_partition:
            hpc_hint += f"\n  - SLURM partition: {slurm_partition}"
        if slurm_max_cpus:
            hpc_hint += f"\n  - Max CPUs available: {slurm_max_cpus}"
        # Container environment — tell the LLM it is already inside a container
        # so it does not try to build/pull another image as a setup step.
        import os as _os_ct
        import platform as _plat_ct
        _ct_image = _os_ct.environ.get("ARI_CONTAINER_IMAGE", "").strip()
        _ct_mode = _os_ct.environ.get("ARI_CONTAINER_MODE", "").strip()
        container_hint = ""
        if _ct_image:
            _arch = _plat_ct.machine()
            container_hint = (
                f"\n  - Container: already running inside `{_ct_image}`"
                f" (runtime={_ct_mode or 'auto'}, arch={_arch})."
                f" Commands issued via run_bash execute inside this container."
                f" Do NOT build, pull, or switch container images — reuse this one."
            )
        # List provided files already present in work_dir
        _provided_hint = ""
        if work_dir:
            import os as _os_ls
            try:
                _files_in_wd = [
                    f for f in _os_ls.listdir(work_dir)
                    if _os_ls.path.isfile(_os_ls.path.join(work_dir, f))
                ]
                if _files_in_wd:
                    _file_list = ", ".join(sorted(_files_in_wd))
                    _provided_hint = f"\n  - Provided files (ready to use): {_file_list}"
            except OSError:
                pass
        _env_body = hpc_hint + container_hint
        work_dir_hint = (
            f"\n\nEXPERIMENT ENVIRONMENT:"
            f"\n  - Work directory (REQUIRED): {work_dir} — write ALL files here, cd here first"
            + _provided_hint
            + _env_body
            if work_dir else (
                f"\n\nEXPERIMENT ENVIRONMENT:{_env_body}" if _env_body else ""
            )
        )
        budget_hint = (
            f"\n\nRESOURCE BUDGET:"
            f"\n  - Max steps: {self.max_react_steps} (plan accordingly — do not waste steps on unnecessary actions)"
            f"\n  - Time limit: {self.timeout_per_node // 60} minutes per node (you will be terminated if exceeded)"
        )
        extra = (
            (f"\n\nNODE ROLE: {label_hint}" if label_hint else "")
            + work_dir_hint
            + budget_hint
            + (f"\n\n{self.hints.extra_system_prompt}" if self.hints.extra_system_prompt else "")
        )
        memory_rules = ""
        if "add_memory" in tool_names:
            memory_rules += _MEMORY_RULES_PER_NODE.format(node_id=node.id)
        # add_global_memory was removed in v0.6.0 (§3) so the global rules
        # block is always empty — the conditional is kept for future use.
        system_content = _system_prompt_template().format(tool_desc=tool_desc, memory_rules=memory_rules, extra=extra)
        # pass only goal from experiment dict (workflow_hint is injected via post_survey_hint)
        goal_text = experiment.get("goal", "") if isinstance(experiment, dict) else str(experiment)
        # ── Trace: log goal_text before truncation ─────────────────
        import hashlib as _hl_goal
        _goal_hash = _hl_goal.sha256(goal_text.encode()).hexdigest()[:16]
        logger.info(
            "[loop.run] node=%s goal_text: len=%d sha256=%s first100=%r",
            node.id, len(goal_text), _goal_hash, goal_text[:100],
        )
        # truncate goal_text to first 1500 chars if too long
        if len(goal_text) > 1500:
            logger.warning(
                "[loop.run] goal_text truncated: %d -> 1500 chars", len(goal_text),
            )
            goal_text = goal_text[:1500] + "\n...[truncated]"
        # Root node vs child node prompt
        _is_child = node.depth > 0
        if _is_child:
            # Child node: provide specific task context from BFTS label
            _label_desc = {
                "improve":     "Improve performance or accuracy beyond what the parent achieved.",
                "ablation":    "Ablation study: remove or vary one component from the parent approach.",
                "validation":  "Validate the parent result under different conditions or parameters.",
                "debug":       "The parent experiment had issues. Diagnose and fix them.",
                "draft":       "Try a new implementation approach for the same goal.",
            }.get(node.label, "Extend or vary the parent experiment.")
            # Reuse post_survey_hint so child nodes follow the same
            # execution workflow as the parent (e.g. slurm_submit when
            # a scheduler is configured, or run_bash for local mode).
            _workflow_hint = ""
            if self.hints.post_survey_hint:
                _workflow_hint = f"\n\nWorkflow:\n{self.hints.post_survey_hint}"
            user_content = (
                f"Experiment goal:\n{goal_text}\n"
                f"Node: {node.id} depth={node.depth} task={node.label}\n\n"
                f"Task: {_label_desc}\n"
                "The parent node already completed the survey and established a research direction. "
                "Prior results are provided below for context — but they belong to the parent, "
                "NOT to you.\n\n"
                "MANDATORY: You must produce NEW artifacts to count as having run an experiment.\n"
                "  • Inherited files: source code, scripts, configs, compiled binaries.\n"
                "  • NOT inherited: the parent's results.csv, slurm-*.out, run.log, "
                "metrics.json — those have been deliberately excluded so you cannot "
                "silently reuse the parent's numbers.\n"
                "  • Modify or extend the source code to reflect your `task` label "
                "(e.g. `improve` must change the kernel; `ablation` must disable a "
                "component; `validation` must run with different conditions / inputs).\n"
                "  • Re-build (when code changes), re-run, and write fresh result files.\n"
                "  • A node that produces zero added/modified files relative to its "
                "parent will be flagged STERILE by BFTS and its score clamped to 0.0 — "
                "merely reading or quoting the parent's numbers does NOT count as work.\n\n"
                "Implement and run your specific experiment, then return JSON with measurements."
                f"{_workflow_hint}"
            )
        else:
            first_tool = (self.hints.tool_sequence or ["generate_ideas"])[0]
            user_content = (
                f"Experiment goal:\n{goal_text}\n"
                f"Node: {node.id} depth={node.depth}\n\n"
                f"START NOW: call {first_tool}() immediately. "
                f"Do NOT output any text or plan — your first response must be a {first_tool}() tool call.\n\n"
                "WORKFLOW ORDER: (1) generate_ideas() sets the research direction and "
                "primary_metric; (2) make_metric_spec() derives the success metrics from "
                "that primary_metric (NOT from a guessed list); (3) survey() gathers related "
                "literature. The survey results are used to generate citations — without "
                "survey, the paper will have no references."
            )

        # NOTE: Planner plan text injection has been removed
        # When plan text is present, LLM tends to "write a plan" and stops calling tools
        # plan = None  (plan_steps is for debugging only; not included in context)

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # ── Tier 1/2 working-context injection (deterministic, loop-orchestrated) ──
        # PLAN_memory_inheritance.md §4-5 (Phase 0). Replaces the prior one-shot
        # semantic pre-seed (aggregate [:800] dump; experiment core never injected).
        # Read-only; never writes memory. Logic lives in build_working_context_messages
        # (module-level, unit-tested) so it stays mockable and side-effect free.
        # goal_text (from the experiment dict, above) is the reliable in-scope goal;
        # the legacy `self.experiment_goal` attribute is never assigned in this class
        # (the old call sites only survived via short-circuit eval + try/except).
        messages.extend(build_working_context_messages(
            self.mcp.call_tool,
            depth=node.depth,
            ancestor_ids=node.ancestor_ids or [],
            eval_summary=node.eval_summary,
            experiment_goal=goal_text,
            work_dir=work_dir,
        ))

        # Inject long-term (cross-experiment) memory if the tool is available
        if "search_global_memory" in tool_names:
            try:
                _g_query = (self.experiment_goal or node.eval_summary or "")[:200]
                g_result = self.mcp.call_tool("search_global_memory", {
                    "query": _g_query,
                    "limit": 5,
                })
                if isinstance(g_result, str):
                    import json as _j2; g_result = _j2.loads(g_result)
                g_entries = g_result.get("results", []) if isinstance(g_result, dict) else []
                if g_entries:
                    g_summary = "\n".join(
                        f"- {e.get('text', '')}" for e in g_entries if e.get("text")
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            f"[Long-term cross-experiment memory ({len(g_entries)} entries):]\n"
                            f"{g_summary[:800]}\n"
                        ),
                    })
            except Exception as _e:
                logger.debug("search_global_memory failed: %s", _e)

        # Track current node depth for tool filtering
        self._current_node_depth = node.depth

        # Inject work_dir as env var so run_bash defaults to it.
        # Directory creation is handled by PathManager in cli.py.
        import os as _os
        if work_dir:
            _os.environ["ARI_WORK_DIR"] = work_dir
            _os.makedirs(work_dir, exist_ok=True)  # idempotent safety net

        self._slurm_real_stdout = ""  # reset per-run state
        tools_called = 0
        exec_called = False          # whether run_bash / run_code has been called
        tool_outputs: list[str] = []
        contract_pending = False     # last emit_results carried contract_warnings

        for step in range(self.max_react_steps):
            job_ids = _extract_job_ids(messages, self.hints.job_id_key)
            job_output_read = exec_called and bool(job_ids) if self.hints.job_submitter_tool else False

            logger.info("Node %s: step %d tools=%d exec=%s jobs=%s",
                        node.id, step + 1, tools_called, exec_called, job_ids)

            can_finish = tools_called >= MIN_TOOL_CALLS and (exec_called or not has_exec)
            # For non-SLURM (run_bash) experiments: job_done fires when exec ran and output exists
            if self.hints.job_submitter_tool:
                job_done = (exec_called and bool(job_ids)) and bool(tool_outputs)
            else:
                job_done = exec_called and bool(tool_outputs)
            # contract_hold: the last emit_results reported UNMET contract obligations
            # and real budget remains -- do NOT force-finish yet (observed: the agent
            # was tool-stripped right after its first job, leaving 66/80 steps unused
            # and the contract warnings unactionable). Bounded: the hold expires 10
            # steps before the cap, so the anti-doom-loop backstop is preserved.
            contract_hold = contract_pending and step < self.max_react_steps - 10
            force_finish = (job_done and step >= 5 and not contract_hold) or (
                step >= self.max_react_steps - 3 and can_finish)

            active = self._active_tools(tools, messages, job_ids, exec_called, force_finish)
            # force_finish overrides active: allow JSON output without requiring tool call
            if force_finish:
                active = None

            # Build window ensuring tool messages always follow their tool_calls
            # Important: keep survey/generate_ideas results pinned so LLM never loses them
            _PINNED_TOOLS = {"survey", "generate_ideas", "make_metric_spec"}
            # Suppress generate_ideas after first call to prevent looping
            if getattr(self, "_ideas_generated", False):
                _suppress_tools = {"generate_ideas"}
            else:
                _suppress_tools = set()
            def _build_safe_window(msgs: list, keep_tail: int = 20) -> list:
                """Keep system+first-user, pinned tool results, and recent tail.
                Always preserves assistant/tool message pairs."""
                def _validate_pairs(lst):
                    """Drop assistant/tool messages without COMPLETE paired counterparts.
                    ALL tool_call IDs in an assistant message must have responses (subset check)."""
                    all_fulfilled: set = set()
                    for m in lst:
                        if m.get("role") == "tool" and m.get("tool_call_id"):
                            all_fulfilled.add(m["tool_call_id"])
                    valid_assistant_tc_ids: set = set()
                    out = []
                    for m in lst:
                        if m.get("role") == "assistant" and m.get("tool_calls"):
                            tc_ids = {tc["id"] for tc in m["tool_calls"]}
                            if tc_ids <= all_fulfilled:  # ALL must be fulfilled
                                valid_assistant_tc_ids |= tc_ids
                                out.append(m)
                            # else: partial/no match — drop entire assistant message
                        elif m.get("role") == "tool":
                            if m.get("tool_call_id") in valid_assistant_tc_ids:
                                out.append(m)
                            # else: orphaned tool message — drop
                        else:
                            out.append(m)
                    return out

                if len(msgs) <= keep_tail + 4:
                    return _validate_pairs(msgs)
                head = msgs[:2]
                pinned = []
                for i, m in enumerate(msgs[2:], start=2):
                    if m.get("role") == "assistant" and m.get("tool_calls"):
                        names = {tc.get("function", {}).get("name") for tc in m["tool_calls"]}
                        if names & _PINNED_TOOLS:
                            pinned.append(m)
                            tc_ids = {tc["id"] for tc in m["tool_calls"]}
                            for j in range(i + 1, min(i + 4, len(msgs))):
                                nm = msgs[j]
                                if nm.get("role") == "tool" and nm.get("tool_call_id") in tc_ids:
                                    pinned.append(nm)
                    # Run-level invariant USER messages (the metric-contract obligation,
                    # the experiment/idea context) must SURVIVE windowing: they sit
                    # outside head (msgs[:2]) and outside the tail once the
                    # conversation grows, so they silently vanished mid-node — the
                    # agent then reported results with no memory of the contract it
                    # had been implementing (observed on a real run). Both are small
                    # (content-capped at build time).
                    elif m.get("role") == "user" and any(
                            mk in str(m.get("content", ""))[:120] for mk in _PINNED_USER_MARKERS):
                        pinned.append(m)
                # Expand tail: if it starts with a tool message, include preceding assistant
                tail = list(msgs[-keep_tail:])
                if tail and tail[0].get("role") == "tool":
                    tid = tail[0].get("tool_call_id")
                    for m in reversed(msgs[:-keep_tail]):
                        if m.get("role") == "assistant" and m.get("tool_calls"):
                            if any(tc["id"] == tid for tc in m["tool_calls"]):
                                tail = [m] + tail
                                break
                combined = head + pinned + tail
                # Deduplicate by object identity position
                msg_positions = {id(m): i for i, m in enumerate(msgs)}
                seen_pos, deduped = set(), []
                for m in combined:
                    pos = msg_positions.get(id(m), -1)
                    if pos not in seen_pos:
                        seen_pos.add(pos)
                        deduped.append(m)
                result = _validate_pairs(deduped)
                # Compress old tool results in the window to save context.
                # Keep the last 3 tool results full; compress earlier ones.
                _tool_indices = [i for i, m in enumerate(result) if m.get("role") == "tool"]
                _compress_cutoff = _tool_indices[-3] if len(_tool_indices) >= 3 else -1
                for i in _tool_indices:
                    if i >= _compress_cutoff:
                        break
                    c = result[i].get("content", "")
                    if len(c) > 500:
                        result[i] = {**result[i], "content": c[:200] + "\n...[compressed]...\n" + c[-200:]}
                return result
            window = _build_safe_window(messages)
            window = repair_tool_message_order(window)
            # Validate message ordering before sending to LLM
            _prev_was_tc = False
            _pending_tc_ids: set = set()
            for _wm in window:
                _wr = _wm.get("role")
                if _wr == "assistant" and _wm.get("tool_calls"):
                    _pending_tc_ids = {tc["id"] for tc in _wm["tool_calls"]}
                    _prev_was_tc = True
                elif _wr == "tool":
                    if not _pending_tc_ids or _wm.get("tool_call_id") not in _pending_tc_ids:
                        logger.error(
                            "Node %s step %d: orphan tool message tool_call_id=%r "
                            "pending_tc_ids=%r — dropping window tail to recover",
                            node.id, step, _wm.get("tool_call_id"), _pending_tc_ids
                        )
                        # Emergency: truncate window to exclude orphan tool messages
                        _safe_idx = window.index(_wm)
                        window = window[:max(2, _safe_idx - 1)]
                        break
                    _pending_tc_ids.discard(_wm.get("tool_call_id"))
                    if not _pending_tc_ids:
                        _prev_was_tc = False
                else:
                    _pending_tc_ids = set()
                    _prev_was_tc = False
            # Pass window as raw dicts to preserve tool_calls/tool_call_id fields
            llm_msgs = window
            effective_tools = active if active is not None else tools
            # force_finish: active=None → effective_tools=tools but require_tool=False
            response = self.llm.complete(
                llm_msgs, tools=effective_tools, require_tool=(active is not None),
                node_id=node.id, phase="react", skill="agent_loop",
            )

            if response.tool_calls:
                # Reject tool calls outside of active_tools
                if active is not None:
                    allowed = {t["function"]["name"] for t in active}
                    bad = [tc for tc in response.tool_calls
                           if tc["function"]["name"] not in allowed]
                    if bad:
                        bad_name = bad[0]["function"]["name"]
                        logger.warning("Node %s: rejected '%s' (allowed: %s)",
                                       node.id, bad_name, sorted(allowed))
                        messages.append({"role": "assistant",
                                         "content": f"[attempted {bad_name}]"})
                        messages.append({"role": "user", "content": (
                            f"'{bad_name}' is not available now. "
                            f"Use one of: {sorted(allowed)}"
                        )})
                        continue

                messages.append({
                    "role": "assistant",
                    "content": response.content or None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["function"]["name"],
                                      "arguments": tc["function"]["arguments"]}}
                        for tc in response.tool_calls
                    ],
                })

                results = self._execute_tool_calls(response.tool_calls, node_id=node.id)
                # Build args lookup by tool name for trace logging
                _tc_args_by_name = {
                    tc.get("function", {}).get("name", ""): tc.get("function", {}).get("arguments", "")
                    for tc in response.tool_calls
                }
                executed_names: list[str] = []
                # Handler-driven USER injections (idea summary, contract obligation,
                # emission nudge) must NOT be appended inside this loop: with an
                # assistant that batched 2+ tool_calls, a user message would land
                # BETWEEN its tool responses, which the API rejects ("tool_call_ids
                # did not have response messages") — this killed the ROOT node on
                # 3 of 5 real runs, right after make_metric_spec. Collect here,
                # extend after the loop (i.e. after the contiguous tool block).
                _deferred_user_msgs: list = []
                for r in results:
                    rc = json.dumps(r["result"], ensure_ascii=False)
                    _FULL_LOG_TOOLS = {"generate_ideas", "survey", "make_metric_spec"}
                    _log_limit = len(rc) if r["name"] in _FULL_LOG_TOOLS else 200
                    logger.info("Tool call: %s -> %s", r["name"], rc[:_log_limit])
                    if r["name"] in _FULL_LOG_TOOLS:
                        print(f"[TOOL] {r['name']} -> {rc[:_log_limit]}", flush=True)
                    else:
                        print(f"[TOOL] {r['name']}", flush=True)
                    # Record in node trace for viz
                    if hasattr(node, "trace_log"):
                        _args_preview = str(_tc_args_by_name.get(r["name"], ""))[:4000]
                        _res_preview = str(r.get("result", ""))
                        node.trace_log.append(f"→ {r['name']}({_args_preview})")
                        if _res_preview:
                            node.trace_log.append(f"  ← {_res_preview}")
                        # Push an incremental tree.json update so the GUI shows
                        # tool-call progress live (throttled inside the callback).
                        self._notify_progress()
                    # Save code artifacts from run_bash/slurm_submit for viz
                    if r["name"] in ("run_bash", "run_code", "slurm_submit"):
                        try:
                            _args_raw = _tc_args_by_name.get(r["name"], "")
                            _args_d = json.loads(_args_raw) if isinstance(_args_raw, str) else _args_raw
                            _code = _args_d.get("code") or _args_d.get("command") or _args_d.get("script", "")
                            if _code and hasattr(node, "artifacts"):
                                node.artifacts.append({
                                    "type": "code",
                                    "tool": r["name"],
                                    "content": _code[:16000],
                                    "step": step,
                                })
                        except Exception:
                            pass
                    try:
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"Tool {r['name']}: {rc[:1000]}",
                            "metadata": {"step": step, "tool": r["name"]},
                        }, cow_node_id=node.id)
                    except Exception:
                        self.memory.add(
                            f"Tool {r['name']}: {rc[:1000]}",
                            metadata={"node_id": node.id, "step": step},
                        )
                    # Truncate long tool results to save context window.
                    # For execution tools, keep head + tail to preserve both
                    # compilation errors (early) and benchmark results (late).
                    _MAX_TOOL_RESULT = 4000
                    if len(rc) > _MAX_TOOL_RESULT:
                        if r["name"] in ("run_bash", "run_code", "slurm_submit"):
                            _head = rc[:1500]
                            _tail = rc[-1500:]
                            rc = _head + f"\n...[truncated {len(rc) - 3000} chars]...\n" + _tail
                        else:
                            rc = rc[:_MAX_TOOL_RESULT] + "...[truncated]"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": r["tool_call_id"],
                        "content": rc,
                    })
                    executed_names.append(r["name"])

                    # survey result: save abstracts to memory (for LLM to use in subsequent steps)
                    if r["name"] == "survey":
                        try:
                            survey_data = json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
                            papers = survey_data.get("papers", [])
                            if papers:
                                summary = "SURVEY RESULTS:\n" + "\n".join(
                                    f"- [{p.get('title','')}]: {p.get('abstract','')[:200]}"
                                    for p in papers[:5]
                                )
                                try:
                                    self.mcp.call_tool("add_memory", {
                                        "node_id": node.id,
                                        "text": summary,
                                        "metadata": {"type": "survey_papers"},
                                    }, cow_node_id=node.id)
                                except Exception:
                                    self.memory.add(
                                        summary,
                                        metadata={"type": "survey_papers", "node_id": node.id},
                                    )
                                # The LLM in the loop will read abstracts and reason in the next step
                                tool_outputs.append(summary)
                        except Exception:
                            pass

                    # job_status COMPLETED + stdout present → actual measurement flag
                    if r["name"] == self.hints.job_reader_tool:
                        try:
                            _raw_r = r["result"]
                            if isinstance(_raw_r, str):
                                _raw_r = json.loads(_raw_r)
                            _inner_r = (_raw_r.get("result") or _raw_r) if isinstance(_raw_r, dict) else {}
                            if isinstance(_inner_r, str):
                                _inner_r = json.loads(_inner_r)
                            _stdout_r = ""
                            if isinstance(_inner_r, dict):
                                if _inner_r.get("status") == "COMPLETED":
                                    _stdout_r = _inner_r.get("stdout", "")   # SLURM format
                                elif "stdout" in _inner_r:
                                    _stdout_r = _inner_r.get("stdout", "")   # run_bash format
                            if _stdout_r.strip():
                                self._slurm_real_stdout = _stdout_r.strip()
                        except Exception:
                            pass

                    # generate_ideas call: capture primary_metric and higher_is_better
                    # Track that generate_ideas was called to prevent repeated calls
                    if r["name"] == "generate_ideas":
                        self._ideas_generated = True
                        self._suppress_tools = {"generate_ideas"}
                        try:
                            idea_raw = r["result"]
                            if isinstance(idea_raw, str):
                                import re as _re_gi
                                _m = _re_gi.search(r"\{.*\}", idea_raw, _re_gi.DOTALL)
                                idea_data = json.loads(_m.group(0)) if _m else {}
                            else:
                                idea_data = idea_raw if isinstance(idea_raw, dict) else {}
                            if isinstance(idea_data, dict) and "result" in idea_data:
                                _inner = idea_data["result"]
                                idea_data = json.loads(_inner) if isinstance(_inner, str) else _inner
                            # Persist full idea data to checkpoint for Idea tab
                            try:
                                _ckpt = getattr(self, "checkpoint_dir", None)
                                if _ckpt:
                                    _idea_path = Path(_ckpt) / "idea.json"
                                    _idea_path.write_text(json.dumps(idea_data, ensure_ascii=False, indent=2))
                                    logger.info("Saved idea.json to %s", _idea_path)
                            except Exception as _se:
                                logger.warning("Failed to save idea.json: %s", _se)
                            pm = idea_data.get("primary_metric", "")
                            hib = idea_data.get("higher_is_better", True)
                            mr = idea_data.get("metric_rationale", "")
                            if pm:
                                # Persist to memory so pipeline.py can read it
                                try:
                                    self.memory.add(
                                        f"EVALUATION_CRITERIA: primary_metric={pm} higher_is_better={hib} rationale={mr}",
                                        metadata={"type": "evaluation_criteria", "node_id": node.id}
                                    )
                                except Exception as _me:
                                    logger.warning("Failed to save evaluation criteria to memory: %s", _me)
                                # Also update metric_extractor for this run
                                import re as _re_pm
                                _pat_pm = _re_pm.compile(
                                    rf"{_re_pm.escape(pm)}[\s:=]+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
                                    _re_pm.IGNORECASE
                                )
                                self.hints.metric_extractor = (
                                    lambda text, p=_pat_pm: [float(x) for x in p.findall(text)]
                                )
                                logger.info("generate_ideas set primary_metric=%s higher_is_better=%s", pm, hib)
                                # Seed Letta core memory with experiment-level static facts.
                                # Spec: docs/concepts/architecture.md:462-465, docs/reference/skills.md:319-323.
                                # primary_metric is only known after generate_ideas, so we seed
                                # here rather than at the literal moment of checkpoint creation.
                                try:
                                    from ari_skill_memory.backends import get_backend as _gmb
                                    from ari.env_detect import get_environment_summary as _es
                                    _ckpt = getattr(self, "checkpoint_dir", None)
                                    if _ckpt:
                                        _exp_md = Path(_ckpt) / "experiment.md"
                                        _goal = _exp_md.read_text(errors="ignore") if _exp_md.exists() else ""
                                        # Compact selected-idea summary (title + description +
                                        # plan §-titles) seeded into core memory so EVERY node —
                                        # including descendants that never re-run generate_ideas —
                                        # inherits the design intent (planned mechanism, target
                                        # workloads), not just the metric. Run-level invariant.
                                        _best_idea = (idea_data.get("ideas") or [{}])[0] if isinstance(idea_data, dict) else {}
                                        _idea_summary = f"{_best_idea.get('title','')}: {(_best_idea.get('description','') or '')[:400]}"
                                        try:
                                            from ari.pipeline import _extract_plan_sections as _eps_seed
                                            _secs_seed = _eps_seed(_best_idea.get("experiment_plan", "") or "")
                                            if _secs_seed:
                                                _idea_summary += " | Plan: " + "; ".join(
                                                    f"{_t} {_ti}" for _t, _ti, _ in _secs_seed
                                                )
                                        except Exception:
                                            pass
                                        _gmb(checkpoint_dir=Path(_ckpt)).seed_core_memory(
                                            persona="",
                                            human="",
                                            context={
                                                "experiment_goal": _goal,
                                                "primary_metric": pm,
                                                "higher_is_better": hib,
                                                "metric_rationale": mr,
                                                "hardware_spec": _es(),
                                                "selected_idea": _idea_summary,
                                            },
                                        )
                                        logger.info("seeded core memory (pm=%s)", pm)
                                except Exception as _seed_err:
                                    logger.warning("seed_core_memory failed: %s", _seed_err)
                        except Exception as _gie:
                            logger.warning("generate_ideas result parse failed: %s", _gie)

                        # Inject best idea content into conversation so LLM implements it
                        if not self._idea_injected:
                            try:
                                _ij_raw = r["result"]
                                if isinstance(_ij_raw, str):
                                    import re as _re_ij
                                    _mij = _re_ij.search(r"\{.*\}", _ij_raw, _re_ij.DOTALL)
                                    _ij_data = json.loads(_mij.group(0)) if _mij else {}
                                else:
                                    _ij_data = _ij_raw if isinstance(_ij_raw, dict) else {}
                                if isinstance(_ij_data, dict) and "result" in _ij_data:
                                    _ij_inner = _ij_data["result"]
                                    _ij_data = json.loads(_ij_inner) if isinstance(_ij_inner, str) else _ij_inner
                                _ideas_list = _ij_data.get("ideas", [])
                                _gap = _ij_data.get("gap_analysis", "")
                                if _ideas_list:
                                    _best = _ideas_list[0]
                                    # Reach §1〜§7 of the plan, not just §1.
                                    # The legacy ``experiment_plan[:600]`` slice
                                    # truncated past the kernel/parameter section,
                                    # so plan items like §5 b ("real-world graphs
                                    # (power-law), PDE/banded, ML sparsity")
                                    # never made it to the implementing agent —
                                    # producing make_random_csr-only runs that
                                    # SC reviewers correctly flag as synthetic.
                                    # _extract_plan_sections is the same §-tag
                                    # parser cli.py uses for BFTS expand context.
                                    _plan_text = _best.get("experiment_plan", "") or ""
                                    _plan_block = ""
                                    if _plan_text:
                                        try:
                                            from ari.pipeline import _extract_plan_sections as _eps
                                            _secs = _eps(_plan_text)
                                        except Exception:
                                            _secs = []
                                        if _secs:
                                            # Per-section budget keeps the
                                            # injected message bounded even when
                                            # the plan is several KB; total stays
                                            # under ~6 KB of plan body.
                                            _per = max(400, 6000 // max(1, len(_secs)))
                                            _lines = ["Experiment plan sections:"]
                                            for _tag, _t, _b in _secs:
                                                _lines.append(f"  {_tag} {_t}")
                                                if _b:
                                                    _lines.append(f"    {_b[:_per]}")
                                            _plan_block = "\n".join(_lines)
                                        else:
                                            # No §-tags → fall back to a single
                                            # generous slice (4 KB) rather than
                                            # the previous 600-char cut.
                                            _plan_block = f"Experiment plan:\n{_plan_text[:4000]}"
                                    _idea_msg = (
                                        f"RESEARCH DIRECTION (from idea generation):\n"
                                        f"Gap analysis: {_gap[:1500]}\n\n"
                                        f"Selected idea: {_best.get('title', 'Untitled')}\n"
                                        f"Description: {_best.get('description', '')[:2000]}\n"
                                        f"{_plan_block}\n\n"
                                        f"NEXT: call make_metric_spec() (it derives the success metrics "
                                        f"from this idea's primary_metric), then survey(), THEN implement "
                                        f"THIS idea. Follow the experiment plan above — address EVERY "
                                        f"section, not just §1."
                                    )
                                    logger.info(
                                        "[loop.run] idea_injection: title=%r len=%d",
                                        _best.get('title', ''), len(_idea_msg),
                                    )
                                    _deferred_user_msgs.append({"role": "user", "content": _idea_msg})
                                    self._idea_injected = True
                                    self._idea_context = _idea_msg
                                    logger.info("Injected best idea into conversation: %s", _best.get('title', '')[:80])
                            except Exception as _ij_err:
                                logger.warning("Failed to inject idea content: %s", _ij_err)

                    # make_metric_spec call: self-determine evaluation criteria
                    if r["name"] == "make_metric_spec":
                        try:
                            spec_data = json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
                            if isinstance(spec_data, dict) and "result" in spec_data:
                                spec_data = json.loads(spec_data["result"]) if isinstance(spec_data["result"], str) else spec_data["result"]
                            kw = spec_data.get("metric_keyword")
                            expected = spec_data.get("expected_metrics", [])
                            expected_params = spec_data.get("expected_params", [])
                            if not isinstance(expected_params, list):
                                expected_params = []
                            guide = spec_data.get("scoring_guide", "")
                            # update metric_extractor to keyword-based
                            if kw:
                                import re as _re_kw
                                _pat = _re_kw.compile(rf"{kw}[:\s=]+([\d.]+)", _re_kw.IGNORECASE)
                                self.hints.metric_extractor = (
                                    lambda text, p=_pat: [float(x) for x in p.findall(text) if float(x) >= 1.0]
                                )
                            # update MetricSpec in LLMEvaluator
                            if self.evaluator and (expected or expected_params or guide):
                                from ari.evaluator import MetricSpec
                                import re as _re_art
                                _art_pat = _re_art.compile(rf"{kw or 'metric'}[:\s=]+([\d.]+)", _re_art.IGNORECASE) if kw else None
                                def _dyn_extractor(text: str, p=_art_pat) -> dict:
                                    if p is None:
                                        nums = [float(x) for x in _re_art.findall(r"\b(\d+\.\d+|\d{4,})\b", text) if float(x) >= 1.0]
                                        return {"result_" + str(i): v for i, v in enumerate(nums[:20])}
                                    return {f"{kw}_{i}": float(x) for i, x in enumerate(p.findall(text))}
                                self.evaluator.metric_spec = MetricSpec(
                                    name=f"self-determined: {kw or 'generic'}",
                                    expected_metrics=expected,
                                    expected_params=expected_params,
                                    artifact_extractor=_dyn_extractor,
                                    scoring_guide=guide,
                                )
                            logger.info(
                                "ARI self-determined MetricSpec: keyword=%s expected=%s params=%s",
                                kw, expected, expected_params
                            )
                            # Producer obligation: when the metric is concept-classified
                            # (make_metric_spec emitted a metric_contract scaffold), tell the
                            # agent — in DOMAIN-NEUTRAL terms — to verify correctness, MEASURE
                            # (never hardcode) any ceiling, emit provenance, and fill the
                            # contract. The agent fulfils this domain-appropriately; the gate
                            # enforces whatever ends up declared. No-op for unclassified metrics.
                            _mc = spec_data.get("metric_contract") if isinstance(spec_data, dict) else None
                            if _mc:
                                try:
                                    from ari.agent.metric_contract import build_contract_obligation
                                    _obl = build_contract_obligation(_mc)
                                    if _obl:
                                        _deferred_user_msgs.append({"role": "user", "content": _obl})
                                        logger.info(
                                            "contract obligation injected after make_metric_spec (claims=%d)",
                                            len(_mc.get("claims") or []) if isinstance(_mc, dict) else 0,
                                        )
                                except Exception as _oe:
                                    logger.debug("contract obligation injection failed: %s", _oe)
                        except Exception as _e:
                            logger.warning("make_metric_spec result parse failed: %s", _e)

                    # emit_results: surface point-of-emission contract feedback as an
                    # ACTIONABLE turn. The tool result alone was not enough on a real
                    # run -- the node force-finished right after its first job, so the
                    # warnings arrived with no steps to act on them. Track the pending
                    # state (holds force_finish above) and nudge the agent to run the
                    # missing measurement(s) and re-emit while budget remains.
                    if r["name"] == "emit_results":
                        try:
                            _er = r["result"]
                            if isinstance(_er, str):
                                _er = json.loads(_er)
                            if isinstance(_er, dict) and "result" in _er and isinstance(_er["result"], str):
                                _er = json.loads(_er["result"])
                            _cw = (_er or {}).get("contract_warnings") or []
                            if _cw:
                                contract_pending = True
                                _left = self.max_react_steps - step - 1
                                from ari.agent.metric_contract import build_emission_nudge
                                _nudge = build_emission_nudge(_cw, _left)
                                if _nudge:
                                    _deferred_user_msgs.append({"role": "user", "content": _nudge})
                                logger.info(
                                    "emit_results returned %d contract warning(s); continuation nudged (%d steps left)",
                                    len(_cw), _left)
                            else:
                                contract_pending = False
                        except Exception as _e:
                            logger.debug("emit_results contract-warning handling failed: %s", _e)

                    # If job_status COMPLETED contains stdout,
                    # treat as having read experiment output and set exec_called = True
                    if r["name"] == self.hints.job_status_tool:
                        try:
                            _raw = r["result"]
                            # result may be dict, or JSON string, or JSON string containing another JSON string
                            if isinstance(_raw, str):
                                _raw = json.loads(_raw)
                            # _raw may now be {"result": "{...}"} or the inner dict directly
                            if isinstance(_raw, dict) and "result" in _raw and isinstance(_raw["result"], str):
                                _js = json.loads(_raw["result"])
                            elif isinstance(_raw, dict):
                                _js = _raw
                            else:
                                _js = {}
                            if isinstance(_js, dict) and _js.get("status") == "COMPLETED" and _js.get("stdout", "").strip():
                                exec_called = True
                                _stdout_content = _js["stdout"].strip()
                                tool_outputs.append(f"stdout:\n{_stdout_content[:2000]}")
                                logger.info("job_status stdout available → exec_called=True, tool_outputs updated (%d chars)", len(_stdout_content))
                        except Exception as _jse:
                            logger.debug("job_status parse failed: %s", _jse)

                    if r["name"] in ("run_bash", "run_code"):
                        exec_called = True
                        try:
                            inner = json.loads(r["result"])
                            stdout = inner.get("stdout", "").strip()
                            stderr = inner.get("stderr", "").strip()
                            exit_code = inner.get("exit_code", -1)
                            if stdout:
                                tool_outputs.append(f"stdout:\n{stdout}")
                            if stderr and not stderr.isspace():
                                tool_outputs.append(f"stderr: {stderr[:300]}")
                            tool_outputs.append(f"exit_code: {exit_code}")

                            # sbatch submitted via run_bash → record job_id in messages
                            # Only when an async-job workflow is active; skipped for local runs.
                            import re as _re
                            sbatch_match = (
                                _re.search(r"Submitted batch job (\d+)", stdout)
                                if self.hints.job_submitter_tool else None
                            )
                            if sbatch_match:
                                sbatch_jid = sbatch_match.group(1)
                                logger.info("Detected sbatch job %s from run_bash stdout", sbatch_jid)
                                # add a dummy record for polling keyed by job_id_key
                                # OpenAI requires assistant tool_calls before tool message
                                messages.append({
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [{
                                        "id": f"sbatch_inject_{sbatch_jid}",
                                        "type": "function",
                                        "function": {
                                            "name": "slurm_submit",
                                            "arguments": json.dumps({"job_id": sbatch_jid}),
                                        },
                                    }],
                                })
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": f"sbatch_inject_{sbatch_jid}",
                                    "content": json.dumps({self.hints.job_id_key: sbatch_jid, "status": "submitted"}),
                                })
                        except Exception:
                            pass

                if _deferred_user_msgs:
                    messages.extend(_deferred_user_msgs)

                tools_called += len(results)
                last = executed_names[-1] if executed_names else ""

                # recalculate (new job IDs may have been added)
                job_ids = _extract_job_ids(messages, self.hints.job_id_key)

                # job_status is RUNNING/PENDING → poll directly without consuming an LLM step
                logger.debug("Auto-poll check: last=%r poller=%r job_ids=%r has_results=%s", last, self.hints.job_poller_tool, job_ids, bool(results))
                # Auto-poll fires after job_status OR slurm_submit (agent skips manual polling)
                _should_autopoll = (
                    (last == self.hints.job_poller_tool or last == self.hints.job_submitter_tool)
                    and job_ids and results
                )
                if _should_autopoll:
                    try:
                        import time as _time
                        _res = results[-1]["result"]
                        if isinstance(_res, str):
                            _res = json.loads(_res)
                        last_status = _res.get("status", "") if isinstance(_res, dict) else ""
                        # After slurm_submit, status is not yet known → seed with PENDING
                        if last == self.hints.job_submitter_tool:
                            last_status = "PENDING"
                        poll_count = 0
                        while last_status in ("RUNNING", "PENDING", "CONFIGURING") and poll_count < 60:
                            _time.sleep(30)
                            poll_count += 1
                            poll_tc = [{
                                "id": f"autopoll_{poll_count}",
                                "type": "function",
                                "function": {
                                    "name": self.hints.job_poller_tool,
                                    "arguments": json.dumps({"job_id": job_ids[-1]}),
                                },
                            }]
                            poll_results = self._execute_tool_calls(poll_tc, node_id=node.id)
                            rc2 = json.dumps(poll_results[0]["result"], ensure_ascii=False)
                            logger.info("Auto-poll job %s: %s", job_ids[-1], rc2[:100])
                            # OpenAI requires tool message to follow assistant message with tool_calls
                            messages.append({
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": f"autopoll_{poll_count}",
                                    "type": "function",
                                    "function": {
                                        "name": self.hints.job_poller_tool,
                                        "arguments": json.dumps({"job_id": job_ids[-1]}),
                                    },
                                }],
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": f"autopoll_{poll_count}",
                                "content": rc2[:800],
                            })
                            try:
                                _pr = poll_results[0]["result"]
                                if isinstance(_pr, str): _pr = json.loads(_pr)
                                last_status = _pr.get("status", "") if isinstance(_pr, dict) else ""
                                # COMPLETED + stdout → set actual measurement flag here too
                                if last_status == "COMPLETED" and isinstance(_pr, dict) and _pr.get("stdout"):
                                    self._slurm_real_stdout = _pr["stdout"]
                                    logger.info("Auto-poll: captured real SLURM stdout (%d chars)", len(self._slurm_real_stdout))
                            except Exception:
                                break
                    except Exception as _e:
                        logger.warning("Auto-poll error: %s", _e)

                guidance = self._guidance(last, job_ids, tool_outputs, messages)
                if guidance:
                    messages.append({"role": "user", "content": guidance})
                continue

            # ---- No tool call → parse JSON output ----
            # no tool used at step 0 → force prompt (model output a text plan without calling tools)
            if step == 0:
                logger.warning("Node %s: step 1 no tool call, forcing: %r",
                               node.id, (response.content or "")[:80])
                messages.append({"role": "assistant", "content": response.content or ""})
                first_tool = (active[0]["function"]["name"] if active else "survey")
                messages.append({"role": "user", "content": (
                    f"STOP. Do not write plans. Call {first_tool}() NOW."
                )})
                continue

            content = (response.content or "").strip()
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if content.startswith("```"):
                lines = content.split("\n")[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            try:
                result = json.loads(content)
                if isinstance(result, dict) and result.get("status") == "success":
                    # In true ReAct design, only "success" terminates the loop.
                    # "failed" is NOT a valid terminal state from the LLM —
                    # the framework marks failure only when MAX_REACT_STEPS is exhausted.

                    # Reject finish if exec has never been called
                    if has_exec and not exec_called and tools:
                        logger.warning("Node %s: refusing finish - exec not called", node.id)
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": (
                            "You have not called run_bash() or run_code() yet. "
                            "Execute the experiment first."
                        )})
                        continue

                    result_str = json.dumps(result).lower()
                    is_fake = any(p in result_str for p in _FAKE_PATTERNS)

                    if not is_fake:
                        job_ids = _extract_job_ids(messages, self.hints.job_id_key)
                        failed = self._validate_metrics(result_str, job_ids, node)
                        if failed:
                            # node.mark_failed was called or hallucination detected
                            if node.status == "failed":
                                return node
                            is_fake = True

                    if is_fake and exec_called and tool_outputs:
                        logger.warning("Node %s: fake artifacts → replacing with real outputs", node.id)
                        result["artifacts"] = [{"type": "result", "stdout": "\n".join(tool_outputs)}]

                    artifacts = result.get("artifacts", [])
                    summary = result.get("summary", "")
                    if self.evaluator is not None:
                        try:
                            eval_result = self.evaluator.evaluate_sync(
                                goal=experiment.get("goal", "")[:500],
                                artifacts=artifacts,
                                summary=summary,
                                node_id=node.id,
                                node_label=(node.label.value if hasattr(node.label, "value") else str(node.label)),
                            )
                            node.metrics = eval_result.get("metrics", {})
                            node.has_real_data = bool(eval_result.get("has_real_data", False))
                            # eval_summary = measurement reason + scientific score rationale
                            # Both are passed to child nodes via expand() so BFTS can improve
                            _reason = eval_result.get("reason", "")
                            _sci_note = ""
                            _sci_score = eval_result.get("scientific_score")
                            if _sci_score is not None:
                                _sci_note = f" [scientific_score={_sci_score:.2f}]"
                            node.eval_summary = (_reason + _sci_note).strip()
                            logger.info("Node %s: eval metrics=%s has_real=%s",
                                        node.id,
                                        {k: v for k, v in list(node.metrics.items())[:4]},
                                        node.has_real_data)
                        except Exception as e:
                            logger.warning("Node %s: evaluator failed: %s", node.id, e)
                    # Save a clean result summary for child nodes to inherit
                    try:
                        metrics_str = ", ".join(f"{k}={v}" for k, v in node.metrics.items()) if node.metrics else "(no metrics)"
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"RESULT SUMMARY node={node.id} label={node.label}: metrics=[{metrics_str}] summary={summary[:300]}",
                            "metadata": {"type": "result_summary", "metrics": node.metrics},
                        }, cow_node_id=node.id)
                    except Exception:
                        pass
                    node.mark_success(artifacts=artifacts, eval_summary=summary)
                    return node

                elif isinstance(result, dict) and result.get("status") == "failed":
                    # LLM tried to self-terminate with failure — not allowed.
                    # Push back: let the LLM try to recover and continue.
                    error_hint = result.get("error", "")
                    logger.warning("Node %s: LLM tried status=failed at step %d — rejected", node.id, step)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": (
                        f"Error encountered: {error_hint}\n"
                        "This is not a terminal failure. Diagnose the problem, fix your approach, "
                        "and continue the experiment. You must keep trying until you have real data."
                    )})
                    continue
            except json.JSONDecodeError:
                pass

            messages.append({"role": "assistant", "content": content})
            # if LLM returns a non-tool, non-JSON response, force a tool call
            if not force_finish:
                if not content.strip():
                    messages.append({"role": "user", "content": (
                        f"Step {step+1}/{self.max_react_steps}: Your response was empty. "
                        f"You MUST call a tool NOW. Available tools: "
                        f"{[t['function']['name'] for t in (effective_tools or [])]}"
                    )})
                    continue
                # Non-empty text but no tool call and no valid JSON → wasting steps
                if not response.tool_calls:
                    _remaining = self.max_react_steps - step - 1
                    messages.append({"role": "user", "content": (
                        f"Step {step+1}/{self.max_react_steps} ({_remaining} steps remaining): "
                        f"Do NOT write text plans or explanations — call a tool immediately. "
                        f"Every text response wastes a step from your limited budget."
                    )})
                    continue

            if force_finish:
                # if actual SLURM stdout is available, use it as artifacts
                if self._slurm_real_stdout:
                    _artifacts = [{"type": "result", "stdout": self._slurm_real_stdout}]
                    _eval_summary = self._slurm_real_stdout[:500]
                    if self.evaluator is not None:
                        try:
                            eval_result = self.evaluator.evaluate_sync(
                                goal=experiment.get("goal", "")[:500] if isinstance(experiment, dict) else str(experiment)[:500],
                                artifacts=_artifacts,
                                summary=_eval_summary,
                                node_id=node.id,
                                node_label=(node.label.value if hasattr(node.label, "value") else str(node.label)),
                            )
                            node.metrics = eval_result.get("metrics", {})
                            node.has_real_data = bool(eval_result.get("has_real_data", False))
                            _reason = eval_result.get("reason", "")
                            _sci_score = eval_result.get("scientific_score")
                            _sci_note = f" [scientific_score={_sci_score:.2f}]" if _sci_score is not None else ""
                            _eval_summary = (_reason + _sci_note).strip() or _eval_summary
                        except Exception as _e:
                            logger.warning("Node %s: evaluator failed on force-finish: %s", node.id, _e)
                    try:
                        _ms = ", ".join(f"{k}={v}" for k, v in node.metrics.items()) if node.metrics else "(no metrics)"
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"RESULT SUMMARY node={node.id} label={node.label}: metrics=[{_ms}] stdout={self._slurm_real_stdout[:300]}",
                            "metadata": {"type": "result_summary", "metrics": node.metrics},
                        }, cow_node_id=node.id)
                    except Exception:
                        pass
                    node.mark_success(
                        artifacts=_artifacts,
                        eval_summary=_eval_summary,
                    )
                    logger.info("Node %s: completed with real SLURM stdout (%d chars)",
                                node.id, len(self._slurm_real_stdout))
                    return node
                if exec_called and tool_outputs:
                    summary = "\n".join(tool_outputs[-3:])
                    try:
                        _ms = ", ".join(f"{k}={v}" for k, v in node.metrics.items()) if node.metrics else "(no metrics)"
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"RESULT SUMMARY node={node.id} label={node.label}: metrics=[{_ms}] summary={summary[:300]}",
                            "metadata": {"type": "result_summary", "metrics": node.metrics},
                        }, cow_node_id=node.id)
                    except Exception:
                        pass
                    node.mark_success(
                        artifacts=[{"type": "result", "stdout": summary}],
                        eval_summary=summary,
                    )
                    logger.warning("Node %s: forced success at step %d", node.id, step + 1)
                    return node
                messages.append({"role": "user", "content": (
                    f"FINAL STEP {step+1}/{self.max_react_steps}. Reply ONLY with JSON:\n"
                    '{"status":"success","artifacts":[{"type":"result","stdout":"<output>"}],'
                    '"summary":"<one sentence>"}'
                )})
            elif not exec_called and has_exec:
                messages.append({"role": "user", "content": (
                    f"Step {step+1}/{self.max_react_steps}. You must still run the experiment. Do it now."
                )})
            else:
                messages.append({"role": "user", "content": (
                    f"Step {step+1}/{self.max_react_steps}. Continue or provide final JSON."
                )})

        if exec_called and tool_outputs:
            summary = "\n".join(tool_outputs[-3:])
            # Run evaluator on forced-success path too
            if self.evaluator is not None:
                try:
                    _artifacts = [{"type": "result", "stdout": summary}]
                    eval_result = self.evaluator.evaluate_sync(
                        goal=experiment.get("goal", "")[:500] if isinstance(experiment, dict) else str(experiment)[:500],
                        artifacts=_artifacts,
                        summary=summary,
                        node_id=node.id,
                        node_label=(node.label.value if hasattr(node.label, "value") else str(node.label)),
                    )
                    node.metrics = eval_result.get("metrics", {})
                    node.has_real_data = bool(eval_result.get("has_real_data", False))
                    if eval_result.get("reason"):
                        summary = eval_result["reason"]
                except Exception as _e:
                    logger.warning("Node %s: evaluator failed on forced path: %s", node.id, _e)
            try:
                _ms = ", ".join(f"{k}={v}" for k, v in node.metrics.items()) if node.metrics else "(no metrics)"
                self.mcp.call_tool("add_memory", {
                    "node_id": node.id,
                    "text": f"RESULT SUMMARY node={node.id} label={node.label}: metrics=[{_ms}] summary={summary[:300]}",
                    "metadata": {"type": "result_summary", "metrics": node.metrics},
                }, cow_node_id=node.id)
            except Exception:
                pass
            node.mark_success(
                artifacts=[{"type": "result", "stdout": summary}],
                eval_summary=summary,
            )
            logger.warning("Node %s: forced success after max steps", node.id)
            return node

        node.mark_failed(error_log="Max ReAct steps exceeded")
        return node
