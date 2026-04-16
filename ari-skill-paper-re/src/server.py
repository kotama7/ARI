"""
ari-skill-paper-re: Reproducibility verification via ReAct agent loop.

Philosophy:
- Reads ONLY the paper text. No original source code provided.
- LLM autonomously implements, compiles, tests, profiles, and iterates
  using tools (write_file, run_bash, submit_job, read_file, report_metric).
- Framework provides executor type, resource constraints, and tool bindings.
- Tests whether the paper is reproducible by an independent implementer.
"""

import asyncio, json, logging, os, re, subprocess, time
from pathlib import Path

log = logging.getLogger(__name__)

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-reproducibility-skill")


def _model():
    # Phase-specific override so the GUI's per-phase model picker takes effect.
    return (os.environ.get("ARI_MODEL_PAPER")
            or os.environ.get("ARI_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")


def _api_base():
    ari = os.environ.get("ARI_LLM_API_BASE")
    if ari is not None:
        return ari or None
    legacy = os.environ.get("LLM_API_BASE", "")
    if legacy:
        return legacy
    if _model().startswith("ollama"):
        return "http://127.0.0.1:11434"
    return None


async def _llm(system, user):
    kwargs = {"model": _model(), "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "timeout": 120}
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


class Executor:
    """Execution backend abstraction. Supports: local, slurm, pbs, lsf."""
    def __init__(self, kind, cpus, timeout_minutes, log_file, extra=None):
        self.kind = kind
        self.cpus = cpus
        self.timeout_minutes = timeout_minutes
        self.log_file = log_file
        self.extra = extra or {}

    @staticmethod
    def _detect_arch() -> str:
        """Detect CPU architecture of the current host."""
        import platform
        return platform.machine() or "unknown"

    def describe(self):
        arch = self._detect_arch()
        k = self.kind
        if k == "local":
            return (f"local bash execution (no scheduler); "
                    f"{self.cpus} CPU threads available; architecture={arch}")
        if k == "slurm":
            p = self.extra.get("partition", "")
            return (f"SLURM scheduler; include #SBATCH header directives; "
                    f"partition={p}, cpus-per-task={self.cpus}, "
                    f"time=00:{self.timeout_minutes:02d}:00, output={self.log_file}, "
                    f"--exclusive (for reliable benchmarking); "
                    f"architecture={arch}")
        if k == "pbs":
            return (f"PBS/Torque scheduler; include #PBS directives; "
                    f"nodes=1:ppn={self.cpus}, walltime=00:{self.timeout_minutes:02d}:00; "
                    f"architecture={arch}")
        if k == "lsf":
            return (f"LSF scheduler; include #BSUB directives; "
                    f"ncpus={self.cpus}, runtime=00:{self.timeout_minutes:02d}; "
                    f"architecture={arch}")
        return f"{k} scheduler (include appropriate scheduler directives)"

    def submit(self, script_path):
        k = self.kind
        if k == "slurm":
            r = subprocess.run(["sbatch", script_path], capture_output=True, text=True, timeout=30)
            m = re.search(r"Submitted batch job (\d+)", r.stdout)
            if not m: raise RuntimeError(f"sbatch failed: {r.stderr}")
            return m.group(1)
        if k == "pbs":
            r = subprocess.run(["qsub", script_path], capture_output=True, text=True, timeout=30)
            if r.returncode != 0: raise RuntimeError(f"qsub failed: {r.stderr}")
            return r.stdout.strip()
        if k == "lsf":
            r = subprocess.run(f"bsub < {script_path}", shell=True, capture_output=True, text=True, timeout=30)
            m = re.search(r"Job <(\d+)>", r.stdout)
            if not m: raise RuntimeError(f"bsub failed: {r.stderr}")
            return m.group(1)
        raise RuntimeError(f"Unknown executor for submit: {k}")

    def is_running(self, job_id):
        k = self.kind
        if k == "slurm":
            r = subprocess.run(["squeue", "-j", job_id, "-h"], capture_output=True, text=True)
            return bool(r.stdout.strip())
        if k == "pbs":
            return subprocess.run(["qstat", job_id], capture_output=True).returncode == 0
        if k == "lsf":
            r = subprocess.run(["bjobs", job_id], capture_output=True, text=True)
            return "DONE" not in r.stdout and "EXIT" not in r.stdout
        return False


# ─── ReAct tool infrastructure ────────────────────────────────────────

_MAX_TOOL_OUTPUT = 4000


def _truncate(text: str, limit: int = _MAX_TOOL_OUTPUT) -> str:
    """Truncate long text keeping head and tail."""
    if not text or len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n... [{len(text) - limit} chars truncated] ...\n\n" + text[-half:]


def _react_tool_defs(exe_kind: str) -> list[dict]:
    """Build OpenAI function-calling tool definitions for the ReAct loop."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file in the work directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Filename (relative to work dir)"},
                        "content": {"type": "string", "description": "File content to write"},
                        "executable": {"type": "boolean", "description": "chmod +x after writing"},
                    },
                    "required": ["filename", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_bash",
                "description": (
                    "Execute a bash command in the work directory. "
                    "Use for: compilation, small-scale correctness tests, profiling, "
                    "inspecting files, checking compiler/environment info. "
                    "Output truncated to 4000 chars. Max timeout: 600s."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Bash command to run"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file. Output truncated to 4000 chars.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (relative to work dir or absolute)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "report_metric",
                "description": (
                    "Report the final reproduced metric value. "
                    "Call ONLY when you have a reliable full-scale measurement. "
                    "This terminates the verification loop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number", "description": "Measured metric value"},
                        "unit": {"type": "string", "description": "Unit (e.g. GFLOP/s, ms)"},
                        "notes": {"type": "string", "description": "Measurement conditions, observations, and any deviations"},
                    },
                    "required": ["value"],
                },
            },
        },
    ]
    # Scheduler-based job submission (not available in local mode)
    if exe_kind != "local":
        tools.append({
            "type": "function",
            "function": {
                "name": "submit_job",
                "description": (
                    f"Submit a job script to the {exe_kind.upper()} scheduler, "
                    "wait for completion, and return the job output. "
                    "The script must already exist (use write_file first). "
                    "Polls every 15s until done or timeout."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script_filename": {"type": "string", "description": "Job script filename in work dir"},
                        "output_file": {
                            "type": "string",
                            "description": "Expected output file path (from #SBATCH --output or similar). "
                                           "Supports %%j for job ID substitution.",
                        },
                    },
                    "required": ["script_filename"],
                },
            },
        })
    return tools


class _ToolHandler:
    """Execute tool calls for the ReAct reproducibility loop."""

    def __init__(self, work_dir: str, executor: Executor, timeout_minutes: int):
        self.work_dir = Path(work_dir)
        self.executor = executor
        self.timeout_minutes = timeout_minutes
        self.reported_metric: dict | None = None
        self.job_id: str = ""

    async def __call__(self, name: str, args: dict) -> dict:
        """Dispatch a tool call by name."""
        try:
            fn = getattr(self, f"_tool_{name}", None)
            if fn is None:
                return {"error": f"Unknown tool: {name}"}
            if asyncio.iscoroutinefunction(fn):
                return await fn(args)
            return fn(args)
        except Exception as e:
            log.warning("Tool %s failed: %s", name, e)
            return {"error": f"{name} failed: {e}"}

    def _resolve(self, filename: str) -> Path:
        """Resolve a filename relative to work_dir (or keep absolute)."""
        p = Path(filename)
        return p if p.is_absolute() else self.work_dir / p

    # ── Individual tools ──

    def _tool_write_file(self, args: dict) -> dict:
        path = self._resolve(args["filename"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"])
        if args.get("executable"):
            path.chmod(0o755)
        return {"ok": True, "path": str(path), "bytes": len(args["content"])}

    def _tool_run_bash(self, args: dict) -> dict:
        cmd = args["command"]
        timeout = min(int(args.get("timeout") or 120), self.timeout_minutes * 60)
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=str(self.work_dir),
            )
            return {
                "exit_code": proc.returncode,
                "stdout": _truncate(proc.stdout),
                "stderr": _truncate(proc.stderr, 2000),
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timed out after {timeout}s", "exit_code": -1}

    def _tool_read_file(self, args: dict) -> dict:
        path = self._resolve(args["path"])
        if not path.exists():
            return {"error": f"File not found: {path}"}
        return {"content": _truncate(path.read_text())}

    async def _tool_submit_job(self, args: dict) -> dict:
        script_filename = args["script_filename"]
        output_file = args.get("output_file", "")
        script_path = self._resolve(script_filename)

        # Auto-detect output file from scheduler directives if not specified
        if not output_file:
            try:
                script_text = script_path.read_text()
                m = re.search(r"#SBATCH\s+(?:--output|-o)\s*=?\s*(\S+)", script_text)
                if m:
                    output_file = m.group(1)
            except Exception:
                pass

        try:
            job_id = self.executor.submit(str(script_path))
            self.job_id = job_id
        except Exception as e:
            return {"error": f"Submission failed: {e}"}

        # Poll until done or timeout
        deadline = time.time() + self.timeout_minutes * 60
        while time.time() < deadline:
            await asyncio.sleep(15)
            if not self.executor.is_running(job_id):
                break
        else:
            return {"job_id": job_id, "status": "timeout",
                    "error": f"Job {job_id} still running after {self.timeout_minutes} min"}

        # Substitute %j with actual job ID (SLURM convention)
        if output_file and "%j" in output_file:
            output_file = output_file.replace("%j", job_id)

        # Read output
        output = ""
        if output_file:
            out_path = self._resolve(output_file)
            if out_path.exists():
                output = _truncate(out_path.read_text())
            else:
                output = f"[Output file not found: {out_path}]"

        return {"job_id": job_id, "status": "completed", "output": output}

    def _tool_report_metric(self, args: dict) -> dict:
        self.reported_metric = {
            "value": float(args["value"]),
            "unit": args.get("unit", ""),
            "notes": args.get("notes", ""),
        }
        return {"ok": True, "recorded": self.reported_metric}


# ─── ReAct loop ───────────────────────────────────────────────────────

def _build_window(messages: list[dict], max_msgs: int = 50) -> list[dict]:
    """Trim conversation preserving system prompt, initial user message, and recent pairs."""
    if len(messages) <= max_msgs:
        return list(messages)
    # Always keep system (0) + initial user with paper text (1)
    head = messages[:2]
    tail = list(messages[-(max_msgs - 2):])
    # Drop orphaned tool messages at the start of the tail
    while tail and tail[0].get("role") == "tool":
        tail.pop(0)
    # If tail starts with an assistant whose tool_calls are partially orphaned, drop it
    if tail and tail[0].get("role") == "assistant" and tail[0].get("tool_calls"):
        needed = {tc["id"] for tc in tail[0]["tool_calls"]}
        present = {m.get("tool_call_id") for m in tail if m.get("role") == "tool"}
        if not needed.issubset(present):
            tail.pop(0)
    return head + tail


async def _run_react(
    system: str,
    user: str,
    tool_defs: list[dict],
    handler: _ToolHandler,
    max_steps: int = 40,
) -> list[dict]:
    """Drive the ReAct loop: Thought -> Action -> Observation -> ..."""
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for step in range(1, max_steps + 1):
        # LLM call with tool definitions
        kwargs: dict = {
            "model": _model(),
            "messages": _build_window(messages),
            "tools": tool_defs,
            "temperature": 0.3,
            "timeout": 180,
        }
        base = _api_base()
        if base:
            kwargs["api_base"] = base

        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as e:
            log.error("ReAct step %d LLM error: %s", step, e)
            messages.append({
                "role": "user",
                "content": f"[System] LLM call failed ({type(e).__name__}: {e}). "
                           "Please continue with available information.",
            })
            continue

        msg = resp.choices[0].message

        # Strip <think> tags from content
        content = msg.content or ""
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()

        # Build assistant message for conversation history
        assistant_msg: dict = {"role": "assistant", "content": content}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        tool_names = [tc.function.name for tc in (msg.tool_calls or [])]
        log.info("ReAct step %d/%d: tools=%s content_len=%d",
                 step, max_steps, tool_names or "(text-only)", len(content))

        # No tool calls → LLM is done (or confused)
        if not msg.tool_calls:
            if not content:
                # Empty response — nudge
                messages.append({
                    "role": "user",
                    "content": "[System] Empty response. Call a tool to proceed, "
                               "or call report_metric() if you have a measurement.",
                })
                continue
            break

        # Execute each tool call
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            result = await handler(tc.function.name, args)
            result_str = json.dumps(result, ensure_ascii=False)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate(result_str, 5000),
            })

        # Terminate if metric was reported
        if handler.reported_metric is not None:
            log.info("ReAct: metric reported at step %d: %s", step, handler.reported_metric)
            break

        # Nudge when running low on steps
        if step == max_steps - 5 and handler.reported_metric is None:
            messages.append({
                "role": "user",
                "content": (
                    "[System] 5 steps remaining. If you already have a measurement, "
                    "call report_metric() now. Otherwise, run the benchmark immediately "
                    "and report the result."
                ),
            })

    return messages


# ─── MCP tools ────────────────────────────────────────────────────────

@mcp.tool()
async def extract_metric_from_output(output_text: str, metric_name: str) -> dict:
    """Use LLM to extract a numeric metric value from raw benchmark output text."""
    prompt = (f"Extract the {metric_name} value from the output below.\n"
              "Return ONLY valid JSON: {\"value\": float or null, \"unit\": str, \"raw_match\": str}\n"
              f"Output:\n{output_text[-2000:]}")
    try:
        resp = await litellm.acompletion(model=_model(), messages=[{"role": "user", "content": prompt}],
                                         temperature=0, timeout=60,
                                         **({"api_base": _api_base()} if _api_base() else {}))
        raw = resp.choices[0].message.content or ""
        if "</think>" in raw:
            raw = raw.split("</think>")[-1]
        s = raw.find("{"); e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            res = json.loads(raw[s:e])
            if res.get("value") is not None:
                res["value"] = float(res["value"])
            return res
    except Exception:
        pass
    # Regex fallback
    _m = re.search(r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)", output_text, re.IGNORECASE)
    if _m:
        return {"value": float(_m.group(1)), "unit": "", "raw_match": _m.group(0)}
    return {"value": None, "unit": "", "raw_match": "", "error": "extraction failed"}


@mcp.tool()
async def reproduce_from_paper(
    paper_path: str = "",
    paper_text: str = "",
    experiment_goal: str = "",
    work_dir: str = "",
    source_file: str = "",
    executor: str = "",
    cpus: int = 64,
    timeout_minutes: int = 15,
    tolerance_pct: float = 5.0,
) -> dict:
    """Reproduce an experiment described in a paper using a ReAct agent loop.

    The agent autonomously: reads the paper → writes code → compiles →
    runs small tests → profiles → fixes → runs full benchmark → reports metric.

    Args:
        paper_path:      Path to .tex/.pdf paper
        paper_text:      Paper content (alternative to paper_path)
        experiment_goal: Optional hint about what to reproduce
        work_dir:        Working directory for generated files
        source_file:     (unused, kept for API compat)
        executor:        "local"|"slurm"|"pbs"|"lsf" (default: ARI_EXECUTOR env)
        cpus:            CPU thread count to request
        timeout_minutes: Max wait time per job
        tolerance_pct:   Acceptable deviation from claimed value (%)
    """
    # ── Load paper ──
    if not paper_text and paper_path:
        p = Path(paper_path)
        if p.suffix == ".pdf":
            try:
                r = subprocess.run(["pdftotext", str(p), "-"],
                                   capture_output=True, text=True, timeout=30)
                paper_text = r.stdout
            except Exception:
                pass
        if not paper_text:
            try:
                paper_text = p.read_text()
            except Exception as e:
                return {"error": f"Cannot read paper: {e}", "verdict": "ERROR"}
    if not paper_text:
        return {"error": "No paper text provided", "verdict": "ERROR"}

    _max_snippet = 30000
    if len(paper_text) <= _max_snippet:
        paper_snippet = paper_text
    else:
        paper_snippet = paper_text[:20000] + "\n\n[...truncated...]\n\n" + paper_text[-10000:]

    # ── Resolve executor ──
    exe_kind = executor or os.environ.get("ARI_EXECUTOR", "local")
    partition = os.environ.get("ARI_SLURM_PARTITION", "")
    if exe_kind == "slurm" and not partition:
        try:
            _sinfo = subprocess.run(["sinfo", "-h", "-o", "%P"],
                                    capture_output=True, text=True, timeout=5)
            _parts = [p.strip().rstrip("*") for p in _sinfo.stdout.strip().splitlines() if p.strip()]
            if _parts:
                partition = _parts[0]
                log.info("Auto-detected SLURM partition: %s", partition)
        except Exception:
            pass
    if exe_kind == "slurm" and not partition:
        log.warning("SLURM partition unavailable — falling back to local executor")
        exe_kind = "local"

    wdir = work_dir or "/tmp/ari_repro"
    Path(wdir).mkdir(parents=True, exist_ok=True)
    log_file = str(Path(wdir) / "repro_output.log")

    # ── Extract claimed config from paper ──
    config_raw = await _llm(
        "Extract the PRIME experimental result from the paper — the value "
        "highlighted in the abstract and conclusion as the paper's main achievement. "
        "This is NOT necessarily from the 'main' benchmark setup; it is the number "
        "the authors chose to advertise. "
        "Do NOT use theoretical peaks, roofline upper bounds, or predictions. "
        "Include in the description the EXACT experimental parameters "
        "(all sizes, settings, configuration) stated near the claimed value. "
        "Return ONLY JSON: {\"metric_name\": str, \"claimed_value\": float, \"description\": str}. "
        "No markdown.",
        f"Paper:\n{paper_snippet}",
    )
    m = re.search(r"\{.*\}", config_raw, re.DOTALL)
    if not m:
        return {"error": "Could not extract config", "raw": config_raw, "verdict": "ERROR"}
    try:
        config = json.loads(m.group(0))
    except Exception as e:
        return {"error": f"JSON parse: {e}", "verdict": "ERROR"}

    metric_name = config.get("metric_name", "metric")
    claimed_val = float(config.get("claimed_value", 0))
    description = config.get("description", "")

    _claimed_threads = None
    _thread_m = re.search(r"(\d+)\s*(?:OpenMP\s+)?threads", description, re.IGNORECASE)
    if _thread_m:
        _claimed_threads = int(_thread_m.group(1))
    threads = _claimed_threads or cpus or 1

    exe = Executor(exe_kind, threads, timeout_minutes, log_file, extra={"partition": partition})

    # ── ReAct agent loop ──
    tool_defs = _react_tool_defs(exe_kind)
    handler = _ToolHandler(wdir, exe, timeout_minutes)

    goal_hint = f"\nExperiment goal: {experiment_goal}" if experiment_goal else ""

    system_prompt = (
        "You are a reproducibility engineer verifying a scientific paper's experimental claims.\n"
        "Your task: independently reproduce the reported result using ONLY the paper text.\n\n"
        "WORKFLOW — follow these steps:\n"
        "1. ANALYZE the paper carefully. Identify:\n"
        "   - The exact algorithm and its structure as described or shown in pseudocode\n"
        "   - All settings, parameters, and environment configuration mentioned\n"
        "   - ALL numerical parameters for the main configuration\n"
        "   - CRITICAL: The paper may describe multiple configurations with different parameters. "
        "Find the EXACT parameters that produced the target metric value by reading the "
        "surrounding context of the claimed number. Use ONLY those parameters — not parameters "
        "from a different experiment or configuration described elsewhere in the paper.\n\n"
        "2. CHECK the execution environment:\n"
        "   - Inspect CPU architecture, compiler version, and system topology\n"
        "   - Verify available resources match the paper's requirements\n\n"
        "3. IMPLEMENT the source code matching the paper's description precisely.\n"
        "   - If the paper provides pseudocode, replicate its structure exactly\n"
        "   - Implement all optimizations and preprocessing steps described\n"
        "   - Apply all settings stated in the paper\n\n"
        "4. COMPILE and run a SMALL-SCALE correctness test (reduced problem size).\n\n"
        "5. RUN the full-scale benchmark with the paper's exact parameters.\n\n"
        "6. DIAGNOSE if the result deviates >20%% from the claimed value:\n"
        "   - Profile the execution to identify bottlenecks\n"
        "   - Compare your implementation against the paper's description\n"
        "   - Experiment with settings mentioned in the paper\n"
        "   - Fix any discrepancies and re-run\n\n"
        "7. Call report_metric(value=...) with the final reliable measurement.\n\n"
        "CRITICAL RULES:\n"
        "- Reproduce the paper's algorithm faithfully — do NOT 'improve' it\n"
        "- Use EXACTLY the parameters stated for the main configuration\n"
        "- Apply all settings and configuration described in the paper\n"
        "- Report ONLY values from actual measurements, never fabricated numbers\n\n"
        f"Execution environment: {exe.describe()}\n"
        f"Work directory: {wdir}\n"
        f"Available CPU threads: {threads}\n"
    )

    user_prompt = (
        f"Paper text:\n{paper_snippet}\n\n"
        f"Target: reproduce {metric_name} = {claimed_val}\n"
        f"Description: {description}\n"
        f"{goal_hint}\n\n"
        "Begin now. Start by analyzing the Methodology, then check the environment, "
        "implement the code, and run the experiment."
    )

    react_messages = await _run_react(
        system_prompt, user_prompt, tool_defs, handler, max_steps=40,
    )

    # ── Extract results ──
    actual_val = None
    if handler.reported_metric:
        actual_val = handler.reported_metric["value"]

    # Fallback: scan tool outputs for METRIC: pattern
    if actual_val is None:
        for msg in reversed(react_messages):
            if msg.get("role") == "tool":
                _m_fb = re.search(
                    r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)",
                    msg.get("content", ""), re.IGNORECASE,
                )
                if _m_fb:
                    actual_val = float(_m_fb.group(1))
                    log.info("Fallback metric extraction from tool output: %s", actual_val)
                    break

    # Collect last tool output snippet for the report
    actual_output = ""
    for msg in reversed(react_messages):
        if msg.get("role") == "tool" and msg.get("content", ""):
            actual_output = msg["content"][:500]
            break

    # Save ReAct conversation log for debugging
    try:
        _log_entries = []
        for msg in react_messages:
            entry = {"role": msg.get("role", ""), "content": (msg.get("content") or "")[:300]}
            if msg.get("tool_calls"):
                entry["tool_calls"] = [tc["function"]["name"] for tc in msg["tool_calls"]]
            if msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]
            _log_entries.append(entry)
        Path(wdir, "react_log.json").write_text(
            json.dumps(_log_entries, indent=2, ensure_ascii=False))
    except Exception:
        pass

    # ── Compute verdict ──
    if actual_val is None:
        verdict, diff_pct = "UNVERIFIABLE", None
    else:
        diff_pct = abs(actual_val - claimed_val) / claimed_val * 100 if claimed_val != 0 else None
        verdict = (
            "REPRODUCED" if (diff_pct is not None and diff_pct <= tolerance_pct)
            else "PARTIAL" if (diff_pct is not None and diff_pct <= 20.0)
            else "NOT_REPRODUCED"
        )

    diff_str = f"{diff_pct:.1f}%" if diff_pct is not None else "N/A"
    notes_ctx = ""
    if handler.reported_metric and handler.reported_metric.get("notes"):
        notes_ctx = f" Agent notes: {handler.reported_metric['notes'][:200]}"
    interp = await _llm(
        "Write a 2-3 sentence reproducibility verdict. Be factual, concise. No markdown.",
        f"Paper claims {claimed_val} {metric_name}. Measured: {actual_val}. "
        f"Verdict: {verdict} (diff: {diff_str}).{notes_ctx}",
    )

    return {
        "verdict": verdict,
        "job_id": handler.job_id,
        "executor": exe_kind,
        "claimed_config": config,
        "claimed_value": claimed_val,
        "actual_value": actual_val,
        "diff_pct": round(diff_pct, 2) if diff_pct is not None else None,
        "metric_name": metric_name,
        "tolerance_pct": tolerance_pct,
        "interpretation": interp,
        "actual_output_snippet": actual_output,
    }


def main():
    mcp.run()

if __name__ == "__main__":
    main()
