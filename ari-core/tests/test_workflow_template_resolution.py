"""Regression tests for workflow.yaml template variable resolution.

The pipeline's :func:`_resolve_templates` is a regex-based dot-notation
substitutor (NOT Jinja2). Earlier v0.7 work-in-progress mistakenly used
``{{ launch_config.ors.foo | default(bar) }}`` syntax in workflow.yaml,
which the regex passes through verbatim — a critical bug. These tests
verify the templating contract: ``launch_config`` is exposed under the
expected key, and dot-notation references resolve correctly.
"""

from __future__ import annotations

from ari.pipeline import _resolve_templates


def test_resolve_templates_supports_dot_notation():
    vars_ = {
        "launch_config": {
            "ors": {
                "iterative_agent": True,
                "replicator_time_limit_sec": 43200,
            },
        },
    }
    assert (
        _resolve_templates("{{launch_config.ors.iterative_agent}}", vars_) == "True"
    )
    assert (
        _resolve_templates(
            "{{launch_config.ors.replicator_time_limit_sec}}", vars_
        )
        == "43200"
    )


def test_resolve_templates_does_not_support_jinja_filters():
    """Documents the constraint: ``| default()`` is not supported.

    If we ever switch to Jinja2, this test breaks intentionally as a
    forcing function to update workflow.yaml syntax cluster-wide.
    """
    vars_ = {"a": {"b": 1}}
    # Filter syntax is treated as part of the dot-notation key and fails to
    # resolve, leaving the literal in place.
    out = _resolve_templates("{{ a.b | default(2) }}", vars_)
    assert out == "{{ a.b | default(2) }}", (
        "if Jinja2 filters are now supported, update workflow.yaml stages "
        "and remove the env-var fallback paths in build_reproduce_sh / "
        "grade_with_simplejudge"
    )


def test_resolve_templates_unresolved_left_in_place():
    """Missing keys leave the template literal in place (regex behavior).

    This is why workflow.yaml uses sentinel values (0 / "") with MCP-side
    defaults rather than ``| default(...)`` filters."""
    vars_ = {"launch_config": {}}
    assert (
        _resolve_templates("{{launch_config.ors.iterative_agent}}", vars_)
        == "{{launch_config.ors.iterative_agent}}"
    )
