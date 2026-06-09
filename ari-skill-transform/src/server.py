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
import re
import shutil
import subprocess
import sys
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transform-skill")


def _default_llm_model() -> str:
    """Pick a fallback model that matches the active backend.

    Why this exists: ``nodes_to_science_data`` and similar transforms are
    invoked from workflow.yaml without an explicit ``llm_model`` argument. The
    historical default ``gpt-4o-mini`` is an OpenAI-only model name, but when
    ``ARI_BACKEND=cli-shim`` the ``ari.cost_tracker`` litellm injector
    auto-fills ``api_base`` with ``ARI_LLM_API_BASE`` for *every* call. The
    cli-shim then rejects ``gpt-4o-mini`` with
    ``unknown model 'gpt-4o-mini'; expected one of claude-cli, ...`` and the
    whole analysis returns an error string that ends up in
    ``experiment_context.error`` of science_data.json. Falling back to
    ``claude-cli`` when the backend is cli-shim lines the model up with what
    the shim actually serves.
    """
    backend = (os.environ.get("ARI_BACKEND") or "").strip().lower()
    if backend in ("cli-shim", "cli_shim"):
        return "claude-cli"
    return "gpt-4o-mini"


try:
    try:
        from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore
    except ImportError:
        from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("transform")
except Exception:
    pass


def _load_nodes(nodes_json_path: str) -> list[dict]:
    data = json.loads(Path(nodes_json_path).read_text())
    return data if isinstance(data, list) else data.get("nodes", [])


def _robust_extract_json(raw: str) -> dict:
    """Extract a JSON object from an LLM response, surviving common malformations.

    Strategy (each step is best-effort and falls through on failure):
      1. Strip <think>…</think> blocks and ```json fences.
      2. Walk balanced braces from each candidate '{' to find the largest
         valid object (handles "{...} prose {...}" by parsing the right one,
         not the concatenation that the legacy greedy `\\{.*\\}` produced).
      3. As a last resort, try the legacy first-`{` to last-`}` slice.

    Raises ValueError with the underlying parser message if every attempt
    fails. Caller is responsible for saving the raw payload for debugging
    before swallowing the error.
    """
    if not raw:
        raise ValueError("empty response")
    # Strip <think>...</think> noise some models emit.
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Strip the most common code fences.
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    # Walk balanced braces from each '{' to find the largest valid object.
    candidates: list[str] = []
    n = len(text)
    for start in range(n):
        if text[start] != "{":
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, n):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break
    # Prefer the longest candidate (typically the outermost / most complete).
    candidates.sort(key=len, reverse=True)
    last_err: Exception | None = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception as e:
            last_err = e
            continue

    # Last-resort: legacy first-`{` to last-`}` slice.
    s = text.find("{")
    e_ = text.rfind("}") + 1
    if s >= 0 and e_ > s:
        try:
            return json.loads(text[s:e_])
        except Exception as e:
            last_err = e

    raise ValueError(f"could not extract JSON: {last_err}")


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
        # pipeline.py now enriches each
        # node with Letta-backed memory entries that carry `text`; the
        # legacy `content` key is kept for pre-v0.6.0 fixtures.
        text = mem if isinstance(mem, str) else (
            mem.get("text") or mem.get("content") or ""
        )
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


_SOURCE_EXTS = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".py", ".pyx", ".pyi",
    ".cu", ".cuh", ".cl",
    ".rs", ".go", ".java", ".kt", ".scala",
    ".js", ".jsx", ".ts", ".tsx", ".mjs",
    ".f", ".f90", ".f95", ".f03", ".for",
    ".jl", ".m", ".r", ".sh", ".bash", ".zsh",
    ".tex", ".bib",
    ".yaml", ".yml", ".toml", ".json",
    ".md", ".rst", ".txt",
    ".cmake", ".mk",
}

_BINARY_MAGIC_PREFIXES = (
    b"\x7fELF",          # ELF executable / shared object
    b"MZ",               # PE/COFF (Windows .exe / .dll)
    b"\xCF\xFA\xED\xFE", # Mach-O 64-bit LE
    b"\xCE\xFA\xED\xFE", # Mach-O 32-bit LE
    b"\xFE\xED\xFA\xCE", # Mach-O 32-bit BE
    b"\xFE\xED\xFA\xCF", # Mach-O 64-bit BE
    b"\xCA\xFE\xBA\xBE", # Java class / Mach-O fat
    b"PK\x03\x04",       # ZIP / JAR / docx
    b"\x1f\x8b",         # gzip
    b"BZh",              # bzip2
    b"\xFD7zXZ\x00",     # xz
    b"7z\xBC\xAF\x27\x1C", # 7-zip
    b"\x89PNG\r\n\x1a\n", # PNG
    b"\xFF\xD8\xFF",     # JPEG
    b"%PDF",             # PDF
    b"\x93NUMPY",        # numpy .npy
    b"\x80\x04",         # python pickle protocol 4
    b"\x80\x05",         # python pickle protocol 5
)


def _looks_like_binary(path: Path) -> bool:
    """Detect binary content by magic bytes / NUL presence / printable ratio.

    Catches files that slip past extension-based filters (e.g. compiled
    executables produced by g++ with no extension like ``spmm_envelope``).
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(4096)
    except Exception:
        return True
    if not head:
        return False
    for magic in _BINARY_MAGIC_PREFIXES:
        if head.startswith(magic):
            return True
    if b"\x00" in head:
        return True
    # Printable-ASCII ratio over the sniff window. Tabs/newlines/CR count
    # as printable; anything below 85% printable is treated as binary.
    printable = sum(
        1 for b in head
        if 0x20 <= b < 0x7F or b in (0x09, 0x0A, 0x0D, 0x0C)
    )
    return (printable / len(head)) < 0.85


def _collect_source_files(node: dict, max_total: int = 65536) -> str:
    """Read source files from the node's experiment directory on disk.

    Two artifact shapes are supported (mirrors ``_collect_node_source_dirs``
    in the EAR generator):
    1. Shell-script content containing ``cd /path``.
    2. Absolute file or directory paths recorded as artifact strings —
       the parent directory of such a file is treated as the node's
       working directory.

    Source-extension files (``.cpp``, ``.py``, ...) are processed before
    other files so that even when the budget fills up the actual source
    code is preserved (the failure mode otherwise: a sibling compiled
    binary with no extension consumes the budget and the ``.cpp`` is
    dropped, leaving the paper writer with no algorithm body).

    Returns formatted source code snippets with filenames.
    """
    import re as _re_sf
    dirs_seen: set[str] = set()
    for art in (node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        if not content:
            continue
        for m in _re_sf.finditer(r'cd\s+(/\S+)', content):
            d = m.group(1).rstrip("&;|")
            if Path(d).is_dir():
                dirs_seen.add(d)
        stripped = content.strip()
        if stripped.startswith("/") and "\n" not in stripped and " " not in stripped:
            p = Path(stripped)
            if p.is_file() and p.parent.is_dir():
                dirs_seen.add(str(p.parent))
            elif p.is_dir():
                dirs_seen.add(str(p))

    if not dirs_seen:
        return ""

    # Exclude known binary and non-text extensions (fast path; the
    # _looks_like_binary content sniff covers the rest, including
    # extensionless compiled executables).
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
    candidates: list[Path] = []
    for d in sorted(dirs_seen):
        dp = Path(d)
        try:
            entries = list(dp.iterdir())
        except Exception:
            continue
        for f in entries:
            if not f.is_file():
                continue
            if f.suffix.lower() in _binary_exts:
                continue
            candidates.append(f)
    # Sort: source-extension files first (priority 0), others second
    # (priority 1), alphabetical within each group. This keeps .cpp /
    # .py / etc. ahead of incidental siblings (logs, env captures,
    # extensionless binaries) so they survive the budget gate.
    candidates.sort(
        key=lambda p: (0 if p.suffix.lower() in _SOURCE_EXTS else 1, p.name)
    )

    parts = []
    total = 0
    for f in candidates:
        try:
            if f.stat().st_size > 65536:
                continue
        except Exception:
            continue
        if _looks_like_binary(f):
            continue
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        if not text.strip():
            continue
        snippet = text[:16000]
        entry = f"── {f.name} ──\n{snippet}\n"
        if total + len(entry) > max_total:
            continue  # try remaining smaller files
        parts.append(entry)
        total += len(entry)

    return "\n".join(parts)


def _load_node_reports_for_tree(nodes_json_path: str, nodes: list[dict]) -> dict[str, dict]:
    """Best-effort discovery of `node_report.json` files for *nodes*.

    Walks two candidate work_dir layouts so both PathManager-shaped
    workspaces (`{ws}/checkpoints/{run_id}/`,
    `{ws}/experiments/{run_id}/{node_id}/`) and flatter test fixtures work.
    """
    from pathlib import Path as _P
    p = _P(nodes_json_path).expanduser().resolve()
    if p.is_file():
        ckpt = p.parent
    else:
        ckpt = p if p.is_dir() else _P(".").resolve()

    workspace = ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent
    run_id = ckpt.name

    reports: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        for cand in (
            workspace / "experiments" / run_id / nid / "node_report.json",
            workspace / "experiments" / nid / "node_report.json",
            ckpt / "experiments" / nid / "node_report.json",
        ):
            if cand.is_file():
                try:
                    reports[nid] = json.loads(cand.read_text())
                except Exception:
                    continue
                break
    return reports


def _resolve_best_node_for_synthesis(nodes: list[dict]) -> str:
    """Same best-node rule as generate_ear (argmax score, validation tie-break)."""
    real = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    if not real:
        return ""
    real.sort(
        key=lambda n: (
            float((n.get("metrics") or {}).get("_scientific_score") or 0.0),
            1 if str(n.get("label") or "").lower() == "validation" else 0,
            int(n.get("depth") or 0),
        ),
        reverse=True,
    )
    return real[0].get("id", "")


@mcp.tool()
async def nodes_to_science_data(
    nodes_json_path: str,
    llm_model: str = "",
    llm_base_url: str = "",
    primary_metric: str = "",
    higher_is_better: str = "true",
) -> dict:
    """
    LLM-powered conversion of BFTS experiment tree to publication-ready scientific data.

    Unlike a regex approach, the LLM reads the actual experiment outputs (stdout,
    logs, scripts) and extracts rich scientific context: hardware specs, methodology,
    implementation details, comparison baselines, and key findings.

    Args:
        nodes_json_path:   Path to nodes_tree.json produced by BFTS
        llm_model:         LLM model name (litellm format). Falls back to env LLM_MODEL.
        llm_base_url:      Optional base URL for OpenAI-compatible API.
        primary_metric:    Name of the metric used for "best" reduction. When empty,
                           summary_stats omits a single-scalar best (the previous
                           naive max-over-all-values produced absurd results when the
                           metrics dict mixed measurements with input parameters like
                           nnz / M / K). Resolved upstream from evaluation_criteria.json.
        higher_is_better:  "true" or "false" — direction for primary_metric reduction.
                           Accepted as a string because workflow.yaml templating renders
                           bool values as their str() form.

    Returns:
        configurations:  list of {rank, parameters, metrics} for successful nodes
        per_key_summary: best/min/max/n per metric key
        experiment_context: LLM-extracted dict with hardware, methodology, findings
        summary_stats:   {count, primary_metric, primary_metric_best, direction}
        implementation_overview: optional LLM-produced architecture / key_algorithms /
                                 optimizations summary (only present when the model
                                 produced it as part of the JSON output)
        report_driven:   true when filter_nodes(for_synthesis) provided the LLM
                         input substrate (i.e. node_report.json is available);
                         false on the legacy artifact-text fallback.
    """
    _hib = str(higher_is_better).strip().lower() not in ("false", "0", "no", "")
    try:
        nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": str(e), "configurations": []}

    # ── Best-effort: load node_report.json for every node ──
    reports = _load_node_reports_for_tree(nodes_json_path, nodes)

    # Filter to successful nodes with real measurements
    good_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    if not good_nodes:
        return {"error": "No successful nodes with real data found", "configurations": []}

    # ── results.json (typed coding-skill emit_results contract) ──
    # Each node's work_dir may contain a typed payload that splits inputs
    # (params) from outputs (measurements/predictions/scores). When present,
    # we propagate it onto configurations[*] so paper-writing and figure
    # generation can tell apart "what we ran on" from "what we measured" —
    # otherwise the metrics dict mixes both and per_key_summary's reduction
    # treats input sizes (nnz, M, K) as candidate maxima.
    _ckpt_dir = Path(nodes_json_path).expanduser().resolve().parent
    _workspace = (
        _ckpt_dir.parent.parent if _ckpt_dir.parent.name == "checkpoints"
        else _ckpt_dir.parent
    )
    _run_id = _ckpt_dir.name

    def _node_results_json(nid: str) -> dict:
        """Return parsed results.json for a node, or {} when absent / malformed."""
        if not nid:
            return {}
        cand = _workspace / "experiments" / _run_id / nid / "results.json"
        if not cand.is_file():
            cand = _workspace / "experiments" / nid / "results.json"
            if not cand.is_file():
                return {}
        try:
            data = json.loads(cand.read_text())
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    # Map node_id → typed payload (only stores entries that exist on disk).
    typed_results: dict[str, dict] = {}
    for n in good_nodes:
        nid = n.get("id") or n.get("node_id") or ""
        rj = _node_results_json(nid)
        if rj:
            typed_results[nid] = rj

    # Build ranked configurations (no domain-specific sorting — pass all to LLM)
    # Include eval_summary and label so downstream stages (paper writing,
    # reproducibility check) can associate each metric with the experiment
    # that produced it (kernel type, configuration, setup).
    #
    # Source priority for the typed split (params / measurements):
    #   1. results.json (D — coding-skill emit_results contract). Authoritative
    #      because the experiment script declared its own contract.
    #   2. node.metrics["_params_dict"] / "_measurements_dict" (C — LLM
    #      evaluator emitted the split). Used when no results.json is on disk.
    #   3. Empty (legacy). parameters stays {} and downstream consumers
    #      treat the flat metrics dict as a single ambiguous bag.
    ranked: list[dict] = []
    for i, n in enumerate(good_nodes):
        nid = n.get("id") or n.get("node_id") or ""
        cfg: dict = {
            "rank": i + 1,
            "parameters": {},
            "metrics": n.get("metrics", {}),
            "label": n.get("label", ""),
            "eval_summary": (n.get("eval_summary") or "")[:400],
        }
        rj = typed_results.get(nid) or {}
        if rj:
            if isinstance(rj.get("params"), dict):
                cfg["parameters"] = dict(rj["params"])
            if isinstance(rj.get("measurements"), dict):
                cfg["measurements"] = dict(rj["measurements"])
            if isinstance(rj.get("predictions"), dict):
                cfg["predictions"] = dict(rj["predictions"])
            if isinstance(rj.get("scores"), dict):
                cfg["scores"] = dict(rj["scores"])
            # Metric-correctness contract: carry the agent-emitted measurement
            # provenance ({metric_name: "microbench"|"benchmark"|...}) so the hard
            # gate can confirm a contract's required ceilings were MEASURED, not
            # a hardcoded placeholder. Domain-neutral: just a pass-through field.
            if isinstance(rj.get("_provenance"), dict):
                cfg["_provenance"] = dict(rj["_provenance"])
            cfg["_typed_schema_version"] = rj.get("schema_version", "")
            cfg["_typed_source"] = "results.json"
        else:
            # Fallback to the LLM evaluator's typed split if it was emitted.
            mref = n.get("metrics") or {}
            ev_params = mref.get("_params_dict") if isinstance(mref, dict) else None
            ev_meas = mref.get("_measurements_dict") if isinstance(mref, dict) else None
            if isinstance(ev_params, dict) and ev_params:
                cfg["parameters"] = dict(ev_params)
                cfg["_typed_source"] = "llm_evaluator"
            if isinstance(ev_meas, dict) and ev_meas:
                cfg["measurements"] = dict(ev_meas)
                cfg.setdefault("_typed_source", "llm_evaluator")
        ranked.append(cfg)

    # ── per_key_summary: exclude declared input parameters ──
    # Once a node declares a typed split (via results.json D-path OR via
    # the LLM evaluator's _params_dict C-path), its param keys are inputs
    # by construction and must NOT participate in best/min/max reductions
    # (they used to dominate via raw size — nnz=3.84M was bigger than any
    # GFlops/s measurement). Build a global "input_keys" set across nodes
    # and skip them in per_key_summary. Also exclude the reserved "_…"
    # bookkeeping keys that the evaluator stores on metrics.
    input_keys: set[str] = set()
    for rj in typed_results.values():
        if isinstance(rj.get("params"), dict):
            input_keys.update(str(k) for k in rj["params"].keys())
    for n in good_nodes:
        mref = n.get("metrics") or {}
        ev_params = mref.get("_params_dict") if isinstance(mref, dict) else None
        if isinstance(ev_params, dict):
            input_keys.update(str(k) for k in ev_params.keys())

    def _is_reserved(k: str) -> bool:
        # Underscore-prefixed keys are internal bookkeeping (axis scores,
        # composite, comparison flag, typed-split mirrors). They're not
        # measurements and must never appear in per_key_summary.
        return isinstance(k, str) and k.startswith("_")

    all_keys: list[str] = []
    for n in good_nodes:
        for k in n.get("metrics", {}):
            if k in all_keys or k in input_keys or _is_reserved(k):
                continue
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
    model = llm_model or os.environ.get("LLM_MODEL") or _default_llm_model()

    # ── Report-driven path: when reports exist, narrow the LLM input via
    #    filter_nodes(for_synthesis) and pull source bytes via the same
    #    selection that generate_ear publishes (FR-SS-5 contract).
    report_driven = False
    selected_source_blob = ""
    selected_node_blocks: list[str] = []
    best_id_for_synth = _resolve_best_node_for_synthesis(nodes)
    if reports and best_id_for_synth:
        try:
            from ari.orchestrator import node_selection as _ns

            kept = _ns.filter_nodes(
                nodes, reports, "for_synthesis",
                always_include_node_ids={best_id_for_synth},
            )
            # Build compact per-report blocks.
            for n in kept:
                rep = reports.get(n.get("id")) or {}
                label = str(n.get("label") or "?").upper()
                depth = n.get("depth", 0)
                metrics = json.dumps(n.get("metrics") or {}, ensure_ascii=False)
                fc = rep.get("files_changed") or {}
                added = [e.get("path") for e in (fc.get("added") or [])][:8]
                modified = [e.get("path") for e in (fc.get("modified") or [])][:8]
                sa = rep.get("self_assessment") or {}
                lines = [
                    f"[{label} depth={depth}]",
                    f"  metrics: {metrics}",
                ]
                if rep.get("delta_vs_parent"):
                    lines.append(f"  delta_vs_parent: {rep['delta_vs_parent'][:240]}")
                if added:
                    lines.append(f"  files_added: {added}")
                if modified:
                    lines.append(f"  files_modified: {modified}")
                if sa.get("headline"):
                    lines.append(f"  headline: {sa['headline'][:240]}")
                if sa.get("concerns"):
                    lines.append(f"  concerns: {sa['concerns'][:5]}")
                if rep.get("build_command"):
                    lines.append(f"  build: {rep['build_command'][:160]}")
                if rep.get("run_command"):
                    lines.append(f"  run: {rep['run_command'][:160]}")
                # Compute-resource provenance (where this measurement came from).
                # node_report exposes these as top-level fields when ari.agent.run_env
                # captured them; absent for legacy runs.
                _exec = rep.get("executor", "")
                _host = rep.get("hostname", "")
                _jid = rep.get("slurm_job_id", "")
                _part = rep.get("slurm_partition", "")
                _cpu = rep.get("cpu_info") or {}
                if _exec or _host:
                    parts = [f"executor={_exec or 'unknown'}", f"host={_host or 'unknown'}"]
                    if _part: parts.append(f"partition={_part}")
                    if _jid: parts.append(f"slurm_job={_jid}")
                    if _cpu.get("model"):
                        parts.append(
                            f"cpu={_cpu.get('model')[:60]} ({_cpu.get('threads', '?')}t)"
                        )
                    lines.append("  ran_on: " + ", ".join(parts))
                selected_node_blocks.append("\n".join(lines))

            # Pull verbatim source bytes — same selection used by generate_ear.
            from pathlib import Path as _P
            sel = _ns.select_source_files_for_publication(
                nodes, reports, best_id_for_synth,
            )
            ckpt_dir = _P(nodes_json_path).expanduser().resolve().parent
            workspace = (ckpt_dir.parent.parent
                         if ckpt_dir.parent.name == "checkpoints"
                         else ckpt_dir.parent)
            run_id_for_src = ckpt_dir.name

            def _wd(nid: str):
                cand = workspace / "experiments" / run_id_for_src / nid
                if cand.is_dir():
                    return cand
                return workspace / "experiments" / nid

            loaded = _ns.load_selected_sources(
                sel, work_dir_for=_wd, size_budget=16384,
            )
            for rel_path, payload in sorted(loaded.items()):
                try:
                    text = payload["bytes"].decode("utf-8", errors="replace")
                except Exception:
                    continue
                selected_source_blob += (
                    f"\n# === {rel_path} (from {payload['from_node_id']}) ===\n"
                    + text + "\n"
                )

            if selected_node_blocks:
                report_driven = True
        except Exception:
            report_driven = False

    # Legacy fallback: read artifacts text + tool outputs for every node.
    # Kept verbatim so checkpoints without node_report.json still work.
    node_index = {n["id"]: n for n in nodes if "id" in n}

    def _node_block(n, depth=0) -> str:
        indent = "  " * depth
        label = n.get("label", "?")
        metrics_str = json.dumps(n.get("metrics", {}), ensure_ascii=False)
        artifact_text = _node_artifacts_text(n, max_chars=1500)
        tool_outputs = _node_tool_outputs(n, max_chars=2000)
        summary = n.get("eval_summary", "")
        source_code = _collect_source_files(n, max_total=32000)
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

    if report_driven:
        # ── Compact prompt fed by node_report aggregates + verbatim source. ──
        # Drops 64KB-budgeted artifact text in favour of structured reports
        # plus the same source bytes that ear/code/ will publish (FR-SS-5).
        report_blob = "\n\n".join(selected_node_blocks)
        analysis_prompt = (
            "You are a scientific analyst. Read the following structured node "
            "reports (search trajectory; each node lists its delta_vs_parent, "
            "files added/modified, headline metric, concerns flagged by the "
            "evaluator, and the literal build/run commands) and the verbatim "
            "source files from the contributing chain, then extract what a "
            "peer reviewer needs to evaluate this work.\n\n"
            "Include only scientifically meaningful content: successful "
            "measurements, key improvements, ablation insights, and validated "
            "results. Omit failed runs and internal system details.\n\n"
            "Return ONLY valid JSON with these keys:\n"
            "  'evaluation_protocol': {domain, primary_metrics[], "
            "required_reporting[], standard_baselines[], ablation_axes[]}\n"
            "  'experiment_context': {hardware, methodology, findings, "
            "implementation_details, ...}\n"
            "    The 'hardware' field MUST be filled from the 'ran_on:' lines "
            "in the node reports — combine the executor type, hostname, "
            "SLURM partition, CPU model, thread count, and memory across "
            "contributing nodes. If different nodes ran on different hosts, "
            "list them. Do NOT write 'not recorded' when ran_on data is "
            "present in the reports.\n"
            "  'implementation_overview' (OPTIONAL): {architecture: '1-3 "
            "sentence prose summary', key_algorithms: [{name, pseudocode}], "
            "optimizations: ['…']}.  Omit this whole key if the reports do "
            "not contain enough material.  Do NOT include source code "
            "verbatim under this key — code lives in ear/code/.\n\n"
            "Extract ONLY what is actually present below. Do not invent "
            "details. If information was not captured, write 'not recorded'.\n\n"
            f"NODE REPORTS:\n{report_blob[:14000]}\n\n"
            f"VERBATIM SOURCE (from contributing chain):\n"
            f"{selected_source_blob[:16000]}"
        )
    else:
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
    implementation_overview: dict | None = None
    try:
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": analysis_prompt}],
            # NFR-6: observability meta — cost_tracker forwards this onto
            # the call record so we can grep for prompt-shrink coverage and
            # implementation_overview success rate over time.
            "metadata": {
                "skill": "transform",
                "tool": "nodes_to_science_data",
                "report_driven": report_driven,
                "prompt_chars": len(analysis_prompt),
                # Filled in below based on the parsed JSON.
                "implementation_overview_extracted": False,
            },
        }
        if llm_base_url:
            kwargs["api_base"] = llm_base_url
        response = await litellm.acompletion(**kwargs)
        raw = response.choices[0].message.content or ""
        try:
            parsed = _robust_extract_json(raw)
        except Exception as parse_err:
            # Persist the raw payload so the failure is debuggable. Without
            # this, the previous error message ("Expecting ':' delimiter")
            # was unactionable because the original response was discarded.
            try:
                _dbg = Path(nodes_json_path).expanduser().resolve().parent / "science_data.debug.txt"
                _dbg.write_text(
                    f"# nodes_to_science_data: JSON parse failed\n"
                    f"# error: {parse_err}\n"
                    f"# response_chars: {len(raw)}\n"
                    f"# ------ raw response ------\n{raw}\n"
                )
            except Exception:
                pass
            raise
        # Support both new format {evaluation_protocol, experiment_context}
        # and legacy flat format
        if "experiment_context" in parsed:
            experiment_context = parsed["experiment_context"]
            experiment_context["_evaluation_protocol"] = parsed.get("evaluation_protocol", {})
        else:
            experiment_context = parsed
        # Optional new-schema field. Surfaced into generate_ear's
        # README "Architecture" section if present.
        if isinstance(parsed.get("implementation_overview"), dict):
            implementation_overview = parsed["implementation_overview"]
            # Update the per-call meta so cost_tracker records success.
            kwargs["metadata"]["implementation_overview_extracted"] = True
    except Exception as e:
        experiment_context = {"error": f"LLM analysis failed: {e}"}

    # Attach raw source code from the best nodes directly (not LLM-summarized)
    # so the paper writer can describe implementations with full fidelity.
    _best_sources = {}
    for n in good_nodes[:3]:
        src = _collect_source_files(n, max_total=32000)
        if src:
            label = n.get("label", n.get("id", "?"))[:30]
            _best_sources[label] = src
    if _best_sources:
        experiment_context["_best_node_source_code"] = _best_sources

    # ── summary_stats: direction-aware reduction over the primary metric ──
    # Previously this was max() over every per_key_summary entry, which
    # picked the largest *number* regardless of what it represented (often
    # an input parameter like nnz=3,840,000). When a primary_metric is
    # known, reduce only over that key with the correct direction; when it
    # is not, omit the scalar best entirely rather than fabricate one.
    summary_stats: dict = {"count": len(ranked)}
    # typed_split_coverage: how many ranked configs have an authoritative
    # params/measurements split, broken down by source. Lets us monitor
    # adoption of the emit_results contract over time without grepping
    # individual configurations.
    _ts_counts: dict[str, int] = {"results.json": 0, "llm_evaluator": 0, "none": 0}
    for c in ranked:
        src = c.get("_typed_source") or "none"
        _ts_counts[src] = _ts_counts.get(src, 0) + 1
    summary_stats["typed_split_coverage"] = _ts_counts
    pm = (primary_metric or "").strip()
    if pm:
        summary_stats["primary_metric"] = pm
        summary_stats["direction"] = "higher_is_better" if _hib else "lower_is_better"
        pm_vals = [
            n["metrics"][pm] for n in good_nodes
            if pm in n.get("metrics", {})
            and isinstance(n["metrics"][pm], (int, float))
        ]
        if pm_vals:
            summary_stats["primary_metric_best"] = (
                max(pm_vals) if _hib else min(pm_vals)
            )
            summary_stats["primary_metric_n"] = len(pm_vals)
    out = {
        "configurations": ranked,
        "per_key_summary": per_key_summary,
        "experiment_context": experiment_context,
        "summary_stats": summary_stats,
        "report_driven": report_driven,
    }
    if implementation_overview is not None:
        out["implementation_overview"] = implementation_overview

    # ── Metric-correctness Phase 4: annotate physically-impossible metric values
    # (e.g. a normalized metric > 1) using the SAME universal invariant registry
    # the hard gate blocks on (ari-core, single source of truth — no duplicated
    # domain logic). The paper writer is told to avoid `_anomalous_metrics`; the
    # gate independently blocks the final paper if such a value survives. Safe /
    # additive; never breaks science_data generation.
    try:
        from ari.public.claim_gate import scan_science_data as _scan_invariants  # type: ignore
        _anoms = _scan_invariants(out)
        if _anoms:
            out["_anomalies"] = _anoms
            _by_cfg: dict = {}
            for _a in _anoms:
                _by_cfg.setdefault(str(_a.get("config_id")), []).append(_a.get("metric"))
            for _c in ranked:
                _cid = str(_c.get("config_id") or _c.get("label") or _c.get("node_id")
                           or _c.get("rank") or "?")
                if _cid in _by_cfg:
                    _c["_anomalous_metrics"] = sorted(set(_by_cfg[_cid]))
    except Exception:
        pass

    # ── Research Contract substrate: candidate claims[] / numeric_assertions[] ──
    # Story2Proposal integration Phase A. Deterministically derived from the
    # executed-node evidence (results.json measurements/scores or node metrics);
    # operands carry real node_id + metric_path. figures[] start empty and are
    # late-bound by the paper post-processor. Claim prose is a templated seed the
    # writer rewrites while preserving % CLAIM anchors; the hard gate re-verifies
    # the numbers. Failure here must never break science_data generation.
    try:
        from claims import build_science_claims as _build_claims  # type: ignore
    except Exception:  # pragma: no cover - import shape varies by entrypoint
        try:
            from src.claims import build_science_claims as _build_claims  # type: ignore
        except Exception:
            _build_claims = None  # type: ignore
    if _build_claims is not None:
        try:
            # Per-node execution environment from node_report (executor / CPU /
            # arch) — universal provenance, no cluster/domain knowledge. Lets the
            # claim generator tag operands and (under same_environment intent)
            # avoid cross-host comparisons.
            _node_env: dict = {}
            for _nid, _rep in (reports or {}).items():
                _ci = _rep.get("cpu_info") or {}
                _node_env[_nid] = {
                    "executor": _rep.get("executor", ""),
                    "cpu_model": _ci.get("model", ""),
                    "arch": _ci.get("arch", ""),
                }
            # Injected research intent (P4): "any" (default) | "same_environment".
            _cmp_scope = os.environ.get("ARI_COMPARISON_SCOPE", "").strip() or "any"
            _contract = _build_claims(
                good_nodes, typed_results, primary_metric, _hib,
                node_env=_node_env, comparison_scope=_cmp_scope,
            )
            out["claims"] = _contract.get("claims", [])
            out["numeric_assertions"] = _contract.get("numeric_assertions", [])
            # Tag each science-facing configuration with a stable handle
            # (config_id) + its execution environment, and build a resolution map
            # so the writer can DECLARE assertions referencing configs (forward
            # declaration, Story2Proposal (c)) and the hard gate can resolve
            # config_id -> node_id without exposing node_id in the paper-facing
            # configuration. ranked[i] is built from good_nodes[i] (same order).
            _config_nodes: dict = {}
            for _i, _n in enumerate(good_nodes):
                if _i >= len(ranked):
                    break
                _nid = _n.get("id") or _n.get("node_id") or ""
                _cid = f"cfg{_i + 1}"
                ranked[_i]["config_id"] = _cid
                if _nid in _node_env:
                    ranked[_i]["environment"] = _node_env[_nid]
                # Carry metric VALUES (not just keys): the writer must pick the
                # metric_key whose recorded value equals the number it states, so
                # it has to SEE the values to declare operands correctly.
                _metric_vals = {
                    k: v for k, v in (_n.get("metrics") or {}).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    and not str(k).startswith("_")
                }
                _config_nodes[_cid] = {
                    "node_id": _nid,
                    "environment": _node_env.get(_nid, {}),
                    "metrics": _metric_vals,
                }
            # Internal (underscore) — resolution map for the writer's forward
            # declarations; not part of the paper-facing science surface.
            out["_config_nodes"] = _config_nodes
        except Exception as _claim_exc:  # pragma: no cover - defensive
            out["claims"] = []
            out["numeric_assertions"] = []
            out["_claims_error"] = str(_claim_exc)
    return out


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
    """Find on-disk experiment directories referenced by a node's artifacts.

    Two patterns are supported:
    1. Shell-script content containing ``cd /path`` or ``pushd /path``.
    2. An artifact whose content is itself an absolute path to a file or
       directory inside the experiment workspace. Many skills record
       artifacts simply as ``"/abs/path/to/file"``; the parent directory of
       such a file is treated as the node's working directory.
    """
    import re as _re
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            if p.is_dir():
                key = str(p)
                if key not in seen:
                    dirs.append(p)
                    seen.add(key)
        except OSError:
            return

    for art in (node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        if not content:
            continue
        for m in _re.finditer(r"(?:cd|pushd)\s+(/\S+)", content):
            d = m.group(1).rstrip("&;|\"'")
            if d:
                _add(Path(d))
        stripped = content.strip()
        if stripped.startswith("/") and "\n" not in stripped and " " not in stripped:
            p = Path(stripped)
            if p.is_file():
                _add(p.parent)
            elif p.is_dir():
                _add(p)
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
    """Document the commands needed to reproduce the top-scoring node.

    Distinguishes three artifact shapes:
    - single absolute path → output artifact (listed under "Output artifacts")
    - multi-line shell-like text → inline commands
    - sibling files of artifact paths matching ``*.sh``/``Makefile`` → run scripts
      whose contents are inlined verbatim (this is what reproduces the run).
    """
    if not top_node:
        return "# Reproduction commands\n\n_No top node available._\n"

    artifact_paths: list[str] = []
    inline_cmds: list[str] = []
    for art in (top_node.get("artifacts") or []):
        content = art.get("content", "") if isinstance(art, dict) else str(art)
        if not content:
            continue
        stripped = content.strip()
        if (
            stripped.startswith("/")
            and "\n" not in stripped
            and " " not in stripped
        ):
            artifact_paths.append(stripped)
            continue
        for line in content.splitlines():
            ln = line.strip()
            if not ln or ln.startswith("#"):
                continue
            inline_cmds.append(ln)

    script_blocks: list[tuple[str, str]] = []
    seen_dirs: set[str] = set()
    script_exts = {".sh", ".bash", ".zsh"}
    script_names = {"Makefile", "makefile", "GNUmakefile"}
    for p in artifact_paths:
        parent = Path(p).parent
        key = str(parent)
        if key in seen_dirs or not parent.is_dir():
            continue
        seen_dirs.add(key)
        for f in sorted(parent.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() not in script_exts and f.name not in script_names:
                continue
            try:
                if f.stat().st_size > 64 * 1024:
                    continue
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            script_blocks.append((f.name, text))

    out = [
        "# Reproduction commands",
        "",
        f"_Top-scoring node: `{str(top_node.get('id', '?'))[-8:]}` "
        f"(label={top_node.get('label', '?')})_",
        "",
    ]
    if script_blocks:
        out.append("## Run scripts (from node working directory)")
        out.append("")
        for name, text in script_blocks[:6]:
            out.append(f"### `{name}`")
            out.append("```bash")
            for ln in text.splitlines()[:300]:
                out.append(ln.rstrip())
            out.append("```")
            out.append("")
    if inline_cmds:
        out.append("## Inline commands recorded in artifacts")
        out.append("")
        out.append("```bash")
        out.extend(inline_cmds[:50])
        out.append("```")
        out.append("")
    if artifact_paths:
        out.append("## Output artifacts")
        out.append("")
        for p in artifact_paths[:50]:
            out.append(f"- `{p}`")
        out.append("")
    if not (script_blocks or inline_cmds or artifact_paths):
        out.append("```bash")
        out.append("# No reproducible commands captured for this node.")
        out.append("```")
    return "\n".join(out).rstrip() + "\n"


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


# ── PR #C helpers (node_report-driven generate_ear) ──────────────────────

# Whitelist of source-file extensions and basenames that may end up under
# ear/code/. These are the "publishable code surfaces"; everything else is
# either an experiment output (not published; reproduce.sh regenerates) or
# an internal artefact (logs, build caches).
_EAR_CODE_EXTS: frozenset[str] = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh",
    ".f", ".f90", ".for",
    ".py", ".ipynb",
    ".sh", ".bash", ".zsh",
    ".rs", ".go", ".java", ".scala", ".kt",
    ".cu", ".cuda", ".cl",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".mk", ".cmake",
    ".toml", ".yaml", ".yml", ".cfg", ".ini",
    ".r", ".jl", ".lua", ".swift",
    ".proto", ".thrift", ".sql",
})

_EAR_CODE_BASENAMES: frozenset[str] = frozenset({
    "Makefile", "makefile", "GNUmakefile",
    "CMakeLists.txt",
    "Dockerfile",
    ".dockerignore",
    "requirements.txt",
    "environment.yml", "environment.yaml",
    "pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in",
    "Cargo.toml", "go.mod", "package.json", "tsconfig.json",
    "build.gradle", "pom.xml",
    ".gitignore",
})

# Hard blocklist (filename or filename pattern). These are never copied into
# ear/code/ even if their extension matches the whitelist.
_EAR_CODE_BLOCKLIST_NAMES: frozenset[str] = frozenset({
    "memory_access.jsonl", "viz_access.jsonl", "cost_trace.jsonl",
    "nodes_tree.json", "tree.json", "bfts_tree.json",
    "science_data.json", "raw_metrics.json", "eval_scores.json",
    "node_report.json",
    ".DS_Store", "Thumbs.db",
})

# Subdirectories never recursed into.
_EAR_CODE_BLOCKLIST_DIRS: frozenset[str] = frozenset({
    ".git", ".cache", ".pytest_cache", "__pycache__",
    "node_modules", ".ipynb_checkpoints",
    ".venv", "venv", "build", "dist", "target",
    ".tox", ".mypy_cache", ".ruff_cache",
})

_EAR_CODE_FILE_SIZE_CAP = 256 * 1024  # 256KB / file


def _is_publishable_code_file(rel_path: str, full_path: Path) -> bool:
    """Return True if *rel_path* should be copied into ear/code/."""
    name = Path(rel_path).name
    if name in _EAR_CODE_BLOCKLIST_NAMES:
        return False
    # Block anything under a known build / cache dir.
    for part in Path(rel_path).parts[:-1]:
        if part in _EAR_CODE_BLOCKLIST_DIRS:
            return False
    # slurm-*.{out,err} are logs.
    if name.startswith("slurm-") and (name.endswith(".out") or name.endswith(".err")):
        return False
    if name in _EAR_CODE_BASENAMES:
        return True
    suffix = Path(name).suffix.lower()
    if suffix in _EAR_CODE_EXTS:
        return True
    if name.startswith("Dockerfile."):
        return True
    return False


def _resolve_pm_run_id(ckpt: Path) -> tuple[Path, str]:
    """Return (workspace_root, run_id) inferred from *ckpt*.

    The PathManager mirrors `experiments/{run_id}/{node_id}/` as a sibling of
    `checkpoints/{run_id}/`. Some test fixtures place experiments alongside
    the checkpoint instead, so we accept that fallback as well.
    """
    return (ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent,
            ckpt.name)


def _node_work_dir(workspace: Path, run_id: str, node_id: str) -> Path:
    """Resolve the on-disk work_dir for a node, with sensible fallbacks."""
    candidates = [
        workspace / "experiments" / run_id / node_id,
        workspace / "experiments" / node_id,  # test fixtures sometimes flatten this.
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _load_node_reports(workspace: Path, run_id: str, nodes: list[dict]) -> dict[str, dict]:
    """Load every available `node_report.json` keyed by node id."""
    reports: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        wd = _node_work_dir(workspace, run_id, nid)
        rp = wd / "node_report.json"
        if rp.is_file():
            try:
                reports[nid] = json.loads(rp.read_text())
            except Exception:
                continue
    return reports


def _resolve_best_node(nodes: list[dict]) -> dict | None:
    """argmax(_scientific_score), with `validation`-label tie-break and depth secondary."""
    real = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    if not real:
        return None
    def _score(n: dict) -> float:
        return float((n.get("metrics") or {}).get("_scientific_score") or 0.0)
    real.sort(
        key=lambda n: (
            _score(n),
            1 if str(n.get("label") or "").lower() == "validation" else 0,
            int(n.get("depth") or 0),
        ),
        reverse=True,
    )
    return real[0]


def _gather_uploads(checkpoint_dir: Path) -> list[Path]:
    uploads = checkpoint_dir / "uploads"
    if not uploads.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(uploads.rglob("*")):
        if p.is_file():
            out.append(p)
    return out


def _gather_top_level_figures(checkpoint_dir: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.pdf", "*.png", "*.svg", "*.jpg", "*.jpeg"):
        for f in sorted(checkpoint_dir.glob(ext)):
            if f.is_file():
                out.append(f)
    return out


def _render_evolution_md(chain: list[dict], reports: dict[str, dict]) -> str:
    """Deterministic EVOLUTION.md from the for_narrative chain.

    Step number + label is the only identifier the reader sees — opaque
    `node_id` and `depth_in_chain` strings are excluded by spec (FR-E-RENDER-2).
    """
    if not chain:
        return "# Evolution\n\n_No nodes were retained for the narrative._\n"

    # Pick the primary metric to track per-step: the metric with the most
    # successful step appearances.
    metric_counter: dict[str, int] = {}
    for n in chain:
        for k in (n.get("metrics") or {}):
            if k.startswith("_"):
                continue
            metric_counter[k] = metric_counter.get(k, 0) + 1
    primary_metric = (
        max(metric_counter, key=metric_counter.get) if metric_counter else None
    )
    best_id = chain[-1].get("id")

    rows: list[str] = ["# Evolution", "", "## Search trajectory", ""]
    rows.append("| Step | Label | Headline metric | Δ vs parent | What changed |")
    rows.append("|---|---|---|---|---|")

    prev_metric: float | None = None
    per_step_blocks: list[str] = []
    for idx, node in enumerate(chain, start=1):
        nid = node.get("id")
        report = reports.get(nid) or {}
        label = str(node.get("label") or "other")
        if nid == best_id:
            label_disp = f"{label} (best)"
        else:
            label_disp = label
        # Headline metric value.
        m_val: float | None = None
        if primary_metric:
            v = (node.get("metrics") or {}).get(primary_metric)
            if isinstance(v, (int, float)):
                m_val = float(v)
        m_str = f"{m_val:.3g} {primary_metric}" if m_val is not None else "—"
        # Δ vs parent.
        if m_val is not None and prev_metric and prev_metric != 0:
            pct = (m_val - prev_metric) / abs(prev_metric) * 100.0
            sign = "+" if pct >= 0 else ""
            delta_str = f"{sign}{pct:.0f}%"
        elif m_val is not None and prev_metric is None:
            delta_str = "—"
        else:
            delta_str = "—"
        prev_metric = m_val if m_val is not None else prev_metric
        delta_text = (
            (report.get("delta_vs_parent") or "").replace("|", " ").splitlines()
        )
        delta_text_first = delta_text[0] if delta_text else ""
        if not delta_text_first:
            delta_text_first = (
                (report.get("self_assessment") or {}).get("headline") or ""
            ).replace("|", " ").splitlines()[:1]
            delta_text_first = delta_text_first[0] if delta_text_first else ""
        rows.append(
            f"| {idx} | {label_disp} | {m_str} | {delta_str} | "
            f"{delta_text_first[:90]} |"
        )

        block = [f"### Step {idx}: {label_disp}", ""]
        if delta_text_first:
            block.append(f"**What changed:** {delta_text_first}")
            block.append("")
        sa = report.get("self_assessment") or {}
        if sa.get("headline"):
            block.append(f"**Headline:** {sa['headline']}")
            block.append("")
        if sa.get("concerns"):
            block.append("**Concerns:**")
            for c in sa["concerns"]:
                block.append(f"- {c}")
            block.append("")
        if nid == best_id and report.get("next_steps_hints"):
            block.append("**Suggested next steps:**")
            for h in report["next_steps_hints"]:
                block.append(f"- {h}")
            block.append("")
        per_step_blocks.append("\n".join(block).rstrip())

    rows.append("")
    rows.append("## Per-step details")
    rows.append("")
    rows.extend(per_step_blocks)
    return "\n".join(rows).rstrip() + "\n"


_BARE_VAR_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _is_substantive_command(line: str) -> bool:
    """Whether a single line actually invokes something (vs env-var setup)."""
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    if s.startswith(("set ", "export ", "source ", "cd ", "module ", "ulimit ", "shopt ")):
        return False
    if _BARE_VAR_ASSIGN_RE.match(s):
        return False
    return True


def _find_runnable_script_in_code(code_dir: Path) -> str | None:
    """Locate a script in code/ that can be wrapped as the run command.

    Preference: ``run_job.sh`` (BFTS executor convention) → ``run.sh`` →
    ``main.sh`` → first executable ``*.sh``. Returns the path RELATIVE to
    ``code_dir`` (e.g. ``run_job.sh``), or None if nothing usable.
    """
    if not code_dir.is_dir():
        return None
    for name in ("run_job.sh", "run.sh", "main.sh"):
        if (code_dir / name).is_file():
            return name
    for p in sorted(code_dir.glob("*.sh")):
        return p.name
    return None


def _render_reproduce_sh(best_report: dict | None, code_dir: Path | None = None) -> str | None:
    """Deterministic reproduce.sh body, or None if no usable input.

    Strategy:
      1. Build from ``best_report.{build_command, run_command}`` when at
         least one is substantive (not just env-var setup).
      2. Otherwise fall back to wrapping the actual script the BFTS executor
         ran (``code/run_job.sh`` or similar). Bug 3b workaround: when the
         node_report's build/run extraction degenerated to env-var-only
         lines, the real compile + run are still in ``code/run_job.sh``.
      3. Returns None when both inputs are absent.
    """
    build = (best_report.get("build_command") or "").strip() if best_report else ""
    run = (best_report.get("run_command") or "").strip() if best_report else ""
    has_substantive = _is_substantive_command(build) or _is_substantive_command(run)

    if has_substantive:
        lines = [
            "#!/usr/bin/env bash",
            "# Generated by ARI generate_ear from node_report.json::{build_command, run_command}.",
            "# Manual review recommended: absolute paths and machine-specific flags may need",
            "# adjustment for your environment.",
            "set -euo pipefail",
            'cd "$(dirname "$0")/code"',
            "",
        ]
        if build:
            lines.append(build)
        if run:
            lines.append(run)
        return "\n".join(lines) + "\n"

    # Fallback: wrap the runnable script in code/.
    wrapped = _find_runnable_script_in_code(code_dir) if code_dir is not None else None
    if not wrapped:
        return None
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by ARI generate_ear (fallback wrapper).\n"
        "# node_report.json::{build_command, run_command} did not contain\n"
        "# substantive commands; this script invokes the executor's actual\n"
        f"# run script ({wrapped}) verbatim.\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")/code"\n'
        '\n'
        '# Provide common build env vars in case the inner script omits them.\n'
        'export CXX="${CXX:-g++}"\n'
        'export CXXFLAGS="${CXXFLAGS:--O3 -march=native -fopenmp -std=c++17}"\n'
        '\n'
        f'bash {wrapped}\n'
        'rc=$?\n'
        '\n'
        '# Promote per-run output artifacts from code/ up to the repo root so\n'
        '# the rubric\'s expected_artifacts (repo-relative paths like\n'
        '# "results.csv") can match them. The inner script writes outputs in\n'
        '# its CWD (= code/), but the PaperBench grader looks for them at\n'
        '# repo root. Idempotent — re-runs overwrite stale copies.\n'
        'shopt -s nullglob\n'
        'for _f in *.csv *.tsv *.pdf *.png *.svg *.jpg *.jpeg *.json *.log *.txt; do\n'
        '    [ "$_f" = "run.log" ] && continue   # surfaced via stdout below instead\n'
        '    cp -f "$_f" "../$_f"\n'
        'done\n'
        'shopt -u nullglob\n'
        '\n'
        '# Surface stderr that the inner script may have redirected to a\n'
        '# local log so the Phase 2 grader (which only sees the runner-\n'
        '# captured stdout) can inspect it too.\n'
        'if [ -f run.log ]; then\n'
        '    echo "--- code/run.log (stderr from inner script) ---"\n'
        '    cat run.log\n'
        'fi\n'
        '\n'
        'exit "$rc"\n'
    )


def _render_readme(
    *,
    goal: str,
    best_node: dict | None,
    best_report: dict | None,
    impl_overview: dict | None,
    has_data_dir: bool,
    has_figures_dir: bool,
    has_evolution: bool,
    has_environment: bool,
    has_license: bool,
    has_reproduce_sh: bool,
) -> str:
    title = goal.strip() or "Experiment Artifact Repository"
    title = title.splitlines()[0][:200]

    lines = [f"# {title}", ""]
    if best_report or best_node:
        sa = (best_report or {}).get("self_assessment") or {}
        headline = (sa.get("headline") or "").strip()
        if not headline and best_node:
            headline = (best_node.get("eval_summary") or "").strip()
        lines.append("## Headline result")
        lines.append("")
        if headline:
            lines.append(headline)
            lines.append("")
        metrics = ((best_report or {}).get("metrics")
                   or (best_node or {}).get("metrics") or {})
        if metrics:
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for k, v in metrics.items():
                if k.startswith("_"):
                    continue
                lines.append(f"| {k} | {v} |")
            lines.append("")

    lines.append("## Build & run")
    lines.append("")
    if has_reproduce_sh:
        lines.append("```bash")
        lines.append("bash reproduce.sh")
        lines.append("```")
    else:
        lines.append("_No reproduce.sh was generated; see code/ for build instructions._")
    lines.append("")

    lines.append("## Layout")
    lines.append("")
    lines.append("- `code/` — verbatim source files from contributing nodes "
                 "in the best chain")
    if has_data_dir:
        lines.append("- `data/` — input data files mirrored from the uploaded "
                     "dataset. Experiment outputs (CSV etc.) are NOT included; "
                     "they are regenerated by `reproduce.sh`.")
    if has_figures_dir:
        lines.append("- `figures/` — figures referenced by the paper")
    if has_environment:
        lines.append("- `environment.json` — captured runtime environment")
    if has_license:
        lines.append("- `LICENSE` — license declared by the author")
    lines.append("")

    if impl_overview and isinstance(impl_overview, dict):
        arch = (impl_overview.get("architecture") or "").strip()
        if arch:
            lines.append("## Architecture")
            lines.append("")
            lines.append(arch)
            lines.append("")
        algos = impl_overview.get("key_algorithms") or []
        if algos:
            lines.append("## Key algorithms")
            lines.append("")
            for a in algos:
                if isinstance(a, dict) and a.get("pseudocode"):
                    lines.append(f"### {a.get('name', '(unnamed)')}")
                    lines.append("")
                    lines.append("```")
                    lines.append(a["pseudocode"])
                    lines.append("```")
                    lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append("Source and data files are verbatim copies from the *contributing* "
                 "nodes in the best chain (determined deterministically via "
                 "`node_report::files_changed`). README and reproduce.sh "
                 "are rendered deterministically from each node's `node_report.json`. "
                 "LLM does not modify code or data files. The full search "
                 "trajectory and per-file origin audit are kept alongside the "
                 "checkpoint as `EVOLUTION.md` and `_provenance.json` (outside "
                 "this artifact).")
    return "\n".join(lines).rstrip() + "\n"


def _read_publish_yaml(checkpoint_dir: Path) -> dict:
    py_path = checkpoint_dir / "ear" / "publish.yaml"
    if not py_path.is_file():
        return {}
    try:
        import yaml as _yaml
        return _yaml.safe_load(py_path.read_text()) or {}
    except Exception:
        return {}


_LICENSE_TEMPLATE_DIR = Path(__file__).parent / "licenses"
_SPDX_TO_TEMPLATE: dict[str, str] = {
    "MIT": "mit.txt",
    "Apache-2.0": "apache-2.0.txt",
    "BSD-3-Clause": "bsd-3-clause.txt",
    "GPL-3.0": "gpl-3.0.txt",
    "GPL-3.0-only": "gpl-3.0.txt",
    "GPL-3.0-or-later": "gpl-3.0.txt",
    "CC-BY-4.0": "cc-by-4.0.txt",
}


def _write_license_if_needed(
    ear_dir: Path,
    publish_yaml: dict,
    *,
    author: str,
    year: int,
) -> bool:
    """Write ear/LICENSE from SPDX template iff one isn't already there."""
    target = ear_dir / "LICENSE"
    if target.exists():
        return True
    spdx = (publish_yaml.get("license") or "").strip()
    if not spdx:
        return False
    template = _SPDX_TO_TEMPLATE.get(spdx)
    if not template:
        return False
    template_path = _LICENSE_TEMPLATE_DIR / template
    if not template_path.is_file():
        return False
    body = template_path.read_text()
    body = body.replace("{year}", str(year)).replace("{author}", author or "Authors")
    target.write_text(body)
    return True


def _read_meta_author(ckpt: Path) -> tuple[str, int]:
    from datetime import datetime as _dt, timezone as _tz
    year = _dt.now(_tz.utc).year
    author = ""
    meta_path = ckpt / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if isinstance(meta, dict):
                author = str(meta.get("author") or meta.get("authors") or "")
        except Exception:
            pass
    return (author, year)


def _resolve_goal(ckpt: Path, tree_data: object) -> str:
    if isinstance(tree_data, dict):
        g = tree_data.get("experiment_goal") or ""
        if g:
            return g
    exp_md = ckpt / "experiment.md"
    if exp_md.is_file():
        try:
            return exp_md.read_text().strip()
        except Exception:
            pass
    meta_path = ckpt / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if isinstance(meta, dict):
                return (meta.get("experiment_goal") or meta.get("goal")
                        or meta.get("research_goal") or meta.get("idea") or "")
        except Exception:
            pass
    return ""


def _read_implementation_overview(ckpt: Path) -> dict | None:
    sd = ckpt / "science_data.json"
    if not sd.is_file():
        return None
    try:
        data = json.loads(sd.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    overview = data.get("implementation_overview")
    return overview if isinstance(overview, dict) else None


def _fallback_collect_code_workdir_scan(work_dir: Path) -> list[tuple[str, bytes]]:
    """Last-resort: enumerate the best node's work_dir for publishable files."""
    if not work_dir.is_dir():
        return []
    out: list[tuple[str, bytes]] = []
    for p in sorted(work_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(work_dir))
        if not _is_publishable_code_file(rel, p):
            continue
        try:
            if p.stat().st_size > _EAR_CODE_FILE_SIZE_CAP:
                continue
            out.append((rel, p.read_bytes()))
        except OSError:
            continue
    return out


def _wipe_legacy_subdirs(ear_dir: Path) -> None:
    """Remove legacy v0.6.0 subdirs so re-runs converge on the new layout."""
    for sub in ("logs", "reproducibility"):
        d = ear_dir / sub
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    # RESULTS.md is the v0.6.0 name; EVOLUTION.md and _provenance.json are
    # v0.7.0 names that have since moved to checkpoint root — remove any
    # stale copies left behind under ear/.
    for stale in ("RESULTS.md", "EVOLUTION.md", "_provenance.json"):
        p = ear_dir / stale
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    # data/raw_metrics.json, data/science_data.json, data/figures are removed
    # only if `data/` exists from a previous run; handled below in the build.


@mcp.tool()
def generate_ear(
    checkpoint_dir: str,
    llm_model: str = "",
    llm_base_url: str = "",
) -> dict:
    """Generate the Experiment Artifact Repository for *checkpoint_dir*.

    The layout is *node_report-driven* and shaped like a typical
    paper-companion code repository:

        <checkpoint>/
        ├── EVOLUTION.md       (search trajectory; opaque node_ids omitted)
        ├── _provenance.json   (origin metadata; sha256 lives in manifest.lock)
        └── ear/
            ├── README.md          (deterministic + optional architecture section)
            ├── LICENSE            (SPDX template, optional)
            ├── reproduce.sh       (best report build_command + run_command literal)
            ├── environment.json   (captured runtime environment)
            ├── code/              (verbatim files from contributing chain nodes)
            ├── data/              (uploads/ mirror — input data only)
            └── figures/           (top-level *.{pdf,png,svg,jpg,jpeg})

    `EVOLUTION.md` and `_provenance.json` are ARI audit logs (search
    trajectory + per-file origin) and live at checkpoint root, *outside*
    `ear/`, so they are not bundled into the published artifact.

    Other internal ARI metadata (tree.json, science_data.json,
    raw_metrics.json, eval_scores.json, commands.md) also stays at
    checkpoint root; experiment output files (CSVs etc.) are not bundled —
    `reproduce.sh` regenerates them.

    Behaviour with respect to `node_report.json`:
    - Each contributing node's `node_report.json` is consulted via
      `select_source_files_for_publication` to decide which (node_id,
      rel_path) pairs are publishable code.
    - If reports are missing for every node, the tool falls back to a
      whitelist scan of the best node's work_dir.
    """
    from ari.orchestrator import node_selection as _ns

    ckpt = Path(checkpoint_dir).expanduser().resolve()
    if not ckpt.exists() or not ckpt.is_dir():
        return {"error": f"checkpoint dir not found: {ckpt}"}

    tree_path = ckpt / "tree.json"
    if not tree_path.exists():
        tree_path = ckpt / "nodes_tree.json"
    if not tree_path.exists():
        return {"error": f"no tree.json or nodes_tree.json under {ckpt}"}
    try:
        tree_data = json.loads(tree_path.read_text())
    except Exception as e:
        return {"error": f"could not parse tree json: {e}"}

    nodes: list[dict] = (
        tree_data if isinstance(tree_data, list) else tree_data.get("nodes", [])
    )
    goal = _resolve_goal(ckpt, tree_data)

    workspace, run_id = _resolve_pm_run_id(ckpt)
    reports = _load_node_reports(workspace, run_id, nodes)

    best_node = _resolve_best_node(nodes)
    best_id = (best_node or {}).get("id", "")
    best_report = reports.get(best_id) if best_id else None

    # ── ear/ directory tree (start fresh on legacy subdirs) ──
    ear = ckpt / "ear"
    code_dir = ear / "code"
    ear.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)
    _wipe_legacy_subdirs(ear)
    # Wipe any pre-existing `code/<node_id>/` subdir so the new flat layout
    # converges (only if we do have reports — fallback may still want them).
    if code_dir.exists():
        for sub in list(code_dir.iterdir()):
            if sub.is_dir() and sub.name.startswith("node_"):
                shutil.rmtree(sub, ignore_errors=True)
    # Wipe data/ ARI internals from previous runs.
    data_dir = ear / "data"
    if data_dir.exists():
        for legacy in ("raw_metrics.json", "science_data.json"):
            lp = data_dir / legacy
            if lp.is_file():
                try:
                    lp.unlink()
                except OSError:
                    pass
        legacy_figs = data_dir / "figures"
        if legacy_figs.is_dir():
            shutil.rmtree(legacy_figs, ignore_errors=True)

    file_count = 0
    verbatim_files = 0
    code_layout = "fallback_workdir_scan"

    # ── code/ collection ──
    written_files: list[tuple[str, str | None, str]] = []  # (dest_rel, from_node_id, introduced_by)

    if best_id and reports:
        selection = _ns.select_source_files_for_publication(nodes, reports, best_id)
        # Map node_id -> work_dir.
        def _wd(nid: str) -> Path:
            return _node_work_dir(workspace, run_id, nid)
        loaded = _ns.load_selected_sources(
            selection, work_dir_for=_wd, size_budget=None,
        )
        for rel_path, payload in loaded.items():
            full = code_dir / rel_path
            if not _is_publishable_code_file(rel_path, full):
                continue
            if payload["size"] > _EAR_CODE_FILE_SIZE_CAP:
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload["bytes"])
            # Mark introduction event.
            from_node_id = payload["from_node_id"]
            from_report = reports.get(from_node_id) or {}
            fc = from_report.get("files_changed") or {}
            introduced_by = "modified"
            if any((e.get("path") == rel_path) for e in (fc.get("added") or [])):
                introduced_by = "added"
            elif any((e.get("path") == rel_path) for e in (fc.get("modified") or [])):
                introduced_by = "modified"
            else:
                introduced_by = "fallback_workdir_scan"
            written_files.append((rel_path, from_node_id, introduced_by))
            verbatim_files += 1
        if written_files:
            code_layout = "node_report"
        excluded_nodes = list(selection.excluded_nodes)
    else:
        excluded_nodes = []

    # Fallback: best work_dir whitelist scan if nothing was selected.
    if not written_files and best_id:
        best_wd = _node_work_dir(workspace, run_id, best_id)
        for rel_path, data in _fallback_collect_code_workdir_scan(best_wd):
            full = code_dir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data)
            written_files.append((rel_path, best_id, "fallback_workdir_scan"))
            verbatim_files += 1
        code_layout = "fallback_workdir_scan"

    file_count += verbatim_files

    # ── data/ — uploads/ verbatim mirror (input only) ──
    data_records: list[dict] = []
    uploads_root = ckpt / "uploads"
    upload_files = _gather_uploads(ckpt)
    if upload_files:
        data_dir.mkdir(parents=True, exist_ok=True)
        for src in upload_files:
            rel = src.relative_to(uploads_root)
            dst = data_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
                data_records.append({
                    "dest": f"data/{rel.as_posix()}",
                    "from_path": f"uploads/{rel.as_posix()}",
                    "size": dst.stat().st_size,
                })
                file_count += 1
            except Exception:
                continue
    elif data_dir.exists():
        # Empty uploads — remove the now-empty data/.
        try:
            for child in list(data_dir.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            data_dir.rmdir()
        except OSError:
            pass

    has_data_dir = data_dir.is_dir()

    # ── figures/ — top-level mirror ──
    figures_dir = ear / "figures"
    fig_records: list[dict] = []
    fig_files = _gather_top_level_figures(ckpt)
    if fig_files:
        figures_dir.mkdir(parents=True, exist_ok=True)
        for src in fig_files:
            dst = figures_dir / src.name
            try:
                shutil.copy2(src, dst)
                fig_records.append({
                    "dest": f"figures/{src.name}",
                    "from_path": src.name,
                    "size": dst.stat().st_size,
                })
                file_count += 1
            except Exception:
                continue
    elif figures_dir.exists():
        # Old run left an empty dir behind.
        try:
            figures_dir.rmdir()
        except OSError:
            pass

    has_figures_dir = figures_dir.is_dir()

    # ── EVOLUTION.md ──
    chain = _ns.build_parent_chain(best_id, nodes) if best_id else []
    narrative_chain = _ns.filter_nodes(
        chain, reports, "for_narrative",
        always_include_node_ids={best_id} if best_id else (),
    )
    has_evolution = False
    if narrative_chain:
        evo = _render_evolution_md(narrative_chain, reports)
        # EVOLUTION.md is an ARI audit log, not part of the published EAR;
        # it lives at checkpoint root alongside tree.json / science_data.json.
        (ckpt / "EVOLUTION.md").write_text(evo)
        has_evolution = True

    # ── reproduce.sh ──
    repro_body = _render_reproduce_sh(best_report, code_dir=code_dir)
    has_reproduce_sh = False
    if repro_body:
        repro_path = ear / "reproduce.sh"
        repro_path.write_text(repro_body)
        try:
            repro_path.chmod(0o755)
        except OSError:
            pass
        file_count += 1
        has_reproduce_sh = True

    # ── environment.json (top-level) ──
    env_info = _capture_environment()
    (ear / "environment.json").write_text(
        json.dumps(env_info, ensure_ascii=False, indent=2)
    )
    file_count += 1
    has_environment = True

    # ── LICENSE (optional, SPDX template-driven) ──
    publish_yaml = _read_publish_yaml(ckpt)
    author, year = _read_meta_author(ckpt)
    has_license = _write_license_if_needed(
        ear, publish_yaml, author=author, year=year,
    )
    if has_license and (ear / "LICENSE").is_file():
        file_count += 1

    # ── README.md (deterministic + optional impl_overview) ──
    impl_overview = _read_implementation_overview(ckpt)
    readme_text = _render_readme(
        goal=goal,
        best_node=best_node,
        best_report=best_report,
        impl_overview=impl_overview,
        has_data_dir=has_data_dir,
        has_figures_dir=has_figures_dir,
        has_evolution=has_evolution,
        has_environment=has_environment,
        has_license=has_license,
        has_reproduce_sh=has_reproduce_sh,
    )
    (ear / "README.md").write_text(readme_text)
    file_count += 1

    # ── _provenance.json (checkpoint-root audit log; not part of EAR) ──
    # `dest` paths are checkpoint-relative so a reader of this file can
    # locate every artifact without knowing it was generated from inside
    # `ear/`. Files that live under `ear/` are recorded as `ear/...`.
    file_records: list[dict] = []
    for rel_path, from_nid, introduced_by in written_files:
        node = next((n for n in nodes if n.get("id") == from_nid), None)
        depth = int((node or {}).get("depth") or 0)
        size = (code_dir / rel_path).stat().st_size if (code_dir / rel_path).is_file() else 0
        file_records.append({
            "dest": f"ear/code/{rel_path}",
            "from_node_id": from_nid,
            "from_filename": Path(rel_path).name,
            "verbatim": True,
            "introduced_by": introduced_by,
            "depth_in_chain": depth,
            "size": size,
        })
    data_records_prov = [
        {**rec, "dest": f"ear/{rec['dest']}"} for rec in data_records
    ]
    fig_records_prov = [
        {**rec, "dest": f"ear/{rec['dest']}"} for rec in fig_records
    ]
    provenance = {
        "schema_version": 1,
        "best_node_id": best_id,
        "method": code_layout,
        "files": file_records,
        "data": data_records_prov,
        "figures": fig_records_prov,
        "rendered": [
            {"dest": "ear/README.md", "method": "deterministic_render",
             "source_field": "node_reports + (optional) science_data.json::implementation_overview"},
            {"dest": "EVOLUTION.md", "method": "deterministic_render",
             "source_field": "node_reports::delta_vs_parent + metrics"} if has_evolution else None,
            {"dest": "ear/reproduce.sh", "method": "deterministic_render",
             "source_field": "node_reports::{build_command, run_command}"} if has_reproduce_sh else None,
        ],
        "excluded_nodes": list(excluded_nodes),
        "warnings": [],
    }
    provenance["rendered"] = [r for r in provenance["rendered"] if r is not None]
    (ckpt / "_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2)
    )

    # ── checkpoint/run_config.json (moved from ear/reproducibility/) ──
    real_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    run_config: dict = {
        "checkpoint_dir": str(ckpt),
        "experiment_goal": (goal or "")[:2000],
        "node_count": len(nodes),
        "real_data_count": len(real_nodes),
    }
    if best_node:
        run_config["top_node_id"] = best_node.get("id", "")
        run_config["top_node_label"] = best_node.get("label", "")
        run_config["top_node_metrics"] = best_node.get("metrics") or {}
    try:
        (ckpt / "run_config.json").write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2)
        )
    except Exception:
        pass

    return {
        "ear_dir": str(ear),
        "code_layout": code_layout,
        "verbatim_files": verbatim_files,
        # Back-compat alias.
        "source_files": verbatim_files,
        "rendered_files": (1 if has_evolution else 0)
                          + (1 if has_reproduce_sh else 0)
                          + 1,  # README.md is always rendered
        "data_count": len(data_records),
        "figure_count": len(fig_records),
        "top_node_id": best_id,
        "best_chain_depth": len(chain),
        "excluded_count": len(excluded_nodes),
        "warnings_count": 0,
        "file_count": file_count,
        "node_count": len(nodes),
        "has_readme": (ear / "README.md").exists(),
        # Back-compat: callers and existing tests expect has_results.
        "has_results": (ear / "README.md").exists(),
        "has_evolution": has_evolution,
        "has_reproduce_sh": has_reproduce_sh,
        "has_license": has_license,
        "has_environment": has_environment,
    }


@mcp.tool()
def curate_ear(checkpoint_dir: str) -> dict:
    """Curate {checkpoint}/ear/ into {checkpoint}/ear_published/ + manifest.lock.

    Reads {checkpoint}/ear/publish.yaml. If publish.yaml is absent, returns
    {"skipped": true} and does not touch ear_published/. The bundle digest
    (sha256 of the canonical manifest) is the value that gets baked into
    the paper's Code Availability section.
    """
    from curate import curate_to_dict  # type: ignore  # local module
    return curate_to_dict(checkpoint_dir)


@mcp.tool()
def publish_ear(
    checkpoint_dir: str,
    backend: str = "ari-registry",
    visibility: str = "staged",
    dry_run: bool = False,
) -> dict:
    """Publish {checkpoint}/ear_published/ to a backend.

    Thin MCP wrapper around ari.publish.publish so the publish step can
    be a workflow stage. Always starts at visibility=staged (FR-P5).
    """
    try:
        from ari.publish import publish, PublishError  # type: ignore
    except Exception as e:
        return {"error": f"ari.publish not importable: {e}"}
    try:
        rec = publish(checkpoint_dir, backend=backend, visibility=visibility, dry_run=dry_run)
    except PublishError as e:
        return {"error": str(e), "kind": "PublishError"}
    return {
        "backend": rec.backend, "ref": rec.ref, "bundle_sha256": rec.bundle_sha256,
        "visibility": rec.visibility, "timestamp": rec.timestamp,
        "dry_run": rec.dry_run, "extra": rec.extra,
    }


@mcp.tool()
def promote_ear(checkpoint_dir: str, target: str = "public") -> dict:
    """Promote a previously-published artefact to a wider visibility."""
    try:
        from ari.publish import promote, PublishError  # type: ignore
    except Exception as e:
        return {"error": f"ari.publish not importable: {e}"}
    try:
        rec = promote(checkpoint_dir, target=target)
    except PublishError as e:
        return {"error": str(e), "kind": "PublishError"}
    return {
        "ref": rec.ref, "visibility": rec.visibility,
        "promoted_at": rec.promoted_at, "promote_failed_at": rec.promote_failed_at,
    }


if __name__ == "__main__":
    mcp.run()
