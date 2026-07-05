"""B6 guard (report ``003`` §8): the model-backend layer ``ari/llm/**`` exposes the
LLM client + provider routing and must not depend "up" on the dashboard, the
evaluator, or the CLI.

Grounded on the live tree, ``ari/llm/`` imports none of ``ari.viz`` / ``ari.evaluator``
/ ``ari.cli``, so this guard PASSES today. (``ari/llm`` legitimately imports
``litellm`` — that is the backend layer where the provider dependency belongs, so
there is no litellm restriction here, unlike the evaluator in B5.)
"""
import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from _arch_boundaries import ari_imports, core_root, iter_py, matches_prefix, rel  # noqa: E402

_LLM_DIR = "llm"
_FORBIDDEN = ("ari.viz", "ari.evaluator", "ari.cli")


def test_llm_backend_independent_of_viz_evaluator_cli():
    offenders: list[str] = []
    for path in iter_py(core_root() / _LLM_DIR):
        for lineno, mod in ari_imports(path):
            if matches_prefix(mod, _FORBIDDEN):
                offenders.append(f"{rel(path)}:{lineno}: {mod}")
    assert not offenders, (
        "ari/llm (model backend) must not import dashboard / evaluator / CLI "
        "(report 003 §8 B6):\n  " + "\n  ".join(offenders)
    )
