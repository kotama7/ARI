"""Venue-conditioned PaperBench rubric template loader.

Mirrors the venue/system_hint pattern already used by
``ari-skill-paper``'s peer-review rubric loader
(``ari-skill-paper/src/rubric.py``). Templates live as YAML files in
``ari-core/config/paperbench_rubrics/<id>.yaml``.

The generator (``generator.py::generate_rubric_async``) accepts an
optional ``paperbench_rubric_id`` argument; when supplied, the loaded
template's ``prompt_overrides`` are injected into the skeleton prompt
via the ``{VENUE_HINT}`` placeholder so the rubric LLM produces
venue-appropriate output. When omitted, generator behavior is the same
as before this module existed (back-compat).

Modes:
  - ``agent_benchmark`` — the default PaperBench framing. The skeleton
    pass decomposes the paper by scientific structure (one direct
    child per major contribution / experiment). Leaves grade whether
    a candidate submission's reproduce.sh output matches the paper.
  - ``paper_audit`` — flips the framing for reproducibility-audit
    research (see ``HPC PaperBench audit research plan``). Direct children
    are a fixed set of audit axes declared in ``top_level_axes``.
    Leaves grade descriptive completeness of the paper itself, not
    submission output.

Discovery search path (first match wins):
  1. ``$ARI_PAPERBENCH_RUBRIC_DIR`` env var
  2. ``<cwd>/ari-core/config/paperbench_rubrics/``
  3. ``<cwd>/config/paperbench_rubrics/``
  4. Repo-relative fallback (resolved from this file's path)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised at first use only
    yaml = None  # loader raises a friendly error when first invoked


_DIR_ENV = os.environ.get("ARI_PAPERBENCH_RUBRIC_DIR", "").strip()
DEFAULT_DIRS: list[Path | None] = [
    Path(_DIR_ENV) if _DIR_ENV else None,
    Path.cwd() / "ari-core" / "config" / "paperbench_rubrics",
    Path.cwd() / "config" / "paperbench_rubrics",
    Path(__file__).resolve().parent.parent.parent
    / "ari-core"
    / "config"
    / "paperbench_rubrics",
]


@dataclass
class TopLevelAxis:
    """One fixed direct-child of the rubric root (paper_audit mode)."""

    id: str
    weight: int
    description: str
    name: str = ""


@dataclass
class PromptOverrides:
    system_hint: str = ""           # injected into skeleton/subtree prompts
    leaf_style: str = ""            # injected into subtree prompt only


@dataclass
class PaperBenchRubricTemplate:
    id: str
    venue: str
    domain: str
    mode: str  # "agent_benchmark" | "paper_audit"
    version: str = ""
    top_level_axes: list[TopLevelAxis] = field(default_factory=list)
    prompt_overrides: PromptOverrides = field(default_factory=PromptOverrides)
    source_path: str = ""


_VALID_MODES = {"agent_benchmark", "paper_audit"}


def _candidate_paths(rubric_id: str) -> list[Path]:
    return [
        d / f"{rubric_id}.yaml"
        for d in DEFAULT_DIRS
        if d is not None
    ]


def load_paperbench_rubric(rubric_id: str) -> PaperBenchRubricTemplate:
    """Find ``<rubric_id>.yaml`` in DEFAULT_DIRS and parse it.

    Raises ``FileNotFoundError`` if the template can't be located,
    ``ValueError`` for malformed YAML, and ``RuntimeError`` if PyYAML
    isn't installed.
    """
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load PaperBench rubric templates "
            "(pip install pyyaml)"
        )
    if not rubric_id or not rubric_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid rubric_id: {rubric_id!r}")

    for path in _candidate_paths(rubric_id):
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"malformed YAML in {path}: {e}") from e
            return _parse_template(data, source_path=str(path))

    searched = [str(p) for p in _candidate_paths(rubric_id)]
    raise FileNotFoundError(
        f"PaperBench rubric template '{rubric_id}' not found. Searched:\n  "
        + "\n  ".join(searched)
    )


def _parse_template(data: dict, *, source_path: str) -> PaperBenchRubricTemplate:
    mode = str(data.get("mode", "agent_benchmark"))
    if mode not in _VALID_MODES:
        raise ValueError(
            f"unknown mode {mode!r} in {source_path}; valid: {sorted(_VALID_MODES)}"
        )

    axes_raw = data.get("top_level_axes") or []
    if mode == "paper_audit" and not axes_raw:
        raise ValueError(
            f"{source_path}: top_level_axes must be non-empty when mode=paper_audit"
        )
    axes: list[TopLevelAxis] = []
    for i, ax in enumerate(axes_raw):
        if not isinstance(ax, dict):
            raise ValueError(f"{source_path}: top_level_axes[{i}] must be a mapping")
        try:
            axes.append(
                TopLevelAxis(
                    id=str(ax["id"]),
                    weight=int(ax["weight"]),
                    description=str(ax["description"]),
                    name=str(ax.get("name", "")),
                )
            )
        except KeyError as e:
            raise ValueError(
                f"{source_path}: top_level_axes[{i}] missing required field {e}"
            ) from e

    po_raw = data.get("prompt_overrides") or {}
    overrides = PromptOverrides(
        system_hint=str(po_raw.get("system_hint", "")),
        leaf_style=str(po_raw.get("leaf_style", "")),
    )

    return PaperBenchRubricTemplate(
        id=str(data.get("id", "")),
        venue=str(data.get("venue", "")),
        domain=str(data.get("domain", "")),
        mode=mode,
        version=str(data.get("version", "")),
        top_level_axes=axes,
        prompt_overrides=overrides,
        source_path=source_path,
    )


def build_skeleton_venue_hint(template: PaperBenchRubricTemplate) -> str:
    """Render the venue-specific block injected into the skeleton prompt.

    The skeleton template contains a ``{VENUE_HINT}`` placeholder near
    the top. This function returns the string that replaces it:

      * ``agent_benchmark`` + empty system_hint → empty string
        (preserves the original prompt verbatim).
      * ``agent_benchmark`` + non-empty system_hint → just the hint
        block, no axis constraint.
      * ``paper_audit`` → a full override block that lists the fixed
        axes, instructs the model to use them verbatim, and embeds
        the leaf-style guidance for the downstream subtree pass.
    """
    hint = (template.prompt_overrides.system_hint or "").strip()
    if template.mode == "agent_benchmark":
        if not hint:
            return ""
        return (
            "=================================================================\n"
            f"VENUE OVERRIDE: {template.venue}\n"
            "=================================================================\n\n"
            f"{hint}\n\n"
            "=================================================================\n"
        )

    # paper_audit mode — enforce fixed axes.
    axes_list = "\n".join(
        f"  {i + 1}. id={a.id!r}  weight={a.weight}  "
        f"requirements=\"{a.description.strip()}\""
        for i, a in enumerate(template.top_level_axes)
    )
    leaf_style = (template.prompt_overrides.leaf_style or "").strip()
    return f"""\
=================================================================
VENUE OVERRIDE: {template.venue}  (mode=paper_audit)
=================================================================

{hint}

YOUR DIRECT CHILDREN MUST BE EXACTLY THESE FIXED AXES — DO NOT ADD,
REMOVE, RENAME, OR REORDER. The list below is normative; everything
else in this prompt (e.g., the "STRUCTURAL AXIS" section that
suggests decomposing by paper contribution) is OVERRIDDEN by this
venue policy:

{axes_list}

For each fixed axis:
  - Set the child's ``requirements`` to the exact description string
    given above (verbatim).
  - Set the child's ``weight`` to the integer shown above.
  - Set the child's ``target_subtree_leaves`` proportional to weight
    so the totals sum to approximately {{TARGET_LEAVES}}.
  - Set the child's ``sub_tasks`` to ``[]`` — the downstream pass
    will populate.

LEAF STYLE FOR THE DOWNSTREAM PASS (informational; this same hint
will be re-injected into the subtree prompt by the generator):

{leaf_style}

=================================================================
"""
