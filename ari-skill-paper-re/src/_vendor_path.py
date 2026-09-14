"""Bootstrap the exact reviewed PaperBench packages without a global path edit.

The vendor tree is a git submodule at ``vendor/paperbench/``. Its three Python
package roots are placed on :data:`sys.path` only while their top-level
packages are imported, then removed in ``finally``. Normal package ``__path__``
resolution handles reviewed submodules afterwards, without leaving a global
search-order override that unrelated imports could observe.

An ``ARI_PAPERBENCH_PATH`` override is admitted only when its Git identity and
the explicit ``ARI_PAPERBENCH_COMMIT`` claim match the reviewed inventory.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

from paperbench_inventory import PaperBenchInventoryError, validate_project_root

log = logging.getLogger(__name__)


def _candidate_root() -> Path:
    """Resolve the reviewed ``vendor/paperbench/project`` root."""

    override = os.environ.get("ARI_PAPERBENCH_PATH", "").strip()
    if override:
        project = Path(override).expanduser()
        if project.is_symlink():
            raise PaperBenchInventoryError(
                "ARI_PAPERBENCH_PATH may not be a symlink"
            )
        if project.name == "paperbench" and project.parent.name == "project":
            project = project.parent
        claimed = os.environ.get("ARI_PAPERBENCH_COMMIT", "").strip()
        if not claimed:
            raise PaperBenchInventoryError(
                "ARI_PAPERBENCH_PATH requires ARI_PAPERBENCH_COMMIT"
            )
        return validate_project_root(
            project,
            claimed_commit=claimed,
            require_git_identity=True,
        )
    here = Path(__file__).resolve().parents[1]
    project = here / "vendor" / "paperbench" / "project"
    if not project.is_dir():
        raise PaperBenchInventoryError(
            "vendor/paperbench is absent; initialize the reviewed submodule"
        )
    return validate_project_root(project)


def _bootstrap() -> list[str]:
    """Import reviewed package roots while temporarily making them visible."""

    project = _candidate_root()
    packages = [
        ("paperbench", project / "paperbench"),
        ("nanoeval", project / "common" / "nanoeval"),
        (
            "preparedness_turn_completer",
            project / "common" / "preparedness_turn_completer",
        ),
    ]
    added: list[str] = []
    for _, root in packages:
        if not root.is_dir() or root.is_symlink():
            raise PaperBenchInventoryError(
                f"reviewed PaperBench package root is unsafe: {root}"
            )
        value = str(root)
        if value not in sys.path:
            sys.path.insert(0, value)
            added.append(value)
    try:
        for package, root in packages:
            module = importlib.import_module(package)
            module_file = getattr(module, "__file__", None)
            if module_file is None:
                raise PaperBenchInventoryError(
                    f"reviewed PaperBench package has no source file: {package}"
                )
            try:
                Path(module_file).resolve(strict=True).relative_to(
                    root.resolve(strict=True)
                )
            except ValueError as exc:
                raise PaperBenchInventoryError(
                    f"{package} was already loaded outside the reviewed vendor tree"
                ) from exc
    finally:
        for value in added:
            try:
                sys.path.remove(value)
            except ValueError:
                pass
    roots = [str(root.resolve(strict=True)) for _, root in packages]
    log.info("reviewed PaperBench packages bootstrapped: %s", roots)
    return roots


_BOOTSTRAPPED_ROOTS: list[str] = _bootstrap()
