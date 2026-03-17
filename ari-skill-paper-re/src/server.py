"""
ari-skill-paper-re: Reproducibility verification via ReAct.

Reads ONLY the paper text to extract experiment configuration,
submits an HPC job to actually reproduce the experiment,
and compares measured results against paper claims.

No access to nodes_tree.json or internal experiment data.
LLM exception (P2): requires reasoning for config extraction and verdict.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-reproducibility-skill")

# ── LLM helpers ──────────────────────────────────────────────────────────────

def _model() -> str:
    return (os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama_chat/qwen3:32b")

def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE"); return (ari if ari is not None else os.environ.get("LLM_API_BASE", "http://127.0.0.1:11434")) or None

async def _llm(system: str, user: str) -> str:
    kwargs = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


# ── Tool ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def extract_metric_from_output(
    output_text: str,
    metric_name: str,
) -> dict:
    """Use LLM to extract a numeric metric value from raw benchmark output text.

    More robust than regex: handles varied output formats, units, and edge cases.

    Args:
        output_text: Raw stdout/stderr from the benchmark job
        metric_name: Name of the metric to extract (e.g. "MFLOPS", "throughput")

    Returns:
        {value: float | null, unit: str, raw_match: str}
    """
    import os, json as _json

    _model = (os.environ.get("ARI_LLM_MODEL")
              or os.environ.get("LLM_MODEL")
              or "ollama_chat/qwen3:32b")
    ari_base = os.environ.get("ARI_LLM_API_BASE"); _api_base = (ari_base if ari_base is not None else os.environ.get("LLM_API_BASE", "")) or ""

    prompt = (
        f"Extract the {metric_name} value from the following benchmark output.\n"
        f"Return ONLY valid JSON with keys: value (float or null), unit (string), raw_match (string).\n"
        f"If multiple values appear, return the final/last one.\n"
        f"Output:\n{output_text[-2000:]}"
    )
    try:
        import litellm
        resp = await litellm.acompletion(
            model=_model,
            **( {"api_base": _api_base} if _api_base else {}),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # Strip <think> tags
        if "</think>" in raw:
            raw = raw.split("</think>")[-1]
        raw = raw.strip()
        # Extract JSON
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = _json.loads(raw[start:end])
            # Ensure value is float or None
            if result.get("value") is not None:
                result["value"] = float(result["value"])
            return result
    except Exception as e:
        pass
    return {"value": None, "unit": "", "raw_match": "", "error": "extraction failed"}


@mcp.tool()
async def reproduce_from_paper(
    paper_path: str = "",
    paper_text: str = "",
    experiment_goal: str = "",
    work_dir: str = "",
    source_file: str = "",
    slurm_partition: str = "cpu",
    slurm_cpus: int = 64,
    timeout_minutes: int = 15,
    tolerance_pct: float = 5.0,
) -> dict:
    """Reproduce an experiment described in a paper using a ReAct loop.

    Reads ONLY the paper text (no access to internal experiment records).

    ReAct loop:
      Reason  → Extract claimed configuration (compiler flags, threads, expected metric)
      Act     → Submit SLURM job with that configuration
      Observe → Parse actual results from job output
      Reason  → Compare against paper claims; generate verdict

    Args:
        paper_path:      Path to .tex/.pdf paper file
        paper_text:      Paper content (if paper_path not given)
        experiment_goal: What the paper claims to do (e.g. "maximize throughput")
        work_dir:        Working directory on HPC (for compilation)
        source_file:     Source code path on HPC to compile+run
        slurm_partition: SLURM partition to use
        slurm_cpus:      Number of CPUs to request
        timeout_minutes: Max wait time for job completion
        tolerance_pct:   Tolerance for claim matching (%)

    Returns:
        verdict, claimed_config, actual_result, matched_claims, report
    """
    # ── Load paper ────────────────────────────────────────────────────────────
    if not paper_text and paper_path:
        try:
            paper_text = Path(paper_path).read_text()
        except Exception as e:
            return {"error": f"Cannot read paper: {e}", "verdict": "ERROR"}

    if not paper_text:
        return {"error": "No paper text provided", "verdict": "ERROR"}

    paper_snippet = paper_text[:6000]  # keep token budget reasonable

    # ── REASON: Extract experiment config from paper ───────────────────────
    extract_prompt = (
        "You are a reproducibility engineer. Read the paper excerpt and extract "
        "the exact experiment configuration needed to reproduce the main result. "
        "Return ONLY valid JSON with these keys:\n"
        "  compiler: str (e.g. 'gcc')\n"
        "  flags: str (e.g. '-O3 -ffast-math -march=native')\n"
        "  threads: int (number of threads/processes)\n"
        "  metric_name: str (e.g. 'throughput', 'accuracy', or any metric name)\n"
        "  claimed_value: float (the main claimed result value)\n"
        "  description: str (one sentence describing what to run)\n"
        "No markdown fences. Pure JSON only."
    )
    extract_raw = await _llm(extract_prompt, f"Paper excerpt:\n{paper_snippet}")
    m = re.search(r"\{.*\}", extract_raw, re.DOTALL)
    if not m:
        return {"error": "Could not extract config from paper", "raw": extract_raw, "verdict": "ERROR"}
    try:
        config = json.loads(m.group(0))
    except Exception as e:
        return {"error": f"JSON parse failed: {e}", "raw": extract_raw, "verdict": "ERROR"}

    compiler    = config.get("compiler", "gcc")
    flags       = config.get("flags", "-O3 -ffast-math -march=native")
    threads     = int(config.get("threads", slurm_cpus))
    metric_name = config.get("metric_name", "metric")
    claimed_val = float(config.get("claimed_value", 0))
    description = config.get("description", "")

    # ── ACT: Build and submit SLURM job ──────────────────────────────────────
    if not source_file:
        return {
            "verdict": "SKIPPED",
            "reason": "source_file not provided; cannot run experiment",
            "claimed_config": config,
        }

    wdir = work_dir or str(Path(source_file).parent)
    src  = Path(source_file)
    binary = str(Path(wdir) / "repro_binary")
    log_file = str(Path(wdir) / "repro_output.log")

    job_script = f"""#!/bin/bash
#SBATCH --job-name=ari-repro
#SBATCH --partition={slurm_partition}
#SBATCH --cpus-per-task={threads}
#SBATCH --time=00:{timeout_minutes}:00
#SBATCH --output={log_file}

export OMP_NUM_THREADS={threads}
{compiler} {flags} -fopenmp -o {binary} {source_file} -lm 2>&1 && \\
{binary} | tee -a {log_file}
echo "REPRO_EXIT_CODE:$?"
"""
    script_path = str(Path(wdir) / "repro_job.sh")
    try:
        Path(script_path).write_text(job_script)
    except Exception as e:
        return {"error": f"Cannot write job script: {e}", "verdict": "ERROR"}

    try:
        result = subprocess.run(
            ["sbatch", script_path],
            capture_output=True, text=True, timeout=30
        )
        job_id_match = re.search(r"Submitted batch job (\d+)", result.stdout)
        if not job_id_match:
            return {"error": f"sbatch failed: {result.stderr}", "claimed_config": config, "verdict": "ERROR"}
        job_id = job_id_match.group(1)
    except Exception as e:
        return {"error": f"sbatch exception: {e}", "claimed_config": config, "verdict": "ERROR"}

    # ── OBSERVE: Poll for job completion ─────────────────────────────────────
    deadline = time.time() + timeout_minutes * 60
    actual_output = ""
    while time.time() < deadline:
        await asyncio.sleep(30)
        check = subprocess.run(
            ["squeue", "-j", job_id, "-h"], capture_output=True, text=True
        )
        if not check.stdout.strip():
            # Job finished
            try:
                actual_output = Path(log_file).read_text()
            except Exception:
                actual_output = ""
            break

    if not actual_output:
        return {
            "error": "Job timed out or no output",
            "job_id": job_id,
            "claimed_config": config,
            "verdict": "TIMEOUT",
        }

    # Use LLM-based metric extraction instead of regex
    _parse_result = await extract_metric_from_output(
        output_text=actual_output,
        metric_name=metric_name,
    )
    actual_val = _parse_result.get("value")

    # ── REASON: Compare and generate verdict ──────────────────────────────────
    if actual_val is None:
        verdict = "UNVERIFIABLE"
        diff_pct = None
    else:
        diff_pct = abs(actual_val - claimed_val) / claimed_val * 100 if claimed_val > 0 else None
        if diff_pct is not None and diff_pct <= tolerance_pct:
            verdict = "REPRODUCED"
        elif diff_pct is not None and diff_pct <= 20.0:
            verdict = "PARTIAL"
        else:
            verdict = "NOT_REPRODUCED"

    # LLM generates final interpretation
    interp_prompt = (
        "You are writing a short reproducibility verdict (2-3 sentences). "
        "Be factual and concise. No markdown."
    )
    diff_str = f"{diff_pct:.1f}%" if diff_pct is not None else "N/A"
    interp_user = (
        f"Paper claims {claimed_val:,.1f} {metric_name} using: {flags}, {threads} threads.\n"
        f"Reproduction measured: {actual_val} {metric_name}.\n"
        f"Verdict: {verdict} (diff: {diff_str}).\n"
        f"Write the interpretation."
    )
    interpretation = await _llm(interp_prompt, interp_user)

    return {
        "verdict": verdict,
        "job_id": job_id,
        "claimed_config": config,
        "claimed_value": claimed_val,
        "actual_value": actual_val,
        "diff_pct": round(diff_pct, 2) if diff_pct is not None else None,
        "metric_name": metric_name,
        "tolerance_pct": tolerance_pct,
        "interpretation": interpretation,
        "actual_output_snippet": actual_output[-500:],
    }


def main():
    mcp.run()

if __name__ == "__main__":
    main()