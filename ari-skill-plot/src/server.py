"""ari-skill-plot — Scientific figure generation MCP server.

Two tools:
  generate_figures     : Deterministic matplotlib figures (P2)
  generate_figures_llm : LLM writes and executes plotting code (AI Scientist v2-style)

Loosely coupled: independent MCP server, no dependency on paper-skill.
"""
from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from collections import defaultdict

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("plot-skill")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_nodes(nodes_json_path: str) -> list[dict]:
    data = json.loads(Path(nodes_json_path).read_text())
    return data if isinstance(data, list) else data.get("nodes", [])


def _real_nodes(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("has_real_data") and n.get("metrics")]


LABEL_COLOR = {
    "improve":    "#2196F3",
    "validation": "#4CAF50",
    "ablation":   "#FF9800",
    "debug":      "#9C27B0",
    "draft":      "#607D8B",
    "root":       "#F44336",
}


# ---------------------------------------------------------------------------
# VLM caption helper
# ---------------------------------------------------------------------------

import base64
import logging

log = logging.getLogger(__name__)

_VLM_MODEL = os.environ.get("VLM_MODEL", "openai/gpt-4o")


async def _vlm_caption(png_path: str, fallback: str, context: str = "") -> str:
    """Generate a figure caption by sending the PNG to a VLM."""
    try:
        data = Path(png_path).read_bytes()
        b64 = base64.b64encode(data).decode()
        mime = "image/png"
        data_uri = f"data:{mime};base64,{b64}"
        ctx_line = f"\nExperiment context: {context}" if context else ""
        resp = await litellm.acompletion(
            model=_VLM_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": (
                        "You are a scientific writing expert. "
                        "Write a single LaTeX figure caption (1-3 sentences) for this figure. "
                        "Be specific: mention the actual axis labels, metric names, "
                        "key numeric values, trends, and number of data points visible. "
                        "Do NOT use generic phrases like 'experimental results'. "
                        "Output ONLY the caption text, no preamble."
                        f"{ctx_line}"
                    )},
                ],
            }],
        )
        caption = resp.choices[0].message.content.strip()
        # Strip wrapping quotes if present
        if caption.startswith('"') and caption.endswith('"'):
            caption = caption[1:-1]
        return caption or fallback
    except Exception as e:
        log.warning("VLM caption failed, using fallback: %s", e)
        return fallback


# ---------------------------------------------------------------------------
# Tool 1: Deterministic figures (P2-compliant, no LLM)
# ---------------------------------------------------------------------------

@mcp.tool()
async def generate_figures(
    nodes_json_path: str,
    output_dir: str,
    figures: list = None,
    science_data_path: str = "",
    vlm_captions: bool = True,
    experiment_context: str = "",
) -> dict:
    """Generate scientific figures from BFTS data using deterministic matplotlib.

    Args:
        nodes_json_path:    Path to nodes_tree.json
        output_dir:         Directory to write PDF files
        figures:            List of figure IDs to generate (default: all)
                            Options: "perf_bar", "tree_depth", "bfts_tree"
        vlm_captions:       If True, use VLM to generate data-aware captions from
                            the rendered figure image (default: True).
        experiment_context: Optional description of the experiment for VLM context.

    Returns:
        figures (dict path), latex_snippets (dict LaTeX)
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    if figures is None:
        figures = ["perf_bar", "tree_depth", "bfts_tree"]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Prefer science_data_path (BFTS-internal-free) if available
        if science_data_path:
            import json as _jsd
            try:
                _sd = _jsd.loads(Path(science_data_path).read_text())
                nodes_raw = [
                    {"has_real_data": True, "metrics": cfg.get("metrics", {}),
                     "memory": [str(cfg.get("parameters", {}))]}
                    for cfg in _sd.get("configurations", [])
                ]
                nodes = nodes_raw
            except Exception:
                nodes = _load_nodes(nodes_json_path)
        else:
            nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": f"Cannot read nodes_json: {e}"}

    rnodes = sorted(_real_nodes(nodes),
                    key=lambda n: max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0),
                    reverse=True)

    result: dict = {"figures": {}, "latex_snippets": {}}

    # Extract metric info for data-aware captions
    _metric_names: list[str] = []
    _peak_val = 0.0
    _peak_metric = "performance"
    if rnodes:
        _all_keys: set[str] = set()
        for n in rnodes:
            for mk, mv in n["metrics"].items():
                if isinstance(mv, (int, float)):
                    _all_keys.add(mk)
        _metric_names = sorted(_all_keys)
        _peak_metric = _metric_names[0] if _metric_names else "performance"
        _peak_val = max(
            (v for n in rnodes for v in n["metrics"].values() if isinstance(v, (int, float))),
            default=0,
        )

    def _save(fig, name: str) -> str:
        path = str(out_dir / f"{name}.pdf")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        png_path = str(out_dir / f"{name}.png")
        fig.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return path

    def _snippet(name: str, caption: str) -> str:
        return (
            f"\\begin{{figure}}[H]\n"
            f"\\centering\n"
            f"\\includegraphics[width=0.85\\linewidth]{{{name}.pdf}}\n"
            f"\\caption{{{caption}}}\n"
            f"\\label{{fig:{name}}}\n"
            f"\\end{{figure}}"
        )

    # ── Figure 1: Performance Bar Chart ──
    if "perf_bar" in figures and rnodes:
        top = rnodes[:10]
        fig, ax = plt.subplots(figsize=(10, 5))
        ids = [n["id"][-8:] for n in top]
        vals = [max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0) / 1000 for n in top]
        colors = ["#1a73e8"] * len(top)
        bars = ax.bar(ids, vals, color=colors, edgecolor="white", linewidth=0.5)
        ax.bar_label(bars, labels=[f"{v:.0f}" for v in vals], padding=2, fontsize=8)
        ax.set_xlabel("Configuration ID", fontsize=11)
        ax.set_ylabel("Performance", fontsize=11)
        ax.set_title("Experimental Results: Top Configurations", fontsize=13, fontweight="bold")
        ax.tick_params(axis="x", rotation=30, labelsize=9)
        patches = []  # removed internal label legend
        ax.legend(handles=patches, fontsize=9)
        fig.tight_layout()
        path = _save(fig, "perf_bar")
        result["figures"]["perf_bar"] = path
        _top_val = vals[0] if vals else 0
        _n_shown = len(top)
        _metrics_str = ", ".join(_metric_names[:3]) if _metric_names else "primary metric"
        result["latex_snippets"]["perf_bar"] = _snippet(
            "perf_bar",
            f"Top {_n_shown} configurations ranked by {_metrics_str} "
            f"(best: {_top_val:.1f}, {len(rnodes)} configurations evaluated).",
        )

    # ── Figure 2: Performance vs Tree Depth ──
    if "tree_depth" in figures and rnodes:
        fig, ax = plt.subplots(figsize=(7, 5))
        for n in rnodes:
            d = n.get("depth", 0)
            v = max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0) / 1000
            c = LABEL_COLOR.get(n.get("label", "draft"), "#607D8B")
            ax.scatter(d, v, color=c, s=80, alpha=0.85, edgecolors="white", linewidth=0.5)
        best_by_depth: dict[int, float] = defaultdict(float)
        for n in rnodes:
            d = n.get("depth", 0)
            v = max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0) / 1000
            best_by_depth[d] = max(best_by_depth[d], v)
        xs = sorted(best_by_depth.keys())
        ax.plot(xs, [best_by_depth[x] for x in xs], "k--", linewidth=1.2, alpha=0.6, label="Best observed so far")
        ax.set_xlabel("Search Step", fontsize=11)
        ax.set_ylabel("Performance", fontsize=11)
        ax.set_title("Performance Across Configuration Search", fontsize=13, fontweight="bold")
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
        patches = []  # removed internal label legend
        patches.append(plt.Line2D([0], [0], color="k", linestyle="--", label="Best observed so far"))
        ax.legend(handles=patches, fontsize=9)
        fig.tight_layout()
        path = _save(fig, "tree_depth")
        result["figures"]["tree_depth"] = path
        _depth_range = max(best_by_depth.keys()) if best_by_depth else 0
        _best_overall = max(best_by_depth.values()) if best_by_depth else 0
        result["latex_snippets"]["tree_depth"] = _snippet(
            "tree_depth",
            f"{_peak_metric} across {_depth_range + 1} search steps "
            f"(peak {_best_overall:.1f} at step {max(best_by_depth, key=best_by_depth.get) if best_by_depth else 0}). "
            f"Dashed line shows the best result observed up to each point.",
        )

    # ── Figure 3: BFTS Tree Diagram ──
    if "bfts_tree" in figures and nodes:
        try:
            import networkx as nx
            fig, ax = plt.subplots(figsize=(12, 7))
            G = nx.DiGraph()
            attrs: dict = {}
            for n in nodes:
                nid = n["id"][-12:]
                G.add_node(nid)
                m = n.get("metrics", {})
                attrs[nid] = {
                    "label": n.get("label", "draft"),
                    "depth": n.get("depth", 0),
                    "perf": max(m.values()) / 1000 if m else 0,
                    "real": n.get("has_real_data", False),
                }
                if n.get("parent_id"):
                    G.add_edge(n["parent_id"][-12:], nid)
            pos: dict = {}
            by_depth: dict = defaultdict(list)
            for nid in G.nodes():
                by_depth[attrs.get(nid, {}).get("depth", 0)].append(nid)
            for depth, nids in by_depth.items():
                for i, nid in enumerate(nids):
                    pos[nid] = ((i - len(nids) / 2.0) * 1.8, -depth * 2.0)
            node_colors = [LABEL_COLOR.get(attrs.get(n, {}).get("label", "draft"), "#607D8B") for n in G.nodes()]
            node_sizes  = [600 + attrs.get(n, {}).get("perf", 0) * 0.5 for n in G.nodes()]
            nx.draw_networkx_edges(G, pos, ax=ax, arrows=True, arrowsize=15,
                                   edge_color="#999", alpha=0.6, connectionstyle="arc3,rad=0.1")
            nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors,
                                   node_size=node_sizes, alpha=0.9)
            labels = {n: f"{attrs.get(n,{}).get('perf',0):.0f}" if attrs.get(n, {}).get("real") else ""
                      for n in G.nodes()}
            nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                                    font_size=7, font_color="white", font_weight="bold")
            ax.set_title("Experiment Exploration Tree (node size proportional to primary metric)",
                         fontsize=13, fontweight="bold")
            ax.axis("off")
            patches = [mpatches.Patch(color=c, label=l) for l, c in LABEL_COLOR.items()]
            ax.legend(handles=patches, loc="upper right", fontsize=9)
            fig.tight_layout()
            path = _save(fig, "bfts_tree")
            result["figures"]["bfts_tree"] = path
            _n_nodes = len(nodes)
            _n_real = len(rnodes)
            _max_depth = max((n.get("depth", 0) for n in nodes), default=0)
            result["latex_snippets"]["bfts_tree"] = _snippet(
                "bfts_tree",
                f"BFTS exploration tree ({_n_nodes} nodes, {_n_real} with measured data, "
                f"depth {_max_depth}). Node size is proportional to {_peak_metric}; "
                f"labels show metric values for nodes with real experimental data.",
            )
        except ImportError:
            result["figures"]["bfts_tree"] = "networkx not available"

    # ── VLM caption generation ──
    if vlm_captions and result["figures"]:
        for fig_name, fig_path in result["figures"].items():
            if not isinstance(fig_path, str) or not Path(fig_path).exists():
                continue
            png_path = str(Path(fig_path).with_suffix(".png"))
            if not Path(png_path).exists():
                continue
            # Extract current fallback caption from snippet
            snip = result["latex_snippets"].get(fig_name, "")
            _fb_m = re.search(r"\\caption\{([^}]+)\}", snip)
            fallback = _fb_m.group(1) if _fb_m else f"Results for {fig_name}."
            caption = await _vlm_caption(png_path, fallback, context=experiment_context)
            result["latex_snippets"][fig_name] = _snippet(fig_name, caption)

    return result


# ---------------------------------------------------------------------------
# Tool 2: LLM-written plotting code (AI Scientist v2-style)
# ---------------------------------------------------------------------------

@mcp.tool()
async def generate_figures_llm(
    nodes_json_path: str,
    output_dir: str,
    experiment_summary: str = "",
    context: str = "",
    n_figures: int = 3,
    science_data_path: str = "",  # preferred: science-facing data from transform-skill
    vlm_feedback: str = "",  # injected by pipeline loop_back_to after VLM review
) -> dict:
    import sys as _sys_fig
    print(f"[DEBUG generate_figures_llm] nodes_json_path={nodes_json_path!r}", file=_sys_fig.stderr)
    print(f"[DEBUG generate_figures_llm] science_data_path={science_data_path!r}", file=_sys_fig.stderr)
    print(f"[DEBUG generate_figures_llm] output_dir={output_dir!r}", file=_sys_fig.stderr)
    print(f"[DEBUG generate_figures_llm] LLM_MODEL={os.environ.get('ARI_LLM_MODEL','unset')!r}", file=_sys_fig.stderr)
    print(f"[DEBUG generate_figures_llm] API_KEY set={bool(os.environ.get('OPENAI_API_KEY'))}", file=_sys_fig.stderr)
    print(f"[DEBUG generate_figures_llm] vlm_feedback_len={len(vlm_feedback)}", file=_sys_fig.stderr)
    """Generate scientific figures using LLM-written matplotlib code.

    AI Scientist v2-style: LLM analyzes experimental data, writes
    matplotlib code, executes it to produce publication-quality figures.

    Args:
        nodes_json_path:     Path to nodes_tree.json
        output_dir:          Directory to write PDF figure files
        experiment_summary / context: Experiment description
        n_figures:           Number of figures to generate
        vlm_feedback:        VLM review feedback from the previous iteration
                              (empty on first pass, non-empty when the
                              pipeline looped back after a low-score review).

    Returns:
        figures (dict name->path), latex_snippets (dict name->latex)
    """
    if not experiment_summary and context:
        experiment_summary = context

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": f"Cannot read nodes_json: {e}"}

    # ---- Build domain-generic data summary ----
    # When science_data_path is available, use it (no BFTS internals).
    # Derive metric name and parameter keys dynamically from the data itself.
    if science_data_path:
        try:
            sd = json.loads(Path(science_data_path).read_text())
            # Pass the full science_data including experiment_context (LLM-extracted
            # hardware, methodology, ablation findings, validated results).
            # The figure-generation LLM decides what to plot based on this rich context.
            data_summary = json.dumps({
                "experiment": experiment_summary[:300],
                "configurations": sd.get("configurations", [])[:20],
                "per_key_summary": sd.get("per_key_summary", {}),
                "experiment_context": sd.get("experiment_context", {}),
                "summary_stats": sd.get("summary_stats", {}),
            }, indent=2)
            metric_name = ""
            param_keys = []
        except Exception as _e:
            metric_name = "metric"
            param_keys = []
            rnodes = sorted(_real_nodes(nodes),
                            key=lambda n: max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0),
                            reverse=True)
            data_summary = json.dumps({"experiment": experiment_summary[:300],
                "configurations": [{"metrics": {k: v for k, v in n["metrics"].items() if isinstance(v, (int, float))}} for n in rnodes[:12]]}, indent=2)
    else:
        metric_name = "metric"
        param_keys = []
        rnodes = sorted(_real_nodes(nodes),
                        key=lambda n: max((v for v in n["metrics"].values() if isinstance(v, (int, float))), default=0),
                        reverse=True)
        # Build rich data_summary: include all metrics per node (not just max)
        data_summary = json.dumps({
            "experiment": experiment_summary[:300],
            "configurations": [
                {"metrics": {k: round(v, 3) if isinstance(v, float) else v
                             for k, v in n["metrics"].items()
                             if isinstance(v, (int, float))}}
                for n in rnodes[:15]
            ],
        }, indent=2)

    # Build suggested figures dynamically from data structure
    _axis2 = f"{metric_name} vs {param_keys[0]}" if param_keys else f"{metric_name} across configurations"
    _axis3 = f"{metric_name} vs {param_keys[1]}" if len(param_keys) > 1 else f"distribution of {metric_name}"

    system_prompt = (
        "You are a scientific visualization expert. "
        "Write complete, runnable Python matplotlib code to produce publication-quality figures. "
        "Output ONLY valid Python code (no markdown fences, no explanation). "
        "The code must: (1) use matplotlib.use('Agg'), "
        "(2) save each figure TWICE — once as fig_N.pdf (for LaTeX embedding) "
        "and once as fig_N.png (dpi=200, for VLM review) in output_dir, "
        "(3) at the very end print a JSON list: "
        '[{"name":"fig_1","path":"<full_path_to_pdf>","caption":"<caption>"},...]'
        " CRITICAL REQUIREMENTS:\n"
        " - Each figure must directly support a claim in the paper.\n"
        " - Use ACTUAL metric names and numeric values from the data — no 'a.u.' units.\n"
        " - Captions MUST be specific and descriptive. BAD: \"experimental results\". "
        "   GOOD: \"Score vs parameter X (0.1–0.9) for method A on benchmark B; "
        "   best 76.3 at X=0.5 (configuration C, 10 trials).\". "
        "   Include: what metric, what x-axis, what experimental conditions, key quantitative finding.\n"
        " - NEVER produce a 'ranked configurations' bar chart unless the paper explicitly "
        "   compares ranked designs.\n"
        " - Prefer: (a) line/scatter of throughput vs sweep parameter, "
        "   (b) comparison bar with real metric labels, (c) scaling plot."
    )
    user_prompt = (
        f"Generate {n_figures} matplotlib figures from this benchmark data.\n\n"
        f"DATA (configurations with all metrics):\n{data_summary}\n\n"
        f"output_dir = {repr(str(out_dir))}\n\n"
        "REQUIRED figures (read the data carefully and choose the best representation):\n"
        f"RULES: Use real metric names (score, throughput, etc.) from the data as axis labels. "
        "No 'a.u.', no 'Performance metric'. NO internal system terms.\n"
        f"1. Primary performance plot: score or throughput vs the main sweep parameter "
        f"   (e.g., N, configuration) — use a line or scatter plot with labeled axes and units.\n"
        f"2. {_axis2} — scatter or line plot with specific units from the data.\n"
        f"3. Comparison or ablation: show effect of a design choice "
        f"   (e.g., feature on/off, parameter value, configuration) on performance.\n\n"
    )
    # If the pipeline looped back with VLM feedback, surface it at the top
    # of the user prompt so the LLM regenerates figures that address the
    # reviewer's complaints instead of blindly re-producing the same output.
    if vlm_feedback.strip():
        user_prompt = (
            "PREVIOUS ATTEMPT WAS REVIEWED BY A VLM AND REJECTED.\n"
            "You MUST address every issue listed below in the new figures.\n"
            f"{vlm_feedback}\n\n"
            "---\n\n"
        ) + user_prompt

    # Unified LLM routing: ARI_LLM_MODEL > LLM_MODEL; ARI_LLM_API_BASE > LLM_API_BASE
    LLM_MODEL = (os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama_chat/qwen3:32b")
    _ari_base = os.environ.get("ARI_LLM_API_BASE")
    if _ari_base is not None:
        LLM_API_BASE = _ari_base or None
    else:
        _legacy_base = os.environ.get("LLM_API_BASE", "")
        if _legacy_base:
            LLM_API_BASE = _legacy_base
        elif LLM_MODEL.startswith("ollama"):
            LLM_API_BASE = "http://127.0.0.1:11434"
        else:
            LLM_API_BASE = None
    kwargs: dict = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    if LLM_API_BASE:  # None = use provider default; truthy = custom endpoint (Ollama, vLLM, etc.)
        kwargs["api_base"] = LLM_API_BASE
    # Retry on connection errors (up to 3 attempts)
    import asyncio as _asyncio_fig
    _last_fig_exc = None
    response = None
    for _fig_attempt in range(3):
        try:
            kwargs["timeout"] = 120  # 2 min timeout per attempt
            response = await litellm.acompletion(**kwargs)
            _last_fig_exc = None
            break
        except Exception as _fig_exc:
            _last_fig_exc = _fig_exc
            if _fig_attempt < 2:
                await _asyncio_fig.sleep(10 * (_fig_attempt + 1))
    if response is None:
        raise _last_fig_exc
    raw = response.choices[0].message.content or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Strip markdown fences
    code_match = re.search(r"```python\n(.*?)```", raw, re.DOTALL)
    if not code_match:
        code_match = re.search(r"```\n(.*?)```", raw, re.DOTALL)
    code = code_match.group(1) if code_match else raw

    # Execute
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            preamble = (
                "import json\n"
                "output_dir = " + repr(str(out_dir)) + "\n"
                "try:\n    import seaborn as sns; sns.set_theme(style='whitegrid')\n"
                "except ImportError:\n    pass\n"
                # Matplotlib compat: legendHandles was renamed legend_handles in mpl 3.7+
                "import matplotlib.legend as _mpl_leg\n"
                "if not hasattr(_mpl_leg.Legend, 'legendHandles'):\n"
                "    _mpl_leg.Legend.legendHandles = property(lambda self: self.legend_handles)\n"
            )
            # Strip any output_dir reassignment from LLM code to prevent path override
            safe_code_lines = []
            for line in code.split("\n"):
                stripped = line.lstrip()
                if stripped.startswith("output_dir") and "=" in stripped.split("#")[0]:
                    safe_code_lines.append("# (removed by preamble) " + line)
                else:
                    safe_code_lines.append(line)
            code = "\n".join(safe_code_lines)
            tf.write(preamble)
            tf.write(code)
            tmp_path = tf.name

        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=120,
        )
        os.unlink(tmp_path)

        if proc.returncode != 0:
            # Retry with simpler prompt that avoids advanced matplotlib features
            stderr_snippet = proc.stderr[:400]
            simple_user_prompt = (
                "Generate "
                + str(n_figures)
                + " simple matplotlib figures from experiment data.\n\n"
                "DATA:\n" + data_summary[:800] + "\n\noutput_dir = " + repr(str(out_dir)) + "\n\n"
                "Write ONLY simple bar charts using basic matplotlib only. "
                "Do NOT use seaborn, networkx, or any advanced features. "
                "Only: import matplotlib; matplotlib.use(\'Agg\'); import matplotlib.pyplot as plt; import json. "
                "Save figures as fig_1.pdf, fig_2.pdf, ... in output_dir. "
                "At the very end print ONE line of JSON: "
                "[{\"name\":\"fig_1\",\"path\":\"<full_path>\",\"caption\":\"<caption>\"},...]. "
                "Write complete runnable Python code:"
            )
            kwargs2 = dict(kwargs)
            kwargs2["messages"] = [
                {"role": "system", "content": (
                    "You are a Python matplotlib expert. Write only simple, runnable code. "
                    "No seaborn. No networkx. No advanced matplotlib features. Output ONLY Python code."
                )},
                {"role": "user", "content": simple_user_prompt},
            ]
            kwargs2["temperature"] = 0.1
            try:
                kwargs2["timeout"] = 120
                response2 = await litellm.acompletion(**kwargs2)
                raw2 = response2.choices[0].message.content or ""
                raw2 = re.sub(r"<think>.*?</think>", "", raw2, flags=re.DOTALL).strip()
                cm2 = re.search(r"```python\n(.*?)```", raw2, re.DOTALL)
                if not cm2:
                    cm2 = re.search(r"```\n(.*?)```", raw2, re.DOTALL)
                code2 = cm2.group(1) if cm2 else raw2
                safe2 = []
                for ln2 in code2.split("\n"):
                    s2 = ln2.lstrip()
                    if s2.startswith("output_dir") and "=" in s2.split("#")[0]:
                        safe2.append("# (removed by preamble) " + ln2)
                    else:
                        safe2.append(ln2)
                code2 = "\n".join(safe2)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf2:
                    tf2.write(preamble)
                    tf2.write(code2)
                    tmp_path2 = tf2.name
                proc2 = subprocess.run(
                    [sys.executable, tmp_path2],
                    capture_output=True, text=True, timeout=120,
                )
                os.unlink(tmp_path2)
                if proc2.returncode != 0:
                    return {
                        "error": "Code execution failed (both attempts). "
                                 "First: " + stderr_snippet + "; Second: " + proc2.stderr[:300],
                        "code": code2[:300],
                    }
                proc = proc2
                code = code2
            except Exception as _retry_exc:
                return {
                    "error": "Code execution failed: " + stderr_snippet + "; retry error: " + str(_retry_exc),
                    "code": code[:300],
                }

        # Parse JSON output
        fig_list: list = []
        for line in proc.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("["):
                try:
                    fig_list = json.loads(line)
                    break
                except Exception:
                    pass

        figures: dict = {}
        latex_snippets: dict = {}
        for item in fig_list:
            name = item.get("name", "fig")
            path = item.get("path", "")
            # Resolve to absolute path so downstream skills can find the file
            # regardless of working directory
            _p = Path(path)
            if not _p.is_absolute():
                _p = (out_dir / _p.name).resolve() if _p.name else Path(path).resolve()
            path = str(_p)
            caption = item.get("caption", "").strip()
            if Path(path).exists():
                figures[name] = path
                fname = Path(path).name
                latex_snippets[name] = (
                    f"\\begin{{figure}}[H]\n"
                    f"\\centering\n"
                    f"\\includegraphics[width=0.85\\linewidth]{{{fname}}}\n"
                    f"\\caption{{{caption}}}\n"
                    f"\\label{{fig:{name}}}\n"
                    f"\\end{{figure}}"
                )

        # Fallback: scan dir
        if not figures:
            for pdf in sorted(out_dir.glob("fig_*.pdf")):
                name = pdf.stem
                figures[name] = str(pdf.resolve())
                latex_snippets[name] = (
                    f"\\begin{{figure}}[H]\n"
                    f"\\centering\n"
                    f"\\includegraphics[width=0.85\\linewidth]{{{pdf.name}}}\n"
                    f"\\caption{{{metric_name} across experimental configurations ({name}). "
                    f"See text for detailed analysis.}}\n"
                    f"\\label{{fig:{name}}}\n"
                    f"\\end{{figure}}"
                )

        # ── VLM caption refinement ──
        if figures:
            _vlm_ctx = experiment_summary or context or ""
            for fig_name, fig_path in figures.items():
                if not Path(fig_path).exists():
                    continue
                # Convert PDF to PNG for VLM if only PDF exists
                _png = Path(fig_path).with_suffix(".png")
                if not _png.exists():
                    try:
                        import matplotlib.image as _mimg
                        import matplotlib.pyplot as _mplt
                        from matplotlib.backends.backend_pdf import PdfPages
                        # Use matplotlib to render PDF page to PNG
                        import subprocess as _sp
                        _sp.run(["python3", "-c",
                                 f"import matplotlib; matplotlib.use('Agg');"
                                 f"from matplotlib.backends.backend_agg import FigureCanvasAgg;"
                                 f"import fitz; doc=fitz.open('{fig_path}');"
                                 f"pix=doc[0].get_pixmap(dpi=150);"
                                 f"pix.save('{_png}')"],
                                timeout=30, capture_output=True)
                    except Exception:
                        pass
                if _png.exists():
                    snip = latex_snippets.get(fig_name, "")
                    _fb_m = re.search(r"\\caption\{([^}]+)\}", snip)
                    fallback = _fb_m.group(1) if _fb_m else f"Results for {fig_name}."
                    caption = await _vlm_caption(str(_png), fallback, context=_vlm_ctx)
                    fname = Path(fig_path).name
                    latex_snippets[fig_name] = (
                        f"\\begin{{figure}}[H]\n"
                        f"\\centering\n"
                        f"\\includegraphics[width=0.85\\linewidth]{{{fname}}}\n"
                        f"\\caption{{{caption}}}\n"
                        f"\\label{{fig:{fig_name}}}\n"
                        f"\\end{{figure}}"
                    )

        return {
            "figures": figures,
            "latex_snippets": latex_snippets,
            "generated_code_preview": code[:200] + "...",
        }

    except Exception:
        return {"error": traceback.format_exc()[:500]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()