"""Shared AST/text scanners for the architecture-boundary guards (subtask 018).

Test-only helper. The leading underscore keeps it out of pytest collection
(``python_files`` defaults to ``test_*.py``). The boundary-guard modules import
from here instead of each re-implementing an ``ari.*`` import scanner
(report ``003_dependency_boundary_report.md`` + subtask 018 §7 P2).

Everything here only *reads* source files with ``ast.parse`` / text; nothing
imports a skill ``src/server.py`` (the single-process hazard documented in the
repo-root ``pytest.ini``). Standard library only (``ast`` / ``pathlib``) — no new
dependency is added (subtask 018 §11).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator


def repo_root() -> Path:
    """Repo root. This file lives at ``ari-core/tests/_arch_boundaries.py``."""
    return Path(__file__).resolve().parents[2]


def core_root() -> Path:
    """The ``ari`` package root (``ari-core/ari``)."""
    return repo_root() / "ari-core" / "ari"


def iter_py(root: Path) -> Iterator[Path]:
    """Yield every ``*.py`` file under *root* (sorted, files only)."""
    for p in sorted(root.rglob("*.py")):
        if p.is_file():
            yield p


def rel(path: Path) -> str:
    """POSIX path relative to the repo root, for stable failure messages."""
    return path.resolve().relative_to(repo_root()).as_posix()


def imports(path: Path) -> list[tuple[int, str]]:
    """Every dotted import target in *path* with its 1-based line number.

    Captures both ``import a.b.c`` (target ``a.b.c``) and ``from a.b import x``
    (target ``a.b``). Purely relative imports (``from . import x``) carry no
    cross-package boundary meaning and are skipped. Unparseable files yield ``[]``.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                continue  # ``from . import x`` — relative, no dotted target
            if node.module:
                out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
    return out


def ari_imports(path: Path) -> list[tuple[int, str]]:
    """``imports()`` filtered to ARI targets: ``ari`` / ``ari.*`` / ``ari_skill*``.

    Mirrors ``test_public_api_boundary._ari_imports`` and additionally surfaces
    ``ari_skill_*`` targets (needed by the B2 core↛skill guard).
    """
    out: list[tuple[int, str]] = []
    for lineno, mod in imports(path):
        if mod == "ari" or mod.startswith("ari.") or mod.startswith("ari_skill"):
            out.append((lineno, mod))
    return out


def top_package(mod: str) -> str:
    """First dotted segment of a module path (``ari.viz.x`` -> ``ari``)."""
    return mod.split(".", 1)[0]


def matches_prefix(mod: str, prefixes: tuple[str, ...]) -> bool:
    """True if *mod* equals, or is a submodule of, any prefix in *prefixes*."""
    return any(mod == p or mod.startswith(p + ".") for p in prefixes)


def in_except_importerror(lines: list[str], lineno: int) -> bool:
    """Heuristic: is the import at 1-based *lineno* an ``except ...``-block shim?

    Mirrors the fallback detection in ``test_skill_public_contract.py``: an import
    whose closest preceding non-blank line opens an ``except`` handler is a
    sanctioned compatibility fallback (public-first, private-on-older-cores), not a
    hard dependency.
    """
    i = lineno - 2  # 0-based index of the line immediately above the import
    while i >= 0 and not lines[i].strip():
        i -= 1
    return i >= 0 and lines[i].strip().startswith("except")
