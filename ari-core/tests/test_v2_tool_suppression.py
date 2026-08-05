"""The v2 search loop hides tools that a 20-step budget cannot afford.

They are SUPPRESSED, not deleted from the MCP servers, so other phases and other
users of ARI are unaffected. Two things must hold together: the tools are gone
from the loop, and the prompt stops telling the agent to call one of them —
otherwise the instruction itself burns a step on a tool that is not there.
"""
import os

import pytest

from ari.agent.loop import v2_suppressed_tools


def test_the_three_v1_tools_are_hidden_by_default(monkeypatch):
    monkeypatch.delenv("ARI_KEEP_V1_TOOLS", raising=False)
    assert v2_suppressed_tools() == {
        "describe_environment", "run_code", "emit_results"}


def test_a_comparison_run_can_restore_them(monkeypatch):
    monkeypatch.setenv("ARI_KEEP_V1_TOOLS", "1")
    assert v2_suppressed_tools() == set()


def test_run_bash_and_write_code_are_never_suppressed(monkeypatch):
    """Suppressing the only execution or edit path would break the loop."""
    monkeypatch.delenv("ARI_KEEP_V1_TOOLS", raising=False)
    hidden = v2_suppressed_tools()
    for essential in ("run_bash", "write_code", "read_file"):
        assert essential not in hidden


def test_the_prompt_sentence_the_patch_targets_still_exists():
    """The replacement is text-exact, so a prompt edit must fail loudly here.

    If system.md is reworded and this assertion is not updated, the patch would
    silently no-op and the agent would keep being told to call a tool that has
    been taken away.
    """
    from pathlib import Path
    import ari.prompts as _p

    src = (Path(_p.__file__).parent / "agent" / "system.md").read_text()
    assert "If `describe_environment` is available, call it first;" in src, (
        "the sentence the suppression patch rewrites has moved; update "
        "loop.py's replacement or the agent will be told to call a hidden tool")
