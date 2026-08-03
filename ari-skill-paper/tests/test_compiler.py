"""Shell-free compiler policy, provenance, logs, and failure tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.public.execution import WorkspaceRefV1, record_completed_execution

from src import compiler


def _workspace(tmp_path: Path, tex: str) -> WorkspaceRefV1:
    workspace = WorkspaceRefV1(root=str(tmp_path))
    workspace.atomic_write_text("main.tex", tex)
    return workspace


def test_compiler_rejects_process_and_undeclared_file_access(tmp_path: Path):
    workspace = _workspace(
        tmp_path,
        r"\documentclass{article}\immediate\write18{touch owned}\begin{document}x\end{document}",
    )
    with pytest.raises(ValueError, match="forbidden"):
        compiler.compile_project(
            workspace=workspace,
            main_file="main.tex",
            bib_file=None,
        )

    workspace.atomic_write_text(
        "main.tex",
        r"\documentclass{article}\begin{document}\includegraphics{/etc/passwd}\end{document}",
    )
    with pytest.raises(ValueError, match="undeclared graphic"):
        compiler.compile_project(
            workspace=workspace,
            main_file="main.tex",
            bib_file=None,
        )


def test_missing_tool_is_typed_and_keeps_full_logs(monkeypatch, tmp_path: Path):
    workspace = _workspace(
        tmp_path,
        r"\documentclass{article}\begin{document}ok\end{document}",
    )
    monkeypatch.setattr(compiler, "_binary", lambda _name: None)
    outcome = compiler.compile_project(
        workspace=workspace,
        main_file="main.tex",
        bib_file=None,
    )
    assert outcome.record.status == "tool-unavailable"
    assert outcome.pdf_path is None
    assert {artifact.role for artifact in outcome.record.log_artifacts} == {
        "compile-stdout",
        "compile-stderr",
    }


def test_compile_uses_fixed_argv_and_execution_contract(monkeypatch, tmp_path: Path):
    workspace = _workspace(
        tmp_path,
        r"\documentclass{article}\begin{document}ok\end{document}",
    )
    executable = Path("/usr/bin/true")
    monkeypatch.setattr(compiler, "_binary", lambda _name: executable)
    requests = []

    def fake_execute(request):
        requests.append(request)
        request.workspace.atomic_write_bytes("main.pdf", b"%PDF" + b"x" * 2048)
        return record_completed_execution(
            request,
            stdout="complete log\n",
            stderr="",
            returncode=0,
            inputs_verified=True,
        )

    monkeypatch.setattr(compiler, "execute_local", fake_execute)
    outcome = compiler.compile_project(
        workspace=workspace,
        main_file="main.tex",
        bib_file=None,
    )
    assert outcome.record.status == "completed"
    assert outcome.pdf_path == "main.pdf"
    assert len(requests) == 3
    assert all(request.argv[1] == "-no-shell-escape" for request in requests)
    assert all(request.shell_command is None for request in requests)
    assert all(request.limits.max_processes == 64 for request in requests)
    assert len(outcome.record.log_artifacts) == 6
