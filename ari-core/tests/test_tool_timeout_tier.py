"""Manifest-driven MCP timeout and declared-budget contract tests."""

from __future__ import annotations

from pathlib import Path

from ari.mcp.client import (
    DEFAULT_TOOL_TIMEOUT,
    SLOW_TOOL_TIMEOUT,
    VERY_SLOW_TOOL_TIMEOUT,
    _resolve_tool_timeout,
)
from ari.skill_manifest import load_skill_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_timeout_class_is_name_independent():
    assert _resolve_tool_timeout({}, timeout_class="slow") == SLOW_TOOL_TIMEOUT
    assert _resolve_tool_timeout({}, timeout_class="very-slow") == VERY_SLOW_TOOL_TIMEOUT
    assert _resolve_tool_timeout({}, timeout_class="bounded") == DEFAULT_TOOL_TIMEOUT


def test_undeclared_argument_cannot_expand_outer_timeout():
    assert (
        _resolve_tool_timeout(
            {"time_limit_sec": 100},
            timeout_class="bounded",
        )
        == DEFAULT_TOOL_TIMEOUT
    )


def test_declared_budget_is_buffered_and_bounded():
    budget = {
        "argument": "time_limit_sec",
        "unit": "seconds",
        "overhead_seconds": 600,
        "maximum_seconds": 46_800,
    }
    assert (
        _resolve_tool_timeout(
            {"time_limit_sec": 100},
            timeout_class="very-slow",
            timeout_budget=budget,
        )
        == 700
    )
    assert (
        _resolve_tool_timeout(
            {"time_limit_sec": 100_000},
            timeout_class="very-slow",
            timeout_budget=budget,
        )
        == 46_800
    )


def test_every_canonical_tool_resolves_timeout_policy():
    manifests = sorted(REPO_ROOT.glob("ari-skill-*/skill.yaml"))
    assert manifests
    for path in manifests:
        manifest = load_skill_manifest(path)
        resolved = manifest.resolved_tools()
        assert len(resolved) == len(manifest.tools)
        for tool in resolved:
            assert tool.timeout_class in {
                "default",
                "bounded",
                "slow",
                "very-slow",
                "async",
            }, f"{path.parent.name}/{tool.name}"
