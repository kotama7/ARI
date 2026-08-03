"""Bounded, shell-free LaTeX compiler built on ARI's execution contract."""

from __future__ import annotations

import hashlib
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ari.public.execution import (
    ExecutionLimitsV1,
    ExecutionRequestV1,
    WorkspaceRefV1,
    execute_local,
)
from ari.public.figures import FigureBatchV1
from ari.public.paper import (
    PaperArtifactV1,
    PaperCompileV1,
    canonical_paper_digest,
)


_FORBIDDEN_TEX = (
    re.compile(r"\\(?:immediate\s*)?write18\b", re.IGNORECASE),
    re.compile(r"\\(?:openin|openout|read|write)\b", re.IGNORECASE),
    re.compile(r"\\begin\{filecontents\*?\}", re.IGNORECASE),
    re.compile(r"\\(?:input|include)\s*\{", re.IGNORECASE),
)
_GRAPHIC = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_SAFE_MAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.tex$")


@dataclass(frozen=True)
class CompileOutcome:
    record: PaperCompileV1
    pdf_path: str | None
    bbl_path: str | None
    diagnostics: tuple[str, ...]


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _paper_artifact(
    *,
    workspace: WorkspaceRefV1,
    role: str,
    relative_path: str,
    media_type: str,
) -> PaperArtifactV1:
    payload = workspace.read_bytes(relative_path, max_bytes=256 * 1024 * 1024)
    return PaperArtifactV1(
        role=role,
        relative_path=relative_path,
        digest=_digest(payload),
        media_type=media_type,
        size_bytes=len(payload),
    )


def _binary(name: str) -> Path | None:
    resolved = shutil.which(name)
    if not resolved:
        return None
    path = Path(resolved).resolve(strict=True)
    # The public command name is fixed by this module; callers never supply an
    # executable path.  TeX distributions commonly install ``pdflatex`` as a
    # symlink to ``pdftex``, so checking the resolved basename would reject a
    # legitimate, allowlisted compiler.
    if not path.is_file():
        return None
    return path


def _environment_digest(binaries: tuple[Path, ...]) -> str:
    identities = []
    for path in binaries:
        identities.append(
            {
                "name": path.name,
                "path": str(path),
                "digest": _digest(path.read_bytes()),
            }
        )
    return canonical_paper_digest(
        {
            "binaries": identities,
            "platform": platform.platform(),
            "compiler_policy": "ari.paper-compiler/v1",
        }
    )


def _validate_tex(tex: str, allowed_graphics: set[str]) -> None:
    if len(tex.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("LaTeX source exceeds 16 MiB")
    for pattern in _FORBIDDEN_TEX:
        if pattern.search(tex):
            raise ValueError("LaTeX source requests forbidden file or process I/O")
    requested = set(_GRAPHIC.findall(tex))
    for value in requested:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or value not in allowed_graphics
        ):
            raise ValueError(f"LaTeX references an undeclared graphic: {value}")


def _stage_project(
    source: WorkspaceRefV1,
    target: WorkspaceRefV1,
    *,
    main_file: str,
    bib_file: str | None,
    figures: FigureBatchV1 | None,
) -> set[str]:
    tex_payload = source.read_bytes(main_file, max_bytes=16 * 1024 * 1024)
    try:
        tex = tex_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("LaTeX source must be UTF-8") from exc
    allowed_graphics: set[str] = set()
    if figures is not None:
        for manifest in figures.manifests:
            for artifact in manifest.artifacts:
                if artifact.role not in {"pdf", "png"}:
                    continue
                payload = source.read_bytes(
                    artifact.relative_path,
                    max_bytes=64 * 1024 * 1024,
                )
                if (
                    len(payload) != artifact.size_bytes
                    or _digest(payload) != artifact.digest
                ):
                    raise ValueError("figure bytes differ from FigureBatchV1")
                target.atomic_write_bytes(artifact.relative_path, payload)
                allowed_graphics.add(artifact.relative_path)
    _validate_tex(tex, allowed_graphics)
    target.atomic_write_bytes(main_file, tex_payload)
    if bib_file:
        target.atomic_write_bytes(
            bib_file,
            source.read_bytes(bib_file, max_bytes=16 * 1024 * 1024),
        )
    return allowed_graphics


def compile_project(
    *,
    workspace: WorkspaceRefV1,
    main_file: str,
    bib_file: str | None = "refs.bib",
    figures: FigureBatchV1 | None = None,
    output_pdf: str | None = None,
    output_bbl: str | None = None,
    timeout_seconds: int = 120,
) -> CompileOutcome:
    """Compile one declared project and retain complete logs in ``workspace``."""

    if not _SAFE_MAIN.fullmatch(main_file) or "/" in main_file:
        raise ValueError("main_file must be a safe root-level .tex filename")
    if bib_file is not None and bib_file != "refs.bib":
        raise ValueError("the compiler accepts only the canonical refs.bib")
    main_stem = main_file.removesuffix(".tex")
    output_pdf = output_pdf or f"{main_stem}.pdf"
    output_bbl = output_bbl or f"{main_stem}.bbl"
    tex_payload = workspace.read_bytes(main_file, max_bytes=16 * 1024 * 1024)
    try:
        tex_source = tex_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("LaTeX source must be UTF-8") from exc
    declared_graphics = {
        artifact.relative_path
        for manifest in (figures.manifests if figures is not None else ())
        for artifact in manifest.artifacts
        if artifact.role in {"pdf", "png"}
    }
    _validate_tex(tex_source, declared_graphics)
    pdflatex = _binary("pdflatex")
    bibtex = _binary("bibtex") if bib_file else None
    planned = [
        (
            "pdflatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            main_file,
        ),
    ]
    if bib_file:
        planned.append(("bibtex", main_stem))
    planned.extend(
        [
            (
                "pdflatex",
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                main_file,
            ),
            (
                "pdflatex",
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                main_file,
            ),
        ]
    )
    if pdflatex is None or (bib_file and bibtex is None):
        missing = "pdflatex" if pdflatex is None else "bibtex"
        log_base = f".ari-paper/compile/unavailable-{missing}"
        workspace.atomic_write_text(f"{log_base}.stdout.log", "")
        workspace.atomic_write_text(
            f"{log_base}.stderr.log",
            f"required compiler executable is unavailable: {missing}\n",
        )
        logs = (
            _paper_artifact(
                workspace=workspace,
                role="compile-stdout",
                relative_path=f"{log_base}.stdout.log",
                media_type="text/plain; charset=utf-8",
            ),
            _paper_artifact(
                workspace=workspace,
                role="compile-stderr",
                relative_path=f"{log_base}.stderr.log",
                media_type="text/plain; charset=utf-8",
            ),
        )
        record = PaperCompileV1.create(
            status="tool-unavailable",
            commands=tuple(planned),
            execution_identities=(),
            log_artifacts=logs,
            environment_digest=canonical_paper_digest(
                {"compiler_policy": "ari.paper-compiler/v1", "missing": missing}
            ),
        )
        return CompileOutcome(record, None, None, (f"{missing} unavailable",))

    assert pdflatex is not None
    binaries = (pdflatex,) + ((bibtex,) if bibtex is not None else ())
    with tempfile.TemporaryDirectory(prefix="ari-paper-compile-") as temp_text:
        temporary = WorkspaceRefV1(root=temp_text)
        _stage_project(
            workspace,
            temporary,
            main_file=main_file,
            bib_file=bib_file,
            figures=figures,
        )
        actual_commands: list[tuple[str, ...]] = []
        identities: list[str] = []
        logs: list[PaperArtifactV1] = []
        diagnostics: list[str] = []
        terminal_status = "completed"
        for index, planned_command in enumerate(planned, start=1):
            executable = pdflatex if planned_command[0] == "pdflatex" else bibtex
            assert executable is not None
            command = (str(executable), *planned_command[1:])
            request = ExecutionRequestV1(
                workspace=temporary,
                argv=list(command),
                timeout_seconds=timeout_seconds,
                environment={"SOURCE_DATE_EPOCH": "0", "TZ": "UTC"},
                limits=ExecutionLimitsV1(
                    cpu_seconds=timeout_seconds,
                    memory_bytes=2 * 1024 * 1024 * 1024,
                    max_processes=64,
                    max_output_bytes=128 * 1024 * 1024,
                ),
                network="inherit",
                request_id=f"paper-compile-{index:02d}",
            )
            result = execute_local(request)
            actual_commands.append(tuple(planned_command))
            identities.append(result.execution_identity)
            for artifact in result.artifacts:
                payload = temporary.read_bytes(
                    artifact.relative_path,
                    max_bytes=128 * 1024 * 1024,
                )
                suffix = "stdout" if artifact.logical_role == "stdout" else "stderr"
                destination = (
                    f".ari-paper/compile/{result.execution_identity.removeprefix('sha256:')}/"
                    f"pass-{index:02d}.{suffix}.log"
                )
                workspace.atomic_write_bytes(destination, payload)
                logs.append(
                    _paper_artifact(
                        workspace=workspace,
                        role=f"compile-{suffix}",
                        relative_path=destination,
                        media_type="text/plain; charset=utf-8",
                    )
                )
                if suffix == "stdout":
                    diagnostics.extend(
                        line
                        for line in payload.decode(
                            "utf-8", errors="replace"
                        ).splitlines()
                        if line.startswith("!")
                        or ("LaTeX Warning:" in line and "undefined" in line)
                    )
            if result.status != "completed":
                terminal_status = (
                    "timed-out" if result.status == "timed_out" else "failed"
                )
                break
        pdf_source = Path(temporary.root) / f"{main_stem}.pdf"
        pdf_artifact = None
        stored_pdf = None
        stored_bbl = None
        if (
            terminal_status == "completed"
            and pdf_source.is_file()
            and pdf_source.stat().st_size > 1024
        ):
            workspace.atomic_write_bytes(output_pdf, pdf_source.read_bytes())
            stored_pdf = output_pdf
            pdf_artifact = _paper_artifact(
                workspace=workspace,
                role="pdf",
                relative_path=output_pdf,
                media_type="application/pdf",
            )
            bbl_source = Path(temporary.root) / f"{main_stem}.bbl"
            if bbl_source.is_file():
                workspace.atomic_write_bytes(output_bbl, bbl_source.read_bytes())
                stored_bbl = output_bbl
        else:
            terminal_status = (
                "failed" if terminal_status == "completed" else terminal_status
            )

    record = PaperCompileV1.create(
        status=terminal_status,
        commands=tuple(actual_commands),
        execution_identities=tuple(identities),
        log_artifacts=tuple(logs),
        pdf_artifact=pdf_artifact,
        environment_digest=_environment_digest(binaries),
    )
    return CompileOutcome(
        record=record,
        pdf_path=stored_pdf,
        bbl_path=stored_bbl,
        diagnostics=tuple(diagnostics[-20:]),
    )


__all__ = ["CompileOutcome", "compile_project"]
