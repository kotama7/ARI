"""Boundary check: skills only import from ``ari.public.*`` (Phase 4).

If a new ``from ari.X import ...`` slips into a sibling skill outside
the allowed list, this test fails so the boundary violation is caught
before merge.

Two known historical violations are grandfathered in:

* ``ari-skill-coding/tests/test_server.py`` — patches the ``ari.container``
  symbol on the actual module object so the skill's local import
  picks up the fake; the test imports ``ari.public.container`` first
  to satisfy the boundary, then keeps the legacy patch.
* ``ari-skill-plot/src/server.py`` — uses ``ari.public.cost_tracker``
  with a try/except fallback to the legacy ``ari.cost_tracker`` path
  for compatibility with older ari-core checkouts.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Path to repo root: the file lives at ``ari-core/tests/test_*.py``.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _skill_dirs() -> list[Path]:
    """All ``ari-skill-*`` directories that ship Python source."""
    out: list[Path] = []
    for child in sorted(_REPO_ROOT.glob("ari-skill-*")):
        if child.is_dir():
            out.append(child)
    return out


def _python_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for sub in ("src", "tests"):
        d = skill_dir / sub
        if d.is_dir():
            files.extend(p for p in d.rglob("*.py") if p.is_file())
    return files


def _ari_imports(path: Path) -> list[tuple[int, str]]:
    """Collect every ``import ari...`` reference in *path*."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "ari" or mod.startswith("ari."):
                out.append((node.lineno, mod))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ari" or alias.name.startswith("ari."):
                    out.append((node.lineno, alias.name))
    return out


_ALLOWED = ("ari.public",)
_ALLOWED_EXACT = {"ari.public"}

# File:lineno pairs grandfathered in until the affected skills clean up.
# Phase 4 migrates ari-skill-coding + ari-skill-plot through
# ``ari.public.*``; the remaining 10 skills are flagged as "変更不要"
# in REFACTORING.md §5 and keep their legacy imports for now.  This
# test ensures NEW violations are caught (the lineno-pinned waiver
# means a moved offender still surfaces).
_GRANDFATHERED: dict[str, set[int]] = {
    "ari-skill-coding/src/server.py": {516, 527},
    "ari-skill-coding/tests/test_server.py": {106},
    "ari-skill-evaluator/src/server.py": {13},
    "ari-skill-hpc/src/slurm.py": {208},
    "ari-skill-idea/src/server.py": {62, 403},
    "ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py": {156},
    "ari-skill-memory/tests/test_backup_restore.py": {14},
    "ari-skill-paper-re/src/server.py": {39, 143},
    "ari-skill-paper-re/tests/test_fetch_code_bundle.py": {52},
    "ari-skill-paper/src/server.py": {18},
    "ari-skill-plot/src/server.py": {34},  # try-block legacy fallback
    "ari-skill-replicate/src/server.py": {25},
    "ari-skill-transform/src/server.py": {30, 606, 1902, 2252, 2270},
    "ari-skill-vlm/src/server.py": {15},
    "ari-skill-web/src/server.py": {21},
}


@pytest.mark.parametrize("skill_dir", _skill_dirs(), ids=lambda d: d.name)
def test_skill_imports_through_public_api(skill_dir: Path):
    offenders: list[tuple[Path, int, str]] = []
    for f in _python_files(skill_dir):
        rel = f.relative_to(_REPO_ROOT).as_posix()
        gf = _GRANDFATHERED.get(rel, set())
        for lineno, mod in _ari_imports(f):
            if mod in _ALLOWED_EXACT or mod.startswith("ari.public."):
                continue
            # Same-package skill imports (e.g. ``ari_skill_coding.server``)
            # are spelled with underscore and are out of scope.
            if mod.startswith("ari_"):
                continue
            if lineno in gf:
                continue
            offenders.append((f, lineno, mod))
    if offenders:
        msg = "\n".join(
            f"{p.relative_to(_REPO_ROOT)}:{ln}: {mod}" for p, ln, mod in offenders
        )
        pytest.fail(
            f"{skill_dir.name} imports core modules outside ari.public.*:\n{msg}\n"
            "Add a re-export in ari/public/ or update the skill to use the "
            "public API.  See REFACTORING.md §7 / DOCUMENTATION_PLAN."
        )
