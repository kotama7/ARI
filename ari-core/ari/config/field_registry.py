"""Canonical config field registry (gui_refresh task 05 Wave 3a).

The single machine-readable inventory of every declared ``ARIConfig`` leaf,
merged with a hand-authored metadata overlay (category / level / scope /
sensitivity / mutability / applies_when), backing ``GET
/api/v1/config/schema`` (plan ``docs/plans/gui_refresh/05`` §Canonical field
metadata / §Configuration scopes).

Design constraints (plan 05 + INDEX.md invariant):

- **Pure and deterministic** — no filesystem, no clock, no ``os.environ``
  read or write, no LLM.  Two builds are identical (P2).
- **Import-light, no viz import** — viz may import ``ari.config``; the
  reverse edge is forbidden (``scripts/check_import_boundaries.py``).
- **Read-only** — enumerating ``model_fields`` never instantiates or
  mutates ``ARIConfig``; ``simple_bfts`` behaviour and checkpoint artifacts
  are untouched (this module is inert unless the GUI calls it).
- **Coverage invariant** (plan 05 §Completion criteria): 100% of walked
  leaves must be covered by a :data:`FIELD_META` prefix or exact entry —
  :func:`get_uncovered` must return ``[]`` and
  :func:`build_field_registry` raises ``LookupError`` otherwise, so a new
  config field cannot silently ship without schema metadata.

Notes on fidelity:

- The walk covers **declared pydantic fields only**.  ``extra="allow"``
  blocks that exist solely as untyped YAML keys (``hpc``, ``container``,
  ``memory``, ``letta``, ``claim_gate_policy``, ``lineage_decision``, ...)
  have no ``model_fields`` entry and therefore no walked leaf; their
  :data:`FIELD_META` prefix entries are forward-declared documentation so
  the overlay is ready the day those blocks become typed.
- List-of-model / dict fields (``skills``, ``evaluator.custom_axes``,
  ``resources``, ``evaluator.axis_weights``) are **single leaves** with a
  composite ``value_type`` — element paths are index-dependent and would
  not be stable registry identities.  Nothing is excluded silently.
- :data:`ENV_OVERRIDES` is a literal transcription of the
  ``apply_*_env_overrides`` family in ``ari/config/__init__.py`` (plus the
  two documented ``auto_config``-path vars); it is pinned verbatim by
  ``tests/test_gui_config_field_registry.py``.
"""

from __future__ import annotations

import copy
import types
import typing

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from . import ARIConfig

# ── closed vocabularies (plan 05 §Canonical field metadata) ────────────────

LEVELS = ("basic", "advanced", "expert")
SCOPES = ("preference", "installation", "project", "template", "run")
SENSITIVITIES = ("public", "internal", "secret_reference")
MUTABILITIES = ("draft", "new_run_only", "resume_mutable", "read_only")

_REQUIRED_META_KEYS = ("category", "level", "scope", "sensitivity", "mutability")

# ── env override families (literal map, transcribed from ari/config) ───────
#
# One entry per config path an ``ARI_*`` variable overrides.  Sources:
#   _apply_llm_env_overrides        -> ARI_MODEL (alias ARI_LLM_MODEL),
#                                      ARI_BACKEND, ARI_LLM_API_BASE
#   _apply_checkpoint_env_overrides -> ARI_CHECKPOINT_DIR, ARI_LOG_DIR
#   apply_bfts_env_overrides        -> ARI_MAX_NODES, ARI_MAX_DEPTH,
#                                      ARI_MAX_REACT, ARI_PARALLEL,
#                                      ARI_TIMEOUT_NODE, ARI_FRONTIER_SCORE,
#                                      ARI_BFTS_ALLOW_WEB
#   apply_evaluator_env_overrides   -> ARI_COMPOSITE, ARI_AXIS_MODE
#   apply_rqgm_env_overrides        -> ARI_MODE, ARI_RQGM_ENABLED
#   apply_paper_env_overrides       -> ARI_PAPER_MODE, ARI_RQGM_PAPER_ENABLED,
#                                      ARI_PAPER_AGENT_AS_JUDGE
#   auto_config (no-YAML path only) -> ARI_LOG_LEVEL
ENV_OVERRIDES: dict[str, str] = {
    "llm.model": "ARI_MODEL",
    "llm.backend": "ARI_BACKEND",
    "llm.base_url": "ARI_LLM_API_BASE",
    "checkpoint.dir": "ARI_CHECKPOINT_DIR",
    "logging.dir": "ARI_LOG_DIR",
    "logging.level": "ARI_LOG_LEVEL",
    "bfts.max_total_nodes": "ARI_MAX_NODES",
    "bfts.max_depth": "ARI_MAX_DEPTH",
    "bfts.max_react_steps": "ARI_MAX_REACT",
    "bfts.max_parallel_nodes": "ARI_PARALLEL",
    "bfts.timeout_per_node": "ARI_TIMEOUT_NODE",
    "bfts.frontier_score": "ARI_FRONTIER_SCORE",
    "bfts.allow_web": "ARI_BFTS_ALLOW_WEB",
    "evaluator.composite": "ARI_COMPOSITE",
    "evaluator.axis_mode": "ARI_AXIS_MODE",
    "ari.mode": "ARI_MODE",
    "rqgm.enabled": "ARI_RQGM_ENABLED",
    "paper.mode": "ARI_PAPER_MODE",
    "rqgm.paper.enabled": "ARI_RQGM_PAPER_ENABLED",
    "rqgm.paper.reviewer.agent_as_judge.enabled": "ARI_PAPER_AGENT_AS_JUDGE",
}

# ── hand-authored metadata overlay ─────────────────────────────────────────
#
# Keys ending in "." are prefixes; other keys are exact paths.  Resolution
# merges every matching entry from the most general prefix to the exact
# path, so an exact entry may override a subset of its prefix defaults
# (including resetting inherited ``applies_when`` back to None).

_YAML_ONLY = (
    "yaml_only: no GUI wizard field or ARI_* env hook today — set via "
    "workflow.yaml."
)
_MODE_INTERLOCK = (
    "One intent with its interlock twin: `ari.mode: ari_rqgm` AND "
    "`rqgm.enabled: true` must agree or the runtime falls back to "
    "simple_bfts (warn + fallback, never an error).  ADR-09: selectable "
    "for a NEW run from one GUI control that writes BOTH keys; a document "
    "carrying only one of them is rejected `mode_interlock_mismatch`."
)
_PAPER_INTERLOCK = (
    "One intent with its interlock twin: `paper.mode: rqgm_archive` AND "
    "`rqgm.paper.enabled: true` must agree or the paper phase falls back "
    "to linear (warn + fallback, never an error).  ADR-09: selectable "
    "for a NEW run from one GUI control that writes BOTH keys; a document "
    "carrying only one of them is rejected `mode_interlock_mismatch`."
)
# applies_when notes naming the paired interlock (ADR-09: the pair is ONE
# user-facing intent).  Deliberately NOT the `path=value` gate grammar used
# by the tuning leaves: neither half of a pair is gated on the other (that
# would make the interlock self-gating and unreachable) — the note states
# the pairing, which is what the GUI renders next to the control.
_MODE_PAIR_NOTE = "paired with rqgm.enabled (one intent — set both)"
_MODE_PAIR_NOTE_TWIN = "paired with ari.mode (one intent — set both)"
_PAPER_PAIR_NOTE = "paired with rqgm.paper.enabled (one intent — set both)"
_PAPER_PAIR_NOTE_TWIN = "paired with paper.mode (one intent — set both)"

FIELD_META: dict[str, dict] = {
    # ── Models (plan 05 scope table: project default; secrets split out) ──
    "llm.": {
        "category": "Models",
        "level": "basic",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "draft",
    },
    "llm.model": {
        "notes": "Env alias ARI_LLM_MODEL is honored too (the "
                 "skill-subprocess bridge variable).",
    },
    "llm.api_key": {
        "scope": "installation",
        "sensitivity": "secret_reference",
        "notes": "Write-only secret reference — readiness/status only; the "
                 "value is never served by any schema/config API. Prefer "
                 "the provider env var (OPENAI_API_KEY, ...).",
    },
    "llm.temperature": {"level": "advanced"},
    # ── Skills ──
    "skills": {
        "category": "Skills",
        "level": "advanced",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "Auto-discovered (ari-skill-* scan) when the YAML omits "
                 "the section; one leaf — per-skill entries are not stable "
                 "registry paths.",
    },
    "disabled_tools": {
        "category": "Skills",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "The viz wizard appends to this list when bfts_pipeline "
                 "stages are toggled off.",
    },
    # ── Search (BFTS): 5 env-hooked core knobs basic/draft; the rest are
    #    advanced (frontier_score / allow_web, env-hooked) or expert
    #    yaml_only tuning knobs. ──
    "bfts.": {
        "category": "Search (BFTS)",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "draft",
    },
    "bfts.max_total_nodes": {"level": "basic"},
    "bfts.max_depth": {"level": "basic"},
    "bfts.max_react_steps": {"level": "basic"},
    "bfts.max_parallel_nodes": {"level": "basic"},
    "bfts.timeout_per_node": {"level": "basic"},
    "bfts.max_expansions_per_node": {"level": "expert", "notes": _YAML_ONLY},
    "bfts.label_saturation_threshold": {"level": "expert", "notes": _YAML_ONLY},
    "bfts.depth_penalty_lambda": {
        "level": "expert",
        "applies_when": "bfts.frontier_score=depth_penalized",
        "notes": _YAML_ONLY,
    },
    "bfts.ucb_c": {
        "level": "expert",
        "applies_when": "bfts.frontier_score=ucb_like",
        "notes": _YAML_ONLY,
    },
    "bfts.select_prompt": {"level": "expert", "notes": _YAML_ONLY},
    "bfts.expand_select_prompt": {"level": "expert", "notes": _YAML_ONLY},
    "bfts.expand_prompt": {"level": "expert", "notes": _YAML_ONLY},
    "bfts.allow_web": {
        "notes": "Opt-in non-reproducible trajectory (P5 marker "
                 "bfts_web_provenance.json).",
    },
    # ── Infrastructure: storage + logging (checkpoint-scoped since v0.5.0) ──
    "checkpoint.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "An explicit ARI_CHECKPOINT_DIR env path always wins.",
    },
    "logging.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "draft",
    },
    "logging.level": {
        "notes": "ARI_LOG_LEVEL is read on the auto_config (no-YAML) path "
                 "only; a workflow.yaml value is not env-overridden.",
    },
    "resources": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "Generic HPC resource defaults (cpus/memory_gb/gpus/"
                 "walltime/partition); auto_config fills it from "
                 "ARI_SLURM_* env vars.",
    },
    # ── Evaluation ──
    "evaluator.": {
        "category": "Evaluation",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "draft",
    },
    "evaluator.axis_weights": {"level": "expert", "notes": _YAML_ONLY},
    "evaluator.custom_axes": {
        "level": "expert",
        "applies_when": "evaluator.axis_mode=custom",
        "notes": _YAML_ONLY,
    },
    # ── Execution mode (the immutable-per-run algorithm switches) ──
    #
    # ADR-09 (accepted 2026-07-27): these four leaves — and ONLY these four —
    # are GUI-selectable for a NEW run (two orthogonal intents, each a
    # mode+interlock pair).  They stay ``new_run_only``/``scope: run``: the
    # project config still rejects them (``not_project_scope``) and a running
    # checkpoint's persisted mode still wins on resume.
    "ari.mode": {
        "category": "Execution mode",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": _MODE_PAIR_NOTE,
        "notes": _MODE_INTERLOCK,
    },
    "paper.mode": {
        "category": "Execution mode",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": _PAPER_PAIR_NOTE,
        "notes": _PAPER_INTERLOCK,
    },
    # ── Manuscript Complete (independent of research and paper modes) ──
    "manuscript.mode": {
        "category": "Manuscript completeness",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "notes": "off | audit | enforce; enforce gates authoring before the writer.",
    },
    "manuscript.profile": {
        "category": "Manuscript completeness",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "manuscript.mode!=off",
    },
    "manuscript.brief_character_budget": {
        "category": "Manuscript completeness",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "manuscript.mode!=off",
    },
    "manuscript.repair.": {
        "category": "Manuscript completeness",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "manuscript.mode=enforce",
        "notes": "Bounded repair policy and budgets; never expands run authority.",
    },
    # ── Knowledge / Provider Binding / Scientific Assurance ──
    # These are run-admission postures, frozen before the first execution
    # epoch. They are intentionally not preference/project settings and have
    # no env override that could alter a resumed run.
    "knowledge.mode": {
        "category": "Scientific assurance",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "ari.mode=ari_rqgm",
        "notes": "off | audit | enforce; Knowledge text grants no executable authority.",
    },
    "capability_binding.mode": {
        "category": "Scientific assurance",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "ari.mode=ari_rqgm",
        "notes": "legacy | audit | enforce; enforce exposes only deterministically bound tools.",
    },
    "assurance.mode": {
        "category": "Scientific assurance",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "ari.mode=ari_rqgm",
        "notes": "off | audit | enforce; enforce gates the scientific frontier and publication.",
    },
    # ── Governance (RQGM): expert, new-run-only, mode-gated ──
    "rqgm.": {
        "category": "Governance",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "ari.mode=ari_rqgm",
    },
    "rqgm.enabled": {
        "category": "Execution mode",
        "level": "advanced",
        # Never the inherited ``ari.mode=ari_rqgm`` gate (that would make the
        # interlock gate itself); the pairing note replaces it.
        "applies_when": _MODE_PAIR_NOTE_TWIN,
        "notes": _MODE_INTERLOCK,
    },
    "rqgm.paper.": {"applies_when": "paper.mode=rqgm_archive"},
    "rqgm.paper.enabled": {
        "category": "Execution mode",
        "level": "advanced",
        "applies_when": _PAPER_PAIR_NOTE_TWIN,
        "notes": _PAPER_INTERLOCK,
    },
    # ── Proposal routing (RQGM Task 03; record_only is the one knob also
    #    honored in simple_bfts) ──
    "proposal_router.": {
        "category": "Proposal routing",
        "level": "expert",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "applies_when": "ari.mode=ari_rqgm",
    },
    "proposal_router.record_only": {
        "applies_when": None,
        "notes": "Honored in simple_bfts too: record-only dual-write of "
                 "idea.json into proposal_records.jsonl (ablation B1, zero "
                 "behavior change).",
    },
    # ── Forward-declared prefixes for extra='allow' YAML blocks that have
    #    NO typed pydantic leaf today (they produce no registry rows yet;
    #    the metadata is ready the day the block becomes typed). ──
    "hpc.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "installation",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "notes": "Untyped workflow.yaml block (extra='allow'); profiles "
                 "merge only hpc.enabled/hpc.scheduler.",
    },
    "container.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "installation",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "notes": "Untyped workflow.yaml block (extra='allow').",
    },
    "memory.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "project",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "notes": "Untyped workflow.yaml block exported to env "
                 "(ARI_MEMORY_BACKEND / LETTA_BASE_URL / "
                 "LETTA_EMBEDDING_CONFIG) by _apply_memory_section.",
    },
    "letta.": {
        "category": "Infrastructure",
        "level": "advanced",
        "scope": "installation",
        "sensitivity": "public",
        "mutability": "new_run_only",
        "notes": "Untyped block (extra='allow'); Letta deployment knobs.",
    },
    "claim_gate_policy.": {
        "category": "Evaluation",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "Untyped workflow.yaml block (extra='allow'); Layer-0 "
                 "claim-evidence gate policy.",
    },
    "lineage_decision.": {
        "category": "Evaluation",
        "level": "advanced",
        "scope": "run",
        "sensitivity": "public",
        "mutability": "draft",
        "notes": "Untyped block (extra='allow'); LLM lineage-decision "
                 "model defaults live in ari/configs/defaults.yaml.",
    },
}


# ── leaf walk ──────────────────────────────────────────────────────────────


def _type_name(ann: object) -> str:
    """Deterministic readable name for a field annotation."""
    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        names = sorted({type(a).__name__ for a in typing.get_args(ann)})
        return " | ".join(names)
    if origin in (types.UnionType, typing.Union):
        return " | ".join(_type_name(a) for a in typing.get_args(ann))
    if origin is not None:
        args = typing.get_args(ann)
        base = getattr(origin, "__name__", str(origin))
        if not args:
            return base
        return f"{base}[{', '.join(_type_name(a) for a in args)}]"
    if ann is type(None):
        return "None"
    return getattr(ann, "__name__", str(ann))


def _is_nested_model(ann: object) -> bool:
    return isinstance(ann, type) and issubclass(ann, BaseModel)


def walk_config_leaves(
    model: type[BaseModel] = ARIConfig, prefix: str = ""
) -> list[dict]:
    """Enumerate every declared leaf of ``ARIConfig`` (depth-first, declared
    field order — deterministic).

    A *leaf* is any ``model_fields`` entry whose annotation is not itself a
    ``BaseModel`` subclass; nested models recurse with a dotted path.  Each
    leaf dict carries ``path`` / ``value_type`` / ``default`` (deep-copied,
    ``None`` when required) / ``enum`` (Literal values or ``None``) /
    ``required``.  Nothing is excluded silently — composite fields
    (``skills``, ``resources``, ...) appear as single typed leaves.
    """
    leaves: list[dict] = []
    for name, f in model.model_fields.items():
        path = f"{prefix}{name}"
        ann = f.annotation
        if _is_nested_model(ann):
            leaves.extend(walk_config_leaves(ann, prefix=f"{path}."))
            continue
        if f.default is not PydanticUndefined:
            default = f.default
        elif f.default_factory is not None:
            default = f.default_factory()
        else:
            default = None
        enum = (
            list(typing.get_args(ann))
            if typing.get_origin(ann) is typing.Literal
            else None
        )
        leaves.append(
            {
                "path": path,
                "value_type": _type_name(ann),
                "default": copy.deepcopy(default),
                "enum": enum,
                "required": f.is_required(),
            }
        )
    return leaves


# ── overlay resolution ─────────────────────────────────────────────────────


def _meta_matches(key: str, path: str) -> bool:
    """Keys ending in '.' are prefixes; all other keys are exact paths."""
    return path.startswith(key) if key.endswith(".") else path == key


def _matching_keys(path: str) -> list[str]:
    """All FIELD_META keys covering ``path``, most general first, exact last."""
    keys = [k for k in FIELD_META if _meta_matches(k, path)]
    keys.sort(key=lambda k: (not k.endswith("."), len(k)))
    return keys


def _resolve_meta(path: str) -> dict | None:
    """Merge every matching overlay entry (prefix defaults, exact override)."""
    keys = _matching_keys(path)
    if not keys:
        return None
    meta: dict = {"applies_when": None, "notes": None}
    for k in keys:
        meta.update(FIELD_META[k])
    return meta


def _validate_meta(path: str, meta: dict) -> None:
    missing = [k for k in _REQUIRED_META_KEYS if k not in meta]
    if missing:
        raise ValueError(
            f"FIELD_META for {path!r} is missing required keys {missing} "
            "after prefix/exact merge"
        )
    for key, allowed in (
        ("level", LEVELS),
        ("scope", SCOPES),
        ("sensitivity", SENSITIVITIES),
        ("mutability", MUTABILITIES),
    ):
        if meta[key] not in allowed:
            raise ValueError(
                f"FIELD_META for {path!r}: {key}={meta[key]!r} not in {allowed}"
            )


def get_uncovered() -> list[str]:
    """Leaf paths with NO FIELD_META coverage (prefix or exact).

    The plan-05 completion criterion pins this to ``[]``; a non-empty result
    means a config field was added without registry metadata.
    """
    return [
        leaf["path"]
        for leaf in walk_config_leaves()
        if not _matching_keys(leaf["path"])
    ]


# ── registry build ─────────────────────────────────────────────────────────


def build_field_registry() -> list[dict]:
    """Walk + overlay -> the canonical list of ConfigFieldMeta dicts.

    Raises ``LookupError`` when any leaf is uncovered (fail loudly — the
    coverage invariant is enforced at runtime, not only in tests).  Fields
    whose merged sensitivity is ``secret_reference`` have their ``default``
    forced to ``None``: the value/default channel is closed for secrets even
    when the pydantic default is trivially empty.
    """
    uncovered = get_uncovered()
    if uncovered:
        raise LookupError(
            "config leaves without FIELD_META coverage — add a prefix or "
            "exact entry to ari.config.field_registry.FIELD_META for: "
            f"{uncovered}"
        )
    entries: list[dict] = []
    for leaf in walk_config_leaves():
        meta = _resolve_meta(leaf["path"])
        assert meta is not None  # guaranteed by the uncovered check above
        _validate_meta(leaf["path"], meta)
        secret = meta["sensitivity"] == "secret_reference"
        entries.append(
            {
                "path": leaf["path"],
                "value_type": leaf["value_type"],
                "default": None if secret else leaf["default"],
                "enum": leaf["enum"],
                "required": leaf["required"],
                "category": meta["category"],
                "level": meta["level"],
                "scope": meta["scope"],
                "sensitivity": meta["sensitivity"],
                "mutability": meta["mutability"],
                "applies_when": meta.get("applies_when"),
                "notes": meta.get("notes"),
                "source": "pydantic",
                "env_override": ENV_OVERRIDES.get(leaf["path"]),
            }
        )
    return entries


# ── patch validation (gui_refresh task 05 Wave 3b) ─────────────────────────
#
# Pure helper backing the /api/v1 config CRUD PATCH bodies
# (``{"values": {"dotted.path": value}}``).  Same purity contract as the
# rest of this module: no filesystem, no clock, no env, no mutation — two
# calls with equal inputs return equal outputs (P2).

# Where a patch is being applied.  ``new_run_only`` fields are legitimate in
# templates/drafts (they configure FUTURE runs) but are rejected in the
# project config unless their scope is ``project`` (plan 05 §Configuration
# scopes: the project document holds project-scoped defaults).
PATCH_TARGETS = ("project_config", "run_template", "run_draft")

# The closed ``reason`` vocabulary of this module's patch validators.  Any
# new code emitting a rejection reason MUST add it here (the GUI renders the
# vocabulary and the API contract documents it).
PATCH_REASONS = (
    "unknown_path",
    "secret_reference",
    "read_only",
    "not_project_scope",
    "invalid_enum",
    "invalid_type",
    # ADR-09: the two mode intents are pairs; a document that names one half
    # of a pair without the other (or with a disagreeing twin) is rejected.
    "mode_interlock_mismatch",
)

# The two mode intents, each ``(mode path, interlock path, active mode value,
# fallback mode value)``.  ``ari.rqgm.mode.resolve_effective_mode`` /
# ``ari.rqgm.paper_mode.resolve_paper_mode`` are the authority on the runtime
# semantics (warn + fall back to the fallback value); this tuple is the
# registry-side transcription both the resolver interlock pass
# (``ari.config.resolver.INTERLOCK_PAIRS``) and the GUI mode selection reuse
# so the three can never drift apart.
MODE_INTERLOCK_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("ari.mode", "rqgm.enabled", "ari_rqgm", "simple_bfts"),
    ("paper.mode", "rqgm.paper.enabled", "rqgm_archive", "linear"),
)

# The four leaves ADR-09 makes GUI-selectable for a NEW run (the union of the
# pairs above) — every OTHER ``rqgm.*`` tuning leaf stays out of the GUI.
MODE_SELECTION_PATHS: frozenset[str] = frozenset(
    p for pair in MODE_INTERLOCK_PAIRS for p in pair[:2]
)


def _split_union(value_type: str) -> list[str]:
    """Split a registry ``value_type`` on top-level ``|`` only (never inside
    ``list[...]`` / ``dict[...]`` brackets)."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in value_type:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _split_top_commas(inner: str) -> list[str]:
    """Split ``dict[K, V]`` argument text on top-level commas only."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in inner:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def value_matches_type(value: object, value_type: str) -> bool:
    """Structural check of one JSON value against a registry ``value_type``
    string (the :func:`_type_name` grammar).

    ``bool`` is never accepted where ``int``/``float`` is expected (JSON has
    a real boolean type; ``True == 1`` must not slip through).  ``float``
    accepts an ``int`` (JSON ``2`` is a valid ``2.0``).  Nested-model
    composite elements (``SkillConfig``, ``CustomAxisSpec``, ...) accept any
    JSON object — element-level validation is out of scope for the registry
    (they are single composite leaves by design, see the module docstring).
    """
    members = _split_union(value_type)
    if len(members) > 1:
        return any(value_matches_type(value, m) for m in members)
    t = members[0]
    if t == "None":
        return value is None
    if t == "bool":
        return isinstance(value, bool)
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "str":
        return isinstance(value, str)
    if t == "list" or t.startswith("list["):
        if not isinstance(value, list):
            return False
        if t == "list":
            return True
        inner = t[len("list["):-1]
        return all(value_matches_type(v, inner) for v in value)
    if t == "dict" or t.startswith("dict["):
        if not isinstance(value, dict):
            return False
        if t == "dict":
            return True
        args = _split_top_commas(t[len("dict["):-1])
        if len(args) != 2:  # unparseable args — accept the dict shape
            return True
        k_t, v_t = args
        return all(
            value_matches_type(k, k_t) and value_matches_type(v, v_t)
            for k, v in value.items()
        )
    # Nested-model composite (single-leaf by design): accept a JSON object.
    return isinstance(value, dict)


def validate_patch(
    values: dict, *, target: str = "run_template"
) -> list[dict]:
    """Validate one ``{dotted.path: value}`` patch map against the registry.

    Returns ``[]`` when the whole patch is acceptable, else one error dict
    per offending path (paths in sorted order — deterministic, P2)::

        {"path": ..., "reason": ..., "message": ...[, "expected": ...]}

    ``reason`` vocabulary (closed — :data:`PATCH_REASONS`): ``unknown_path``,
    ``secret_reference``, ``read_only``, ``not_project_scope``,
    ``invalid_enum``, ``invalid_type`` (this function) and
    ``mode_interlock_mismatch`` (:func:`validate_mode_interlocks`, the
    cross-path pass this one cannot express).  ``expected`` carries the
    allowed enum values (``invalid_enum``), the registry ``value_type``
    string (``invalid_type``) or the consistent pair alternatives
    (``mode_interlock_mismatch``).

    Mutability policy (plan 05 §Configuration scopes):

    - ``read_only`` fields are rejected for every target;
    - ``secret_reference`` fields are rejected for every target (secrets go
      through their own write-only flow, never the config API);
    - ``new_run_only`` fields are allowed in ``run_template``/``run_draft``
      (they configure future runs) but rejected in ``project_config`` when
      their scope is not ``project``.
    """
    if target not in PATCH_TARGETS:
        raise ValueError(
            f"unknown patch target {target!r} (choose from {PATCH_TARGETS})"
        )
    if not isinstance(values, dict):
        raise ValueError("values must be a dict of {dotted.path: value}")
    registry = {e["path"]: e for e in build_field_registry()}
    errors: list[dict] = []
    for path in sorted(values, key=str):
        value = values[path]
        if not isinstance(path, str):
            errors.append(
                {
                    "path": str(path),
                    "reason": "unknown_path",
                    "message": f"config paths must be strings, got {path!r}",
                }
            )
            continue
        entry = registry.get(path)
        if entry is None:
            errors.append(
                {
                    "path": path,
                    "reason": "unknown_path",
                    "message": f"unknown config path: {path}",
                }
            )
            continue
        if entry["sensitivity"] == "secret_reference":
            errors.append(
                {
                    "path": path,
                    "reason": "secret_reference",
                    "message": (
                        f"{path} is a secret reference — secrets go through "
                        "the dedicated secrets flow, never the config API"
                    ),
                }
            )
            continue
        if entry["mutability"] == "read_only":
            errors.append(
                {
                    "path": path,
                    "reason": "read_only",
                    "message": f"{path} is read_only and cannot be patched",
                }
            )
            continue
        if (
            target == "project_config"
            and entry["mutability"] == "new_run_only"
            and entry["scope"] != "project"
        ):
            errors.append(
                {
                    "path": path,
                    "reason": "not_project_scope",
                    "message": (
                        f"{path} is new_run_only with scope "
                        f"{entry['scope']!r} — set it on a run template or "
                        "run draft, not the project config"
                    ),
                }
            )
            continue
        if entry["enum"] is not None and value not in entry["enum"]:
            errors.append(
                {
                    "path": path,
                    "reason": "invalid_enum",
                    "expected": list(entry["enum"]),
                    "message": (
                        f"{path} must be one of {entry['enum']!r}, "
                        f"got {value!r}"
                    ),
                }
            )
            continue
        if not value_matches_type(value, entry["value_type"]):
            errors.append(
                {
                    "path": path,
                    "reason": "invalid_type",
                    "expected": entry["value_type"],
                    "message": (
                        f"{path} expects {entry['value_type']}, "
                        f"got {type(value).__name__}"
                    ),
                }
            )
    return errors


def validate_mode_interlocks(values) -> list[dict]:
    """Paired-intent check for the two ADR-09 mode pairs — the cross-path
    rule :func:`validate_patch` (one path at a time) cannot express.

    *values* is one ``{dotted.path: value}`` map of the EFFECTIVE document
    values a launch would use: a single document's merged values (PATCH) or
    the union of the project/template/draft layer maps (launch).  Same purity
    contract as the rest of this module: no filesystem, no clock, no env.

    Rule (plan 05 §Interlocks, ADR-09): if either key of a pair appears, BOTH
    must appear and agree — ``ari.mode=ari_rqgm`` ⇔ ``rqgm.enabled=true`` and
    ``paper.mode=rqgm_archive`` ⇔ ``rqgm.paper.enabled=true``.  A half-set or
    disagreeing pair is a hard error here (reason
    ``mode_interlock_mismatch``, one error per offending pair keyed on the
    MODE path), even though the runtime resolves the same disagreement
    warn+fallback — the GUI must not launch an intent it cannot honor.
    ``expected`` carries the two consistent alternatives verbatim.
    """
    if not isinstance(values, dict):
        raise ValueError("values must be a dict of {dotted.path: value}")
    errors: list[dict] = []
    for mode_path, enable_path, active, fallback in MODE_INTERLOCK_PAIRS:
        has_mode = mode_path in values
        has_enable = enable_path in values
        if not (has_mode or has_enable):
            continue  # the pair is untouched — the defaults are consistent
        alternatives = [
            {mode_path: fallback, enable_path: False},
            {mode_path: active, enable_path: True},
        ]
        if has_mode and has_enable:
            mode_v, enable_v = values[mode_path], values[enable_path]
            if (mode_v == active) == (enable_v is True):
                continue
            message = (
                f"{mode_path}={mode_v!r} and {enable_path}={enable_v!r} "
                "disagree — the pair is ONE intent; set "
                f"{{{mode_path}: {active}, {enable_path}: true}} or "
                f"{{{mode_path}: {fallback}, {enable_path}: false}}"
            )
        else:
            present, missing = (
                (mode_path, enable_path) if has_mode
                else (enable_path, mode_path)
            )
            message = (
                f"{present}={values[present]!r} is set without its interlock "
                f"twin {missing} — the pair is ONE intent; set "
                f"{{{mode_path}: {active}, {enable_path}: true}} or "
                f"{{{mode_path}: {fallback}, {enable_path}: false}}"
            )
        errors.append(
            {
                "path": mode_path,
                "reason": "mode_interlock_mismatch",
                "expected": alternatives,
                "message": message,
            }
        )
    return errors
