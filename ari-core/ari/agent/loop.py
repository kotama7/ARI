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

MAX_REACT_STEPS = 32
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
- If `make_metric_spec` tool is available, call it FIRST with the full experiment goal text to self-determine evaluation criteria before running experiments.
- NEVER fabricate numeric values — only report values from actual tool outputs
- When all experiments are done, return JSON: {{"status": "success", "metrics": {{...}}, "summary": "..."}}
- Do NOT call gap_analysis or generate_hypothesis{extra}
"""


def _extract_job_ids(messages: list[dict], job_id_key: str) -> list[str]:
    """Generic function to extract async job IDs from tool messages (with deduplication)."""
    seen: set[str] = set()
    ids: list[str] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        try:
            r = json.loads(m.get("content", "{}"))
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

    def _available_tools_openai(self) -> list[dict]:
        """Return the MCP tool list in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for t in self.mcp.list_tools()
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

        # make_metric_spec done → all tools unlocked (model decides autonomously)
        if seq[0] == "make_metric_spec" and has("make_metric_spec"):
            rest = seq[1:]  # ["survey", "slurm_submit", ...]
            if rest and rest[0] == "survey" and has("survey"):
                # survey done → enable slurm_submit and beyond
                return by_name(*rest[1:]) or None
            # after make_metric_spec, provide all remaining tools
            return by_name(*rest) or None

        # survey already done
        if seq[0] == "survey" and has("survey"):
            next_tools = seq[1:3]  # allow the next 2 steps after survey
            return by_name(*next_tools) or None

        # allow only the first step (make_metric_spec is always included)
        filtered = by_name(seq[0]) or all_tools
        evaluator_tools = [t for t in all_tools if t["function"]["name"] == "make_metric_spec"
                           and t not in filtered]
        return evaluator_tools + filtered

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
        tools = self._available_tools_openai()
        tool_names = [t["function"]["name"] for t in tools] if tools else []
        tool_desc = ", ".join(tool_names) if tool_names else "none"
        has_exec = any(n in ("run_bash", "run_code") for n in tool_names)

        label_hint = node.label.system_hint() if hasattr(node, "label") else ""
        extra = (
            (f"\n\nNODE ROLE: {label_hint}" if label_hint else "")
            + (f"\n\n{self.hints.extra_system_prompt}" if self.hints.extra_system_prompt else "")
        )
        system_content = SYSTEM_PROMPT.format(tool_desc=tool_desc, extra=extra)
        # pass only goal from experiment dict (workflow_hint is injected via post_survey_hint)
        goal_text = experiment.get("goal", "") if isinstance(experiment, dict) else str(experiment)
        # truncate goal_text to first 1500 chars if too long
        if len(goal_text) > 1500:
            goal_text = goal_text[:1500] + "\n...[truncated]"
        first_tool = (self.hints.tool_sequence or ["survey"])[0]
        user_content = (
            f"Experiment goal:\n{goal_text}\n"
            f"Node: {node.id} depth={node.depth}\n\n"
            f"START NOW: call {first_tool}() immediately. "
            f"Do NOT output any text or plan — your first response must be a {first_tool}() tool call."
        )

        # NOTE: Planner plan text injection has been removed
        # When plan text is present, LLM tends to "write a plan" and stops calling tools
        # plan = None  (plan_steps is for debugging only; not included in context)

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # Skip survey for nodes at depth > 0:
        # The root node already saved its survey knowledge to memory; skip re-surveying
        if node.depth > 0 and node.ancestor_ids:
            try:
                mem_result = self.mcp.call_tool("search_memory", {
                    "query": "survey knowledge actionable insights performance optimization result",
                    "ancestor_ids": node.ancestor_ids,  # Only memories up to parent node
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
                            f"{knowledge_summary[:1000]}\n\n"
                            "Use this knowledge. Skip the survey step if already done."
                        ),
                    })
            except Exception as _e:
                logger.debug("search_memory failed: %s", _e)

        tools_called = 0
        exec_called = False          # whether run_bash / run_code has been called
        tool_outputs: list[str] = []

        for step in range(MAX_REACT_STEPS):
            job_ids = _extract_job_ids(messages, self.hints.job_id_key)
            job_output_read = exec_called and bool(job_ids) if self.hints.job_submitter_tool else False

            logger.info("Node %s: step %d tools=%d exec=%s jobs=%s",
                        node.id, step + 1, tools_called, exec_called, job_ids)

            can_finish = tools_called >= MIN_TOOL_CALLS and (exec_called or not has_exec)
            job_done = job_output_read and bool(tool_outputs)
            force_finish = (job_done and step >= 5) or (step >= MAX_REACT_STEPS - 3 and can_finish)

            active = self._active_tools(tools, messages, job_ids, exec_called, force_finish)

            window = messages[:2] + messages[-12:] if len(messages) > 14 else messages
            llm_msgs = [
                LLMMessage(role=m["role"], content=m.get("content") or "")
                for m in window
            ]
            effective_tools = active if active is not None else tools
            # force_finish phase (effective_tools=None): JSON output is allowed
            response = self.llm.complete(llm_msgs, tools=effective_tools, require_tool=(effective_tools is not None))

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
                executed_names: list[str] = []
                for r in results:
                    rc = json.dumps(r["result"], ensure_ascii=False)
                    logger.info("Tool call: %s -> %s", r["name"], rc[:200])
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
                            jr = json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
                            inner = json.loads(jr.get("result","{}")) if isinstance(jr.get("result"), str) else jr.get("result",{})
                            if inner.get("status") == "COMPLETED" and inner.get("stdout"):
                                self._slurm_real_stdout = inner["stdout"]
                        except Exception:
                            pass

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
                                        nums = [float(x) for x in _re_art.findall(r"\b(\d+\.\d+|\d{{4,}})\b", text) if float(x) >= 1.0]
                                        return {{"result_" + str(i): v for i, v in enumerate(nums[:20])}}
                                    return {{f"{kw}_{{i}}": float(x) for i, x in enumerate(p.findall(text))}}
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
                            _js = json.loads(r["result"]) if isinstance(r["result"], str) else r["result"]
                            if isinstance(_js, dict) and _js.get("status") == "COMPLETED" and _js.get("stdout", "").strip():
                                exec_called = True
                                logger.info("job_status stdout available → exec_called=True (no run_bash needed)")
                        except Exception:
                            pass

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
                if last == self.hints.job_poller_tool and job_ids and results:
                    try:
                        import time as _time
                        _res = results[-1]["result"]
                        if isinstance(_res, str):
                            _res = json.loads(_res)
                        last_status = _res.get("status", "") if isinstance(_res, dict) else ""
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
                            node.eval_summary = eval_result.get("reason", "")
                            logger.info("Node %s: eval metrics=%s has_real=%s",
                                        node.id,
                                        {k: v for k, v in list(node.metrics.items())[:4]},
                                        node.has_real_data)
                        except Exception as e:
                            logger.warning("Node %s: evaluator failed: %s", node.id, e)
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
                    node.mark_success(
                        artifacts=[{"type": "result", "stdout": self._slurm_real_stdout}],
                        eval_summary=self._slurm_real_stdout[:500],
                    )
                    logger.info("Node %s: completed with real SLURM stdout (%d chars)",
                                node.id, len(self._slurm_real_stdout))
                    return node
                if exec_called and tool_outputs:
                    summary = "\n".join(tool_outputs[-3:])
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
            node.mark_success(
                artifacts=[{"type": "result", "stdout": summary}],
                eval_summary=summary,
            )
            logger.warning("Node %s: forced success after max steps", node.id)
            return node

        node.mark_failed(error_log="Max ReAct steps exceeded")
        return node
