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
import json
import os
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


def _collect_source_files(node: dict, max_total: int = 16000) -> str:
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

    # Accept any text-based source file; exclude known binary/data extensions
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
            snippet = text[:4000]
            entry = f"── {f.name} ──\n{snippet}\n"
            if total + len(entry) > max_total:
                break
            parts.append(entry)
            total += len(entry)
        if total >= max_total:
            break

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
    ranked = [
        {"rank": i + 1, "parameters": {}, "metrics": n.get("metrics", {})}
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
        summary = n.get("eval_summary", "")
        source_code = _collect_source_files(n, max_total=4000)
        lines = [
            f"{indent}[{label.upper()} depth={n.get('depth', depth)}]",
            f"{indent}  metrics: {metrics_str}",
            f"{indent}  summary: {summary[:200]}",
            f"{indent}  artifacts: {artifact_text[:800]}",
        ]
        if source_code:
            lines.append(f"{indent}  source_files:\n{source_code}")
        return "\n".join(lines)

    # Traverse tree breadth-first, preserving parent→child relationships
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
        if n.get("has_real_data") and n.get("metrics"):
            depth = n.get("depth", 0)
            artifact_blocks.append(_node_block(n, depth))
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
        "experiment directories (under 'source_files:'). If present, extract all "
        "details from the code that an independent researcher would need to "
        "reproduce the exact same results. Include these under "
        "'implementation_details' within 'experiment_context'. "
        "Extract ONLY what is actually present — do not invent details.\n\n"
        "Return ONLY valid JSON with keys 'evaluation_protocol' and 'experiment_context'. "
        "No markdown fences.\n\n"
        f"EXPERIMENT TREE:\n{artifacts_combined[:16000]}"
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

    return {
        "configurations": ranked,
        "per_key_summary": per_key_summary,
        "experiment_context": experiment_context,
        "summary_stats": {
            "count": len(ranked),
            "best": max((v["best_value"] for v in per_key_summary.values()), default=0),
        },
    }


if __name__ == "__main__":
    mcp.run()
