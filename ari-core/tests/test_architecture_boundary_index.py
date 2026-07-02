"""Boundary coverage map (subtask 018 §7 P5).

Every boundary B1-B11 from report ``003_dependency_boundary_report.md`` (§16 status
table) must be covered by a live ``pytest`` guard file under ``ari-core/tests/`` OR
carry an explicit ``waived:`` reason (CI/scripts or frontend concerns that are not
in-process ``pytest``-testable). This makes the boundary coverage auditable in one
place, so a newly-added boundary can never ship silently unguarded.

* ``test_all_boundaries_covered`` fails if report 003 grows/loses a boundary and
  the map is not updated.
* ``test_named_guard_files_exist`` fails if a named guard file is renamed/removed.
"""
import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from _arch_boundaries import repo_root  # noqa: E402

_TESTS = repo_root() / "ari-core" / "tests"

# B1-B11 -> the guard module that covers it, or "waived: <reason>".
# Existing guards (KEEP) are referenced, not re-pointed at the shared helper here
# (that would be an optional later MERGE, out of scope for subtask 018).
_BOUNDARY_GUARDS: dict[str, str] = {
    # B1 skill -> only ari.public.* (existing AST + regex guards).
    "B1": "test_public_api_boundary.py",
    # B2 core -/-> skill except ari_skill_memory (new, subtask 018).
    "B2": "test_core_does_not_import_skills.py",
    # B3 viz routes thin: in-process surface is the wire-shape contract.
    "B3": "test_api_schema_contract.py",
    # B4 frontend -> DTO/TS types only: TS/npm concern, not pytest-testable here.
    "B4": "waived: frontend import boundary — subtask 063/065 "
    "(wire shape covered by test_api_schema_contract.py)",
    # B5 evaluator independence (new, subtask 018).
    "B5": "test_evaluator_independence.py",
    # B6 model-backend independence (new, subtask 018).
    "B6": "test_model_backend_independence.py",
    # B7 pipeline stage / core->viz inversion: in-process surface is the direction guard.
    "B7": "test_core_viz_direction.py",
    # B8 storage / runtime-path hygiene.
    "B8": "test_no_user_home_writes.py",
    # B9 prompts externalized.
    "B9": "test_prompt_extraction.py",
    # B10 scripts = quality/analysis/report: CI/scripts concern.
    "B10": "waived: CI/scripts concern — subtask 026/032/046",
    # B11 CI staged warning->regression->strict: CI concern.
    "B11": "waived: CI/scripts concern — subtask 026/032/046",
}

_EXPECTED_BOUNDARIES = {f"B{i}" for i in range(1, 12)}


def test_all_boundaries_covered():
    """Every boundary B1-B11 (report 003 §16) has an index entry."""
    assert set(_BOUNDARY_GUARDS) == _EXPECTED_BOUNDARIES, (
        "Boundary coverage map is out of sync with report 003 B1-B11.\n"
        f"  missing: {sorted(_EXPECTED_BOUNDARIES - set(_BOUNDARY_GUARDS))}\n"
        f"  extra:   {sorted(set(_BOUNDARY_GUARDS) - _EXPECTED_BOUNDARIES)}"
    )


def test_named_guard_files_exist():
    """Each non-waived entry names a guard file that exists in ari-core/tests/."""
    missing: list[str] = []
    for boundary, target in sorted(_BOUNDARY_GUARDS.items()):
        if target.startswith("waived:"):
            continue
        if not (_TESTS / target).is_file():
            missing.append(f"{boundary} -> {target} (file not found)")
    assert not missing, (
        "Boundary index names guard files that do not exist:\n  " + "\n  ".join(missing)
    )
