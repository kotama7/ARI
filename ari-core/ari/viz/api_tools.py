from __future__ import annotations
"""ARI viz: api_tools."""
"""ARI Experiment Tree Visualizer — WebSocket + HTTP server.

Usage:
    python -m ari.viz.server --checkpoint ./logs/my_ckpt/ [--port 8765]
"""


import argparse
import asyncio
import json
import re
import os
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Set

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    raise SystemExit("websockets package required: pip install websockets")

# ──────────────────────────────────────────────
# Shared state
# ──────────────────────────────────────────────



from . import state as _st


def _api_chat_goal(body: bytes) -> dict:
    """Multi-turn chat using OpenAI directly (avoids LLMClient tool-forcing hang)."""
    data = json.loads(body)
    messages = data.get("messages", [])
    context_md = data.get("context_md", "")
    if not messages:
        return {"error": "messages required"}
    try:
        import os
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            env_path = Path.home() / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
        if not api_key:
            return {"error": "OPENAI_API_KEY not found"}
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=60.0)
        system = (
            "You are an assistant helping a researcher set up an ARI experiment. "
            "ARI automatically writes, runs, benchmarks code, then produces a paper. "
            "Ask focused questions ONE AT A TIME to understand: "
            "(1) what to optimize or investigate, "
            "(2) how to measure success (metric name and direction), "
            "(3) platform/hardware constraints, "
            "(4) any baseline to compare against. "
            "Be concise. After 3-5 exchanges and sufficient info, output EXACTLY: "
            "---READY--- "
            "followed by a complete experiment.md with sections: "
            "## Research Goal, ## Evaluation Metric, ## Constraints. "
            "Do NOT output the MD before getting at least 2 user responses."
        )
        full_messages = [{"role": "system", "content": system}] + messages
        # Use OpenAI model; always use gpt-4o-mini for reliable chat
        model = "gpt-4o-mini"
        resp = client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=800,
            temperature=0.7,
        )
        text = resp.choices[0].message.content or ""
        ready = "---READY---" in text
        md_content = ""
        if ready:
            parts = text.split("---READY---", 1)
            text = parts[0].strip()
            md_content = parts[1].strip() if len(parts) > 1 else context_md
        return {"reply": text, "ready": ready, "md": md_content}
    except Exception as e:
        return {"error": str(e)}



def _api_generate_config(body: bytes) -> dict:
    """Generate experiment.md content from natural language goal via LLM."""
    data = json.loads(body)
    goal = data.get("goal", "")
    if not goal:
        return {"error": "goal required"}
    try:
        from ari.config import auto_config
        from ari.llm.client import LLMClient
        cfg = auto_config()
        client = LLMClient(cfg.llm)
        prompt = (
            "You are helping a researcher set up an automated experiment. "
            "Convert the following research goal into a concise experiment.md file "
            "with a ## Research Goal section. Keep it to 3-5 sentences maximum. "
            "Do not add code or technical details. "
            f"Research goal: {goal}"
        )
        messages = [{"role": "user", "content": prompt}]
        resp = client.complete(messages, require_tool=False)
        # LLMResponse.content is a plain str
        text = resp.content if hasattr(resp, "content") else str(resp)
        return {"content": text or "## Research Goal\n\n" + goal}
    except Exception as e:
        return {"error": str(e)}



def _api_upload_file(headers, body: bytes) -> dict:
    """Handle file upload."""
    content_type = headers.get("Content-Type", "")
    filename = headers.get("X-Filename", "upload.md")
    filename = Path(filename).name  # sanitize
    if "multipart/form-data" not in content_type:
        # Raw body upload with X-Filename header
        save_path = Path.cwd() / filename
        save_path.write_bytes(body)
        return {"ok": True, "path": str(save_path), "filename": filename}
    # Multipart: extract first file part
    boundary = content_type.split("boundary=")[-1].strip().encode()
    CRLF2 = b"\r\n\r\n"
    parts = body.split(b"--" + boundary)
    for part in parts[1:]:
        if b"filename=" in part and CRLF2 in part:
            header_end = part.index(CRLF2)
            header_raw = part[:header_end].decode("utf-8", errors="replace")
            data = part[header_end + 4:].rstrip(b"\r\n--")
            m = re.search(r'filename="([^"]+)"', header_raw)
            filename = Path(m.group(1)).name if m else "upload.md"
            save_path = Path.cwd() / filename
            save_path.write_bytes(data)
            return {"ok": True, "path": str(save_path), "filename": filename}
    return {"error": "no file found in upload"}



def _api_ssh_test(body: bytes) -> dict:
    """Test SSH connectivity to a remote host."""
    import subprocess as _sp, json as _json
    try:
        data = _json.loads(body) if body else {}
    except Exception:
        data = {}
    host = data.get("ssh_host", "")
    port = int(data.get("ssh_port", 22))
    user = data.get("ssh_user", "")
    ssh_key = data.get("ssh_key", "")
    ssh_path = data.get("ssh_path", "")
    if not host:
        return {"ok": False, "error": "No host specified"}
    target = f"{user}@{host}" if user else host
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
           "-p", str(port)]
    if ssh_key:
        cmd += ["-i", ssh_key]
    cmd += [target, "uname -n && python3 --version"]
    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            info = r.stdout.strip().replace(chr(10), " | ")
            if ssh_path:
                # Check ARI path exists
                r2 = _sp.run(cmd[:-1] + [target, f"test -d {ssh_path} && echo 'ARI path OK'"],
                              capture_output=True, text=True, timeout=10)
                if "ARI path OK" in r2.stdout:
                    info += f" | ARI: {ssh_path} ✓"
                else:
                    info += f" | ARI path not found: {ssh_path}"
            return {"ok": True, "info": info or "connected"}
        else:
            return {"ok": False, "error": (r.stderr or r.stdout or "connection refused").strip()[:200]}
    except _sp.TimeoutExpired:
        return {"ok": False, "error": "Connection timed out (10s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


