"""Core->viz direction guard (report ``003`` §9).

Non-viz ``ari-core`` code must not import ``ari.viz.*``. The only SANCTIONED
importer is the ``viz`` CLI command in ``ari/cli/commands.py`` (it launches the
dashboard). The known INVERSION at ``ari/cli/lineage.py`` (``from
ari.viz.api_orchestrator import _api_launch_sub_experiment``) is a live B7
violation, fixed by subtask 011/012, so it is guarded with
``xfail(strict=False)`` — the case turns to XPASS the moment the inversion is
routed through an injected launcher hook.

Allow-listing is by FILE, not line, to avoid line-drift churn (subtask 018 §17).
"""
import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest  # noqa: E402

from _arch_boundaries import (  # noqa: E402
    ari_imports,
    core_root,
    iter_py,
    matches_prefix,
    rel,
)

_VIZ_PREFIXES = ("ari.viz",)
_VIZ_DIR_PREFIX = "ari-core/ari/viz/"
# Sanctioned core->viz importer (the dashboard-launching CLI command).
_ALLOWED_IMPORTER = "ari-core/ari/cli/commands.py"
# Known inversion, waived until subtask 011/012 lands.
_WAIVED_IMPORTER = "ari-core/ari/cli/lineage.py"


def _core_to_viz_importers() -> dict[str, list[str]]:
    """Map ``{repo-relative file: ["<line>: <module>", ...]}`` for ``ari.viz.*``
    imports made from ``ari-core`` code OUTSIDE the ``ari/viz/`` package itself."""
    hits: dict[str, list[str]] = {}
    for path in iter_py(core_root()):
        r = rel(path)
        if r.startswith(_VIZ_DIR_PREFIX):
            continue  # viz importing itself is fine
        for lineno, mod in ari_imports(path):
            if matches_prefix(mod, _VIZ_PREFIXES):
                hits.setdefault(r, []).append(f"{lineno}: {mod}")
    return hits


def test_no_unexpected_core_to_viz_imports():
    """General rule (passes today): the only core->viz importers are the allow-listed
    ``viz`` command and the separately-waived ``lineage`` inversion."""
    hits = _core_to_viz_importers()
    offenders = {
        f: mods
        for f, mods in hits.items()
        if f not in (_ALLOWED_IMPORTER, _WAIVED_IMPORTER)
    }
    assert not offenders, (
        "Unexpected ari-core -> ari.viz imports (report 003 §9 core->viz inversion):\n  "
        + "\n  ".join(f"{f} -> {mods}" for f, mods in sorted(offenders.items()))
    )


def test_viz_command_import_is_allowed():
    """Anti-rot: the sanctioned viz-command edge must exist (documents the allow-list)."""
    hits = _core_to_viz_importers()
    assert _ALLOWED_IMPORTER in hits, (
        f"Expected the sanctioned viz CLI command in {_ALLOWED_IMPORTER} to import "
        "ari.viz.* (it launches the dashboard); none found."
    )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "B7 core->viz inversion at ari/cli/lineage.py "
        "(imports ari.viz.api_orchestrator._api_launch_sub_experiment) — fixed by "
        "subtask 011/012; remove this marker when the launcher is inverted behind an "
        "injected hook."
    ),
)
def test_lineage_does_not_import_viz():
    """Desired end-state: ``lineage`` must NOT reach up into ``ari.viz``. Currently
    violated -> xfailed; auto-XPASSes when subtask 011/012 removes the inversion."""
    hits = _core_to_viz_importers()
    assert _WAIVED_IMPORTER not in hits, (
        f"{_WAIVED_IMPORTER} still imports ari.viz.* "
        f"({hits.get(_WAIVED_IMPORTER)}) — core->viz inversion (B7)."
    )
