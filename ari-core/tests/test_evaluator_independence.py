"""B5 guard (report ``003`` §7): the evaluator stays independent of CLI / dashboard
/ file-layout, and its LLM calls should route through ``LLMClient``.

Two cases:

* Forbidden-import rule — ``ari/evaluator/**`` must not import ``ari.cli``,
  ``ari.viz``, ``ari.paths``, or ``ari.checkpoint`` (except-``ImportError`` compat
  shims are ignored). PASSES today.
* Model-backend leak — ``ari/evaluator/llm_evaluator.py`` imports ``litellm``
  directly (``:24``) and calls ``litellm.acompletion`` (``:585``), bypassing
  ``LLMClient`` / ``resolve_litellm_model``. A live B5/B6 violation fixed by
  subtask 008/009, so it is ``xfail(strict=False)`` here.
"""
import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest  # noqa: E402

from _arch_boundaries import (  # noqa: E402
    core_root,
    imports,
    in_except_importerror,
    iter_py,
    matches_prefix,
    rel,
)

_EVALUATOR_DIR = "evaluator"
_FORBIDDEN = ("ari.cli", "ari.viz", "ari.paths", "ari.checkpoint")


def _evaluator_files() -> list[Path]:
    return list(iter_py(core_root() / _EVALUATOR_DIR))


def test_evaluator_independent_of_cli_viz_and_layout():
    offenders: list[str] = []
    for path in _evaluator_files():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for lineno, mod in imports(path):
            if not matches_prefix(mod, _FORBIDDEN):
                continue
            # An ``except ImportError`` fallback is a sanctioned compat shim, not a
            # hard dependency — ignore it (there are none in the evaluator today).
            if in_except_importerror(lines, lineno):
                continue
            offenders.append(f"{rel(path)}:{lineno}: {mod}")
    assert not offenders, (
        "ari/evaluator must not import CLI / dashboard / file-layout modules "
        "(report 003 §7 B5):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "B5/B6 provider leak: ari/evaluator/llm_evaluator.py imports litellm directly "
        "and calls litellm.acompletion, bypassing LLMClient/resolve_litellm_model — "
        "fixed by subtask 008/009; remove this marker when the evaluator routes "
        "through the model backend."
    ),
)
def test_evaluator_does_not_call_litellm_directly():
    """Desired end-state: the evaluator makes no direct ``litellm`` import. Currently
    violated -> xfailed; auto-XPASSes when subtask 008/009 lands."""
    offenders: list[str] = []
    for path in _evaluator_files():
        for lineno, mod in imports(path):
            if mod == "litellm" or mod.startswith("litellm."):
                offenders.append(f"{rel(path)}:{lineno}: {mod}")
    assert not offenders, (
        "ari/evaluator imports litellm directly (should route via LLMClient):\n  "
        + "\n  ".join(offenders)
    )
