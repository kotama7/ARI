"""Regression tests for deterministic, Git-bounded README indexes."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "readme_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_readme_sync", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load_module()


def _write(root: Path, relative: str, text: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_write_ignores_local_artifacts_but_lists_new_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _git(tmp_path, "init", "--quiet")
    _write(tmp_path, ".gitignore", "__pycache__/\n*.log\nexperiments/\n")
    readme = _write(
        tmp_path,
        "package/README.md",
        "# Package\n\nPackage role.\n\n## Contents\n\n- `README.md` — this file.\n",
    )
    _write(tmp_path, "package/stable.py", "STABLE = True\n")
    _git(tmp_path, "add", ".gitignore", "package/README.md", "package/stable.py")

    # These local-only paths reproduced the CI-only drift: their directories
    # exist on a developer checkout but disappear from a clean checkout.
    _write(tmp_path, "package/cache/__pycache__/module.pyc", "bytecode")
    _write(tmp_path, "package/artifact/run.log", "runtime output")
    _write(tmp_path, "scripts/local/experiments/case.md", "local experiment")
    _write(tmp_path, "package/new_source.py", "NEW = True\n")

    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    sync.git_inventory.cache_clear()

    assert sync.write() == 0
    rendered = readme.read_text(encoding="utf-8")
    assert "`stable.py`" in rendered
    assert "`new_source.py`" in rendered
    assert "cache/" not in rendered
    assert "artifact/" not in rendered
    assert "experiments/" not in rendered
    assert sync.check() == 0
