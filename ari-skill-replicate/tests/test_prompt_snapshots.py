"""Prompt snapshot tests for ari-skill-replicate (subtask 042).

Raw byte snapshots of the skill-local prompt templates under ``src/prompts/``.
Those templates are loaded via ad-hoc ``Path.read_text()`` in
``generator.py:64,77,93`` and ``auditor.py:130`` (not the ari-core loader), so
they have **no** other drift guard.

This module is deliberately self-contained (no ari-core / ``src`` import), so it
is safe under the shared multi-skill process used by ``scripts/run_all_tests.sh``.

Re-bless intentional edits with::

    ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-skill-replicate/tests/test_prompt_snapshots.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_UPDATE_ENV = "ARI_UPDATE_PROMPT_SNAPSHOTS"
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "src" / "prompts"
_SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "prompts"


def _assert_snapshot(path: Path, value: bytes) -> None:
    """Compare *value* to the golden at *path*, or write it when updating."""
    if os.environ.get(_UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return
    assert path.exists(), (
        f"missing snapshot golden: {path}\n"
        f"run with {_UPDATE_ENV}=1 to create it."
    )
    assert value == path.read_bytes(), (
        f"snapshot drift for {path}.\n"
        f"if the change is intentional, re-bless with {_UPDATE_ENV}=1."
    )


def _discover() -> list[str]:
    """``.md`` prompt basenames, excluding ``README.md`` and non-``.md`` files
    such as ``mpi_aggregate_skel.py`` (a code skeleton, not a prompt)."""
    return sorted(
        p.name for p in _PROMPTS_DIR.glob("*.md") if p.name != "README.md"
    )


_PROMPTS = _discover()


def test_prompts_discovered():
    assert _PROMPTS, f"no .md prompts found under {_PROMPTS_DIR}"


def test_all_prompts_have_snapshots():
    if os.environ.get(_UPDATE_ENV) == "1":
        pytest.skip(f"{_UPDATE_ENV}=1: goldens are being (re)written")
    goldens = sorted(p.name for p in _SNAP_DIR.glob("*.md"))
    assert _PROMPTS == goldens, f"prompts {_PROMPTS} != goldens {goldens}"


@pytest.mark.parametrize("name", _PROMPTS)
def test_prompt_raw_snapshot(name):
    _assert_snapshot(_SNAP_DIR / name, (_PROMPTS_DIR / name).read_bytes())
