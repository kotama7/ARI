"""
ari-skill-orchestrator — ARI orchestrator MCP server

Allows running ARI experiments from other agents or Claude Desktop
Exposes ARI experiments as MCP tools.

Tools:
  run_experiment   Accepts an experiment file (Markdown), runs it asynchronously, and returns a run_id
  get_status       Returns progress and results for a given run_id
  list_runs        Returns a list of past runs
  get_paper        Returns the experiment_section.tex for the given run_id
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

ARI_WORKSPACE = Path(os.environ.get("ARI_WORKSPACE", Path.home() / "ARI"))
LOGS_DIR = ARI_WORKSPACE / "logs"
ARI_CLI = str(ARI_WORKSPACE / "ari-core" / ".venv" / "bin" / "ari") \
    if (ARI_WORKSPACE / "ari-core" / ".venv").exists() \
    else "ari"  # if already in PATH

server = Server("ari-orchestrator")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runs() -> list[dict]:
    """Return all runs from the log directory."""
    runs = []
    for ckpt in sorted(LOGS_DIR.glob("*_ckpt_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        results_file = ckpt / "results.json"
        if not results_file.exists():
            continue
        try:
            data = json.loads(results_file.read_text())
            nodes = data.get("nodes", {})
            success = sum(1 for v in nodes.values() if v.get("status") == "success")
            runs.append({
                "run_id": data.get("run_id", ckpt.name),
                "checkpoint_dir": str(ckpt),
                "total_nodes": len(nodes),
                "success_nodes": success,
                "has_paper": (ckpt / "experiment_section.tex").exists(),
            })
        except Exception:
            continue
    return runs


def _get_run(run_id: str) -> dict | None:
    for r in _runs():
        if r["run_id"] == run_id or run_id in r["run_id"]:
            return r
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_experiment",
            description=(
                "Run an experiment using ARI. Pass experiment content in Markdown format and "
                "Runs autonomously with BFTS + ReAct and returns a run_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_md": {
                        "type": "string",
                        "description": "Experiment specification (Markdown). Should include ## Research Goal, ## Required Workflow, etc.",
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "Maximum number of nodes (default: 10)",
                        "default": 10,
                    },
                    "model": {
                        "type": "string",
                        "description": "LLM to use (default: qwen3:32b)",
                        "default": "qwen3:32b",
                    },
                },
                "required": ["experiment_md"],
            },
        ),
        types.Tool(
            name="get_status",
            description="Return experiment progress and results for a given run_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "The run_id returned by run_experiment"},
                },
                "required": ["run_id"],
            },
        ),
        types.Tool(
            name="list_runs",
            description="Return a list of past experiment runs.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_paper",
            description="Return the paper section (LaTeX) corresponding to a run_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # ---- run_experiment ----
    if name == "run_experiment":
        md = arguments.get("experiment_md", "")
        max_nodes = arguments.get("max_nodes", 10)
        model = arguments.get("model", "qwen3:32b")

        # Write experiment specification to a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=str(ARI_WORKSPACE), delete=False
        ) as f:
            f.write(md)
            exp_path = f.name

        # Launch ari run in background
        log_out = str(LOGS_DIR / f"orchestrator_mcp_{os.getpid()}.out")
        cmd = [
            ARI_CLI, "run", exp_path,
            "--max-nodes", str(max_nodes),
            "--model", model,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=open(log_out, "w"),
            stderr=subprocess.STDOUT,
            cwd=str(ARI_WORKSPACE),
        )
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "status": "started",
                "pid": proc.pid,
                "experiment_file": exp_path,
                "log": log_out,
                "message": (
                    "Experiment started in background. "
                    "Use get_status(run_id) after a few minutes to check progress. "
                    "run_id will appear in the log file once the run begins."
                ),
            }, ensure_ascii=False, indent=2),
        )]

    # ---- get_status ----
    elif name == "get_status":
        run_id = arguments.get("run_id", "")
        run = _get_run(run_id)
        if run is None:
            # Return the most recent run
            runs = _runs()
            if runs:
                run = runs[0]
            else:
                return [types.TextContent(type="text",
                                          text=json.dumps({"error": f"run_id '{run_id}' not found"}))]

        ckpt = Path(run["checkpoint_dir"])
        results_file = ckpt / "results.json"
        data = json.loads(results_file.read_text())
        nodes = data.get("nodes", {})

        summary = []
        for nid, ndata in nodes.items():
            m = ndata.get("metrics") or {}
            summary.append({
                "node_id": nid[-8:],
                "status": ndata.get("status"),
                "has_real_data": ndata.get("has_real_data", False),
                "metrics": dict(list(m.items())[:5]),
            })

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "run_id": run["run_id"],
                "total_nodes": run["total_nodes"],
                "success_nodes": run["success_nodes"],
                "has_paper": run["has_paper"],
                "nodes": summary,
            }, ensure_ascii=False, indent=2),
        )]

    # ---- list_runs ----
    elif name == "list_runs":
        return [types.TextContent(
            type="text",
            text=json.dumps(_runs(), ensure_ascii=False, indent=2),
        )]

    # ---- get_paper ----
    elif name == "get_paper":
        run_id = arguments.get("run_id", "")
        run = _get_run(run_id)
        if run is None:
            return [types.TextContent(type="text",
                                      text=json.dumps({"error": f"run_id '{run_id}' not found"}))]
        paper_path = Path(run["checkpoint_dir"]) / "experiment_section.tex"
        if not paper_path.exists():
            return [types.TextContent(type="text",
                                      text=json.dumps({"error": "Paper not generated yet. Wait for experiment to complete."}))]
        return [types.TextContent(type="text", text=paper_path.read_text())]

    return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
