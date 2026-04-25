"""MCP Server for code writing and execution."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool


_STDOUT_LIMIT = 4000
_STDERR_LIMIT = 2000
_READ_FILE_LIMIT = 8000

# ── Fail-safe: process sandbox ──────────────────────────
# Prevent fork bombs and ensure cleanup of all child processes on timeout.
# The limit caps the number of user processes that can exist while the
# child is running.  It is intentionally generous (legitimate scientific
# workloads rarely exceed a few hundred), but low enough to stop runaway
# recursive spawns like the 70k-process incident.
_MAX_CHILD_PROCS = int(os.environ.get("ARI_MAX_CHILD_PROCS", "1024"))


def _sandbox_preexec() -> None:
    """Pre-exec hook: new process group + RLIMIT_NPROC cap."""
    os.setsid()
    try:
        import resource
        _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        cap = min(hard, _MAX_CHILD_PROCS)
        resource.setrlimit(resource.RLIMIT_NPROC, (cap, hard))
    except Exception:
        pass


def _run_sandboxed(
    cmd: str | list[str],
    *,
    shell: bool = False,
    timeout: int = 60,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess inside a process-group sandbox.

    * Creates a new session (``setsid``) so all descendants share a PGID.
    * Applies ``RLIMIT_NPROC`` to cap runaway process creation.
    * On timeout, sends ``SIGTERM`` then ``SIGKILL`` to the **entire**
      process group — not just the direct child.
    """
    proc = subprocess.Popen(
        cmd,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        preexec_fn=_sandbox_preexec,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout or "", stderr or "")
    except subprocess.TimeoutExpired:
        # Graceful shutdown: SIGTERM the group, wait briefly, then SIGKILL.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
        raise


def _resolve_work_dir(explicit: str | None) -> str:
    """Return the effective work directory: explicit arg > ARI_WORK_DIR env > /tmp/ari_work."""
    wd = explicit or os.environ.get("ARI_WORK_DIR") or "/tmp/ari_work"
    Path(wd).mkdir(parents=True, exist_ok=True)
    return wd


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Truncate keeping head and tail with a visible marker. Returns (preview, truncated)."""
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    half = limit // 2
    omitted = len(text) - limit
    marker = (
        f"\n\n... [{omitted} chars truncated — "
        f"redirect output to a file via run_bash (e.g. `<your command> > out.log 2>&1`) "
        f"and use read_file to retrieve the full content] ...\n\n"
    )
    return text[:half] + marker + text[-half:], True


server = Server("coding-skill")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="write_code",
            description=(
                "Write source code to a file in the specified working directory. "
                "Language is chosen by the caller; pick whatever fits the task "
                "(e.g. Python, C, C++, Fortran, Rust, Go, shell, ...). "
                "For compiled languages, invoke the compiler via run_bash afterwards."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "File name to write. The extension determines the "
                            "interpreter used by run_code and the tooling expected "
                            "from run_bash (e.g. main.py, main.c, main.cpp, "
                            "main.f90, main.rs, main.go, run.sh)."
                        ),
                    },
                    "code": {
                        "type": "string",
                        "description": "Code content to write",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                },
                "required": ["filename", "code"],
            },
        ),
        Tool(
            name="run_code",
            description=(
                "Execute a source file using an interpreter selected by its "
                "extension (.py -> python3, .sh -> bash, .js -> node, "
                ".rb -> ruby, .pl -> perl, .lua -> lua). "
                "For compiled languages (C/C++/Fortran/Rust/Go/...) or any "
                "custom build step, use run_bash to invoke the compiler and "
                "then run the resulting binary — run_code does NOT compile. "
                "Output is truncated if large; check the 'truncated' flag and "
                "re-run via run_bash with shell redirection (e.g. "
                "`<your command> > out.log 2>&1`) then use read_file to fetch "
                "the full output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "File name to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["filename"],
            },
        ),
        Tool(
            name="run_bash",
            description=(
                "Execute a bash command and return stdout/stderr/exit_code. "
                "Output is truncated if large; check the 'truncated' flag and "
                "redirect to a file (e.g. `cmd > out.log 2>&1`) then use "
                "read_file to fetch the full output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Bash command to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="read_file",
            description=(
                "Read a text file from the working directory. Supports "
                "offset/limit for paginated reads of large files (use the "
                "returned 'next_offset' to continue)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path (absolute, or relative to work_dir)",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Start character offset (default 0)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Max characters to return (default {_READ_FILE_LIMIT})",
                        "default": _READ_FILE_LIMIT,
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_code":
        result = _write_code(
            filename=arguments["filename"],
            code=arguments["code"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
        )
    elif name == "run_code":
        result = _run_code(
            filename=arguments["filename"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    elif name == "run_bash":
        result = _run_bash(
            command=arguments["command"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    elif name == "read_file":
        result = _read_file(
            path=arguments["path"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            offset=arguments.get("offset", 0),
            limit=arguments.get("limit", _READ_FILE_LIMIT),
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


def _write_code(filename: str, code: str, work_dir: str) -> dict:
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    file_path = work_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(code, encoding="utf-8")
    return {
        "path": str(file_path),
        "lines": len(code.splitlines()),
        "status": "written",
    }


def _format_run_result(stdout: str, stderr: str, returncode: int) -> dict:
    stdout_text, stdout_truncated = _truncate(stdout or "", _STDOUT_LIMIT)
    stderr_text, stderr_truncated = _truncate(stderr or "", _STDERR_LIMIT)
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "truncated": stdout_truncated or stderr_truncated,
        "exit_code": returncode,
        "status": "success" if returncode == 0 else "failed",
    }


_INTERPRETERS: dict[str, list[str]] = {
    ".py": ["python3"],
    ".sh": ["bash"],
    ".js": ["node"],
    ".rb": ["ruby"],
    ".pl": ["perl"],
    ".lua": ["lua"],
}


def _run_code(filename: str, work_dir: str, timeout: int) -> dict:
    file_path = Path(work_dir) / filename
    if not file_path.exists():
        return {"error": f"File not found: {file_path}", "exit_code": -1}

    interp = _INTERPRETERS.get(file_path.suffix.lower())
    if interp is None:
        return {
            "error": (
                f"run_code has no interpreter for '{file_path.suffix}'. "
                "Use run_bash to compile and/or execute this file "
                "(e.g. `gcc -O3 main.c -o main && ./main`, "
                "`gfortran -O3 main.f90 -o main && ./main`, "
                "`cargo run --release`)."
            ),
            "exit_code": -1,
        }

    try:
        result = _run_sandboxed(
            interp + [str(file_path)],
            timeout=timeout,
            cwd=work_dir,
        )
        return _format_run_result(result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s (process group killed)", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


def _run_bash(command: str, work_dir: str, timeout: int) -> dict:
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    try:
        # When ARI_CONTAINER_IMAGE is set, wrap the command so it executes
        # inside the configured container. Falls back to sandboxed subprocess
        # when no container is configured or the ari.container import is
        # unavailable.
        _ct_cfg = None
        try:
            from ari.container import config_from_env, run_shell_in_container
            _ct_cfg = config_from_env()
        except Exception:
            _ct_cfg = None
        if _ct_cfg is not None:
            result = run_shell_in_container(
                _ct_cfg, command, cwd=work_dir, timeout=timeout,
            )
        else:
            result = _run_sandboxed(
                command,
                shell=True,
                timeout=timeout,
                cwd=work_dir,
            )
        return _format_run_result(result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s (process group killed)", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


def _read_file(path: str, work_dir: str, offset: int, limit: int) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = Path(work_dir) / path
    if not p.exists():
        return {"error": f"File not found: {p}"}
    if not p.is_file():
        return {"error": f"Not a file: {p}"}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Read failed: {e}"}
    total = len(text)
    if offset < 0:
        offset = 0
    end = offset + limit
    chunk = text[offset:end]
    return {
        "path": str(p),
        "content": chunk,
        "offset": offset,
        "returned_chars": len(chunk),
        "total_chars": total,
        "truncated": end < total,
        "next_offset": end if end < total else None,
    }


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
