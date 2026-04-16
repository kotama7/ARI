"""Tests for ari-skill-coding MCP server tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server import (
    _read_file,
    _run_bash,
    _run_code,
    _truncate,
    _write_code,
    _STDOUT_LIMIT,
)


@pytest.fixture
def work_dir(tmp_path):
    return str(tmp_path)


def test_write_code(work_dir):
    result = _write_code("test.py", "print('hello')", work_dir)
    assert result["status"] == "written"
    assert result["lines"] == 1
    assert Path(result["path"]).read_text() == "print('hello')"


def test_write_code_nested(work_dir):
    result = _write_code("sub/test.py", "x = 1", work_dir)
    assert result["status"] == "written"
    assert Path(result["path"]).exists()


def test_run_code_success(work_dir):
    _write_code("hello.py", "print('hello world')", work_dir)
    result = _run_code("hello.py", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "hello world" in result["stdout"]


def test_run_code_error(work_dir):
    _write_code("err.py", "raise ValueError('test error')", work_dir)
    result = _run_code("err.py", work_dir, timeout=10)
    assert result["exit_code"] != 0
    assert result["status"] == "failed"


def test_run_code_not_found(work_dir):
    result = _run_code("nonexistent.py", work_dir, timeout=10)
    assert "error" in result


def test_run_bash_success(work_dir):
    result = _run_bash("echo hello", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


def test_run_bash_python(work_dir):
    result = _run_bash("python3 -c 'print(1+1)'", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "2" in result["stdout"]


def test_run_bash_failure(work_dir):
    result = _run_bash("exit 1", work_dir, timeout=10)
    assert result["exit_code"] == 1


def test_run_bash_uses_container_when_env_set(work_dir, monkeypatch):
    """When ARI_CONTAINER_IMAGE is set, _run_bash must delegate to
    ari.container.run_shell_in_container so commands execute inside the
    configured container — not on the bare host.

    Regression: hpc-skill used to own run_bash with this behavior; after
    moving run_bash to coding-skill, the container-wrap path must stay.
    """
    import subprocess as _sp
    from src import server as _srv

    calls = {"container": 0, "bare": 0}

    def _fake_run_shell(cfg, cmd, *, cwd=None, timeout=60):
        calls["container"] += 1
        return _sp.CompletedProcess(
            args=cmd, returncode=0, stdout="inside-container\n", stderr=""
        )

    def _fake_subprocess_run(*a, **k):
        calls["bare"] += 1
        return _sp.CompletedProcess(args="", returncode=0, stdout="bare\n", stderr="")

    monkeypatch.setenv("ARI_CONTAINER_IMAGE", "ghcr.io/example/img:latest")
    monkeypatch.setenv("ARI_CONTAINER_MODE", "singularity")
    # Patch container helpers at their source module so the local import
    # inside _run_bash picks up the fakes.
    import ari.container as _ct
    monkeypatch.setattr(_ct, "run_shell_in_container", _fake_run_shell)
    monkeypatch.setattr(_srv.subprocess, "run", _fake_subprocess_run)

    result = _srv._run_bash("echo hi", work_dir, timeout=5)
    assert result["exit_code"] == 0
    assert calls["container"] == 1, "container-wrapped path must be taken"
    assert calls["bare"] == 0, "bare subprocess.run must not be used when ARI_CONTAINER_IMAGE is set"
    assert "inside-container" in result["stdout"]


def test_run_bash_falls_back_to_host_without_env(work_dir, monkeypatch):
    """Without ARI_CONTAINER_IMAGE, _run_bash must execute directly on the host."""
    monkeypatch.delenv("ARI_CONTAINER_IMAGE", raising=False)
    result = _run_bash("echo host-ok", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "host-ok" in result["stdout"]


def test_truncate_short_text():
    text, truncated = _truncate("hello", 100)
    assert text == "hello"
    assert truncated is False


def test_truncate_long_text_marker():
    long_text = "a" * 5000
    text, truncated = _truncate(long_text, 1000)
    assert truncated is True
    assert "chars truncated" in text
    assert "read_file" in text  # marker hints at the recovery workflow
    # Head and tail are both preserved
    assert text.startswith("a" * 100)
    assert text.endswith("a" * 100)


def test_run_code_truncation_flag(work_dir):
    # Generate stdout larger than _STDOUT_LIMIT
    code = f"print('x' * {_STDOUT_LIMIT * 2})"
    _write_code("big.py", code, work_dir)
    result = _run_code("big.py", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert result["truncated"] is True
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is False
    assert "chars truncated" in result["stdout"]


def test_run_code_no_truncation_flag(work_dir):
    _write_code("small.py", "print('hi')", work_dir)
    result = _run_code("small.py", work_dir, timeout=10)
    assert result["truncated"] is False
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False


def test_read_file_relative(work_dir):
    _write_code("hello.txt", "hello world", work_dir)
    result = _read_file("hello.txt", work_dir, offset=0, limit=8000)
    assert "error" not in result
    assert result["content"] == "hello world"
    assert result["total_chars"] == 11
    assert result["truncated"] is False
    assert result["next_offset"] is None


def test_read_file_absolute(work_dir):
    p = Path(work_dir) / "abs.txt"
    p.write_text("absolute content")
    result = _read_file(str(p), work_dir, offset=0, limit=8000)
    assert result["content"] == "absolute content"


def test_read_file_pagination(work_dir):
    body = "abcdefghij" * 100  # 1000 chars
    _write_code("page.txt", body, work_dir)
    first = _read_file("page.txt", work_dir, offset=0, limit=400)
    assert first["returned_chars"] == 400
    assert first["truncated"] is True
    assert first["next_offset"] == 400
    second = _read_file("page.txt", work_dir, offset=first["next_offset"], limit=400)
    assert second["returned_chars"] == 400
    assert second["next_offset"] == 800
    third = _read_file("page.txt", work_dir, offset=second["next_offset"], limit=400)
    assert third["returned_chars"] == 200
    assert third["truncated"] is False
    assert third["next_offset"] is None
    # Concatenation reproduces the full body
    assert first["content"] + second["content"] + third["content"] == body


def test_read_file_not_found(work_dir):
    result = _read_file("missing.txt", work_dir, offset=0, limit=8000)
    assert "error" in result


def test_read_file_redirect_workflow(work_dir):
    """Round-trip: produce a large stdout via run_bash redirect, then read via read_file."""
    big_payload = "z" * (_STDOUT_LIMIT * 3)
    _write_code("emit.py", f"print('{big_payload}')", work_dir)
    # Use run_bash to redirect output to a file (the truncation-recovery workflow)
    redirect = _run_bash("python3 emit.py > out.log 2>&1", work_dir, timeout=10)
    assert redirect["exit_code"] == 0
    # Now read the full content via read_file
    full = _read_file("out.log", work_dir, offset=0, limit=_STDOUT_LIMIT * 4)
    assert "error" not in full
    assert big_payload in full["content"]
