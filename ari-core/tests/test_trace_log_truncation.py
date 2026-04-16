"""Tests for trace_log argument-preview truncation in ari/agent/loop.py.

The bug: tool call arguments displayed in the GUI's trace_log were truncated
to 500 characters, which mid-cut JSON payloads like generate_ideas() with
multi-paper abstracts (e.g. "...quantum pr" with no closing brace), making
the displayed log unreadable.

The fix raises the per-call argument preview cap to 4000 characters so that
typical generate_ideas / search payloads fit in full, while still bounding
runaway pathological inputs.
"""
from __future__ import annotations

import inspect
import json
import re

import ari.agent.loop as agent_loop


def test_args_preview_cap_raised_to_4000():
    """Source-level guard: the trace_log argument preview limit must not regress
    below 4000 characters."""
    src = inspect.getsource(agent_loop)
    # Look for the specific assignment we patched.
    m = re.search(
        r"_args_preview\s*=\s*str\(_tc_args_by_name\.get\([^)]*\)\)\[:(\d+)\]",
        src,
    )
    assert m, "Expected `_args_preview = str(_tc_args_by_name.get(...))[:N]` in loop.py"
    cap = int(m.group(1))
    assert cap >= 4000, (
        f"_args_preview truncation cap regressed to {cap}; must remain >= 4000 so that "
        "typical generate_ideas() payloads (multi-paper abstracts) display in full"
    )


def test_args_preview_cap_not_500():
    """Explicit regression guard against the original 500-char cap."""
    src = inspect.getsource(agent_loop)
    assert (
        'str(_tc_args_by_name.get(r["name"], ""))[:500]' not in src
    ), (
        "Found legacy [:500] truncation for _args_preview — this regresses the "
        "fix that raised the cap so generate_ideas() arguments aren't cut mid-JSON"
    )


def test_args_preview_truncation_handles_realistic_generate_ideas_payload():
    """Behavioural sanity: a realistic generate_ideas payload (one paper with
    a typical-length abstract) must NOT be truncated by the active cap.
    """
    src = inspect.getsource(agent_loop)
    m = re.search(
        r"_args_preview\s*=\s*str\(_tc_args_by_name\.get\([^)]*\)\)\[:(\d+)\]",
        src,
    )
    assert m
    cap = int(m.group(1))

    # Reproduce the user's failing payload shape.
    payload = {
        "topic": "QCoder Benchmark",
        "papers": [
            {
                "title": (
                    "QCoder Benchmark: Bridging Language Generation and Quantum "
                    "Hardware through Simulator-Based Feedback"
                ),
                "abstract": (
                    "Large language models (LLMs) have increasingly been applied "
                    "to automatic programming code generation. This task can be "
                    "viewed as a language generation task that bridges natural "
                    "language, human knowledge, and programming logic. However, "
                    "it remains underexplored in domains that require interaction "
                    "with hardware devices, such as quantum programming where "
                    "circuits must be expressed using gate-level primitives and "
                    "validated against simulator feedback before deployment."
                ),
            }
        ],
    }
    serialised = str(payload)
    assert len(serialised) <= cap, (
        f"Cap {cap} is too small for a realistic generate_ideas payload "
        f"({len(serialised)} chars). Raise the cap or shrink the test fixture."
    )
    # And critically: the original 500-char cap would have truncated it.
    assert len(serialised) > 500, (
        "Test fixture must be larger than the legacy 500-char cap to be a "
        "meaningful regression check"
    )
