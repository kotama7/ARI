"""Rubric YAML loader and validator for rubric-driven paper review.

Supports the plan.md design: venue-agnostic YAML rubrics with configurable
score dimensions, text sections, decision rules, and v2-compatible execution
parameters. Includes SHA256 hash for P2 determinism guarantee.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError as _e:
    yaml = None  # loader will raise on first use

log = logging.getLogger(__name__)


# Default search paths (first match wins). Allow override via ARI_RUBRIC_DIR.
# Empty strings are filtered so an unset ARI_RUBRIC_DIR does not silently
# fall back to Path("") == cwd and scoop up unrelated *.yaml files.
_ARI_RUBRIC_DIR_ENV = os.environ.get("ARI_RUBRIC_DIR", "").strip()
DEFAULT_RUBRIC_DIRS = [
    Path(_ARI_RUBRIC_DIR_ENV) if _ARI_RUBRIC_DIR_ENV else None,
    Path.cwd() / "ari-core" / "config" / "reviewer_rubrics",
    Path.cwd() / "config" / "reviewer_rubrics",
    Path(__file__).resolve().parent.parent.parent
    / "ari-core"
    / "config"
    / "reviewer_rubrics",
]


@dataclass
class ScoreDimension:
    name: str
    scale: tuple[int, int]
    description: str = ""


@dataclass
class TextSection:
    name: str
    required: bool = False


@dataclass
class Decision:
    type: str = "binary"  # "binary" | "categorical"
    options: list[str] = field(default_factory=lambda: ["accept", "reject"])
    threshold_dimension: str = "overall"
    threshold_value: float = 6.0


@dataclass
class RubricParams:
    num_reflections: int = 5
    num_fs_examples: int = 1
    num_reviews_ensemble: int = 1
    temperature: float = 0.75
    score_threshold_decision: float = 6.0
    fewshot_mode: str = "static"  # "static" | "dynamic"
    fewshot_dir: str = ""


@dataclass
class Rubric:
    id: str
    version: str
    venue: str
    domain: str
    params: RubricParams
    score_dimensions: list[ScoreDimension]
    text_sections: list[TextSection]
    decision: Decision
    system_hint: str = ""
    description: str = ""
    source_path: str = ""
    hash: str = ""

    def dimension_names(self) -> list[str]:
        return [d.name for d in self.score_dimensions]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "hash": self.hash,
            "venue": self.venue,
            "domain": self.domain,
            "score_dimensions": [
                {
                    "name": d.name,
                    "scale": list(d.scale),
                    "description": d.description,
                }
                for d in self.score_dimensions
            ],
            "text_sections": [
                {"name": s.name, "required": s.required} for s in self.text_sections
            ],
            "decision": {
                "type": self.decision.type,
                "options": self.decision.options,
                "threshold_dimension": self.decision.threshold_dimension,
                "threshold_value": self.decision.threshold_value,
            },
            "params": {
                "num_reflections": self.params.num_reflections,
                "num_fs_examples": self.params.num_fs_examples,
                "num_reviews_ensemble": self.params.num_reviews_ensemble,
                "temperature": self.params.temperature,
                "fewshot_mode": self.params.fewshot_mode,
            },
        }


class RubricError(Exception):
    """Rubric loading / validation error."""


def _find_rubric_file(rubric_id: str) -> Path:
    for base in DEFAULT_RUBRIC_DIRS:
        if not base:
            continue
        try:
            base = Path(base)
        except Exception:
            continue
        if not base.exists():
            continue
        candidate = base / f"{rubric_id}.yaml"
        if candidate.exists():
            return candidate
        candidate_yml = base / f"{rubric_id}.yml"
        if candidate_yml.exists():
            return candidate_yml
    raise RubricError(
        f"Rubric '{rubric_id}' not found in any of: "
        + ", ".join(str(p) for p in DEFAULT_RUBRIC_DIRS if p)
    )


def _parse_rubric(data: dict, source_path: Path) -> Rubric:
    if not isinstance(data, dict):
        raise RubricError(f"Rubric root must be a mapping ({source_path})")
    missing = [
        k for k in ("id", "venue", "score_dimensions") if k not in data
    ]
    if missing:
        raise RubricError(
            f"Rubric {source_path.name} missing required keys: {missing}"
        )

    # Score dimensions
    dims: list[ScoreDimension] = []
    for d in data.get("score_dimensions", []):
        if not isinstance(d, dict) or "name" not in d or "scale" not in d:
            raise RubricError(
                f"Rubric {data.get('id')} has malformed score_dimension: {d}"
            )
        scale = d["scale"]
        if not isinstance(scale, list) or len(scale) != 2:
            raise RubricError(
                f"Rubric {data.get('id')} dimension {d['name']}: "
                f"scale must be [lo, hi] pair"
            )
        try:
            lo, hi = int(scale[0]), int(scale[1])
        except Exception as e:
            raise RubricError(
                f"Rubric {data.get('id')} dimension {d['name']}: "
                f"scale must be ints ({e})"
            )
        if hi <= lo:
            raise RubricError(
                f"Rubric {data.get('id')} dimension {d['name']}: "
                f"scale hi ({hi}) must exceed lo ({lo})"
            )
        dims.append(
            ScoreDimension(
                name=str(d["name"]),
                scale=(lo, hi),
                description=str(d.get("description", "")),
            )
        )
    if not dims:
        raise RubricError(
            f"Rubric {data.get('id')} must define at least one score dimension"
        )

    # Text sections
    sects: list[TextSection] = []
    for s in data.get("text_sections", []) or []:
        if isinstance(s, str):
            sects.append(TextSection(name=s))
        elif isinstance(s, dict):
            sects.append(
                TextSection(
                    name=str(s.get("name", "")),
                    required=bool(s.get("required", False)),
                )
            )
        else:
            raise RubricError(
                f"Rubric {data.get('id')} text_section must be str or dict: {s}"
            )

    # Decision
    decision_data = data.get("decision", {}) or {}
    decision = Decision(
        type=str(decision_data.get("type", "binary")),
        options=list(decision_data.get("options", ["accept", "reject"])),
        threshold_dimension=str(decision_data.get("threshold_dimension", "overall")),
        threshold_value=float(decision_data.get("threshold_value", 6.0)),
    )

    # Params
    p_data = data.get("params", {}) or {}
    params = RubricParams(
        num_reflections=int(p_data.get("num_reflections", 5)),
        num_fs_examples=int(p_data.get("num_fs_examples", 1)),
        num_reviews_ensemble=int(p_data.get("num_reviews_ensemble", 1)),
        temperature=float(p_data.get("temperature", 0.75)),
        score_threshold_decision=float(
            p_data.get("score_threshold_decision", decision.threshold_value)
        ),
        fewshot_mode=str(p_data.get("fewshot_mode", "static")),
        fewshot_dir=str(p_data.get("fewshot_dir", "")),
    )
    if params.fewshot_mode not in ("static", "dynamic"):
        raise RubricError(
            f"Rubric {data['id']}: fewshot_mode must be 'static' or 'dynamic' "
            f"(got {params.fewshot_mode!r})"
        )
    if params.num_reviews_ensemble < 1:
        raise RubricError(
            f"Rubric {data['id']}: num_reviews_ensemble must be >= 1"
        )
    if params.num_reflections < 0:
        raise RubricError(
            f"Rubric {data['id']}: num_reflections must be >= 0"
        )

    # Prompt overrides
    overrides = data.get("prompt_overrides", {}) or {}
    system_hint = str(overrides.get("system_hint", "") or "")

    # Hash: SHA256 of canonical YAML bytes for determinism traceability
    try:
        raw_bytes = source_path.read_bytes()
    except Exception:
        raw_bytes = b""
    digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else ""

    return Rubric(
        id=str(data["id"]),
        version=str(data.get("version", "0")),
        venue=str(data.get("venue", "")),
        domain=str(data.get("domain", "")),
        params=params,
        score_dimensions=dims,
        text_sections=sects,
        decision=decision,
        system_hint=system_hint,
        description=str(data.get("description", "")),
        source_path=str(source_path),
        hash=digest,
    )


def load_rubric(rubric_id: str) -> Rubric:
    """Load and validate a rubric by id.

    Search paths (first hit wins):
        1. $ARI_RUBRIC_DIR
        2. ./ari-core/config/reviewer_rubrics/
        3. ./config/reviewer_rubrics/
        4. <repo root>/ari-core/config/reviewer_rubrics/
    """
    if yaml is None:
        raise RubricError(
            "PyYAML is required for rubric loading. Install with: pip install pyyaml"
        )
    path = _find_rubric_file(rubric_id)
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        raise RubricError(f"Failed to parse {path}: {e}") from e
    return _parse_rubric(data, path)


def list_available_rubrics() -> list[dict]:
    """Return list of {id, venue, domain, path, hash, version} for all rubrics."""
    seen: dict[str, Path] = {}
    for base in DEFAULT_RUBRIC_DIRS:
        if not base:
            continue
        try:
            base = Path(base)
        except Exception:
            continue
        if not base.exists():
            continue
        for p in base.glob("*.yaml"):
            if p.stem not in seen:
                seen[p.stem] = p
        for p in base.glob("*.yml"):
            if p.stem not in seen:
                seen[p.stem] = p
    result = []
    for rid, path in sorted(seen.items()):
        try:
            r = load_rubric(rid)
            result.append(
                {
                    "id": r.id,
                    "venue": r.venue,
                    "domain": r.domain,
                    "version": r.version,
                    "hash": r.hash,
                    "path": r.source_path,
                }
            )
        except Exception as e:
            log.warning("failed to load rubric %s: %s", rid, e)
    return result
