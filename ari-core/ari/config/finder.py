"""Workflow / profile YAML discovery (Phase 2 — PR-2A).

Three call sites used to spell out their own search strategy:
* ``cli.py:_resolve_cfg`` — CLI ``--config`` flag, then package-bundled
  ``ari/config/workflow.yaml``.
* ``pipeline.py:load_workflow`` — single ``base/workflow.yaml`` →
  ``base/pipeline.yaml`` lookup.
* ``viz/server.py:_build_experiment_detail_config`` — checkpoint
  ``workflow.yaml`` → profile-specific yaml → bundled ``default.yaml``.

The functions below expose those primitives without changing the search
order or the on-disk file names.  Callers stay independent of where the
yaml lives so we can ship Phase 1 (PathManager-driven checkpoint roots)
without re-tweaking three different `os.path.join` chains.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Names searched in priority order inside a single directory.
_WORKFLOW_NAMES: tuple[str, ...] = ("workflow.yaml", "pipeline.yaml")


def package_config_root() -> Path:
    """Return the bundled ``ari-core/config/`` directory shipped with the package.

    Used as the last-resort fallback by both CLI and viz when no
    checkpoint-scoped or profile yaml is present.  Matches the literal
    path used by the legacy callers:

    * ``cli.py``     uses ``Path(__file__).parent.parent / "config"``
    * ``viz/server`` uses ``Path(__file__).parent.parent.parent / "config"``

    Both resolve to ``ari-core/config/`` (a sibling of ``ari/``), not
    ``ari-core/ari/config/``.  ``__file__`` here is
    ``ari-core/ari/config/finder.py`` so we walk up three levels.
    """
    return Path(__file__).resolve().parent.parent.parent / "config"


def find_workflow_in_dir(base: str | Path) -> Path | None:
    """Return ``base/workflow.yaml`` if present, else ``base/pipeline.yaml``.

    Mirrors the order in ``pipeline.py:load_workflow`` exactly: the
    legacy ``pipeline.yaml`` is only consulted when ``workflow.yaml`` is
    absent so a checkpoint that has both keeps preferring the new name.
    """
    b = Path(base)
    for name in _WORKFLOW_NAMES:
        p = b / name
        if p.exists():
            return p
    return None


def find_workflow_yaml(
    checkpoint_dir: str | Path | None = None,
    *,
    profile: str | None = None,
    package_root: Path | None = None,
) -> Path | None:
    """Locate a workflow yaml using the union of viz / pipeline strategies.

    Search order:
        1. ``{checkpoint_dir}/workflow.yaml`` (or ``pipeline.yaml``)
        2. ``{package_root}/profiles/{profile}.yaml`` when *profile* is set
        3. ``{package_root}/default.yaml`` (when present)
        4. ``{package_root}/workflow.yaml`` (the bundled CLI fallback)

    Each step preserves the legacy behaviour of the corresponding caller;
    when a step doesn't apply (no checkpoint, no profile) it is skipped
    silently so existing call-sites can ask for whichever subset they
    relied on.
    """
    if package_root is None:
        package_root = package_config_root()

    if checkpoint_dir is not None:
        cand = find_workflow_in_dir(checkpoint_dir)
        if cand is not None:
            return cand

    if profile:
        prof = package_root / "profiles" / f"{profile}.yaml"
        if prof.exists():
            return prof

    default = package_root / "default.yaml"
    if default.exists():
        return default

    bundled = package_root / "workflow.yaml"
    if bundled.exists():
        return bundled

    return None


def find_profile_yaml(
    profile_name: str,
    checkpoint_dir: str | Path | None = None,
    *,
    package_root: Path | None = None,
) -> Path | None:
    """Locate the profile-specific yaml for *profile_name*.

    Matches the lookup performed by
    ``viz/server.py:_build_experiment_detail_config`` so callers can
    move off the inline `Path(...)` arithmetic without changing
    behaviour.
    """
    if not profile_name:
        return None
    if package_root is None:
        package_root = package_config_root()
    if checkpoint_dir is not None:
        ck_prof = Path(checkpoint_dir) / "profiles" / f"{profile_name}.yaml"
        if ck_prof.exists():
            return ck_prof
    p = package_root / "profiles" / f"{profile_name}.yaml"
    return p if p.exists() else None


def load_workflow_config(workflow_path: str | Path) -> dict[str, Any]:
    """Parse *workflow_path* and return the raw (un-templated) dict.

    Returns an empty dict when the file is missing or not a mapping so
    downstream code can ``.get(...)`` without guarding for ``None``;
    the legacy ``pipeline.py:load_workflow`` had the same semantics.
    """
    p = Path(workflow_path).expanduser()
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    data["_source"] = str(p)
    return data
