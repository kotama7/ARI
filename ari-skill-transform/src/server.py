"""
ari-skill-transform: LLM-powered experiment tree analysis.

Reads nodes_tree.json (BFTS output) and uses an LLM to deeply understand:
- Hardware environment discovered during experiments
- Implementation methodology of the best configurations
- Performance measurements and their scientific meaning
- Comparison baselines if any were measured
- Key findings suitable for paper writing

Replaces the former regex-only transform with full LLM comprehension.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transform-skill")


def _load_nodes(nodes_json_path: str) -> list[dict]:
    data = json.loads(Path(nodes_json_path).read_text())
    return data if isinstance(data, list) else data.get("nodes", [])


def _node_artifacts_text(node: dict, max_chars: int = 3000) -> str:
    """Extract text from node artifacts and memory for LLM analysis."""
    parts = []
    for art in (node.get("artifacts") or []):
        if isinstance(art, dict):
            for key in ("stdout", "content", "output", "text"):
                val = art.get(key, "")
                if val:
                    parts.append(str(val))
                    break
        elif isinstance(art, str):
            parts.append(art)
    for mem in (node.get("memory") or []):
        text = mem if isinstance(mem, str) else mem.get("content", "")
        if text:
            parts.append(str(text))
    combined = "\n".join(parts)
    return combined[:max_chars]


def _node_tool_outputs(node: dict, max_chars: int = 2000) -> str:
    """Extract actual tool execution outputs from trace_log.

    This is a deterministic extraction (no LLM, no domain knowledge).
    It makes the agent's real observations available so downstream
    LLM analysis is grounded in facts rather than guesses.

    trace_log entries can be either:
      - dicts with {"role": "tool", "content": "..."}
      - strings like "  ← {'result': '...'}" (arrow format)
    """
    import ast
    parts = []
    total = 0
    for entry in (node.get("trace_log") or []):
        content = ""
        if isinstance(entry, dict):
            if entry.get("role") != "tool":
                continue
            content = entry.get("content", "")
        elif isinstance(entry, str):
            # Arrow format: tool results start with "  ← "
            stripped = entry.strip()
            if not stripped.startswith("←") and not stripped.startswith("\u2190"):
                continue
            # Extract the result part after the arrow
            arrow_idx = stripped.find("←")
            if arrow_idx < 0:
                arrow_idx = stripped.find("\u2190")
            if arrow_idx >= 0:
                payload = stripped[arrow_idx + 1:].strip()
                # Try to parse as Python dict literal
                try:
                    parsed = ast.literal_eval(payload)
                    if isinstance(parsed, dict):
                        content = parsed.get("result", str(parsed))
                    else:
                        content = str(parsed)
                except Exception:
                    content = payload
        else:
            continue

        if not content or len(str(content)) < 10:
            continue
        # Unwrap JSON-wrapped results
        if isinstance(content, str) and content.startswith("{"):
            try:
                parsed = json.loads(content)
                content = parsed.get("result", content)
            except Exception:
                pass
        text = str(content).strip()
        if not text:
            continue
        chunk = text[:800]
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n---\n".join(parts)


def _collect_source_files(node: dict, max_total: int = 32000) -> str:
    """Read source files from the node's experiment directory on disk.

    Scans artifact commands for directory paths, then reads .c, .cpp, .h,
    .f90, .sh, and Makefile files from those directories.
    Returns formatted source code snippets with filenames.
    """
    import re as _re_sf
    dirs_seen: set[str] = set()
    for art in (node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        # Extract 'cd /path/to/...' from shell commands
        for m in _re_sf.finditer(r'cd\s+(/\S+)', content):
            d = m.group(1).rstrip("&;|")
            if Path(d).is_dir():
                dirs_seen.add(d)

    if not dirs_seen:
        return ""

    # Exclude known binary and non-text extensions
    _binary_exts = {
        ".o", ".a", ".so", ".dylib", ".dll", ".exe", ".bin",
        ".pyc", ".pyo", ".class", ".jar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".pdf", ".ps", ".eps",
        ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z",
        ".pkl", ".npy", ".npz", ".h5", ".hdf5",
        ".csv", ".tsv", ".parquet",
        ".log", ".out", ".err",
    }
    parts = []
    total = 0
    for d in sorted(dirs_seen):
        dp = Path(d)
        for f in sorted(dp.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() in _binary_exts:
                continue
            # Skip files larger than 64KB (likely data, not source)
            try:
                if f.stat().st_size > 65536:
                    continue
            except Exception:
                continue
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            if not text.strip():
                continue
            snippet = text[:8000]
            entry = f"── {f.name} ──\n{snippet}\n"
            if total + len(entry) > max_total:
                continue  # try remaining smaller files
            parts.append(entry)
            total += len(entry)

    return "\n".join(parts)


@mcp.tool()
async def nodes_to_science_data(
    nodes_json_path: str,
    llm_model: str = "",
    llm_base_url: str = "",
) -> dict:
    """
    LLM-powered conversion of BFTS experiment tree to publication-ready scientific data.

    Unlike a regex approach, the LLM reads the actual experiment outputs (stdout,
    logs, scripts) and extracts rich scientific context: hardware specs, methodology,
    implementation details, comparison baselines, and key findings.

    Args:
        nodes_json_path: Path to nodes_tree.json produced by BFTS
        llm_model:       LLM model name (litellm format). Falls back to env LLM_MODEL.
        llm_base_url:    Optional base URL for OpenAI-compatible API.

    Returns:
        configurations:  list of {rank, parameters, metrics} for successful nodes
        per_key_summary: best/min/max/n per metric key
        experiment_context: LLM-extracted dict with hardware, methodology, findings
        summary_stats:   basic count/best stats
    """
    try:
        nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": str(e), "configurations": []}

    # Filter to successful nodes with real measurements
    good_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    if not good_nodes:
        return {"error": "No successful nodes with real data found", "configurations": []}

    # Build ranked configurations (no domain-specific sorting — pass all to LLM)
    # Include eval_summary and label so downstream stages (paper writing,
    # reproducibility check) can associate each metric with the experiment
    # that produced it (kernel type, configuration, setup).
    ranked = [
        {
            "rank": i + 1,
            "parameters": {},
            "metrics": n.get("metrics", {}),
            "label": n.get("label", ""),
            "eval_summary": (n.get("eval_summary") or "")[:400],
        }
        for i, n in enumerate(good_nodes)
    ]

    # Per-key summary
    all_keys: list[str] = []
    for n in good_nodes:
        for k in n.get("metrics", {}):
            if k not in all_keys:
                all_keys.append(k)
    per_key_summary: dict = {}
    for k in all_keys:
        vals = [n["metrics"][k] for n in good_nodes
                if k in n.get("metrics", {}) and isinstance(n["metrics"][k], (int, float))]
        if vals:
            per_key_summary[k] = {
                "best_value": max(vals), "min": min(vals),
                "max": max(vals), "n": len(vals)
            }

    # ── LLM analysis: read top nodes' artifacts and extract scientific context ──
    model = llm_model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
    # Build a tree-aware summary: preserve parent-child structure so the LLM
    # understands the search trajectory (root → improve → ablation → validation).
    # Include ALL successful nodes (not just top-5) so ablation/validation results appear.
    node_index = {n["id"]: n for n in nodes if "id" in n}

    def _node_block(n, depth=0) -> str:
        indent = "  " * depth
        label = n.get("label", "?")
        metrics_str = json.dumps(n.get("metrics", {}), ensure_ascii=False)
        artifact_text = _node_artifacts_text(n, max_chars=1500)
        tool_outputs = _node_tool_outputs(n, max_chars=2000)
        summary = n.get("eval_summary", "")
        source_code = _collect_source_files(n, max_total=16000)
        lines = [
            f"{indent}[{label.upper()} depth={n.get('depth', depth)}]",
            f"{indent}  metrics: {metrics_str}",
            f"{indent}  summary: {summary[:500]}",
            f"{indent}  artifacts: {artifact_text[:2000]}",
        ]
        if tool_outputs:
            lines.append(f"{indent}  execution_outputs:\n{tool_outputs}")
        if source_code:
            lines.append(f"{indent}  source_files:\n{source_code}")
        return "\n".join(lines)

    # Traverse tree breadth-first, preserving parent→child relationships.
    # Include ALL nodes (not just successful ones) so the LLM can see
    # the full execution context — including environment observations
    # that may have been captured in exploratory or failed nodes.
    artifact_blocks = []
    visited = set()
    queue = [n for n in nodes if not n.get("parent_id")]  # roots first
    if not queue:
        queue = list(nodes[:1])
    while queue:
        n = queue.pop(0)
        nid = n.get("id", "")
        if nid in visited:
            continue
        visited.add(nid)
        depth = n.get("depth", 0)
        if n.get("has_real_data") and n.get("metrics"):
            artifact_blocks.append(_node_block(n, depth))
        else:
            # Non-successful nodes: include tool outputs only (compact)
            tool_out = _node_tool_outputs(n, max_chars=2000)
            if tool_out:
                indent = "  " * depth
                label = n.get("label", "?")
                artifact_blocks.append(
                    f"{indent}[{label.upper()} depth={depth} (no metrics)]\n"
                    f"{indent}  execution_outputs:\n{tool_out}"
                )
        # enqueue children
        for child_id in (n.get("children") or []):
            if child_id in node_index and child_id not in visited:
                queue.append(node_index[child_id])

    artifacts_combined = "\n\n".join(artifact_blocks)

    analysis_prompt = (
        "You are a scientific analyst. Read the following experiment tree "
        "(nodes ordered root-to-leaf, showing the search trajectory) "
        "and extract information a peer reviewer needs to evaluate this work.\n\n"
        "Include only scientifically meaningful content: successful measurements, "
        "key improvements, ablation insights, and validated results. "
        "Omit failed runs, debug artifacts, and internal system details.\n\n"
        "Your JSON output MUST include an 'evaluation_protocol' object with:\n"
        "  - 'domain': what research domain/task this is (inferred from outputs)\n"
        "  - 'primary_metrics': list of the most important metrics for this domain "
        "(e.g. task-appropriate success rate, throughput, or accuracy — infer from the experiment outputs, do not assume domain)\n"
        "  - 'required_reporting': list of quantities that MUST be reported for "
        "reproducibility in this domain (sample size, sparsity, precision, config params, etc.)\n"
        "  - 'standard_baselines': list of standard baselines this domain typically compares against\n"
        "  - 'ablation_axes': list of the most scientifically meaningful dimensions to ablate\n\n"
        "Also include an 'experiment_context' object with all other findings. "
        "Use clear field names with units where applicable.\n\n"
        "The experiment tree may include actual source code and scripts from the "
        "experiment directories (under 'source_files:'). If present, extract ALL "
        "details from the code that an independent researcher would need to "
        "reproduce the exact same results. Include these under "
        "'implementation_details' within 'experiment_context'. Specifically:\n"
        "  - Pseudocode for the key algorithms and functions\n"
        "  - Data structures and their layouts\n"
        "  - All optimization techniques applied (with specifics, not just names)\n"
        "  - Build configuration and any platform-specific settings\n"
        "  - Exact experimental parameters used\n"
        "  - How each reported metric is computed\n"
        "Extract ONLY what is actually present in the tree — do not invent details. "
        "For any factual claim, it must be traceable to a specific node's output. "
        "If information was not captured during execution, write 'not recorded' "
        "rather than guessing.\n\n"
        "Return ONLY valid JSON with keys 'evaluation_protocol' and 'experiment_context'. "
        "No markdown fences.\n\n"
        f"EXPERIMENT TREE:\n{artifacts_combined[:64000]}"
    )

    experiment_context: dict = {}
    try:
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": analysis_prompt}],
        }
        if llm_base_url:
            kwargs["api_base"] = llm_base_url
        response = await litellm.acompletion(**kwargs)
        raw = response.choices[0].message.content or ""
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            # Support both new format {evaluation_protocol, experiment_context}
            # and legacy flat format
            if "experiment_context" in parsed:
                experiment_context = parsed["experiment_context"]
                experiment_context["_evaluation_protocol"] = parsed.get("evaluation_protocol", {})
            else:
                experiment_context = parsed
    except Exception as e:
        experiment_context = {"error": f"LLM analysis failed: {e}"}

    # Attach raw source code from the best nodes directly (not LLM-summarized)
    # so the paper writer can describe implementations with full fidelity.
    _best_sources = {}
    for n in good_nodes[:3]:
        src = _collect_source_files(n, max_total=16000)
        if src:
            label = n.get("label", n.get("id", "?"))[:30]
            _best_sources[label] = src
    if _best_sources:
        experiment_context["_best_node_source_code"] = _best_sources

    return {
        "configurations": ranked,
        "per_key_summary": per_key_summary,
        "experiment_context": experiment_context,
        "summary_stats": {
            "count": len(ranked),
            "best": max((v["best_value"] for v in per_key_summary.values()), default=0),
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# Experiment Artifact Repository (EAR) — issue #4
# ──────────────────────────────────────────────────────────────────────────


def _safe_run(cmd: list[str], timeout: int = 10) -> str:
    """Run a shell command and return its trimmed stdout, or '' on failure."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _capture_environment() -> dict:
    """Capture python version, platform, key packages, and hardware specs."""
    env: dict = {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "hostname": platform.node(),
    }
    # Best-effort: pip list (may take a few seconds; cap timeout)
    pip_out = _safe_run([sys.executable, "-m", "pip", "list", "--format=json"], timeout=15)
    if pip_out:
        try:
            env["installed_packages"] = json.loads(pip_out)
        except Exception:
            env["installed_packages"] = []
    else:
        env["installed_packages"] = []
    # Hardware specs (best-effort)
    cpu_count = os.cpu_count() or 0
    env["cpu_count"] = cpu_count
    # Linux memory
    try:
        with open("/proc/meminfo") as fh:
            meminfo = {}
            for line in fh:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = v.strip()
            if "MemTotal" in meminfo:
                env["mem_total"] = meminfo["MemTotal"]
    except Exception:
        pass
    return env


def _collect_node_source_dirs(node: dict) -> list[Path]:
    """Find on-disk experiment directories referenced by a node's artifacts."""
    import re as _re
    dirs: list[Path] = []
    seen: set[str] = set()
    for art in (node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        for m in _re.finditer(r"(?:cd|pushd)\s+(/\S+)", content):
            d = m.group(1).rstrip("&;|\"'")
            if d and d not in seen:
                p = Path(d)
                if p.is_dir():
                    dirs.append(p)
                    seen.add(d)
    return dirs


def _copy_node_sources(node: dict, dest_dir: Path) -> int:
    """Copy source files from a node's experiment directory into dest_dir.

    Returns the number of files copied.
    """
    src_dirs = _collect_node_source_dirs(node)
    if not src_dirs:
        return 0
    # Skip binary / heavy file extensions
    binary_exts = {
        ".o", ".a", ".so", ".dylib", ".dll", ".exe", ".bin",
        ".pyc", ".pyo", ".class", ".jar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".pdf", ".ps", ".eps",
        ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z",
        ".pkl", ".npy", ".npz", ".h5", ".hdf5",
        ".parquet",
    }
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for sd in src_dirs:
        for f in sorted(sd.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() in binary_exts:
                continue
            try:
                if f.stat().st_size > 256 * 1024:  # 256KB cap per file
                    continue
            except Exception:
                continue
            try:
                shutil.copy2(f, dest_dir / f.name)
                copied += 1
            except Exception:
                continue
    return copied


def _llm_generate_doc(prompt: str, model: str, base_url: str = "") -> str:
    """Best-effort LLM call. Returns empty string on failure (caller falls back)."""
    try:
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if base_url:
            kwargs["api_base"] = base_url
        resp = litellm.completion(**kwargs)
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""


def _build_readme_fallback(nodes: list[dict], goal: str, top_node: dict | None) -> str:
    """Deterministic README when LLM is unavailable."""
    n_total = len(nodes)
    n_real = sum(1 for n in nodes if n.get("has_real_data"))
    lines = [
        "# Experiment Artifact Repository",
        "",
        f"**Goal:** {goal[:400] if goal else '(not recorded)'}",
        "",
        f"- Total nodes explored: {n_total}",
        f"- Nodes with real measurements: {n_real}",
    ]
    if top_node:
        sci = (top_node.get("metrics") or {}).get("_scientific_score")
        lines.append(
            f"- Best node: id={top_node.get('id', '?')[-8:]} "
            f"score={sci if sci is not None else 'n/a'}"
        )
        if top_node.get("eval_summary"):
            lines.append("")
            lines.append(f"**Best result summary:** {top_node['eval_summary'][:300]}")
    return "\n".join(lines) + "\n"


def _build_results_md_fallback(nodes: list[dict]) -> str:
    """Deterministic RESULTS.md when LLM is unavailable."""
    real = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    real.sort(
        key=lambda n: float((n.get("metrics") or {}).get("_scientific_score") or 0.0),
        reverse=True,
    )
    lines = ["# Results", "", "| node_id | label | scientific_score | metrics |", "| --- | --- | --- | --- |"]
    for n in real[:25]:
        m = n.get("metrics") or {}
        sci = m.get("_scientific_score")
        sci_str = f"{float(sci):.2f}" if sci is not None else "n/a"
        metrics_str = json.dumps(
            {k: v for k, v in m.items() if not k.startswith("_")}, ensure_ascii=False
        )[:160]
        lines.append(
            f"| {str(n.get('id', '?'))[-8:]} | {n.get('label', '?')} | {sci_str} | {metrics_str} |"
        )
    if not real:
        lines.append("| _no nodes with measurements_ | | | |")
    return "\n".join(lines) + "\n"


def _build_commands_md(top_node: dict | None) -> str:
    """Document the commands needed to reproduce the top-scoring node."""
    if not top_node:
        return "# Reproduction commands\n\n_No top node available._\n"
    cmds: list[str] = []
    for art in (top_node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        if not content:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cmds.append(stripped)
    out = [
        "# Reproduction commands",
        "",
        f"_Top-scoring node: `{str(top_node.get('id', '?'))[-8:]}` "
        f"(label={top_node.get('label', '?')})_",
        "",
        "```bash",
    ]
    if cmds:
        out.extend(cmds[:50])
    else:
        out.append("# No reproducible commands captured for this node.")
    out.append("```")
    return "\n".join(out) + "\n"


def _consolidate_metrics(nodes: list[dict]) -> dict:
    """Consolidate per-node metrics into a single JSON-serialisable dict."""
    out: dict = {"nodes": [], "summary": {}}
    all_keys: dict[str, list] = {}
    for n in nodes:
        m = n.get("metrics") or {}
        if not m:
            continue
        out["nodes"].append({
            "id": n.get("id", ""),
            "label": n.get("label", ""),
            "raw_label": n.get("raw_label", ""),
            "depth": n.get("depth", 0),
            "has_real_data": bool(n.get("has_real_data", False)),
            "metrics": m,
        })
        for k, v in m.items():
            if isinstance(v, (int, float)):
                all_keys.setdefault(k, []).append(v)
    for k, vals in all_keys.items():
        if not vals:
            continue
        out["summary"][k] = {
            "min": min(vals),
            "max": max(vals),
            "mean": sum(vals) / len(vals),
            "count": len(vals),
        }
    return out


def _copy_figures(checkpoint_dir: Path, figures_dir: Path) -> int:
    """Copy any figure files (PDF/PNG/SVG) from the checkpoint into figures/."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for ext in ("*.pdf", "*.png", "*.svg", "*.jpg", "*.jpeg"):
        for f in checkpoint_dir.glob(ext):
            try:
                shutil.copy2(f, figures_dir / f.name)
                copied += 1
            except Exception:
                continue
    return copied


@mcp.tool()
def generate_ear(
    checkpoint_dir: str,
    llm_model: str = "",
    llm_base_url: str = "",
) -> dict:
    """Generate Experiment Artifact Repository directory from checkpoint.

    Builds a structured 'pseudo-GitHub' directory under <checkpoint_dir>/ear/
    containing README/RESULTS docs, source code, consolidated metrics,
    figures, environment info, and reproduction commands.

    Args:
        checkpoint_dir: Path to the checkpoint directory containing
            tree.json (or nodes_tree.json) and science_data.json.
        llm_model: Optional LLM model name (litellm format) used to
            auto-generate README.md and RESULTS.md. Falls back to a
            deterministic template when no LLM is available.
        llm_base_url: Optional base URL for OpenAI-compatible LLM APIs.

    Returns:
        Summary JSON containing:
        - ear_dir: Absolute path to the generated EAR directory
        - file_count: Number of files written under ear/
        - source_files: Number of source files copied
        - has_readme / has_results: Whether the docs were generated
    """
    ckpt = Path(checkpoint_dir).expanduser().resolve()
    if not ckpt.exists() or not ckpt.is_dir():
        return {"error": f"checkpoint dir not found: {ckpt}"}

    # ── Load tree ──
    tree_path = ckpt / "tree.json"
    if not tree_path.exists():
        tree_path = ckpt / "nodes_tree.json"
    if not tree_path.exists():
        return {"error": f"no tree.json or nodes_tree.json under {ckpt}"}
    try:
        tree_data = json.loads(tree_path.read_text())
    except Exception as e:
        return {"error": f"could not parse tree json: {e}"}

    nodes: list[dict] = tree_data if isinstance(tree_data, list) else tree_data.get("nodes", [])
    goal: str = (
        tree_data.get("experiment_goal", "") if isinstance(tree_data, dict) else ""
    )

    # ── Identify top-scoring node ──
    real_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    real_nodes.sort(
        key=lambda n: float((n.get("metrics") or {}).get("_scientific_score") or 0.0),
        reverse=True,
    )
    top_node = real_nodes[0] if real_nodes else None

    # ── Build EAR directory tree ──
    ear = ckpt / "ear"
    code_dir = ear / "code"
    data_dir = ear / "data"
    figures_dir = data_dir / "figures"
    logs_dir = ear / "logs"
    repro_dir = ear / "reproducibility"
    for d in (ear, code_dir, data_dir, figures_dir, logs_dir, repro_dir):
        d.mkdir(parents=True, exist_ok=True)

    file_count = 0
    source_files = 0

    # ── code/<node_id>/ — copy source files per node ──
    for n in nodes:
        node_id = str(n.get("id") or "").strip()
        if not node_id:
            continue
        node_dir = code_dir / node_id
        copied = _copy_node_sources(n, node_dir)
        if copied:
            source_files += copied
            file_count += copied
        else:
            # Remove empty per-node dir to avoid cluttering the tree
            try:
                node_dir.rmdir()
            except OSError:
                pass

    # ── data/raw_metrics.json ──
    raw_metrics = _consolidate_metrics(nodes)
    (data_dir / "raw_metrics.json").write_text(
        json.dumps(raw_metrics, ensure_ascii=False, indent=2)
    )
    file_count += 1

    # ── data/science_data.json (copy if present) ──
    sd_src = ckpt / "science_data.json"
    if sd_src.exists():
        try:
            shutil.copy2(sd_src, data_dir / "science_data.json")
            file_count += 1
        except Exception:
            pass

    # ── data/figures/ ──
    fig_count = _copy_figures(ckpt, figures_dir)
    file_count += fig_count

    # ── logs/bfts_tree.json ──
    try:
        shutil.copy2(tree_path, logs_dir / "bfts_tree.json")
        file_count += 1
    except Exception:
        pass

    # ── logs/eval_scores.json ──
    eval_scores = []
    for n in nodes:
        sci = (n.get("metrics") or {}).get("_scientific_score")
        if sci is not None:
            eval_scores.append({
                "node_id": n.get("id", ""),
                "label": n.get("label", ""),
                "raw_label": n.get("raw_label", ""),
                "depth": n.get("depth", 0),
                "scientific_score": sci,
                "eval_summary": (n.get("eval_summary") or "")[:500],
            })
    (logs_dir / "eval_scores.json").write_text(
        json.dumps(eval_scores, ensure_ascii=False, indent=2)
    )
    file_count += 1

    # ── reproducibility/environment.json ──
    env_info = _capture_environment()
    (repro_dir / "environment.json").write_text(
        json.dumps(env_info, ensure_ascii=False, indent=2)
    )
    file_count += 1

    # ── reproducibility/run_config.json ──
    run_config: dict = {
        "checkpoint_dir": str(ckpt),
        "experiment_goal": goal[:1000] if goal else "",
        "node_count": len(nodes),
        "real_data_count": len(real_nodes),
    }
    # Pull workflow.yaml summary if available
    wf = ckpt.parent.parent / "config" / "workflow.yaml"
    if wf.exists():
        try:
            run_config["workflow_yaml"] = wf.read_text()[:4000]
        except Exception:
            pass
    (repro_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2)
    )
    file_count += 1

    # ── reproducibility/commands.md ──
    (repro_dir / "commands.md").write_text(_build_commands_md(top_node))
    file_count += 1

    # ── README.md ──
    model = llm_model or os.environ.get("LLM_MODEL", "") or os.environ.get("ARI_LLM_MODEL", "")
    base_url = llm_base_url or os.environ.get("ARI_LLM_API_BASE", "")
    readme_text = ""
    if model:
        readme_prompt = (
            "Write a concise README.md for an experiment artifact repository. "
            "Cover: (1) what was done, (2) the best result, (3) the key finding. "
            "Keep it under ~200 words and avoid speculation. "
            f"Goal: {goal[:600]}\n\n"
            f"Top result metrics: {json.dumps((top_node or {}).get('metrics', {}), ensure_ascii=False)}\n"
            f"Top result summary: {((top_node or {}).get('eval_summary') or '')[:600]}\n"
            f"Total nodes: {len(nodes)}, with measurements: {len(real_nodes)}.\n\n"
            "Return Markdown only, no code fences."
        )
        readme_text = _llm_generate_doc(readme_prompt, model, base_url)
    if not readme_text:
        readme_text = _build_readme_fallback(nodes, goal, top_node)
    (ear / "README.md").write_text(readme_text)
    file_count += 1

    # ── RESULTS.md ──
    results_text = ""
    if model:
        results_prompt = (
            "Generate a structured RESULTS.md for an experiment artifact repository. "
            "Include: (1) a metrics table for the top configurations, "
            "(2) a comparison table vs. baseline / parent if any, "
            "(3) one short paragraph on what the best run achieved. "
            "Use Markdown tables. Do NOT invent metrics that are not in the data.\n\n"
            f"Top nodes (sorted by scientific_score):\n"
            f"{json.dumps([{'id': n.get('id', '')[-8:], 'label': n.get('label', ''), 'metrics': n.get('metrics', {})} for n in real_nodes[:10]], ensure_ascii=False, indent=2)}\n\n"
            "Return Markdown only, no code fences."
        )
        results_text = _llm_generate_doc(results_prompt, model, base_url)
    if not results_text:
        results_text = _build_results_md_fallback(nodes)
    (ear / "RESULTS.md").write_text(results_text)
    file_count += 1

    return {
        "ear_dir": str(ear),
        "file_count": file_count,
        "source_files": source_files,
        "figure_count": fig_count,
        "node_count": len(nodes),
        "has_readme": (ear / "README.md").exists(),
        "has_results": (ear / "RESULTS.md").exists(),
        "top_node_id": (top_node or {}).get("id", ""),
    }


if __name__ == "__main__":
    mcp.run()
