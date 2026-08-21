"""The commit gate that refuses a catalog its own bundles no longer describe.

WHY THIS FILE EXISTS. `repin check` asks whether a manifest pins the code it is
measured by. Nothing asked whether the artifacts BESIDE that manifest still
describe it, and moving a manifest without re-earning its evidence passes the
first and fails the second. MEASURED, on the day this was written: that happened
three times, by three different actors, and every one of those commits was
clean. The failure surfaced later, in `load_harness_catalog`, in the working
tree of whoever pulled next -- and it takes the whole catalog down, not one row,
so every test that reads it fails at once.

WHAT IS ASSERTED HERE, AND WHAT IS NOT. Not that the shipped catalog loads --
`test_harness_catalog_revision` and the suite at large already fail loudly when
it does not, and duplicating that would make one fact answer to two tests. What
is asserted is the GATE: that it reports a broken catalog, that it does not
report a sound one, and that the escape hatch it offers is its own rather than
the pin gate's.

THE ESCAPE HATCH IS THE SUBTLE PART. Moving an instrument is exactly what the
pin check refuses, so every actor that moves one reaches for
ARI_SKIP_PIN_CHECK; that is the documented flow, and a commit in this history
says so in as many words while being the commit that left two Harnesses pinning
drivers that no longer existed. One variable carrying both assertions would hand
that habitual escape the catalog too -- which is the case this gate was built
for. So the two are separate, and this file checks that the hook keeps them
separate rather than trusting the shell to have been written correctly.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY = Path(__file__).resolve().parents[2]
GATE = REPOSITORY / "scripts" / "rqgm_assurance" / "check_catalog_loads.py"
HOOK = REPOSITORY / "scripts" / "git-hooks" / "pre-commit"
HARNESS_ROOT = REPOSITORY / "ari-core" / "config" / "harnesses"


def _gate_module():
    spec = importlib.util.spec_from_file_location("check_catalog_loads", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_catalog_loads"] = module
    spec.loader.exec_module(module)
    return module


def _catalog_tree(tmp_path: Path) -> Path:
    """A whole scratch copy: the loader reads files beside the catalog."""
    import shutil

    destination = tmp_path / "harnesses"
    shutil.copytree(HARNESS_ROOT, destination)
    return destination


# --- the gate itself ---------------------------------------------------------

def test_a_sound_catalog_passes(tmp_path: Path) -> None:
    """The good case is in the same file as the bad one, or this proves only
    that the gate is noisy."""
    module = _gate_module()
    assert module.catalog_load_failure(_catalog_tree(tmp_path) / "catalog.yaml") is None


def test_a_manifest_moved_without_its_evidence_is_refused(tmp_path: Path) -> None:
    """The defect, replayed: the exact act that broke the catalog three times.

    `manifest_digest` is derived from every other field, so editing any field
    moves it -- and the report and evidence beside it go on naming the old one.
    The pin check passes throughout, because the DERIVED pins still match the
    code; it is the back-references that no longer match the manifest.
    """
    from ari.assurance.models import HarnessManifestV1

    tree = _catalog_tree(tmp_path)
    path = tree / "builtin" / "hpc_gemm_problem_correctness.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("manifest_digest")
    raw["description"] = raw["description"] + " "
    moved = HarnessManifestV1.create(**raw)
    path.write_text(yaml.safe_dump(moved.model_dump(mode="json"), sort_keys=True,
                                   default_flow_style=False), encoding="utf-8")

    module = _gate_module()
    failure = module.catalog_load_failure(tree / "catalog.yaml")
    assert failure is not None, "a bundle that stopped describing its manifest passed"
    assert "hpc/gemm-dense-fp64-problem-correctness" in failure, (
        "the message must name the harness, or an operator cannot act on it")


def test_a_missing_catalog_is_not_a_failure(tmp_path: Path) -> None:
    """A checkout that ships no catalog has nothing to contradict.

    Refusing here would block every commit in such a tree, which is a gate
    failing closed on the absence of the thing it judges rather than on a
    finding about it.
    """
    module = _gate_module()
    assert module.catalog_load_failure(tmp_path / "nothing.yaml") is None


def test_the_gate_exits_nonzero_and_names_the_repair(tmp_path: Path) -> None:
    """What the hook actually consumes: the exit code and the advice.

    The advice matters as much as the refusal. A stale pin is repaired by
    re-pinning and an operator who has just been refused will reach for that;
    here re-pinning cannot repair anything, so the message has to say the
    evidence must be re-earned.
    """
    from ari.assurance.models import HarnessManifestV1

    tree = _catalog_tree(tmp_path)
    path = tree / "builtin" / "hpc_gemm_performance.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("manifest_digest")
    raw["description"] = raw["description"] + " "
    path.write_text(yaml.safe_dump(HarnessManifestV1.create(**raw).model_dump(mode="json"),
                                   sort_keys=True, default_flow_style=False),
                    encoding="utf-8")

    module = _gate_module()
    code = module.main(["--catalog", str(tree / "catalog.yaml")])
    assert code == 1
    code = module.main(["--catalog", str(_catalog_tree(tmp_path / "sound") / "catalog.yaml")])
    assert code == 0


# --- the two escapes stay two ------------------------------------------------

def test_the_catalog_gate_does_not_answer_to_the_pin_gates_escape() -> None:
    """One variable for two assertions would hand the habitual escape this one.

    Read out of the hook rather than assumed: the block that runs the catalog
    check must be guarded by ARI_SKIP_CATALOG_CHECK and must NOT be nested
    inside the block guarded by ARI_SKIP_PIN_CHECK.
    """
    text = HOOK.read_text(encoding="utf-8")
    assert "ARI_SKIP_CATALOG_CHECK" in text, "the catalog gate has no escape of its own"

    lines = text.splitlines()
    pin_guard = next(i for i, line in enumerate(lines)
                     if line.strip().startswith('if [ -z "${ARI_SKIP_PIN_CHECK'))
    catalog_guard = next(i for i, line in enumerate(lines)
                         if line.strip().startswith('if [ -z "${ARI_SKIP_CATALOG_CHECK'))
    # The pin block is closed before the catalog block opens: a bare `fi` at
    # column zero between them. Nesting would leave the catalog check unreached
    # whenever the pin escape is set, which is exactly the failure this asserts
    # against.
    closers = [i for i, line in enumerate(lines)
               if line == "fi" and pin_guard < i < catalog_guard]
    assert closers, (
        "the catalog check is inside the pin check's guard, so setting "
        "ARI_SKIP_PIN_CHECK skips it too")


def test_the_catalog_gate_runs_only_for_commits_that_touch_the_harness_tree() -> None:
    """A broken catalog must not block work that has nothing to do with it.

    The gate is scoped by the staged paths, in the hook, so the scoping does not
    require the re-pin surface to name the published tree -- which a separate
    guard forbids it from doing.
    """
    text = HOOK.read_text(encoding="utf-8")
    assert "*ari-core/config/harnesses/*" in text, (
        "the catalog gate is unscoped and will fire on unrelated commits")


def test_the_gate_names_the_published_tree_and_the_repin_surface_does_not() -> None:
    """WHY THIS IS A SEPARATE FILE, asserted rather than left in a docstring.

    `repin_and_promote_harness` is held to naming no path inside the published
    harness tree, on the principle that it cannot write a bundle it cannot name.
    This check must READ those bytes. Putting it there would have forced that
    surface to name all four, so the two live apart -- and if someone later
    moves this in, that guard turns red rather than being quietly relaxed.
    """
    assert "catalog.yaml" in GATE.read_text(encoding="utf-8")
    repin = (REPOSITORY / "scripts" / "rqgm_assurance"
             / "repin_and_promote_harness.py").read_text(encoding="utf-8")
    for published in ("evidence", "approvals", "reports", "catalog.yaml"):
        assert f'"{published}"' not in repin, (
            f"the re-pin surface now names {published!r}; the separation this "
            f"file documents has been lost")


def test_the_gate_asks_the_loader_rather_than_reimplementing_it() -> None:
    """The subset-guard trap, in the gate written to stop a different defect.

    Comparing each manifest's `manifest_digest` against the two back-references
    would catch today's three occurrences and go quiet the first time
    `load_harness_catalog` grew a fourth cross-check. It already compares each
    artifact's own digest, its harness id, the approval, and the digest the
    catalog row advertises.
    """
    import ast

    source = GATE.read_text(encoding="utf-8")
    assert "load_harness_catalog" in source

    # THE CODE, NOT THE PROSE. The module's docstring explains at length which
    # comparisons it declines to make, and naming them there is the point; an
    # assertion over the raw text would fire on the explanation. So docstrings
    # are stripped and what remains is what the module DOES.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    executable = ast.unparse(tree)
    for field in ("manifest_digest", "report_digest", "evidence_digest"):
        assert field not in executable, (
            f"the gate compares {field} itself, which makes it a subset of the "
            f"loader rather than a question put to it")
