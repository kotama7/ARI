"""The v2 search loop hides tools that a 20-step budget cannot afford.

They are SUPPRESSED, not deleted from the MCP servers, so other phases and other
users of ARI are unaffected. Two things must hold together: the tools are gone
from the loop, and the prompt stops telling the agent to call one of them —
otherwise the instruction itself burns a step on a tool that is not there.
"""
import os

import pytest

from ari.agent.loop import v2_suppressed_tools


def test_nothing_is_hidden_unless_asked_for(monkeypatch):
    """Opt-in, not opt-out.

    Suppression is not a local trim: it also rewrites the prompt's finish
    condition and changes the evidence path a run is scored through, so a run
    that never mentions it must get every tool.
    """
    monkeypatch.delenv("ARI_V2_SUPPRESS_TOOLS", raising=False)
    assert v2_suppressed_tools() == set()


def test_the_three_v1_tools_are_hidden_when_enabled(monkeypatch):
    monkeypatch.setenv("ARI_V2_SUPPRESS_TOOLS", "1")
    assert v2_suppressed_tools() == {
        "describe_environment", "run_code", "emit_results"}


def test_run_bash_and_write_code_are_never_suppressed(monkeypatch):
    """Suppressing the only execution or edit path would break the loop."""
    monkeypatch.setenv("ARI_V2_SUPPRESS_TOOLS", "1")
    hidden = v2_suppressed_tools()
    for essential in ("run_bash", "write_code", "read_file"):
        assert essential not in hidden


def _system_prompt_text() -> str:
    from pathlib import Path
    import ari.prompts as _p

    return (Path(_p.__file__).parent / "agent" / "system.md").read_text()


def test_the_prompt_sentence_the_patch_targets_still_exists():
    """The replacement is text-exact, so a prompt edit must fail loudly here.

    The earlier version of this guard named the `describe_environment`
    sentence, which has since been reworded away; pinning one sentence made
    the guard fail for a prompt edit that was harmless while saying nothing
    about the one that is not. It now names the sentence the patch actually
    targets: the finish condition. If that moves and the replacement is not
    updated, the patch no-ops and the agent is left unable to stop.
    """
    src = _system_prompt_text()
    assert (
        "Do not manually write or copy `results.json`, and do not "
        "finish until `emit_results` reports "
        "`scientifically_admissible=true`."
    ) in src, (
        "the sentence the suppression patch rewrites has moved; update "
        "loop.py's replacement or a suppressed emit_results leaves the agent "
        "with a finish condition it cannot satisfy")


def _finish_conditions(text: str) -> list[str]:
    """The text right after each 'do not finish until', lower-cased."""
    return [tail[:200] for tail in text.lower().split("do not finish until")[1:]]


def test_the_patch_removes_the_unsatisfiable_finish_condition(monkeypatch):
    """Whatever is hidden must not be what the prompt demands before stopping.

    This is the property the text-exact guard protects, stated so it survives
    rewording. The RAW template legitimately still names `emit_results` — the
    rewrite happens at render time — so the check runs on the patched text,
    which is what the model is actually given.

    The flag is set explicitly: with suppression off (the default) the loop
    below has nothing to iterate and the test would pass without checking
    anything.
    """
    from ari.agent.loop import patch_prompt_for_suppressed_tools

    monkeypatch.setenv("ARI_V2_SUPPRESS_TOOLS", "1")
    raw = _system_prompt_text()
    assert any("emit_results" in c for c in _finish_conditions(raw)), (
        "precondition for this test: the raw prompt gates finishing on "
        "emit_results, which is why the patch exists")

    patched = patch_prompt_for_suppressed_tools(raw)
    for name in v2_suppressed_tools():
        for condition in _finish_conditions(patched):
            assert name not in condition, (
                f"the rendered prompt still makes the suppressed tool {name!r} "
                f"a precondition for finishing; the loop hides it, so the "
                f"agent could never satisfy it")


def test_the_patch_is_a_no_op_by_default(monkeypatch):
    # Default: every tool is offered, so the finish condition is satisfiable
    # and the prompt must reach the model exactly as written. This is also the
    # guarantee that a run which never mentions suppression is unaffected.
    from ari.agent.loop import patch_prompt_for_suppressed_tools

    monkeypatch.delenv("ARI_V2_SUPPRESS_TOOLS", raising=False)
    raw = _system_prompt_text()
    assert patch_prompt_for_suppressed_tools(raw) == raw
