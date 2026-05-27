from __future__ import annotations
"""OpenAI-compatible HTTP shim that serves agentic CLIs (`claude -p`,
`codex exec`) as chat-completion backends.

ARI talks to every model through ``litellm`` (see ``ari/llm/client.py``).
litellm speaks the OpenAI ``/v1/chat/completions`` protocol, so this shim lets
ARI drive the Claude Code / Codex CLIs by pointing ``base_url`` at it — no
changes to the agent loop required.

Register in ARI config (config/*.yaml or the GUI wizard)::

    llm:
      backend: openai
      model: openai/claude-cli   # "openai/" => litellm routes to base_url
      base_url: http://localhost:8900/v1
      api_key: dummy             # litellm requires a key; the shim ignores it

The ``openai/`` prefix tells litellm to use its OpenAI-compatible handler and
dial ``base_url``; litellm strips the prefix before calling, so the shim sees
``claude-cli``. ``parse_model`` also tolerates the prefix defensively.

Virtual models (the ``model`` field selects engine + mode)::

    claude-cli            claude -p, tools disabled  -> plain text / JSON
    claude-cli-agent      claude -p, own tool loop   -> final text only
    codex-cli             codex exec, read-only      -> plain text / JSON
    codex-cli-agent       codex exec, full auto      -> final text only

    # append ":<alias>" to pick the underlying model, e.g.
    claude-cli:sonnet     codex-cli-agent:gpt-5-codex

Endpoints::

    POST /v1/chat/completions   OpenAI chat completions (non-stream + stream)
    GET  /v1/models             list the virtual models
    GET  /healthz               liveness probe (used by start.sh)

IMPORTANT — billing / auth (see also the project docs): the shim shells out to
the real ``claude`` / ``codex`` binaries, so requests consume tokens against
whatever auth those CLIs use (subscription login *or* API key). The "agent"
modes can read/write files and run commands via the CLI's own tool loop; they
return only the CLI's final text, NOT OpenAI ``tool_calls``, so they cannot
drive ARI's own ReAct tool loop — use them for whole-task delegation, and use
the plain modes for judge / expand / select style text generation.
"""

import argparse
import json
import logging
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("ari.llm.cli_server")

# ──────────────────────────────────────────────────────────────────────────
# Configuration (all overridable via env)
# ──────────────────────────────────────────────────────────────────────────
DEFAULT_PORT = int(os.environ.get("ARI_CLI_SHIM_PORT", "8900"))
TIMEOUT = float(os.environ.get("ARI_CLI_SHIM_TIMEOUT", "1800"))
MAX_CONCURRENCY = int(os.environ.get("ARI_CLI_SHIM_MAX_CONCURRENCY", "4"))
CLAUDE_BIN = os.environ.get("ARI_CLI_SHIM_CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("ARI_CLI_SHIM_CODEX_BIN", "codex")
# Pass `claude --bare`: minimal mode (no CLAUDE.md/hooks/auto-memory). Strongly
# cuts the per-call input-token overhead but forces ANTHROPIC_API_KEY auth.
CLAUDE_BARE = os.environ.get("ARI_CLI_SHIM_CLAUDE_BARE", "0") == "1"
# Permission mode for claude-cli-agent (claude --permission-mode ...).
CLAUDE_AGENT_PERMISSION = os.environ.get(
    "ARI_CLI_SHIM_CLAUDE_AGENT_PERMISSION", "acceptEdits"
)
# Optional per-call spend cap for claude (claude --max-budget-usd).
MAX_BUDGET_USD = os.environ.get("ARI_CLI_SHIM_MAX_BUDGET_USD", "").strip()
# Working dir for agent-mode runs (file edits / commands land here). When
# unset each request gets a throwaway temp dir.
SHIM_CWD = os.environ.get("ARI_CLI_SHIM_CWD", "").strip()

# Cap simultaneous CLI subprocesses so a burst of requests can't fork-bomb the
# host. Acquired for the duration of each completion.
_slots = threading.BoundedSemaphore(max(1, MAX_CONCURRENCY))


# ──────────────────────────────────────────────────────────────────────────
# Model routing
# ──────────────────────────────────────────────────────────────────────────
class ShimError(Exception):
    """Raised for client-facing 4xx errors (bad model, bad request)."""


def parse_model(model: str) -> tuple[str, bool, str | None]:
    """Split a virtual model id into ``(engine, agent, real_model)``.

    ``engine`` is "claude" or "codex"; ``agent`` selects the tool-using mode;
    ``real_model`` is the optional ``:alias`` suffix (None => CLI default).
    """
    name = (model or "").strip()
    # litellm normally strips the "openai/" routing prefix, but tolerate it in
    # case a caller passes the model id through verbatim.
    if name.startswith("openai/"):
        name = name[len("openai/"):]
    real_model: str | None = None
    if ":" in name:
        name, real_model = name.split(":", 1)
        real_model = real_model.strip() or None
    agent = name.endswith("-agent")
    if agent:
        name = name[: -len("-agent")]
    if name in ("claude-cli", "claude"):
        return "claude", agent, real_model
    if name in ("codex-cli", "codex"):
        return "codex", agent, real_model
    raise ShimError(
        f"unknown model {model!r}; expected one of claude-cli, "
        f"claude-cli-agent, codex-cli, codex-cli-agent (optional :alias)"
    )


def render_prompt(messages: list[dict]) -> tuple[str, str]:
    """Flatten OpenAI ``messages`` into ``(system_text, prompt_text)``.

    System messages are concatenated separately so claude can receive them via
    ``--system-prompt``; the remaining turns are rendered as a plain transcript
    fed to the CLI on stdin.
    """
    system_parts: list[str] = []
    turns: list[str] = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # OpenAI content-parts -> concatenate the text parts.
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        content = str(content or "")
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            turns.append(f"Assistant: {content}")
        elif role == "tool":
            turns.append(f"Tool result: {content}")
        else:
            turns.append(f"User: {content}")
    system_text = "\n\n".join(p for p in system_parts if p).strip()
    # A single user turn is by far the common case — send it verbatim so the
    # CLI sees a clean prompt rather than a "User:"-prefixed transcript.
    if len(turns) == 1 and turns[0].startswith("User: "):
        prompt_text = turns[0][len("User: "):]
    else:
        prompt_text = "\n\n".join(turns).strip()
    return system_text, prompt_text


# ──────────────────────────────────────────────────────────────────────────
# CLI invocation
# ──────────────────────────────────────────────────────────────────────────
def _run(cmd: list[str], stdin_text: str, cwd: str) -> subprocess.CompletedProcess:
    log.info("shim exec: %s (cwd=%s, stdin=%dB)", cmd[0:3], cwd, len(stdin_text))
    return subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        cwd=cwd,
    )


def run_claude(
    system: str, prompt: str, agent: bool, real_model: str | None, cwd: str
) -> tuple[str, dict]:
    cmd = [CLAUDE_BIN, "-p", "--output-format", "json"]
    if CLAUDE_BARE:
        cmd.append("--bare")
    if real_model:
        cmd += ["--model", real_model]
    if system:
        cmd += ["--system-prompt", system]
    if agent:
        cmd += ["--permission-mode", CLAUDE_AGENT_PERMISSION]
    else:
        # No tools => pure text/JSON generation.
        cmd += ["--allowedTools", ""]
    if MAX_BUDGET_USD:
        cmd += ["--max-budget-usd", MAX_BUDGET_USD]
    proc = _run(cmd, prompt, cwd)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude returned non-JSON output: {proc.stdout[:500]}") from e
    if data.get("is_error"):
        raise RuntimeError(f"claude reported error: {data.get('result', '')[:500]}")
    text = data.get("result", "") or ""
    u = data.get("usage", {}) or {}
    prompt_tokens = (
        int(u.get("input_tokens", 0) or 0)
        + int(u.get("cache_creation_input_tokens", 0) or 0)
        + int(u.get("cache_read_input_tokens", 0) or 0)
    )
    completion_tokens = int(u.get("output_tokens", 0) or 0)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return text, usage


def run_codex(
    system: str, prompt: str, agent: bool, real_model: str | None, cwd: str
) -> tuple[str, dict]:
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
    with tempfile.NamedTemporaryFile(
        "w+", suffix=".txt", dir=cwd, delete=False
    ) as fh:
        last_msg_file = fh.name
    cmd = [
        CODEX_BIN, "exec",
        "--skip-git-repo-check",
        "--json",
        "-o", last_msg_file,
    ]
    if real_model:
        cmd += ["-m", real_model]
    if agent:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd += ["--sandbox", "read-only"]
    # Pass the prompt as a positional argument, NOT on stdin: `codex exec`
    # reading from stdin hangs after the turn starts (it keeps the stream open
    # waiting for more input and never finalises the turn), whereas an argv
    # prompt runs to completion. Very large prompts (>~ARG_MAX) are the only
    # caveat; codex task prompts are well under that.
    cmd.append(full_prompt)
    try:
        proc = _run(cmd, "", cwd)
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}"
            )
        try:
            with open(last_msg_file, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            text = ""
    finally:
        try:
            os.unlink(last_msg_file)
        except OSError:
            pass
    # Best-effort usage from the JSONL event stream (token_count events).
    usage = _parse_codex_usage(proc.stdout)
    return text, usage


def _parse_codex_usage(stdout: str) -> dict:
    prompt_tokens = completion_tokens = 0
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Codex emits token-count info nested under varying keys across
        # versions; scan for the common ones without hard-coding a schema.
        info = ev.get("info") if isinstance(ev.get("info"), dict) else ev
        tu = info.get("token_usage") or info.get("usage") or {}
        if isinstance(tu, dict):
            prompt_tokens = int(tu.get("input_tokens", prompt_tokens) or prompt_tokens)
            completion_tokens = int(
                tu.get("output_tokens", completion_tokens) or completion_tokens
            )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def complete(model: str, messages: list[dict]) -> tuple[str, dict]:
    """Run the selected CLI and return ``(text, usage)``."""
    engine, agent, real_model = parse_model(model)
    system, prompt = render_prompt(messages)
    if not prompt and not system:
        raise ShimError("no prompt content in messages")

    # Resolve the working directory (throwaway temp dir unless configured).
    tmp_cwd = None
    cwd = SHIM_CWD
    if not cwd:
        tmp_cwd = tempfile.mkdtemp(prefix="ari-cli-shim-")
        cwd = tmp_cwd
    with _slots:
        try:
            if engine == "claude":
                return run_claude(system, prompt, agent, real_model, cwd)
            return run_codex(system, prompt, agent, real_model, cwd)
        finally:
            if tmp_cwd:
                # Leave agent artifacts only if the caller pinned a cwd; the
                # throwaway dir is removed best-effort.
                import shutil
                shutil.rmtree(tmp_cwd, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# OpenAI response envelopes
# ──────────────────────────────────────────────────────────────────────────
def _completion_envelope(model: str, text: str, usage: dict) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


def _chunk(model: str, cid: str, delta: dict, finish: str | None) -> str:
    obj = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(obj)}\n\n"


VIRTUAL_MODELS = ["claude-cli", "claude-cli-agent", "codex-cli", "codex-cli-agent"]


# ──────────────────────────────────────────────────────────────────────────
# HTTP handler
# ──────────────────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = "ARICliShim/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter access log
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code: int, message: str, etype: str = "invalid_request_error") -> None:
        self._send_json(code, {"error": {"message": message, "type": etype}})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if path in ("/v1/models", "/models"):
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": m, "object": "model", "owned_by": "ari-cli-shim"}
                        for m in VIRTUAL_MODELS
                    ],
                },
            )
            return
        self._send_error(404, f"not found: {path}", "not_found")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_error(404, f"not found: {path}", "not_found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            req = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"invalid request body: {e}")
            return

        model = req.get("model", "")
        messages = req.get("messages", [])
        stream = bool(req.get("stream", False))

        try:
            text, usage = complete(model, messages)
        except ShimError as e:
            self._send_error(400, str(e))
            return
        except subprocess.TimeoutExpired:
            self._send_error(504, f"CLI timed out after {TIMEOUT}s", "timeout")
            return
        except Exception as e:  # noqa: BLE001 — surface CLI failures as 502
            log.exception("shim completion failed")
            self._send_error(502, f"CLI backend error: {e}", "api_error")
            return

        if not stream:
            self._send_json(200, _completion_envelope(model, text, usage))
            return

        # Single-chunk SSE: clients that require stream=true still work; we
        # don't get token-level streaming from the JSON output format.
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        # SSE body has no Content-Length; under HTTP/1.1 the client would
        # block waiting for more data. Delimit the body by EOF: close the
        # connection after the final event.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in (
            _chunk(model, cid, {"role": "assistant", "content": text}, None),
            _chunk(model, cid, {}, "stop"),
            "data: [DONE]\n\n",
        ):
            self.wfile.write(piece.encode("utf-8"))
        self.wfile.flush()


class _DualStackServer(ThreadingHTTPServer):
    """IPv6 socket that also accepts IPv4 (mirrors ari.viz.server)."""

    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def serve(port: int = DEFAULT_PORT) -> None:
    logging.basicConfig(
        level=os.environ.get("ARI_CLI_SHIM_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    srv = _DualStackServer(("", port), _Handler)
    log.info(
        "ARI CLI shim listening on http://localhost:%d/v1  "
        "(models: %s; concurrency=%d; claude_bare=%s)",
        port, ", ".join(VIRTUAL_MODELS), MAX_CONCURRENCY, CLAUDE_BARE,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenAI-compatible shim for claude/codex CLIs")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
