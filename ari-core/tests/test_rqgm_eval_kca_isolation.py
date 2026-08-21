"""Criterion 67: production runtime never depends on the Task-13/20 evaluation harness.

``ari.rqgm.evaluation`` is that harness -- the metric computer, the injection
appliers, the scripted doubles, the condition expansion and the offline smoke
runner behind ``scripts/rqgm_eval/run_ablation.py``. All of it runs OVER a
finished checkpoint. Production may be measured by it; production must not
depend on it, or the thing being measured contains the measurer.

TWO SCANS, AND THE SECOND ONE IS THE CRITERION. The first is the original
K/C/A check and is kept exactly as it was: four packages, any textual mention.
It is deliberately stricter than an import check and nothing here relaxes it.

The second scans the WHOLE production tree, which is where the criterion
actually lives and where this file used to stop looking. Scanning only
knowledge/providers/capability_binding/assurance left ``ari/rqgm/`` -- the
runtime itself -- unexamined, and there were five real imports in it:
``runtime.py`` twice and ``paper_runtime.py`` three times, all reached by an
ordinary ``ari paper`` run through ``paper_phase=True`` and none of them behind
an evaluation-only flag. The one in ``RQGMRuntime.__init__`` was not even
wrapped, so a build that did not ship the harness broke the paper phase
outright; the three in ``paper_runtime`` sat inside ``except Exception``, which
would have swallowed the ImportError and silently run a declared P-arm as an
unfiltered ordinary run. Fixed by moving ``paper_ablation`` to
``ari.rqgm.paper_ablation``: it is read DURING a run, its config field is
declared in ``ari.config``, and no module inside the evaluation package ever
imported it.

Imports are resolved with ``ast`` rather than by substring, so a docstring that
merely NAMES the harness (``ari/config/__init__.py`` documents
``rqgm.eval.scripted_components`` as "Keys of ari.rqgm.evaluation.doubles") is
not counted as a dependency -- naming is not importing. Dynamic
``importlib.import_module("ari.rqgm.evaluation...")`` string arguments ARE
counted, so the check cannot be stepped around with a literal.
"""

from __future__ import annotations

import ast
from pathlib import Path

ARI_ROOT = Path(__file__).resolve().parents[1] / "ari"
HARNESS = "ari.rqgm.evaluation"

#: The harness itself, which is of course allowed to import its own submodules.
HARNESS_DIR = ARI_ROOT / "rqgm" / "evaluation"


def _is_harness(module: str) -> bool:
    return module == HARNESS or module.startswith(HARNESS + ".")


def _harness_imports(path: Path) -> list[str]:
    """Every real import of the evaluation harness in one production module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken file is another test's job
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"{path}:{node.lineno} import {alias.name}"
                      for alias in node.names if _is_harness(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import; inside ari/ none of them can reach
            # the harness without naming it, and node.module is what names it.
            if node.module and _is_harness(node.module):
                found.append(f"{path}:{node.lineno} from {node.module}")
        elif isinstance(node, ast.Call):
            # importlib.import_module("ari.rqgm.evaluation.x") and friends.
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _is_harness(arg.value):
                        found.append(f"{path}:{node.lineno} dynamic {arg.value!r}")
    return found


def test_production_kca_packages_do_not_import_rqgm_evaluation():
    """The original four-package check, unchanged: any textual mention fails."""
    packages = (
        ARI_ROOT / "knowledge",
        ARI_ROOT / "providers",
        ARI_ROOT / "capability_binding",
        ARI_ROOT / "assurance",
    )
    violations = []
    for package in packages:
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if HARNESS in text:
                violations.append(path.relative_to(ARI_ROOT).as_posix())
    assert violations == []


def test_no_production_module_imports_the_evaluation_harness():
    """Criterion 67 over the whole of ``ari/``, the harness's own tree excepted.

    This is the assertion the criterion names. It covers ``ari/rqgm/`` --
    including ``runtime.py`` and ``paper_runtime.py``, the ordinary paper path
    -- and ``ari/cli/``, ``ari/core``, and every other production package.
    """
    violations: list[str] = []
    for path in sorted(ARI_ROOT.rglob("*.py")):
        if HARNESS_DIR in path.parents:
            continue
        violations += [
            entry.replace(str(ARI_ROOT) + "/", "")
            for entry in _harness_imports(path)
        ]
    assert violations == [], (
        "production code imports the Task-13/20 evaluation harness; production "
        "may be measured by it but must not depend on it:\n  "
        + "\n  ".join(violations))


def test_the_scan_would_catch_a_reintroduced_dependency():
    """The scan is only worth its green if it can go red. Prove it can.

    Written because the version this replaces passed while five real imports
    existed -- it simply was not looking at the files that had them. Each form
    the production code actually used, plus the dynamic one, is checked against
    the same helper the real scan uses.
    """
    import tempfile

    samples = (
        "from ari.rqgm.evaluation.paper_ablation import posture_from_config\n",
        "import ari.rqgm.evaluation.metrics\n",
        "from ari.rqgm.evaluation import doubles\n",
        "import importlib\n"
        "m = importlib.import_module('ari.rqgm.evaluation.smoke')\n",
    )
    with tempfile.TemporaryDirectory(prefix="ari-crit67-") as tmp:
        for index, source in enumerate(samples):
            probe = Path(tmp) / f"probe_{index}.py"
            probe.write_text(source, encoding="utf-8")
            assert _harness_imports(probe), f"scan missed: {source!r}"

        # ...and does not fire on a mere mention, which is not a dependency.
        mention = Path(tmp) / "mention.py"
        mention.write_text('"""Keys of ari.rqgm.evaluation.doubles."""\n',
                           encoding="utf-8")
        assert _harness_imports(mention) == []
