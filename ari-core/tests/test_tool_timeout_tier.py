"""MCP tool-call timeout tiering (ari.mcp.client._resolve_tool_timeout).

Regression guard: an LLM-heavy stage omitted from _SLOW_TOOLS silently inherits
the 300s default and times out under CLI-shim congestion (this is exactly what
happened to paper_refine — write_paper, already slow-tiered, never failed).
"""
from ari.mcp.client import (
    _resolve_tool_timeout,
    SLOW_TOOL_TIMEOUT,
    VERY_SLOW_TOOL_TIMEOUT,
    DEFAULT_TOOL_TIMEOUT,
)


def test_llm_and_compile_paper_stages_are_slow_tiered():
    # Every paper stage that does an internal LLM call OR a multi-pass latexmk
    # sequence must exceed the 300s default.
    for tool in ("write_paper_iterative", "paper_refine", "review_compiled_paper",
                 "compile_paper", "generate_ideas", "collect_references_iterative"):
        assert _resolve_tool_timeout(tool, {}) == SLOW_TOOL_TIMEOUT, tool


def test_plain_deterministic_tool_gets_default():
    # Pure string/dict tools (no LLM, no subprocess) keep the short default.
    for tool in ("link_paper_claims", "claim_evidence_hard_gate", "inject_code_availability"):
        assert _resolve_tool_timeout(tool, {}) == DEFAULT_TOOL_TIMEOUT, tool


def test_very_slow_sandbox_tools():
    assert _resolve_tool_timeout("build_reproduce_sh", {}) == VERY_SLOW_TOOL_TIMEOUT


def test_explicit_budget_overrides_with_buffer():
    assert _resolve_tool_timeout("run_reproduce", {"time_limit_sec": 100}) == 700
