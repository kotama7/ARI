"""Tests for ari-skill-coding MCP server tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server import _write_code, _run_code, _run_bash


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
