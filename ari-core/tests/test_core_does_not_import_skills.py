"""B2 guard: ``ari-core`` must not import ``ari-skill-*`` except ``ari_skill_memory``.

Report ``003`` §4 + §11: the ONLY sanctioned ``ari-core -> ari-skill-*`` edge is
``ari_skill_memory`` (first core->skill dependency, v0.6.0; editable-installed by
``setup.sh`` before ``ari-core``). Every other ``import ari_skill_*`` under
``ari-core/ari/**`` is a hard failure.

Grounded on the live tree: all skill-import sites under ``ari-core/ari/`` target
``ari_skill_memory.backends`` (13 imports across 12 files), so this guard PASSES
today. A stray ``import ari_skill_web`` in, say, ``ari/pipeline/`` would fail it.

This is the in-process ``pytest`` surface of the rule that subtask ``026``
(``scripts/check_import_boundaries.py``) enforces in CI; the allow-list is kept
conceptually parallel.
"""
import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from _arch_boundaries import ari_imports, core_root, iter_py, rel, top_package  # noqa: E402

_SANCTIONED_SKILL = "ari_skill_memory"


def test_core_does_not_import_nonmemory_skills():
    offenders: list[str] = []
    for path in iter_py(core_root()):
        for lineno, mod in ari_imports(path):
            top = top_package(mod)
            if top.startswith("ari_skill") and top != _SANCTIONED_SKILL:
                offenders.append(f"{rel(path)}:{lineno}: {mod}")
    assert not offenders, (
        "ari-core must not import ari-skill-* except the sanctioned "
        f"'{_SANCTIONED_SKILL}' edge (report 003 §11):\n  " + "\n  ".join(offenders)
    )


def test_sanctioned_memory_edge_exists():
    """Anti-rot: the sanctioned core->``ari_skill_memory`` edge must be real.

    Without this, the guard above could pass vacuously if every memory import
    disappeared — the allow-list would then mean nothing.
    """
    found = False
    for path in iter_py(core_root()):
        if any(top_package(mod) == _SANCTIONED_SKILL for _ln, mod in ari_imports(path)):
            found = True
            break
    assert found, (
        f"Expected at least one sanctioned '{_SANCTIONED_SKILL}' import under "
        "ari-core/ari/ (report 003 §11); none found — the B2 allow-list may be rotting."
    )
