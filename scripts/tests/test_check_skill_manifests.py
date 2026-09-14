"""Focused tests for canonical Skill manifest environment-source analysis."""

from __future__ import annotations

from pathlib import Path

from scripts.check_skill_manifests import (
    _filter_reviewed_dynamic_environment_forwarders,
    _scan_environment_reads,
)


def test_environment_scan_resolves_aliases_loops_helpers_and_membership(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "server.py").write_text(
        """
import os as _os
from os import environ as DIRECT_ENV
from os import getenv as direct_getenv

ENV = _os.environ
NAMES = ("LOOP_ONE", "LOOP_TWO")
for name in NAMES:
    ENV.get(name)

direct_getenv("DIRECT_GETENV")
DIRECT_ENV["SUBSCRIPT_READ"]
DIRECT_ENV["SUBSCRIPT_WRITE"] = "value"
"MEMBERSHIP" in DIRECT_ENV

def read_env(name):
    return _os.getenv(name)

read_env("HELPER_POSITIONAL")
read_env(name="HELPER_KEYWORD")
read_env(name=dynamic_name)
ENV.get("PREFIX_" + suffix)
""",
        encoding="utf-8",
    )

    reads, unresolved = _scan_environment_reads(source)

    assert reads == {
        "DIRECT_GETENV",
        "HELPER_KEYWORD",
        "HELPER_POSITIONAL",
        "LOOP_ONE",
        "LOOP_TWO",
        "MEMBERSHIP",
        "SUBSCRIPT_READ",
        "SUBSCRIPT_WRITE",
    }
    assert len(unresolved) == 2
    assert any("dynamic_name" in item for item in unresolved)
    assert any("suffix" in item for item in unresolved)


def test_environment_scan_fails_closed_on_unparseable_source(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    reads, unresolved = _scan_environment_reads(source)

    assert reads == set()
    assert len(unresolved) == 1
    assert unresolved[0].endswith(":syntax-error")


def test_reviewed_dynamic_environment_forwarder_is_byte_and_location_pinned() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    proxy = (
        repo_root / "ari-skill-tool-registry/src/stdio_process_proxy.py"
    ).resolve()

    assert _filter_reviewed_dynamic_environment_forwarders(
        repo_root,
        [f"{proxy}:102:name", f"{proxy}:103:name"],
    ) == [f"{proxy}:103:name"]
