"""workflow.yaml / pipeline.yaml loaders + template helper (Phase 3C).

Pure functions extracted from the legacy ``ari/pipeline.py``:

- :func:`load_pipeline` — return enabled stage list from workflow.yaml
  (``pipeline:`` section).
- :func:`load_disabled_stage_names` — return the *complement* (names of
  stages declared with ``enabled: false``) so depends_on can short-
  circuit cleanly.
- :func:`load_workflow` — full workflow dict, falls back to the legacy
  ``pipeline.yaml`` filename via :mod:`ari.config.finder`.
- :func:`_resolve_templates` — recursively substitute ``{{var}}`` over
  strings, lists, dicts (no Jinja, just dot-notation lookup).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml


log = logging.getLogger(__name__)


def load_pipeline(config_yaml: str | Path) -> list[dict]:
    """Load pipeline stages from workflow.yaml or legacy pipeline.yaml.

    Returns only stages with enabled != false.
    """
    path = Path(config_yaml).expanduser()
    if not path.exists():
        log.warning("Config not found: %s", path)
        return []
    data = yaml.safe_load(path.read_text())
    stages = data.get("pipeline", [])
    return [s for s in stages if s.get("enabled", True)]


def load_disabled_stage_names(config_yaml: str | Path) -> set[str]:
    """Names of pipeline stages with ``enabled: false``.

    Used by ``run_pipeline`` so depends_on on an intentionally-disabled
    stage (e.g. EAR-off skipping ``generate_ear``) does not cascade-skip
    every downstream consumer.
    """
    path = Path(config_yaml).expanduser()
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return set()
    return {
        s.get("stage", "")
        for s in (data.get("pipeline") or [])
        if not s.get("enabled", True) and s.get("stage")
    }


def derive_workflow_with_disabled(
    src: str | Path, dst: str | Path, disable_stages,
) -> "Path | None":
    """Copy the workflow at ``src`` to ``dst`` with ``disable_stages`` marked
    ``enabled: false``; return ``dst``, or ``None`` if it could not be derived.

    A pure, caller-driven transform: it reads no config and knows nothing about
    WHY a stage is being turned off, so it introduces no mode conditional into
    the pipeline. The whole document is copied verbatim (``paper_context``,
    ``skills``, every stage's args) and ONLY the named stages' ``enabled`` flags
    flip — so the derived file is a faithful stand-in that
    :func:`load_pipeline` (which drops ``enabled: false``) and
    :func:`load_disabled_stage_names` (which reports the complement, so
    ``depends_on`` on a disabled stage resolves instead of cascade-skipping)
    both read consistently.

    Returns ``None`` on any failure so the caller can fail open to the original
    workflow rather than lose the paper phase to a config-derivation error.
    """
    want = {str(s) for s in (disable_stages or ())}
    if not want:
        return None
    try:
        src_p, dst_p = Path(src).expanduser(), Path(dst).expanduser()
        data = yaml.safe_load(src_p.read_text()) or {}
        found: set[str] = set()
        for s in (data.get("pipeline") or []):
            if s.get("stage") in want:
                s["enabled"] = False
                found.add(s.get("stage"))
        missing = want - found
        if missing:
            # Not fatal: a workflow legitimately need not declare every stage.
            log.debug("derive_workflow_with_disabled: %s not present in %s",
                      sorted(missing), src_p)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        dst_p.write_text(yaml.safe_dump(data, sort_keys=False,
                                        allow_unicode=True))
        return dst_p
    except Exception:
        log.warning("failed to derive a workflow with %s disabled from %s",
                    sorted(want), src, exc_info=True)
        return None


def load_workflow(config_dir: str | Path) -> dict:
    """Load workflow.yaml if present, else fall back to pipeline.yaml.

    Returns full workflow dict including skills list.  Search order
    (workflow.yaml first, pipeline.yaml as legacy fallback) is delegated
    to ``ari.config.finder`` so this and the viz / CLI sites share one
    discovery path (Phase 2 §6-2).
    """
    from ari.config.finder import find_workflow_in_dir, load_workflow_config
    p = find_workflow_in_dir(config_dir)
    if p is None:
        return {"pipeline": [], "skills": []}
    data = load_workflow_config(p)
    if not data:
        # finder returned a path but YAML parse failed — preserve the
        # legacy "no workflow loaded" semantics.
        return {"pipeline": [], "skills": []}
    return data


def _resolve_templates(value: Any, vars_: dict) -> Any:
    """Recursively resolve {{var}} templates in strings, lists, dicts."""
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            key = m.group(1).strip()
            # Support dot-notation: stages.search_related_work.output
            parts = key.split(".")
            v = vars_
            try:
                for p in parts:
                    v = v[p]
                return str(v)
            except (KeyError, TypeError):
                return m.group(0)  # leave unresolved
        return re.sub(r"\{\{(.+?)\}\}", _sub, value)
    elif isinstance(value, dict):
        return {k: _resolve_templates(v, vars_) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_templates(v, vars_) for v in value]
    return value
