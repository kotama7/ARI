from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ari.config import SkillConfig
from ari.mcp.connection import SkillConnection


def test_stdio_guard_drops_only_whitespace_stdout_records():
    child = (
        "import sys; "
        "print(''); print('   '); print('provider stdout diagnostic'); "
        "print('{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{}}'); "
        "print('diagnostic', file=sys.stderr)"
    )
    completed = subprocess.run(
        [sys.executable, "-m", "ari.mcp.stdio_guard", "--", sys.executable, "-c", child],
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stdout == '{"jsonrpc":"2.0","id":1,"result":{}}\n'
    assert completed.stderr == "provider stdout diagnostic\ndiagnostic\n"


def test_skill_connection_places_stdio_guard_before_provider(tmp_path, monkeypatch):
    entrypoint = tmp_path / "server.py"
    entrypoint.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("ARI_ROOT", str(tmp_path))
    skill = SkillConfig(
        name="guard-fixture",
        path=str(tmp_path),
        entrypoint="server.py",
        phase=["bfts"],
    )

    params = SkillConnection(skill)._server_params()
    assert params.command == SkillConnection._resolve_python(tmp_path)
    assert params.args[:3] == ["-m", "ari.mcp.stdio_guard", "--"]
    assert Path(params.args[-1]) == entrypoint
