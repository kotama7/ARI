#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_import_boundaries.py.

Covers (subtask 026 §8 item 8):
  (a) B1 fires on a skill's private-core edge and not on its ari.public edge;
  (b) B2 allows ari_skill_memory from core and flags any other ari_skill_*;
  (c) a repo-level smoke test asserts the checker reports EXACTLY the 7 seed
      edges (9 line occurrences) with an empty allowlist, and ZERO net-new
      findings with the seeded allowlist.

The checker is exercised as a subprocess (matching the §12 manual acceptance
runs), so REPO_ROOT resolves from the script's own location.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
CHECKER = SCRIPTS_DIR / "check_import_boundaries.py"

# The frozen seed set (docs/refactoring/003 §3/§16), as <file>::<module> ids.
SEED_IDS = {
    "ari-skill-idea/src/server.py::ari.lineage",
    "ari-skill-paper-re/src/server.py::ari.clone",
    "ari-skill-transform/src/server.py::ari.orchestrator",
    "ari-skill-transform/src/server.py::ari.publish",
    "ari-skill-coding/src/server.py::ari.container",
    "ari-skill-coding/src/server.py::ari.agent.run_env",
    "ari-skill-hpc/src/slurm.py::ari.agent.run_env",
}
# The 9 line-level occurrences those 7 edges expand to.
SEED_OCCURRENCES = {
    ("ari-skill-idea/src/server.py", 614),
    ("ari-skill-paper-re/src/server.py", 146),
    ("ari-skill-transform/src/server.py", 681),
    ("ari-skill-transform/src/server.py", 2083),
    ("ari-skill-transform/src/server.py", 2433),
    ("ari-skill-transform/src/server.py", 2451),
    ("ari-skill-coding/src/server.py", 569),
    ("ari-skill-coding/src/server.py", 583),
    ("ari-skill-hpc/src/slurm.py", 211),
}


def run_checker(*args: str) -> tuple[int, dict]:
    """Run the checker with --json and return (exit_code, parsed_report)."""
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def _write(base: Path, rel: str, text: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# -- (a) B1 fixture ---------------------------------------------------------


def test_b1_flags_private_core_but_not_public(tmp_path: Path) -> None:
    skill = "ari-skill-fixture/src/server.py"
    _write(tmp_path, skill, (
        "def _bootstrap():\n"
        "    from ari.public import cost_tracker  # allowed root\n"
        "    from ari.protocols import Evaluator  # allowed root\n"
        "    from ari import cost_tracker as ct    # bare top-level: not flagged\n"
        "    from ari.lineage import record        # B1 violation\n"
        "    import ari.publish                    # B1 violation\n"
        "    return cost_tracker, Evaluator, ct, record\n"
    ))
    code, report = run_checker("--target", str(tmp_path), "--allow", os.devnull)
    b1 = {(f["file"], f["imported_module"]) for f in report["findings"]
          if f["rule"] == "B1"}
    assert (skill, "ari.lineage") in b1
    assert (skill, "ari.publish") in b1
    # The ari.public / ari.protocols / bare-ari imports must NOT be flagged.
    assert (skill, "ari.public") not in b1
    assert (skill, "ari.protocols") not in b1
    assert (skill, "ari") not in b1
    assert report["summary"]["b1"] == 2
    assert code == 0  # default posture is warning-mode


# -- (b) B2 fixture ---------------------------------------------------------


def test_b2_allows_memory_flags_other_skill(tmp_path: Path) -> None:
    core = "ari-core/ari/thing.py"
    _write(tmp_path, core, (
        "def _load():\n"
        "    from ari_skill_memory.backends import get_backend  # sanctioned\n"
        "    import ari_skill_paper                              # B2 violation\n"
        "    return get_backend, ari_skill_paper\n"
    ))
    code, report = run_checker("--target", str(tmp_path), "--allow", os.devnull)
    b2 = {(f["file"], f["imported_module"]) for f in report["findings"]
          if f["rule"] == "B2"}
    assert (core, "ari_skill_paper") in b2
    assert (core, "ari_skill_memory.backends") not in b2
    assert report["summary"]["b2"] == 1
    assert code == 0


def test_b2_regression_gate_fails_on_new_edge(tmp_path: Path) -> None:
    _write(tmp_path, "ari-core/ari/thing.py",
           "import ari_skill_paper\n")
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--target", str(tmp_path),
         "--allow", os.devnull, "--fail-on-regression"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr


# -- (c) repo-level smoke ---------------------------------------------------


def test_repo_smoke_empty_allowlist_reports_exactly_seed(tmp_path: Path) -> None:
    code, report = run_checker("--allow", os.devnull)
    ids = {f["id"] for f in report["findings"]}
    occ = {(f["file"], f["line"]) for f in report["findings"]}
    assert ids == SEED_IDS, sorted(ids ^ SEED_IDS)
    assert occ == SEED_OCCURRENCES, sorted(occ ^ SEED_OCCURRENCES)
    assert report["summary"]["b2"] == 0  # ari_skill_memory is sanctioned
    assert report["summary"]["new"] == 9
    assert code == 0


def test_repo_smoke_seeded_allowlist_has_zero_new() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--fail-on-regression"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
