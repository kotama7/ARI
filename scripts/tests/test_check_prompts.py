#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_prompts.py.

Covers (subtask 043 §8 item 9 / §13 acceptance):
  (a) a synthetic role-marked multi-line prompt is flagged as a NEW candidate;
      an allowlisted one is suppressed (`known`);
  (b) ``ari-core/ari/agent/loop.py`` yields ZERO candidates (negative control --
      its system prompt is externalized to ``agent/system.md``);
  (c) a repo-level smoke asserts the checker reproduces the Subtask 036 census
      high-value targets (evaluator/paper/plot/vlm/transform/web), every finding
      id is unique (no name-collision), and the seeded allowlist yields zero
      net-new debt under ``--fail-on-regression``;
  (d) ``--with-snapshots`` folds Gate 10's pass/fail into the report and a
      missing Gate 10 script is an environment error (exit 2).

The checker is exercised as a subprocess (matching the §12 acceptance runs), so
REPO_ROOT resolves from the script's own location.
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
CHECKER = SCRIPTS_DIR / "check_prompts.py"

# High-value 036 targets the inventory slice must reproduce (file, line).
CENSUS_TARGETS = {
    ("ari-skill-evaluator/src/server.py", 192),   # _METRIC_EXTRACT_SYS
    ("ari-skill-evaluator/src/server.py", 791),   # _SEMANTIC_SYSTEM_PROMPT
    ("ari-skill-paper/src/server.py", 542),       # academic_reviewer
    ("ari-skill-paper/src/server.py", 1487),      # fill_in_writer
    ("ari-skill-paper/src/server.py", 2544),      # global_coherence
    ("ari-skill-plot/src/server.py", 560),        # viz_expert
    ("ari-skill-vlm/src/server.py", 97),          # figure_reviewer
    ("ari-skill-transform/src/server.py", 834),   # node_report_analyst
    ("ari-skill-web/src/server.py", 465),         # query_librarian
}

_SYNTH_PROMPT = (
    'NEW_PROMPT = (\n'
    '    "You are a meticulous grading assistant. Evaluate the answer and "\n'
    '    "return ONLY valid JSON with keys score and rationale.\\n"\n'
    '    "Rule 1: be strict.\\n"\n'
    '    "Rule 2: never invent facts.\\n"\n'
    '    "Respond ONLY with JSON: {score, rationale}."\n'
    ')\n'
)


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


# -- (a) synthetic new / allowlist suppression -----------------------------


def test_synthetic_prompt_is_flagged_new(tmp_path: Path) -> None:
    _write(tmp_path, "ari-core/ari/mod.py", _SYNTH_PROMPT)
    code, report = run_checker("--target", str(tmp_path / "ari-core/ari"),
                               "--allow", os.devnull)
    ids = {f["id"] for f in report["findings"]}
    assert any(i.endswith("mod.py::NEW_PROMPT") for i in ids), ids
    assert report["summary"]["new"] == 1
    assert code == 0  # default posture is advisory (warning-mode-first)

    # Under the ratchet it fails; with the id allowlisted it passes.
    fail = subprocess.run(
        [sys.executable, str(CHECKER), "--target", str(tmp_path / "ari-core/ari"),
         "--allow", os.devnull, "--fail-on-regression"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert fail.returncode == 1, fail.stdout + fail.stderr

    fid = next(i for i in ids if i.endswith("mod.py::NEW_PROMPT"))
    allow = tmp_path / "allow.yaml"
    allow.write_text(f'version: 1\nknown:\n  - id: "{fid}"\n    verdict: REVIEW_REQUIRED\n',
                     encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(CHECKER), "--target", str(tmp_path / "ari-core/ari"),
         "--allow", str(allow), "--fail-on-regression"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_user_message_assembler_not_flagged(tmp_path: Path) -> None:
    # A multi-line USER-message assembler with an incidental "return JSON" must
    # NOT fire (no role opener) -- the loop.py false-positive class.
    _write(tmp_path, "ari-core/ari/mod.py", (
        'def build(goal):\n'
        '    msg = (\n'
        '        f"Experiment goal:\\n{goal}\\n"\n'
        '        "MANDATORY: You must produce NEW artifacts to count as work.\\n"\n'
        '        "Do not reuse the parent numbers; run your own experiment.\\n"\n'
        '        "Implement and run, then return JSON with measurements."\n'
        '    )\n'
        '    return msg\n'
    ))
    _code, report = run_checker("--target", str(tmp_path / "ari-core/ari"),
                                "--allow", os.devnull)
    assert report["summary"]["candidates"] == 0, report["findings"]


# -- (b) negative control ---------------------------------------------------


def test_agent_loop_yields_no_candidate() -> None:
    _code, report = run_checker("--target", "ari-core/ari/agent/loop.py",
                                "--allow", os.devnull)
    assert report["summary"]["candidates"] == 0, report["findings"]


# -- (c) repo smoke ---------------------------------------------------------


def test_repo_smoke_reproduces_census_and_unique_ids() -> None:
    code, report = run_checker()  # default allowlist, default scope
    found = {(f["file"], f["line"]) for f in report["findings"]}
    missing = CENSUS_TARGETS - found
    assert not missing, f"census targets not detected: {sorted(missing)}"
    ids = [f["id"] for f in report["findings"]]
    assert len(ids) == len(set(ids)), "duplicate finding ids"
    # ari-core/ari contributes nothing (prompts externalized).
    assert not any(f["file"].startswith("ari-core/ari/") for f in report["findings"])
    assert report["summary"]["new"] == 0  # seeded allowlist covers the tree
    assert code == 0


def test_repo_smoke_seeded_allowlist_has_zero_new() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--fail-on-regression"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# -- (d) snapshot delegation ------------------------------------------------


def test_with_snapshots_folds_gate10() -> None:
    _code, report = run_checker("--with-snapshots")
    assert report["summary"]["snapshots"] in {"pass", "fail"}


def test_missing_gate10_is_environment_error(tmp_path: Path, monkeypatch) -> None:
    # Point the checker module at a non-existent Gate 10 path and assert exit 2.
    import importlib.util
    spec = importlib.util.spec_from_file_location("cp_mod", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "GATE10", tmp_path / "nonexistent.py")
    with pytest.raises(SystemExit) as exc:
        mod.run_gate10()
    assert exc.value.code == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
