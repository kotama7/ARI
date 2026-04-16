from __future__ import annotations
"""ARI viz: api_tools — chat, config generation, file upload, SSH test."""

import json
import logging
import os
import re
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)


def _api_chat_goal(body: bytes) -> dict:
    """Multi-turn chat using the provider configured in Settings."""
    data = json.loads(body)
    messages = data.get("messages", [])
    context_md = data.get("context_md", "")
    if not messages:
        return {"error": "messages required"}
    try:
        from .api_settings import _api_get_settings
        settings = _api_get_settings()
        provider = settings.get("llm_provider", "") or os.environ.get("ARI_BACKEND", "openai")
        model = settings.get("llm_model", "") or os.environ.get("ARI_MODEL", "gpt-4o-mini")
        # Resolve API key: settings → environment → .env files
        api_key = settings.get("api_key", "") or settings.get("llm_api_key", "")
        if not api_key or len(api_key) < 20:
            if provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY", "")
            elif provider in ("anthropic", "claude"):
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key or len(api_key) < 20:
            # Fallback: read from .env files
            _ari_root = Path(__file__).parent.parent.parent.parent
            for env_path in [_ari_root / ".env", Path.home() / ".env"]:
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if provider == "openai" and k == "OPENAI_API_KEY":
                                api_key = v
                            elif provider in ("anthropic", "claude") and k == "ANTHROPIC_API_KEY":
                                api_key = v
                    if api_key and len(api_key) >= 20:
                        break
        if not api_key or len(api_key) < 20:
            key_name = "ANTHROPIC_API_KEY" if provider in ("anthropic", "claude") else "OPENAI_API_KEY"
            return {"error": f"{key_name} not found. Configure it in Settings."}
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
        # Use litellm for unified provider support
        import litellm
        litellm_model = model
        if provider in ("anthropic", "claude"):
            litellm_model = f"anthropic/{model}"
        elif provider == "ollama":
            litellm_model = f"ollama_chat/{model}"
        kwargs = {
            "model": litellm_model,
            "messages": full_messages,
            "max_tokens": 2048,
            "api_key": api_key,
            "timeout": 60,
        }
        # gpt-5* only supports temperature=1
        if not model.startswith("gpt-5"):
            kwargs["temperature"] = 0.7
        if provider == "ollama":
            base_url = settings.get("ollama_host", "") or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            kwargs["api_base"] = base_url
        resp = litellm.completion(**kwargs)
        text = resp.choices[0].message.content or ""
        ready = "---READY---" in text
        md_content = ""
        if ready:
            parts = text.split("---READY---", 1)
            text = parts[0].strip()
            md_content = parts[1].strip() if len(parts) > 1 else context_md
        return {"reply": text, "ready": ready, "md": md_content}
    except Exception as e:
        log.warning("Chat goal error: %s", e, exc_info=True)
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
    """Handle file upload.

    If no checkpoint directory exists yet (e.g. fresh wizard), a staging
    directory is created automatically under {ARI}/workspace/staging/ so
    uploads succeed before launch. The staging root must share the workspace
    with checkpoints/, otherwise launched runs end up under an unrelated
    parent and disappear from the GUI's checkpoint list.
    """
    content_type = headers.get("Content-Type", "")
    filename = headers.get("X-Filename", "upload.md")
    filename = Path(filename).name  # sanitize
    err = _st.require_checkpoint_dir()
    if err:
        # Auto-create staging directory so wizard uploads work before launch
        from ari.paths import PathManager
        _pm = PathManager(_st._ari_root / "workspace")
        staging = _pm.new_staging_dir()
        _st.set_active_checkpoint(staging)
        _st._staging_dir = staging
        log.info("Created staging dir for uploads: %s", staging)
    uploads_dir = _st._checkpoint_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    if "multipart/form-data" not in content_type:
        # Raw body upload with X-Filename header
        save_path = uploads_dir / filename
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
            save_path = uploads_dir / filename
            save_path.write_bytes(data)
            return {"ok": True, "path": str(save_path), "filename": filename}
    return {"error": "no file found in upload"}



def _api_upload_delete(body: bytes) -> dict:
    """Delete a previously uploaded file from the checkpoint/staging directory."""
    try:
        data = json.loads(body) if body else {}
    except Exception:
        return {"ok": False, "error": "Invalid JSON"}
    filename = data.get("filename", "")
    if not filename:
        return {"ok": False, "error": "filename required"}
    filename = Path(filename).name  # sanitize
    err = _st.require_checkpoint_dir()
    if err:
        return {"ok": False, "error": err}
    target = _st._checkpoint_dir / "uploads" / filename
    if not target.exists():
        # Fallback: check root for backward compatibility
        target = _st._checkpoint_dir / filename
    if not target.exists():
        return {"ok": False, "error": f"File not found: {filename}"}
    try:
        target.unlink()
        return {"ok": True, "filename": filename}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_ssh_test(body: bytes) -> dict:
    """Test SSH connectivity to a remote host."""
    import shlex
    import subprocess as _sp, json as _json
    try:
        data = _json.loads(body) if body else {}
    except Exception:
        log.debug("SSH test body parse error", exc_info=True)
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
                # Check ARI path exists (sanitize path to prevent injection)
                safe_path = shlex.quote(ssh_path)
                r2 = _sp.run(cmd[:-1] + [target, f"test -d {safe_path} && echo 'ARI path OK'"],
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


