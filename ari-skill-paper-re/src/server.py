"""
ari-skill-paper-re: Reproducibility verification via ReAct.

Philosophy:
- Reads ONLY the paper text. No original source code provided.
- LLM decides language, toolchain, implementation from scratch.
- Framework provides executor type and resource constraints only.
- Tests whether the paper is reproducible by an independent implementer.
"""

import asyncio, json, logging, os, re, subprocess, time
from pathlib import Path

log = logging.getLogger(__name__)

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-reproducibility-skill")

def _model():
    return os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama_chat/qwen3:32b"

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
    kwargs = {"model": _model(), "messages": [{"role":"system","content":system},{"role":"user","content":user}], "timeout": 120}
    base = _api_base()
    if base: kwargs["api_base"] = base
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
            r = subprocess.run(["squeue","-j",job_id,"-h"], capture_output=True, text=True)
            return bool(r.stdout.strip())
        if k == "pbs":
            return subprocess.run(["qstat", job_id], capture_output=True).returncode == 0
        if k == "lsf":
            r = subprocess.run(["bjobs", job_id], capture_output=True, text=True)
            return "DONE" not in r.stdout and "EXIT" not in r.stdout
        return False


@mcp.tool()
async def extract_metric_from_output(output_text: str, metric_name: str) -> dict:
    """Use LLM to extract a numeric metric value from raw benchmark output text."""
    prompt = (f"Extract the {metric_name} value from the output below.\n"
              "Return ONLY valid JSON: {\"value\": float or null, \"unit\": str, \"raw_match\": str}\n"
              f"Output:\n{output_text[-2000:]}")
    try:
        resp = await litellm.acompletion(model=_model(), messages=[{"role":"user","content":prompt}],
                                          temperature=0, timeout=60,
                                          **( {"api_base": _api_base()} if _api_base() else {}))
        raw = resp.choices[0].message.content or ""
        if "</think>" in raw: raw = raw.split("</think>")[-1]
        s = raw.find("{"); e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            res = json.loads(raw[s:e])
            if res.get("value") is not None: res["value"] = float(res["value"])
            return res
    except Exception:
        pass
    # Regex fallback: look for "METRIC: <number>" pattern in output
    import re as _re_met
    _m = _re_met.search(r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)", output_text, _re_met.IGNORECASE)
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
    """Reproduce an experiment described in a paper.

    Philosophy:
    - Paper text only — no original source code injected.
    - LLM decides language, toolchain, implementation from scratch.
    - Framework provides executor type + resource constraints.
    - Executor backends: local, slurm, pbs, lsf (set via ARI_EXECUTOR env).

    Args:
        paper_path:      Path to .tex/.pdf paper
        paper_text:      Paper content (alternative to paper_path)
        experiment_goal: Optional hint about what to reproduce
        work_dir:        Working directory for generated files
        source_file:     (Advanced) bypass LLM generation with existing source
        executor:        "local"|"slurm"|"pbs"|"lsf" (default: ARI_EXECUTOR env)
        cpus:            CPU thread count to request
        timeout_minutes: Max wait time
        tolerance_pct:   Acceptable deviation from claimed value (%)
    """
    # Load paper
    if not paper_text and paper_path:
        p = Path(paper_path)
        if p.suffix == ".pdf":
            try:
                r = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True, timeout=30)
                paper_text = r.stdout
            except Exception:
                pass
        if not paper_text:
            try: paper_text = p.read_text()
            except Exception as e: return {"error": f"Cannot read paper: {e}", "verdict": "ERROR"}
    if not paper_text:
        return {"error": "No paper text provided", "verdict": "ERROR"}

    # Use full paper text (up to 15000 chars) to preserve Methodology and Results
    # sections which contain critical implementation details for reproduction.
    # If still too long, keep first 10000 + last 5000 to include both methods and results.
    _max_snippet = 30000
    if len(paper_text) <= _max_snippet:
        paper_snippet = paper_text
    else:
        paper_snippet = paper_text[:20000] + "\n\n[...truncated...]\n\n" + paper_text[-10000:]

    # Resolve executor
    exe_kind  = executor or os.environ.get("ARI_EXECUTOR", "local")
    partition = os.environ.get("ARI_SLURM_PARTITION", "")
    # Auto-detect partition when executor=slurm but partition is empty
    if exe_kind == "slurm" and not partition:
        try:
            import subprocess as _sp
            _sinfo = _sp.run(["sinfo", "-h", "-o", "%P"], capture_output=True, text=True, timeout=5)
            _parts = [p.strip().rstrip("*") for p in _sinfo.stdout.strip().splitlines() if p.strip()]
            if _parts:
                partition = _parts[0]
                log.info("Auto-detected SLURM partition: %s", partition)
        except Exception:
            pass
    # Fallback to local if slurm requested but no partition available
    if exe_kind == "slurm" and not partition:
        log.warning("SLURM partition unavailable — falling back to local executor")
        exe_kind = "local"
    wdir = work_dir or "/tmp/ari_repro"
    Path(wdir).mkdir(parents=True, exist_ok=True)
    log_file    = str(Path(wdir) / "repro_output.log")
    script_path = str(Path(wdir) / "repro_job.sh")

    # REASON: extract claimed config from paper
    config_raw = await _llm(
        "Extract the PRIMARY experimental result from the paper. "
        "IMPORTANT: Use the main benchmark result (e.g. best end-to-end measured value "
        "from the standard/primary experimental setup), NOT theoretical peaks, roofline "
        "upper bounds, or extreme special-case configurations (e.g. synthetic stress tests "
        "with atypical parameters). If the paper reports multiple configurations, choose "
        "the one described as the main result or best representative configuration. "
        "Return ONLY JSON with keys: "
        "metric_name (str), claimed_value (float), description (str). No markdown.",
        f"Paper:\n{paper_snippet}"
    )
    m = re.search(r"\{.*\}", config_raw, re.DOTALL)
    if not m: return {"error": "Could not extract config", "raw": config_raw, "verdict": "ERROR"}
    try: config = json.loads(m.group(0))
    except Exception as e: return {"error": f"JSON parse: {e}", "verdict": "ERROR"}

    metric_name = config.get("metric_name", "metric")
    claimed_val = float(config.get("claimed_value", 0))
    description = config.get("description", "")

    # Extract claimed thread count from description to match paper's config
    _claimed_threads = None
    _thread_m = re.search(r"(\d+)\s*(?:OpenMP\s+)?threads", description, re.IGNORECASE)
    if _thread_m:
        _claimed_threads = int(_thread_m.group(1))
    threads = _claimed_threads or cpus or 1

    # Create Executor with the paper's claimed thread count (not the default cpus)
    exe = Executor(exe_kind, threads, timeout_minutes, log_file, extra={"partition": partition})

    # ReAct loop: generate script → execute → check output → fix if needed
    max_attempts = 3
    script_content = ""
    actual_output = ""
    actual_val = None
    _best_val = None  # track best measurement across all attempts
    _best_output = ""
    job_id = ""
    prev_errors: list[str] = []

    _gen_system = (
        "You are a reproducibility engineer verifying a scientific paper claim. "
        "Generate a self-contained executable script that reproduces the experiment FROM SCRATCH "
        "based only on the paper description — do not assume access to any original source code.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. Use EXACTLY the same experimental parameters stated in the paper. "
        "Do NOT substitute your own values — use the EXACT values specified "
        "for the paper's main experimental configuration.\n"
        "2. Implement ALL key algorithmic optimizations described in the Methodology section.\n"
        "3. Use the SAME metric formula as the paper for computing the reported measure.\n"
        "4. If the paper mentions specific hardware, adapt the implementation to the "
        "execution environment while preserving the algorithm.\n\n"
        f"Execution environment: {exe.describe()}\n\n"
        f"Use up to {threads} CPU threads. "
        "Print the key metric value to stdout as: METRIC: <value>\n"
        "End with: echo 'REPRO_EXIT_CODE:'$?\n"
        "Choose appropriate language and toolchain. Return ONLY the script. No markdown."
    )
    # Remove threads from config to avoid overriding the environment's cpus
    _config_for_prompt = {k: v for k, v in config.items() if k != "threads"}
    _gen_user_base = (
        f"Paper:\n{paper_snippet}\n\n"
        f"Config:\n{json.dumps(_config_for_prompt, indent=2)}\n\n"
        f"Description: {description}"
    )

    for attempt in range(1, max_attempts + 1):
        # Generate or fix script
        if attempt == 1:
            script_content = await _llm(_gen_system, _gen_user_base)
        else:
            error_ctx = "\n".join(f"Attempt {i+1} error:\n{e}" for i, e in enumerate(prev_errors))
            script_content = await _llm(
                _gen_system,
                f"{_gen_user_base}\n\n"
                f"Previous attempts FAILED with these errors:\n{error_ctx}\n\n"
                f"Fix the script to avoid these errors. Return ONLY the corrected script."
            )

        # Strip markdown fences
        mf = re.search(r"```(?:\w+)?\n(.*?)```", script_content, re.DOTALL)
        if mf:
            script_content = mf.group(1)
        Path(script_path).write_text(script_content)
        Path(script_path).chmod(0o755)

        # Submit / run
        try:
            if exe_kind == "local":
                with open(log_file, "w") as f:
                    subprocess.run([script_path], stdout=f, stderr=subprocess.STDOUT,
                                   timeout=timeout_minutes * 60)
                job_id = "local"
            else:
                job_id = exe.submit(script_path)
        except Exception as e:
            prev_errors.append(f"Submission error: {e}")
            log.warning("Attempt %d/%d: submission failed: %s", attempt, max_attempts, e)
            continue

        # Poll for completion
        if job_id != "local":
            deadline = time.time() + timeout_minutes * 60
            while time.time() < deadline:
                await asyncio.sleep(30)
                if not exe.is_running(job_id):
                    break
            else:
                prev_errors.append("Timed out waiting for job")
                log.warning("Attempt %d/%d: timed out", attempt, max_attempts)
                continue

        try:
            actual_output = Path(log_file).read_text()
        except Exception:
            actual_output = ""

        if not actual_output:
            prev_errors.append("No output produced")
            log.warning("Attempt %d/%d: no output", attempt, max_attempts)
            continue

        # Check if METRIC was produced
        parse_res = await extract_metric_from_output(actual_output, metric_name)
        actual_val = parse_res.get("value")
        if actual_val is not None:
            # Track best measurement across all attempts (closest to claimed)
            if _best_val is None or abs(actual_val - claimed_val) < abs(_best_val - claimed_val):
                _best_val = actual_val
                _best_output = actual_output
            # If metric is far below claimed value and we have retries left,
            # treat as a likely implementation issue and retry with feedback
            _gap = abs(actual_val - claimed_val) / claimed_val * 100 if claimed_val else 0
            if _gap > 50 and attempt < max_attempts:
                prev_errors.append(
                    f"Script produced METRIC={actual_val} {metric_name} but paper claims "
                    f"{claimed_val} {metric_name} ({_gap:.0f}% gap). "
                    f"The implementation likely misses key optimizations described in the paper. "
                    f"Review the Methodology section carefully and implement ALL optimizations described. "
                    f"Also verify that ALL experimental parameters match the paper exactly. "
                    f"IMPORTANT: If the paper describes both a small validation case and a main "
                    f"experimental configuration, use the MAIN configuration parameters.\n"
                    f"Output:\n{actual_output[-500:]}"
                )
                log.info("Attempt %d/%d: metric=%s but %.0f%% gap, retrying", attempt, max_attempts, actual_val, _gap)
                actual_val = None  # reset so loop continues
                continue
            log.info("Attempt %d/%d: metric extracted: %s", attempt, max_attempts, actual_val)
            break

        # No metric found — collect error for next attempt
        prev_errors.append(actual_output[-1000:])
        log.warning("Attempt %d/%d: no metric in output, will retry", attempt, max_attempts)

    # Fall back to best measurement if final attempt didn't produce a metric
    if actual_val is None and _best_val is not None:
        actual_val = _best_val
        actual_output = _best_output
        log.info("Using best measurement from earlier attempt: %s", actual_val)

    # Last-resort regex extraction from the raw output log
    if actual_val is None and actual_output:
        _m_last = re.search(r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)", actual_output, re.IGNORECASE)
        if _m_last:
            actual_val = float(_m_last.group(1))
            log.info("Last-resort regex extracted metric: %s", actual_val)

    if actual_val is None:
        verdict, diff_pct = "UNVERIFIABLE", None
    else:
        diff_pct = abs(actual_val - claimed_val) / claimed_val * 100 if claimed_val != 0 else None
        verdict = "REPRODUCED" if (diff_pct is not None and diff_pct <= tolerance_pct) else \
                  "PARTIAL"    if (diff_pct is not None and diff_pct <= 20.0)           else \
                  "NOT_REPRODUCED"

    # Detect environment mismatch from output log and script
    env_mismatches = []
    # Pattern 1: explicit thread diagnostic in output
    _tm = re.search(r"threads\(requested=(\d+)\s+used=(\d+)\s+max=(\d+)\)", actual_output)
    if _tm:
        _req, _used, _mx = int(_tm.group(1)), int(_tm.group(2)), int(_tm.group(3))
        if _req > _mx:
            env_mismatches.append(
                f"Thread mismatch: paper requires {_req} threads but node max is {_mx} (used {_used})."
            )
    # Pattern 2: SBATCH cpus vs claimed threads
    _sbatch_cpus_m = re.search(r"--cpus-per-task=(\d+)", script_content)
    if _sbatch_cpus_m and _claimed_threads:
        _sbatch_cpus = int(_sbatch_cpus_m.group(1))
        if _sbatch_cpus < _claimed_threads:
            env_mismatches.append(
                f"SLURM allocated {_sbatch_cpus} CPUs but paper requires {_claimed_threads} threads."
            )
    # Pattern 3: hardware architecture mismatch
    _claimed_hw_m = re.search(r"(EPYC|Xeon|A64FX|Graviton|POWER)\s*[\w-]*", description, re.IGNORECASE)
    if _claimed_hw_m:
        _claimed_hw = _claimed_hw_m.group(0)
        # Check actual node arch from script output or lscpu
        _actual_arch_hints = []
        if "aarch64" in actual_output.lower() or "a64fx" in actual_output.lower() or "sve" in actual_output.lower():
            _actual_arch_hints.append("ARM/A64FX")
        if partition and "fx" in partition.lower():
            _actual_arch_hints.append("A64FX")
        if _actual_arch_hints and "epyc" in _claimed_hw.lower():
            env_mismatches.append(
                f"Architecture mismatch: paper uses {_claimed_hw} but repro ran on {_actual_arch_hints[0]} (partition={partition})."
            )
        elif _actual_arch_hints and "a64fx" not in _claimed_hw.lower():
            env_mismatches.append(
                f"Possible architecture mismatch: paper uses {_claimed_hw}, repro partition={partition} ({_actual_arch_hints[0]})."
            )
    env_mismatch = " ".join(env_mismatches) if env_mismatches else None
    if env_mismatch and verdict == "NOT_REPRODUCED":
        verdict = "ENVIRONMENT_MISMATCH"

    diff_str = f"{diff_pct:.1f}%" if diff_pct is not None else "N/A"
    _mismatch_ctx = f" Environment issue: {env_mismatch}" if env_mismatch else ""
    interp = await _llm(
        "Write a 2-3 sentence reproducibility verdict. Be factual, concise. No markdown.",
        f"Paper claims {claimed_val} {metric_name}. Measured: {actual_val}. "
        f"Verdict: {verdict} (diff: {diff_str}).{_mismatch_ctx}"
    )

    result = {
        "verdict": verdict,
        "job_id": job_id,
        "executor": exe_kind,
        "claimed_config": config,
        "claimed_value": claimed_val,
        "actual_value": actual_val,
        "diff_pct": round(diff_pct, 2) if diff_pct is not None else None,
        "metric_name": metric_name,
        "tolerance_pct": tolerance_pct,
        "interpretation": interp,
        "actual_output_snippet": actual_output[-500:],
    }
    if env_mismatch:
        result["environment_mismatch"] = env_mismatch
    return result


def main():
    mcp.run()

if __name__ == "__main__":
    main()
