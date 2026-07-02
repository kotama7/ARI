"""Prompt snapshot tests (subtask 042) — auto-discovered raw + rendered snapshots.

Complements the hand-maintained ``sha256`` pin in ``test_prompt_extraction.py``
(kept as-is): this module *discovers* every ``ari/prompts/**/*.md`` template
automatically, so a newly-added or deleted prompt file that is not re-blessed
fails the suite. It additionally pins the *rendered* output
(``str.format`` over fixture kwargs copied from the real call sites) and the
placeholder set of each template.

Re-bless intentional changes with::

    ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-core/tests/test_prompt_snapshots.py -q

then re-run *without* the flag to confirm green (a clean ``git diff`` on the
goldens means nothing drifted).

Design notes grounded in the current tree:

- Read/compare as **bytes** (``Path.read_bytes``); no newline translation. Some
  templates end without a trailing newline (``pipeline/keyword_librarian.md``)
  and some with one (``evaluator/extract_metrics.md``) — the snapshot preserves
  each exactly.
- ``orchestrator/lineage_decision.md`` and ``orchestrator/root_idea_selector.md``
  embed literal JSON braces (e.g. ``{"action": ...}``) that ``str.Formatter``
  reads as pseudo-fields. Their real call sites load them **raw** and never call
  ``.format`` (``lineage_decision.py:293``, ``root_idea_selector.py:63``), so
  ``FIXTURE_KWARGS`` maps them to ``None`` and their rendered snapshot equals the
  raw template.
"""
from __future__ import annotations

import os
import string
from pathlib import Path

import pytest

from ari.prompts import FilesystemPromptLoader, package_prompts_root

_UPDATE_ENV = "ARI_UPDATE_PROMPT_SNAPSHOTS"
_SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "prompts"


def _updating() -> bool:
    return os.environ.get(_UPDATE_ENV) == "1"


def _assert_snapshot(path: Path, value: bytes) -> None:
    """Compare *value* to the golden at *path*, or write it when updating.

    Bytes in, bytes out — no newline translation, no encoding guesswork.
    """
    if _updating():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return
    assert path.exists(), (
        f"missing snapshot golden: {path}\n"
        f"run with {_UPDATE_ENV}=1 to create it."
    )
    expected = path.read_bytes()
    assert value == expected, (
        f"snapshot drift for {path}.\n"
        f"if the change is intentional, re-bless with {_UPDATE_ENV}=1."
    )


def _discover_keys(root: Path) -> list[str]:
    """Loader keys for every ``.md`` under *root*, excluding ``README.md``."""
    return sorted(
        p.relative_to(root).with_suffix("").as_posix()
        for p in root.glob("**/*.md")
        if p.name != "README.md"
    )


_KEYS = _discover_keys(package_prompts_root())


# ``FIXTURE_KWARGS`` — kwargs each key's real call site passes to ``str.format``
# (copied from the §5 call-site table of subtask 042). ``None`` means the call
# site loads the template raw and never formats it (the two JSON-schema
# orchestrator prompts above), in which case the rendered snapshot == raw.
FIXTURE_KWARGS: dict[str, dict[str, object] | None] = {
    "agent/system": {
        "tool_desc": "<tool_desc>",
        "memory_rules": "<memory_rules>",
        "extra": "<extra>",
    },
    "evaluator/extract_metrics": {},
    "evaluator/peer_review": {"axes_block": "<axes_block>"},
    "orchestrator/bfts_expand": {
        "goal_line": "<goal_line>",
        "parent_id_short": "<parent_id_short>",
        "parent_depth": "<parent_depth>",
        "parent_status": "<parent_status>",
        "depth_note": "<depth_note>",
        "budget_note": "<budget_note>",
        "parent_metrics_json": "<parent_metrics_json>",
        "parent_summary": "<parent_summary>",
        "sci_note": "<sci_note>",
        "idea_block": "<idea_block>",
        "parent_report_block": "<parent_report_block>",
        "siblings_block": "<siblings_block>",
        "ancestors_block": "<ancestors_block>",
        "existing_block": "<existing_block>",
        "diversity_block": "<diversity_block>",
    },
    "orchestrator/bfts_expand_select": {
        "experiment_goal": "<experiment_goal>",
        "candidates": "<candidates>",
    },
    "orchestrator/bfts_select": {
        "experiment_goal": "<experiment_goal>",
        "memory_context": "<memory_context>",
        "candidates": "<candidates>",
    },
    "orchestrator/lineage_decision": None,
    "orchestrator/root_idea_selector": None,
    "pipeline/keyword_librarian": {},
    "viz/wizard_chat_goal": {},
    "viz/wizard_generate_config": {"goal": "<goal>"},
}


# ``EXPECTED_FIELDS`` — the exact placeholder set ``string.Formatter().parse``
# yields for each template today. The two orchestrator entries carry pseudo
# "fields" that are actually literal JSON braces in the prompt body; they are
# pinned deliberately so a change to the JSON output schema is caught too.
EXPECTED_FIELDS: dict[str, frozenset[str]] = {
    "agent/system": frozenset({"tool_desc", "memory_rules", "extra"}),
    "evaluator/extract_metrics": frozenset(),
    "evaluator/peer_review": frozenset({"axes_block"}),
    "orchestrator/bfts_expand": frozenset({
        "goal_line", "parent_id_short", "parent_depth", "parent_status",
        "depth_note", "budget_note", "parent_metrics_json", "parent_summary",
        "sci_note", "idea_block", "parent_report_block", "siblings_block",
        "ancestors_block", "existing_block", "diversity_block",
    }),
    "orchestrator/bfts_expand_select": frozenset({"experiment_goal", "candidates"}),
    "orchestrator/bfts_select": frozenset(
        {"experiment_goal", "memory_context", "candidates"}
    ),
    "orchestrator/lineage_decision": frozenset({'"action"'}),
    "orchestrator/root_idea_selector": frozenset({'"chosen_index"'}),
    "pipeline/keyword_librarian": frozenset(),
    "viz/wizard_chat_goal": frozenset(),
    "viz/wizard_generate_config": frozenset({"goal"}),
}


def _fields(template: str) -> frozenset[str]:
    return frozenset(
        name for _, name, _, _ in string.Formatter().parse(template) if name is not None
    )


def _render(key: str, template: str) -> str:
    kwargs = FIXTURE_KWARGS[key]
    if kwargs is None:  # loaded raw at the call site; no str.format
        return template
    return template.format(**kwargs)


def test_prompts_discovered():
    """Guard against a broken glob silently zero-parametrizing everything."""
    assert _KEYS, f"no prompt templates discovered under {package_prompts_root()}"


def test_all_prompts_have_snapshots():
    """Every discovered template has a raw + rendered golden, and vice versa."""
    if _updating():
        pytest.skip(f"{_UPDATE_ENV}=1: goldens are being (re)written")
    raw = sorted(
        p.relative_to(_SNAP_DIR).with_suffix("").as_posix()
        for p in _SNAP_DIR.glob("**/*.md")
    )
    suffix = ".rendered.txt"
    rendered = sorted(
        p.relative_to(_SNAP_DIR).as_posix()[: -len(suffix)]
        for p in _SNAP_DIR.glob("**/*" + suffix)
    )
    assert _KEYS == raw, f"template keys {_KEYS} != raw goldens {raw}"
    assert _KEYS == rendered, f"template keys {_KEYS} != rendered goldens {rendered}"


@pytest.mark.parametrize("key", _KEYS)
def test_prompt_metadata_declared(key):
    """Every discovered key must have FIXTURE_KWARGS + EXPECTED_FIELDS entries."""
    assert key in FIXTURE_KWARGS, f"add FIXTURE_KWARGS[{key!r}] (new prompt?)"
    assert key in EXPECTED_FIELDS, f"add EXPECTED_FIELDS[{key!r}] (new prompt?)"


@pytest.mark.parametrize("key", _KEYS)
def test_prompt_raw_snapshot(key):
    template_path = package_prompts_root() / f"{key}.md"
    _assert_snapshot(_SNAP_DIR / f"{key}.md", template_path.read_bytes())


@pytest.mark.parametrize("key", _KEYS)
def test_prompt_placeholders(key):
    template = FilesystemPromptLoader().load(key)
    assert _fields(template) == EXPECTED_FIELDS[key], (
        f"placeholder set for '{key}' changed; update EXPECTED_FIELDS + call site."
    )


@pytest.mark.parametrize("key", _KEYS)
def test_prompt_rendered_snapshot(key):
    template = FilesystemPromptLoader().load(key)
    rendered = _render(key, template)
    _assert_snapshot(_SNAP_DIR / f"{key}.rendered.txt", rendered.encode("utf-8"))
