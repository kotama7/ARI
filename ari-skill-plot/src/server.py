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

# Wire skill-scoped cost tracking (see ari.cost_tracker.bootstrap_skill).
try:
    from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("plot")
except Exception:
    pass


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
# Figure execution helpers (shared by generate_figures_llm)
# ---------------------------------------------------------------------------


def _rasterize_svg(svg_code: str, png_path: Path, pdf_path: Path) -> bool:
    """Write PNG and PDF renderings of `svg_code`. Returns True on success.

    Tries cairosvg first; falls back to inkscape CLI when cairosvg or its
    underlying cairo library is unavailable. Either path is sufficient —
    both raster files are required before the caller considers the figure
    done (PNG for VLM review, PDF for LaTeX embedding).
    """
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(
            bytestring=svg_code.encode("utf-8"),
            write_to=str(png_path),
            output_width=1200,
        )
        cairosvg.svg2pdf(
            bytestring=svg_code.encode("utf-8"),
            write_to=str(pdf_path),
        )
        if png_path.exists() and pdf_path.exists():
            return True
    except Exception as e:
        log.warning("cairosvg failed (%s); trying inkscape fallback", e)
    svg_tmp = png_path.with_suffix(".svg")
    try:
        svg_tmp.write_text(svg_code, encoding="utf-8")
    except OSError:
        return False
    for target, export_type, extra in (
        (png_path, "png", ["--export-width=1200"]),
        (pdf_path, "pdf", []),
    ):
        try:
            subprocess.run(
                ["inkscape", str(svg_tmp),
                 f"--export-type={export_type}",
                 f"--export-filename={target}", *extra],
                capture_output=True, timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return png_path.exists() and pdf_path.exists()


def _run_plot_code(code: str, out_dir: Path, name: str) -> tuple[bool, str]:
    """Execute one matplotlib snippet in a subprocess.

    The snippet is expected to write {out_dir}/{name}.pdf and
    {out_dir}/{name}.png. `output_dir` and `name` are predefined for the
    snippet; any reassignment of `output_dir` is stripped to protect the
    pipeline contract.
    """
    preamble = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import json, os\n"
        f"output_dir = {str(out_dir)!r}\n"
        f"name = {name!r}\n"
        "try:\n    import seaborn as sns; sns.set_theme(style='whitegrid')\n"
        "except ImportError:\n    pass\n"
        "import matplotlib.legend as _mpl_leg\n"
        "if not hasattr(_mpl_leg.Legend, 'legendHandles'):\n"
        "    _mpl_leg.Legend.legendHandles = property(lambda self: self.legend_handles)\n"
    )
    safe_lines = []
    for line in code.split("\n"):
        s = line.lstrip()
        if s.startswith("output_dir") and "=" in s.split("#")[0]:
            safe_lines.append("# (removed by preamble) " + line)
        else:
            safe_lines.append(line)
    code = "\n".join(safe_lines)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
        tf.write(preamble)
        tf.write(code)
        tmp = tf.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp], capture_output=True, text=True, timeout=90,
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return proc.returncode == 0, proc.stderr[:400]


def _extract_figure_manifest(raw: str) -> list[dict]:
    """Parse the LLM response into a list of per-figure items.

    Accepts either a JSON array or a JSON array wrapped in markdown fences.
    Returns [] if nothing parseable is found.
    """
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    payload = fence.group(1).strip() if fence else raw
    try:
        data = json.loads(payload)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[\s*\{.*\}\s*\]", payload, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


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
        "You are a scientific visualization expert. Produce figures for a research paper.\n"
        "For EACH figure, independently choose ONE generator:\n"
        "  - kind=\"plot\": matplotlib Python code (data plots — bar, line, scatter, heatmap, etc.)\n"
        "  - kind=\"svg\":  self-contained SVG code (architecture/concept/flow/pipeline diagrams).\n"
        "Prefer plot for quantitative data; prefer svg for system/architecture/concept illustrations.\n\n"
        "OUTPUT FORMAT: a single JSON array, no markdown fences, no prose. Schema per element:\n"
        '  {"name":"fig_1","kind":"plot","code":"<matplotlib python>","caption":"<caption>"}\n'
        '  {"name":"fig_2","kind":"svg","svg":"<svg ...>...</svg>","caption":"<caption>"}\n\n'
        "For kind=\"plot\" the code MUST:\n"
        "  - use matplotlib.use('Agg')\n"
        "  - save BOTH output_dir/<name>.pdf (dpi=150) AND output_dir/<name>.png (dpi=200)\n"
        "  - use the predefined variables `output_dir` and `name` (do NOT reassign them)\n"
        "For kind=\"svg\" the svg MUST:\n"
        "  - start with <svg ...> and end with </svg>\n"
        "  - use viewBox for responsive sizing, readable fonts (14–16px), clean palette\n"
        "  - be self-contained (no external references)\n\n"
        "CRITICAL REQUIREMENTS:\n"
        " - Each figure must directly support a claim in the paper.\n"
        " - Use ACTUAL metric names and numeric values from the data — no 'a.u.' units.\n"
        " - Captions MUST be specific (metric, axis, values, conditions, key finding).\n"
        "   BAD: \"experimental results\". "
        "GOOD: \"Score vs X (0.1–0.9); best 76.3 at X=0.5, 10 trials.\".\n"
        " - NEVER produce a 'ranked configurations' bar chart unless the paper explicitly "
        "compares ranked designs.\n"
    )
    user_prompt = (
        f"Generate {n_figures} figures from this benchmark data.\n\n"
        f"DATA (configurations with all metrics):\n{data_summary}\n\n"
        f"output_dir = {repr(str(out_dir))}\n\n"
        "REQUIRED figures (read the data carefully and choose the best representation):\n"
        f"RULES: Use real metric names (score, throughput, etc.) from the data as axis labels. "
        "No 'a.u.', no 'Performance metric'. NO internal system terms.\n"
        f"1. Primary performance plot (kind=\"plot\"): score or throughput vs the main sweep parameter "
        f"   (e.g., N, configuration) — line or scatter plot with labeled axes and units.\n"
        f"2. {_axis2} (kind=\"plot\") — scatter or line plot with specific units from the data.\n"
        f"3. Comparison, ablation, or architecture/pipeline figure: choose kind=\"svg\" "
        f"   ONLY if the figure is a system/architecture/concept diagram; otherwise kind=\"plot\".\n\n"
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
    manifest = _extract_figure_manifest(raw)

    # If the LLM produced no parseable manifest, retry once with a simpler,
    # plot-only instruction (no SVG) to increase the chance of success.
    async def _retry_plot_only() -> list[dict]:
        simple_system = (
            "You are a matplotlib expert. Output a JSON array only (no markdown, no prose). "
            'Schema per item: {"name":"fig_N","kind":"plot","code":"<python>","caption":"<caption>"}. '
            "Each code snippet must use matplotlib.use('Agg'), the predefined `output_dir` "
            "and `name` variables, and save BOTH output_dir/<name>.pdf AND output_dir/<name>.png."
        )
        simple_user = (
            f"Generate {n_figures} simple matplotlib figures from this data. "
            f"Use only matplotlib (no seaborn, no networkx).\n\nDATA:\n{data_summary[:800]}"
        )
        kwargs2 = dict(kwargs)
        kwargs2["messages"] = [
            {"role": "system", "content": simple_system},
            {"role": "user", "content": simple_user},
        ]
        kwargs2["temperature"] = 0.1
        kwargs2["timeout"] = 120
        try:
            response2 = await litellm.acompletion(**kwargs2)
            raw2 = response2.choices[0].message.content or ""
            return _extract_figure_manifest(raw2)
        except Exception:
            return []

    if not manifest:
        manifest = await _retry_plot_only()

    figures: dict = {}
    latex_snippets: dict = {}
    figure_kinds: dict = {}
    errors: list[str] = []

    for item in manifest:
        name = str(item.get("name") or "").strip() or f"fig_{len(figures) + 1}"
        kind = str(item.get("kind") or "plot").strip().lower()
        caption = str(item.get("caption") or "").strip()

        pdf_path = out_dir / f"{name}.pdf"
        png_path = out_dir / f"{name}.png"

        if kind == "svg":
            svg_code = str(item.get("svg") or "").strip()
            if not svg_code or "<svg" not in svg_code or "</svg>" not in svg_code:
                errors.append(f"{name}: invalid or missing svg")
                continue
            svg_path = out_dir / f"{name}.svg"
            svg_path.write_text(svg_code, encoding="utf-8")
            if not _rasterize_svg(svg_code, png_path, pdf_path):
                errors.append(f"{name}: svg rasterization failed")
                continue
        else:
            code_str = str(item.get("code") or "").strip()
            if not code_str:
                errors.append(f"{name}: missing plot code")
                continue
            ok, stderr_tail = _run_plot_code(code_str, out_dir, name)
            if not ok or not pdf_path.exists():
                errors.append(f"{name}: plot code failed — {stderr_tail}")
                continue
            kind = "plot"

        figures[name] = str(pdf_path.resolve())
        figure_kinds[name] = kind
        fname = pdf_path.name
        latex_snippets[name] = (
            f"\\begin{{figure}}[H]\n"
            f"\\centering\n"
            f"\\includegraphics[width=0.85\\linewidth]{{{fname}}}\n"
            f"\\caption{{{caption or f'Results for {name}.'}}}\n"
            f"\\label{{fig:{name}}}\n"
            f"\\end{{figure}}"
        )

    # Fallback: scan dir for any figures written outside the manifest flow
    if not figures:
        for pdf in sorted(out_dir.glob("fig_*.pdf")):
            name = pdf.stem
            figures[name] = str(pdf.resolve())
            figure_kinds[name] = "plot"
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
            _png = Path(fig_path).with_suffix(".png")
            if not _png.exists():
                # PDF-only (e.g. plot code skipped the .png save) — try to
                # rasterize via PyMuPDF so VLM still has something to look at.
                try:
                    subprocess.run(
                        [sys.executable, "-c",
                         f"import fitz; doc=fitz.open({str(fig_path)!r});"
                         f"doc[0].get_pixmap(dpi=150).save({str(_png)!r})"],
                        timeout=30, capture_output=True,
                    )
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

    result: dict = {
        "figures": figures,
        "latex_snippets": latex_snippets,
        "figure_kinds": figure_kinds,
    }
    if errors:
        result["errors"] = errors[:10]
    if not figures:
        result["error"] = "No figures produced. " + ("; ".join(errors[:5]) if errors
                                                     else "Empty or unparseable LLM response.")
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()