"""ReAct agent loop for executing research within a single node.

Design principles:
- AgentLoop is a pure ReAct loop with no domain-specific knowledge
- Experiment-specific settings are injected via WorkflowHints
- Terms like SLURM or MFLOPS do not appear in this file
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ari.agent.workflow import WorkflowHints
from ari.llm.client import LLMClient, LLMMessage
from ari.mcp.client import MCPClient
from ari.memory.client import MemoryClient
from ari.orchestrator.node import Node

logger = logging.getLogger(__name__)

MAX_REACT_STEPS = 80
MIN_TOOL_CALLS = 2

# Clearly placeholder strings (used to detect LLM-fabricated values)
_FAKE_PATTERNS = [
    "found n papers", "[title1]", "[title2]",
    "x.xx speedup", "serial baseline x",
    "actual papers", "actual code", "actual stdout",
    "what was actually done",
]

SYSTEM_PROMPT = """\
You are a research agent. You MUST use tools to execute experiments. Do NOT write plans or text descriptions — call a tool immediately.

AVAILABLE TOOLS:
{tool_desc}

RULES:
- Your FIRST action must be a tool call. Never output a text plan.
- If `make_metric_spec` tool is available and this is a new experiment (not a continuation), call it early to self-determine evaluation criteria.
- NEVER fabricate numeric values — only report values from actual tool outputs
- When all experiments are done, return JSON: {{"status": "success", "metrics": {{...}}, "summary": "..."}}
- Do NOT call gap_analysis or generate_hypothesis
- Ensure your experiment is reproducible: capture whatever information would be needed for an independent researcher to reproduce your results and verify your findings{extra}
"""


def _extract_job_ids(messages: list[dict], job_id_key: str) -> list[str]:
    """Extract async job IDs from tool messages (JSON field and sbatch stdout)."""
    import re as _re_jid
    seen: set[str] = set()
    ids: list[str] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        # Direct "Submitted batch job NNN" scan (eliminates need for synthetic inject)
        for _sbatch_m in _re_jid.finditer(r"Submitted batch job (\d+)", content):
            jid = _sbatch_m.group(1)
            if jid not in seen:
                seen.add(jid)
                ids.append(jid)
        # JSON structured result
        try:
            r = json.loads(content)
            if isinstance(r, dict) and "result" in r:
                r = json.loads(r["result"])
            if isinstance(r, dict) and job_id_key in r:
                jid = str(r[job_id_key])
                if jid not in seen:
                    seen.add(jid)
                    ids.append(jid)
        except Exception:
            pass
    return ids


def _tool_was_called(messages: list[dict], tool_name: str) -> bool:
    """Check whether the message history contains a call to the specified tool."""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("function", {}).get("name") == tool_name:
                return True
    return False


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryClient,
        mcp: MCPClient,
        evaluator: object | None = None,
        workflow_hints: WorkflowHints | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.mcp = mcp
        self.evaluator = evaluator
        self._slurm_real_stdout: str = ""
        self.hints = workflow_hints or WorkflowHints()

    # ------------------------------------------------------------------
    # Tool filtering (derived from WorkflowHints)
    # ------------------------------------------------------------------

    def _available_tools_openai(self, suppress: set | None = None, phase: str | None = None) -> list[dict]:
        """Return the MCP tool list in OpenAI function-calling format.
        suppress: set of tool names to exclude (e.g. already-called once-only tools).
        phase: if set, only tools with matching phase (or phase='all') are included.
        """
        suppress = suppress or set()
        return [
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for t in self.mcp.list_tools(phase=phase)
            if t.get("name", "") not in suppress
        ]

    def _execute_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        """Execute a batch of tool calls and return results."""
        import json as _json
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            try:
                args = _json.loads(func.get("arguments", "{}"))
            except _json.JSONDecodeError:
                args = {}
            result = self.mcp.call_tool(name, args)
            results.append({"tool_call_id": tc.get("id", ""), "name": name, "result": result})
        return results

    def _active_tools(
        self,
        all_tools: list[dict],
        messages: list[dict],
        job_ids: list[str],
        exec_called: bool,
        force_all: bool,
    ) -> list[dict] | None:
        """
        Filter available tools based on current progress.
        Returning None makes all tools available (e.g. during forced-finish phase).
        """
        if force_all or not all_tools:
            return None

        h = self.hints
        # If no sequence is specified, all tools are available
        if not h.tool_sequence:
            return None

        seq = h.tool_sequence  # e.g. ["survey", "slurm_submit", "job_status", "run_bash"]

        def has(name: str) -> bool:
            return _tool_was_called(messages, name)

        def by_name(*names: str) -> list[dict]:
            return [t for t in all_tools if t["function"]["name"] in names]

        # async job read complete
        if h.job_reader_tool and exec_called and job_ids:
            return None  # everything done → JSON output phase

        # async job submitted
        if h.job_submitter_tool and job_ids:
            # If job is COMPLETED, re-enable slurm_submit (for submitting the next experiment)
            _last_job_done = False
            for _msg in reversed(messages):
                if _msg.get("role") == "tool":
                    import json as _json
                    try:
                        _r = _json.loads(_msg.get("content", "{}"))
                        if isinstance(_r, dict) and _r.get("status") in ("COMPLETED", "FAILED"):
                            _last_job_done = True
                    except Exception:
                        pass
                    break
            if _last_job_done:
                # COMPLETED: provide slurm_submit + run_bash + job_status
                # (even if stdout is null, can submit next experiment or read output file)
                extra = [h.job_submitter_tool] if h.job_submitter_tool else []
                rb = ["run_bash"] if any(t["function"]["name"] == "run_bash" for t in all_tools) else []
                candidates = extra + rb
                if h.job_poller_tool:
                    candidates = candidates + [h.job_poller_tool]
                if h.job_reader_tool and h.job_reader_tool not in candidates:
                    candidates = candidates + [h.job_reader_tool]
                return by_name(*candidates) or None
            candidates = []
            if h.job_poller_tool:
                candidates.append(h.job_poller_tool)
            if h.job_reader_tool:
                candidates.append(h.job_reader_tool)
            return by_name(*candidates) or None

        # All tools available — LLM decides what to call
        return None

    # ------------------------------------------------------------------
    # Step guidance (derived from WorkflowHints)
    # ------------------------------------------------------------------

    def _guidance(
        self,
        last_tool: str,
        job_ids: list[str],
        tool_outputs: list[str],
    ) -> str | None:
        """Return additional instructions to LLM based on the most recent tool call."""
        h = self.hints

        # after survey completes
        if last_tool == "survey" and not job_ids:
            if h.post_survey_hint:
                return f"Good. Now proceed:\n{h.post_survey_hint}"
            return "Good. Now execute the experiment using available tools."

        # after async job submitted
        if h.job_submitter_tool and last_tool == h.job_submitter_tool and job_ids:
            jid = job_ids[-1]
            poller = h.job_poller_tool or "job_status"
            return (
                f"Job {jid} submitted. "
                f"Now call {poller}(job_id='{jid}') to wait for completion."
            )

        # after job status checked
        if h.job_poller_tool and last_tool == h.job_poller_tool and job_ids:
            jid = job_ids[-1]
            reader = h.job_reader_tool or "run_bash"
            if h.output_file_pattern:
                path = h.output_file_pattern.format(job_id=jid)
                return f"Good. Now read results:\n{reader}(command='cat {path}')"
            return (
                f"Good. Use {reader}() to read the job output. "
                f"Check the output path specified in your job script."
            )

        # after execution result read
        if h.job_reader_tool and last_tool in (h.job_reader_tool, "run_bash", "run_code"):
            summary = "\n".join(tool_outputs[-5:])
            return (
                f"Execution output:\n{summary}\n\n"
                "Now return the final JSON with REAL measured values.\n"
                'Format: {"status":"success","artifacts":[...],"summary":"..."}\n'
                "Use ONLY values from actual tool outputs."
            )

        return None

    # ------------------------------------------------------------------
    # metrics validation (derived from WorkflowHints)
    # ------------------------------------------------------------------

    def _validate_metrics(self, result_str: str, job_ids: list[str], node: Node) -> bool:
        """
        Validate metrics. Returns True and marks node as failed if there is a problem.
        Returns False if no problem.
        """
        h = self.hints
        if h.metric_extractor is None and h.min_expected_metric == 0:
            return False

        vals: list[float] = []
        if h.metric_extractor:
            try:
                vals = h.metric_extractor(result_str)
            except Exception:
                pass

        if not vals:
            return False

        # values appeared without going through a job → hallucination
        if h.job_submitter_tool and not job_ids:
            logger.warning("Node %s: metrics without async job → hallucination", node.id)
            return True  # treat as fabricated value

        # threshold check
        if h.min_expected_metric > 0 and len(vals) > 1 and max(vals) < h.min_expected_metric:
            logger.warning("Node %s: metric too low %s < %s → failed",
                           node.id, vals, h.min_expected_metric)
            node.mark_failed(
                error_log=f"Metric too low: max={max(vals)} < expected={h.min_expected_metric}"
            )
            return True  # marked node as failed

        return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, node: Node, experiment: dict) -> Node:
        node.mark_running()
        # Inject work_dir BEFORE forking MCP servers (env snapshot taken at fork time)
        _work_dir_early = experiment.get("work_dir", "") if isinstance(experiment, dict) else ""
        if _work_dir_early:
            import os as _os_early
            _os_early.environ["ARI_WORK_DIR"] = _work_dir_early
            _os_early.makedirs(_work_dir_early, exist_ok=True)
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
        work_dir_hint = (
            f"\n\nEXPERIMENT ENVIRONMENT:"
            f"\n  - Work directory (REQUIRED): {work_dir} — write ALL files here, cd here first"
            + hpc_hint
            if work_dir else (
                f"\n\nEXPERIMENT ENVIRONMENT:{hpc_hint}" if hpc_hint else ""
            )
        )
        extra = (
            (f"\n\nNODE ROLE: {label_hint}" if label_hint else "")
            + work_dir_hint
            + (f"\n\n{self.hints.extra_system_prompt}" if self.hints.extra_system_prompt else "")
        )
        system_content = SYSTEM_PROMPT.format(tool_desc=tool_desc, extra=extra)
        # pass only goal from experiment dict (workflow_hint is injected via post_survey_hint)
        goal_text = experiment.get("goal", "") if isinstance(experiment, dict) else str(experiment)
        # truncate goal_text to first 1500 chars if too long
        if len(goal_text) > 1500:
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
            user_content = (
                f"Experiment goal:\n{goal_text}\n"
                f"Node: {node.id} depth={node.depth} task={node.label}\n\n"
                f"Task: {_label_desc}\n"
                "The parent node already completed the survey and established a research direction. "
                "Prior results are provided below. "
                "Implement and run your specific experiment, then return JSON with measurements."
            )
        else:
            first_tool = (self.hints.tool_sequence or ["survey"])[0]
            user_content = (
                f"Experiment goal:\n{goal_text}\n"
                f"Node: {node.id} depth={node.depth}\n\n"
                f"START NOW: call {first_tool}() immediately. "
                f"Do NOT output any text or plan — your first response must be a {first_tool}() tool call.\n\n"
                "IMPORTANT: After make_metric_spec, call survey() to search related literature. "
                "The survey results will be used to generate citations in the paper. "
                "Without survey, the paper will have no references."
            )

        # NOTE: Planner plan text injection has been removed
        # When plan text is present, LLM tends to "write a plan" and stops calling tools
        # plan = None  (plan_steps is for debugging only; not included in context)

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # For child nodes: inject parent memory via search_memory
        # (ancestor_ids is now serialized correctly, so search_memory works)
        if node.depth > 0:
            if node.ancestor_ids:
                try:
                    # Use node's own goal as query so retrieved memories are relevant
                    _mem_query = (node.eval_summary or self.experiment_goal or "experiment result")[:200]
                    mem_result = self.mcp.call_tool("search_memory", {
                        "query": _mem_query,
                        "ancestor_ids": node.ancestor_ids,
                        "limit": 5,
                    })
                    if isinstance(mem_result, str):
                        import json as _j; mem_result = _j.loads(mem_result)
                    prior_entries = mem_result.get("results", []) if isinstance(mem_result, dict) else []
                    if prior_entries:
                        knowledge_summary = "\n".join(
                            e.get("text", "") for e in prior_entries if e.get("text")
                        )
                        messages.append({
                            "role": "user",
                            "content": (
                                f"[Prior knowledge from ancestor nodes ({len(prior_entries)} entries):]\n"
                                f"{knowledge_summary[:800]}\n"
                            ),
                        })
                except Exception as _e:
                    logger.debug("search_memory failed: %s", _e)

        # Track current node depth for tool filtering
        self._current_node_depth = node.depth

        # Inject work_dir as env var so run_bash defaults to it
        import os as _os
        if work_dir:
            _os.environ["ARI_WORK_DIR"] = work_dir
            _os.makedirs(work_dir, exist_ok=True)

        self._slurm_real_stdout = ""  # reset per-run state
        tools_called = 0
        exec_called = False          # whether run_bash / run_code has been called
        tool_outputs: list[str] = []

        for step in range(MAX_REACT_STEPS):
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
            force_finish = (job_done and step >= 5) or (step >= MAX_REACT_STEPS - 3 and can_finish)

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
                return _validate_pairs(deduped)
            window = _build_safe_window(messages)
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
            response = self.llm.complete(llm_msgs, tools=effective_tools, require_tool=(active is not None))

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

                results = self._execute_tool_calls(response.tool_calls)
                # Build args lookup by tool name for trace logging
                _tc_args_by_name = {
                    tc.get("function", {}).get("name", ""): tc.get("function", {}).get("arguments", "")
                    for tc in response.tool_calls
                }
                executed_names: list[str] = []
                for r in results:
                    rc = json.dumps(r["result"], ensure_ascii=False)
                    logger.info("Tool call: %s -> %s", r["name"], rc[:200])
                    print(f"[TOOL] {r['name']}", flush=True)
                    # Record in node trace for viz
                    if hasattr(node, "trace_log"):
                        _args_preview = str(_tc_args_by_name.get(r["name"], ""))[:120]
                        _res_preview = str(r.get("result", ""))[:200]
                        node.trace_log.append(f"→ {r['name']}({_args_preview})")
                        if _res_preview:
                            node.trace_log.append(f"  ← {_res_preview}")
                    try:
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"Tool {r['name']}: {rc[:300]}",
                            "metadata": {"step": step, "tool": r["name"]},
                        })
                    except Exception:
                        self.memory.add(
                            f"Tool {r['name']}: {rc[:300]}",
                            metadata={"node_id": node.id, "step": step},
                        )
                    if len(rc) > 800:
                        rc = rc[:800] + "...[truncated]"
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
                                    })
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
                            pm = idea_data.get("primary_metric", "")
                            hib = idea_data.get("higher_is_better", True)
                            mr = idea_data.get("metric_rationale", "")
                            if pm:
                                # Persist to memory so pipeline.py can read it
                                try:
                                    self.memory.write(
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
                        except Exception as _gie:
                            logger.warning("generate_ideas result parse failed: %s", _gie)

                    # make_metric_spec call: self-determine evaluation criteria
                    if r["name"] == "make_metric_spec":
                        try:
                            spec_data = json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
                            if isinstance(spec_data, dict) and "result" in spec_data:
                                spec_data = json.loads(spec_data["result"]) if isinstance(spec_data["result"], str) else spec_data["result"]
                            kw = spec_data.get("metric_keyword")
                            expected = spec_data.get("expected_metrics", [])
                            guide = spec_data.get("scoring_guide", "")
                            # update metric_extractor to keyword-based
                            if kw:
                                import re as _re_kw
                                _pat = _re_kw.compile(rf"{kw}[:\s=]+([\d.]+)", _re_kw.IGNORECASE)
                                self.hints.metric_extractor = (
                                    lambda text, p=_pat: [float(x) for x in p.findall(text) if float(x) >= 1.0]
                                )
                            # update MetricSpec in LLMEvaluator
                            if self.evaluator and (expected or guide):
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
                                    artifact_extractor=_dyn_extractor,
                                    scoring_guide=guide,
                                )
                            logger.info(
                                "ARI self-determined MetricSpec: keyword=%s expected=%s",
                                kw, expected
                            )
                        except Exception as _e:
                            logger.warning("make_metric_spec result parse failed: %s", _e)

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
                            import re as _re
                            sbatch_match = _re.search(r"Submitted batch job (\d+)", stdout)
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
                            poll_results = self._execute_tool_calls(poll_tc)
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

                guidance = self._guidance(last, job_ids, tool_outputs)
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
                        })
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
            # if LLM returns an empty response, force a tool call
            if not content.strip() and not response.tool_calls and not force_finish:
                messages.append({"role": "user", "content": (
                    f"Step {step+1}/{MAX_REACT_STEPS}: Your response was empty. "
                    f"You MUST call a tool NOW. Available tools: "
                    f"{[t['function']['name'] for t in (effective_tools or [])]}"
                )})
                continue

            if force_finish:
                # if actual SLURM stdout is available, use it as artifacts
                if self._slurm_real_stdout:
                    try:
                        _ms = ", ".join(f"{k}={v}" for k, v in node.metrics.items()) if node.metrics else "(no metrics)"
                        self.mcp.call_tool("add_memory", {
                            "node_id": node.id,
                            "text": f"RESULT SUMMARY node={node.id} label={node.label}: metrics=[{_ms}] stdout={self._slurm_real_stdout[:300]}",
                            "metadata": {"type": "result_summary", "metrics": node.metrics},
                        })
                    except Exception:
                        pass
                    node.mark_success(
                        artifacts=[{"type": "result", "stdout": self._slurm_real_stdout}],
                        eval_summary=self._slurm_real_stdout[:500],
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
                        })
                    except Exception:
                        pass
                    node.mark_success(
                        artifacts=[{"type": "result", "stdout": summary}],
                        eval_summary=summary,
                    )
                    logger.warning("Node %s: forced success at step %d", node.id, step + 1)
                    return node
                messages.append({"role": "user", "content": (
                    f"FINAL STEP {step+1}/{MAX_REACT_STEPS}. Reply ONLY with JSON:\n"
                    '{"status":"success","artifacts":[{"type":"result","stdout":"<output>"}],'
                    '"summary":"<one sentence>"}'
                )})
            elif not exec_called and has_exec:
                messages.append({"role": "user", "content": (
                    f"Step {step+1}/{MAX_REACT_STEPS}. You must still run the experiment. Do it now."
                )})
            else:
                messages.append({"role": "user", "content": (
                    f"Step {step+1}/{MAX_REACT_STEPS}. Continue or provide final JSON."
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
                })
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
