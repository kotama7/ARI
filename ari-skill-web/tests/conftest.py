"""Load the web Skill under an isolated name for repository-wide test runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_SPEC = importlib.util.spec_from_file_location(
    "ari_skill_web_test_server", _SRC / "server.py"
)
assert _SPEC is not None and _SPEC.loader is not None
WEB_SERVER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = WEB_SERVER
_SPEC.loader.exec_module(WEB_SERVER)


@pytest.fixture(autouse=True)
def _isolate_web_server_module(monkeypatch):
    """Make legacy ``import server`` calls deterministic within this test tree."""

    monkeypatch.setitem(sys.modules, "server", WEB_SERVER)
