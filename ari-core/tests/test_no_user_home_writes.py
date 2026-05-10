"""Guard against accidental writes to ``$HOME/.ari/`` (DEPRECATION_REMOVAL.md §8-1).

ARI v0.5.0 removed the global ``~/.ari/`` directory in favour of
checkpoint-scoped state.  This test ensures the most common module
imports do not eagerly create that legacy directory as a side effect.

This is a *minimal* regression net for Phase DR0.  Phase DR4 will extend
it with end-to-end ``ari status``/``ari projects`` invocations under a
fake HOME, plus a CI guard.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


_TARGET_MODULES = [
    # Modules historically caught with ``Path.home() / ".ari" / ...``
    # at import time.  Extend this list when DR2/DR3 lands.
    "ari.config",
    "ari.paths",
    "ari.cost_tracker",
    "ari.lineage",
    "ari.memory.client",
    "ari.memory.local_client",
    "ari.publish.backends.ari_registry",
    "ari.clone.resolvers.ari",
]


def test_module_imports_do_not_write_user_home(tmp_path, monkeypatch):
    """Importing core ARI modules must not create ``$HOME/.ari/``."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    for mod in _TARGET_MODULES:
        # Force a fresh import so module-level side effects re-run under
        # the patched HOME.
        if mod in list(_loaded_modules()):
            del _loaded_modules()[mod]
        importlib.import_module(mod)

    legacy = fake_home / ".ari"
    if legacy.exists():
        offending = sorted(p.relative_to(fake_home) for p in legacy.rglob("*"))
        pytest.fail(
            "Importing core modules created the deprecated ~/.ari/ dir: "
            f"{offending}"
        )


def _loaded_modules():
    import sys
    return sys.modules
