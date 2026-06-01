"""Guard: skills import core only through the public contract (req 09).

Scans every ``ari-skill-*/src`` tree for production imports of ``ari.*`` and
fails if a skill reaches a PRIVATE core path instead of ``ari.public.*`` /
``ari.protocols.*`` / ``ari.mcp.*``.

A small allowlist holds the imports req 09 deliberately DEFERRED (each needs a
protocol design or signature-stability check before a public re-export — see
refactoring/notes/09_skill_public_contract.md). The allowlist is the live to-do
list: shrinking it (by adding the public re-export + migrating the skill) is the
follow-up. Imports inside an ``except ImportError:`` fallback are ignored — the
migrated call sites prefer the public path and fall back to the internal one only
on older cores, which is the sanctioned compatibility shim.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Private-core imports that are KNOWN and deferred (file-relative-to-repo : symbol).
# Shrinking this set is the req-09 §12 follow-up.
_ALLOWLIST = {
    ("ari-skill-idea/src/server.py", "ari.lineage"),
    ("ari-skill-paper-re/src/server.py", "ari.clone"),
    ("ari-skill-transform/src/server.py", "ari.orchestrator"),
    ("ari-skill-transform/src/server.py", "ari.publish"),
}

# ari.* paths considered part of the stable public contract.
_PUBLIC_PREFIXES = ("ari.public", "ari.protocols", "ari.mcp")

# Match an `ari` / `ari.x.y` module path, but NOT `ari_skill_*` (word boundary
# via the negative lookahead on `_`): the trailing (?![\w]) rejects `ari_...`.
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(ari(?:\.[A-Za-z0-9_]+)*)(?![\w])")


def _skill_src_files() -> list[Path]:
    out: list[Path] = []
    for skill in sorted(_REPO.glob("ari-skill-*")):
        src = skill / "src"
        if src.is_dir():
            out.extend(sorted(src.rglob("*.py")))
    return out


def _is_private(mod: str) -> bool:
    """True if ``mod`` (an ``ari.x.y`` dotted path) is a private core path.

    ``ari.public.*`` / ``ari.protocols.*`` / ``ari.mcp.*`` are the stable
    contract → public. Bare ``ari`` is handled by the caller (it inspects the
    imported symbol). Everything else under ``ari.`` is private.
    """
    if mod == "ari":
        return False  # caller inspects `from ari import <symbol>` separately
    return not any(mod == p or mod.startswith(p + ".") for p in _PUBLIC_PREFIXES)


def test_skills_use_public_contract():
    violations: list[str] = []
    for f in _skill_src_files():
        rel = f.relative_to(_REPO).as_posix()
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            mod = m.group(1)
            # `from ari import cost_tracker` — top-level symbol import. Only the
            # known-public symbols are allowed bare; everything else is private.
            if mod == "ari":
                sym = ""
                fm = re.match(r"^\s*from\s+ari\s+import\s+([A-Za-z0-9_]+)", line)
                if fm:
                    sym = fm.group(1)
                if sym in ("public", "protocols", "mcp"):
                    continue
                # Ignore the compatibility fallback inside `except ImportError:`.
                prev = lines[i - 1].strip() if i > 0 else ""
                if prev.startswith("except"):
                    continue
                violations.append(f"{rel}:{i+1}: bare `from ari import {sym}` (use ari.public)")
                continue
            if not _is_private(mod):
                continue
            # private ari.* path — allowed only if in the deferred allowlist OR a
            # fallback inside an `except ImportError:` block.
            prev = lines[i - 1].strip() if i > 0 else ""
            if prev.startswith("except"):
                continue
            top = ".".join(mod.split(".")[:2])  # e.g. ari.lineage, ari.orchestrator
            if (rel, top) in _ALLOWLIST:
                continue
            violations.append(f"{rel}:{i+1}: private import `{mod}` (expose via ari.public or add to allowlist)")

    assert not violations, (
        "Skills reaching private core internals (req 09 contract):\n  "
        + "\n  ".join(violations)
    )


def test_allowlist_entries_still_exist():
    """The deferred allowlist must not rot: every entry must still be a real
    private import in that file (else it should be removed from the allowlist)."""
    stale = []
    for rel, top in _ALLOWLIST:
        f = _REPO / rel
        if not f.is_file():
            stale.append(f"{rel} (file gone)")
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if f"from {top} import" not in text and f"import {top}" not in text:
            stale.append(f"{rel}:{top} (import gone — drop from allowlist)")
    assert not stale, "Stale req-09 allowlist entries:\n  " + "\n  ".join(stale)
