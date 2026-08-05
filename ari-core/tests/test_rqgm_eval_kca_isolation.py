"""Production K/C/A packages never depend on the Task-20 evaluator."""

from __future__ import annotations

from pathlib import Path


def test_production_kca_packages_do_not_import_rqgm_evaluation():
    ari_root = Path(__file__).resolve().parents[1] / "ari"
    packages = (
        ari_root / "knowledge",
        ari_root / "providers",
        ari_root / "capability_binding",
        ari_root / "assurance",
    )
    violations = []
    for package in packages:
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "ari.rqgm.evaluation" in text:
                violations.append(path.relative_to(ari_root).as_posix())
    assert violations == []
