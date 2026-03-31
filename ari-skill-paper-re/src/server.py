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
                    f"time=00:{self.timeout_minutes:02d}:00, output={self.log_file}; "
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

    paper_snippet = paper_text[:6000]

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
    exe = Executor(exe_kind, cpus, timeout_minutes, log_file, extra={"partition": partition})

    # REASON: extract claimed config from paper
    config_raw = await _llm(
        "Extract experiment config from the paper. Return ONLY JSON with keys: "
        "threads (int), metric_name (str), claimed_value (float), description (str). No markdown.",
        f"Paper:\n{paper_snippet}"
    )
    m = re.search(r"\{.*\}", config_raw, re.DOTALL)
    if not m: return {"error": "Could not extract config", "raw": config_raw, "verdict": "ERROR"}
    try: config = json.loads(m.group(0))
    except Exception as e: return {"error": f"JSON parse: {e}", "verdict": "ERROR"}

    threads     = int(config.get("threads", None) or cpus or 1)
    metric_name = config.get("metric_name", "metric")
    claimed_val = float(config.get("claimed_value", 0))
    description = config.get("description", "")

    # ReAct loop: generate script → execute → check output → fix if needed
    max_attempts = 3
    script_content = ""
    actual_output = ""
    actual_val = None
    job_id = ""
    prev_errors: list[str] = []

    _gen_system = (
        "You are a reproducibility engineer verifying a scientific paper claim. "
        "Generate a self-contained executable script that reproduces the experiment FROM SCRATCH "
        "based only on the paper description — do not assume access to any original source code.\n\n"
        f"Execution environment: {exe.describe()}\n\n"
        f"Use up to {threads} CPU threads. "
        "Print the key metric value to stdout as: METRIC: <value>\n"
        "End with: echo 'REPRO_EXIT_CODE:'$?\n"
        "Choose appropriate language and toolchain. Return ONLY the script. No markdown."
    )
    _gen_user_base = (
        f"Paper:\n{paper_snippet}\n\n"
        f"Config:\n{json.dumps(config, indent=2)}\n\n"
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
            log.info("Attempt %d/%d: metric extracted: %s", attempt, max_attempts, actual_val)
            break

        # No metric found — collect error for next attempt
        prev_errors.append(actual_output[-1000:])
        log.warning("Attempt %d/%d: no metric in output, will retry", attempt, max_attempts)

    if actual_val is None:
        verdict, diff_pct = "UNVERIFIABLE", None
    else:
        diff_pct = abs(actual_val - claimed_val) / claimed_val * 100 if claimed_val != 0 else None
        verdict = "REPRODUCED" if (diff_pct is not None and diff_pct <= tolerance_pct) else \
                  "PARTIAL"    if (diff_pct is not None and diff_pct <= 20.0)           else \
                  "NOT_REPRODUCED"

    diff_str = f"{diff_pct:.1f}%" if diff_pct is not None else "N/A"
    interp = await _llm(
        "Write a 2-3 sentence reproducibility verdict. Be factual, concise. No markdown.",
        f"Paper claims {claimed_val} {metric_name}. Measured: {actual_val}. Verdict: {verdict} (diff: {diff_str})."
    )

    return {
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


def main():
    mcp.run()

if __name__ == "__main__":
    main()
