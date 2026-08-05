"""Ablation-condition expansion (RQGM Task 13 §5.1/§6).

The nine conditions B0-B8 are named presets in
``scripts/rqgm_eval/ablation_matrix.yaml``. A preset only sets ``ari.mode``,
``rqgm.*`` and ``proposal_router.*`` feature flags defined by Tasks 01-11
under their own names — Task 13 invents no runtime switch. ``inherits`` is
harness-side deep-merge sugar making the additive ladder explicit.

Everything here is pure and deterministic: expansion of the same matrix
always yields the same overlay dict (P2).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import yaml

#: The closed condition vocabulary (plan 13 §5.1).
CONDITION_IDS: tuple[str, ...] = (
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8",
)

#: The paper-archive B-baseline ladder (paper-archive Task 07 §5.6). Named
#: presets in the ablation matrix's `paper_conditions` block that expand to
#: `paper.mode` + `rqgm.paper.*` flag sets owned by paper-archive Tasks 01-06 —
#: Task 07 invents no new runtime switch. `B0_paper_linear` == the shipped
#: default paper config (the control).
PAPER_CONDITION_IDS: tuple[str, ...] = (
    "B0_paper_linear", "B_archive_no_coevo", "B_full",
)

#: RQGM-original-paper-aligned comparison arms. These are evaluation presets
#: over the existing ``rqgm_archive`` runtime, not additional paper modes.
RQGM_PAPER_CONDITION_IDS: tuple[str, ...] = (
    "P0_hgm_h_fixed_critic",
    "P1_rqgm_replacement_only",
    "P2_rqgm_no_erasure",
    "P3_rqgm_full",
    "P4_constitutional_rqgm",
)

#: ``eval_defaults.models`` role → the phase env var ``build_runtime`` /
#: the evaluator actually read (per-campaign model pinning, plan 13 §5.2).
MODEL_ENV_VARS: dict = {
    "coding": "ARI_MODEL_CODING",
    "bfts": "ARI_MODEL_BFTS",
    "eval": "ARI_MODEL_EVAL",
    "paper": "ARI_MODEL_PAPER",
    "rubric": "ARI_MODEL_RUBRIC",
}

#: ``${VAR}``-style placeholder accepted in ``eval_defaults.models`` values.
_ENV_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")

#: Rungs whose expansion must be additive over the previous rung
#: (B2/B3 fork only on VirSci and are excepted; B0->B1 is additive too).
ADDITIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("B0", "B1"),
    ("B3", "B4"),
    ("B4", "B5"),
    ("B5", "B6"),
    ("B6", "B7"),
    ("B7", "B8"),
)


def default_matrix_path() -> Path:
    """``scripts/rqgm_eval/ablation_matrix.yaml`` at the repo root.

    Resolved relative to this file (``ari-core/ari/rqgm/evaluation/`` →
    four parents up is the repo root, the ``ari.config`` ``{{ari_root}}``
    convention). May not exist on an installed package — callers pass an
    explicit path then.
    """
    return (
        Path(__file__).resolve().parents[4]
        / "scripts" / "rqgm_eval" / "ablation_matrix.yaml"
    )


def load_matrix(path: "str | Path | None" = None) -> dict:
    """Parse the ablation matrix YAML. Raises on a missing/invalid file —
    the harness must never run with a half-defined condition set."""
    p = Path(path) if path is not None else default_matrix_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "conditions" not in data:
        raise ValueError(f"ablation matrix {p} has no `conditions:` mapping")
    return data


def deep_merge(base: dict, overlay: dict) -> dict:
    """Pure recursive dict merge; *overlay* leaves win. Inputs unmodified."""
    out = copy.deepcopy(dict(base))
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def expand_condition(matrix: dict, condition_id: str) -> dict:
    """Resolve one preset to its concrete flag set (``inherits`` folded in).

    Returns the preset dict without the ``inherits`` key: ``mode`` plus the
    ``rqgm``/``proposal_router`` overlay blocks. Unknown ids and inheritance
    cycles raise ``KeyError``/``ValueError``.
    """
    conditions = matrix.get("conditions") or {}
    seen: list[str] = []
    cid = str(condition_id)
    chain: list[dict] = []
    while True:
        if cid in seen:
            raise ValueError(f"inheritance cycle at {cid!r}: {seen}")
        seen.append(cid)
        preset = conditions.get(cid)
        if preset is None:
            raise KeyError(
                f"unknown ablation condition {cid!r} "
                f"(known: {sorted(conditions)})"
            )
        chain.append(dict(preset))
        parent = preset.get("inherits")
        if parent is None:
            break
        cid = str(parent)
    expanded: dict = {}
    for preset in reversed(chain):
        preset = {k: v for k, v in preset.items() if k != "inherits"}
        expanded = deep_merge(expanded, preset)
    return expanded


def _expand_chain(conditions: dict, condition_id: str, *, block: str) -> dict:
    """Fold ``inherits`` for one preset in *conditions* (shared by the
    exploration and paper ladders)."""
    seen: list[str] = []
    cid = str(condition_id)
    chain: list[dict] = []
    while True:
        if cid in seen:
            raise ValueError(f"inheritance cycle at {cid!r}: {seen}")
        seen.append(cid)
        preset = conditions.get(cid)
        if preset is None:
            raise KeyError(
                f"unknown {block} condition {cid!r} "
                f"(known: {sorted(conditions)})"
            )
        chain.append(dict(preset))
        parent = preset.get("inherits")
        if parent is None:
            break
        cid = str(parent)
    expanded: dict = {}
    for preset in reversed(chain):
        preset = {k: v for k, v in preset.items() if k != "inherits"}
        expanded = deep_merge(expanded, preset)
    return expanded


def expand_paper_condition(matrix: dict, condition_id: str) -> dict:
    """Resolve one paper-archive B-ladder preset to its concrete
    ``paper.mode`` + ``rqgm.paper.*`` flag set (``inherits`` folded in;
    paper-archive Task 07 §5.6).

    Reads the ablation matrix's ``paper_conditions:`` block. Unlike the
    exploration presets, the paper presets are ALREADY in workflow config-path
    form (``paper: {mode: ...}`` / ``rqgm: {paper: {...}}``), so the expansion
    IS the overlay — Task 07 defines no runtime switch, only requires the
    Tasks 01-06 flags. ``B0_paper_linear`` expands to the shipped default paper
    config (``paper.mode: linear``, ``rqgm.paper.enabled: false``).
    """
    conditions = matrix.get("paper_conditions") or {}
    if not conditions:
        raise ValueError("ablation matrix has no `paper_conditions:` mapping")
    return _expand_chain(conditions, condition_id, block="paper")


def paper_condition_overlay(matrix: dict, condition_id: str) -> dict:
    """The workflow.yaml overlay for one paper-archive condition. The paper
    presets are config-path native (§5.6), so the overlay is the expansion —
    the ``paper`` and ``rqgm`` blocks passed through under their own paths."""
    preset = expand_paper_condition(matrix, condition_id)
    overlay: dict = {}
    for block in ("paper", "rqgm", "bfts"):
        if isinstance(preset.get(block), dict):
            overlay[block] = copy.deepcopy(preset[block])
    return overlay


def expand_rqgm_paper_condition(matrix: dict, condition_id: str) -> dict:
    """Resolve one RQGM-paper-aligned P0-P4 evaluation preset.

    The presets live in ``rqgm_paper_conditions:`` and expand to ordinary
    workflow paths. Every condition uses ``paper.mode: rqgm_archive``; the
    P identifier is carried only under the evaluation interlock.
    """

    conditions = matrix.get("rqgm_paper_conditions") or {}
    if not conditions:
        raise ValueError(
            "ablation matrix has no `rqgm_paper_conditions:` mapping"
        )
    return _expand_chain(
        conditions, condition_id, block="RQGM-paper",
    )


def rqgm_paper_condition_overlay(matrix: dict, condition_id: str) -> dict:
    """Workflow overlay for an RQGM-paper-aligned P0-P4 condition."""

    preset = expand_rqgm_paper_condition(matrix, condition_id)
    overlay: dict = {}
    for block in ("paper", "rqgm", "bfts"):
        if isinstance(preset.get(block), dict):
            overlay[block] = copy.deepcopy(preset[block])
    return overlay


#: The anchor-corpus case namespace the fixed external panel must never touch
#: (paper-archive Task 07 §5.5 disjointness).
_ANCHOR_ID_PREFIX = "anchor_"


def panel_disjointness_violations(
    panel: dict, reviewer_prompt_lineage=(), panel_input_ids=()
) -> list:
    """The §5.5/R1 hard harness check (empty == disjoint).

    The fixed external reviewer panel MUST NOT reuse the co-evolving
    ``paper_reviewer`` prompt lineage (else acceptance rate measures
    self-agreement) and MUST NOT read any ``anchor_*`` case (else the panel
    grades on the same corpus the reviewer trained against). *panel* carries
    ``{rubrics, ...}``; *reviewer_prompt_lineage* the run's active/historical
    ``paper_reviewer`` prompt hashes/ids; *panel_input_ids* the ids fed to the
    panel run. Pure, deterministic (P2)."""
    out: list = []
    lineage = frozenset(str(x) for x in (reviewer_prompt_lineage or ()))
    rubrics = list((panel or {}).get("rubrics") or ())
    for rubric in rubrics:
        if str(rubric) in lineage:
            out.append(
                f"panel rubric {rubric!r} collides with the paper_reviewer "
                f"prompt lineage"
            )
    for pid in panel_input_ids or ():
        if str(pid).startswith(_ANCHOR_ID_PREFIX):
            out.append(
                f"anchor case {pid!r} leaked into the panel inputs "
                f"(anchor_* is held out from the panel)"
            )
    return out


def condition_overlay(matrix: dict, condition_id: str) -> dict:
    """The workflow.yaml overlay for one condition.

    Maps the preset's ``mode`` key to the ``ari.mode`` config path and
    passes the ``rqgm`` / ``proposal_router`` blocks through under the
    owning tasks' own config paths (plan 13 §5.1).
    """
    preset = expand_condition(matrix, condition_id)
    overlay: dict = {}
    if "mode" in preset:
        overlay["ari"] = {"mode": str(preset["mode"])}
    for block in ("rqgm", "proposal_router", "bfts"):
        if isinstance(preset.get(block), dict):
            overlay[block] = copy.deepcopy(preset[block])
    return overlay


def eval_defaults_overlay(matrix: dict) -> dict:
    """The §5.2 node-budget parity block shared by every condition.

    Returns ``{"bfts": {...}}`` from ``eval_defaults.bfts`` (``{}`` when the
    matrix declares none). The harness merges it UNDER each condition
    overlay, so a preset could still override it explicitly — no shipped
    preset does, which is what makes ``max_total_nodes`` / ``max_depth``
    identical across the whole B0-B8 ladder.
    """
    defaults = (matrix.get("eval_defaults") or {}).get("bfts")
    if not isinstance(defaults, dict) or not defaults:
        return {}
    return {"bfts": copy.deepcopy(defaults)}


def resolve_models(matrix: dict, env) -> dict:
    """Resolve ``eval_defaults.models`` to pinned phase env vars (§5.2).

    Returns the declared ``ARI_MODEL_*`` phase variables for the harness to
    stamp on every spawned run (coding, BFTS, evaluation, paper writing, and
    fixed rubric review),
    so one campaign-start snapshot pins the models for all conditions.
    ``${VAR}`` values are expanded against *env* (a mapping — the caller
    passes its ``os.environ`` snapshot; nothing is read here, P2); entries
    that resolve empty are dropped and the run falls through to
    workflow.yaml's ``llm.model``. Unknown roles raise ``ValueError`` — a
    typo must not silently unpin a campaign model.
    """
    models = (matrix.get("eval_defaults") or {}).get("models") or {}
    out: dict = {}
    for role in sorted(models):
        var = MODEL_ENV_VARS.get(str(role))
        if var is None:
            raise ValueError(
                f"unknown model role {role!r} in eval_defaults.models "
                f"(known: {sorted(MODEL_ENV_VARS)})"
            )
        value = str(models[role] or "")
        placeholder = _ENV_PLACEHOLDER.match(value)
        if placeholder:
            value = str(env.get(placeholder.group(1)) or "")
        if value:
            out[var] = value
    return out


def flag_paths(preset: dict, prefix: str = "") -> dict:
    """Flatten a preset/overlay to ``dotted.path -> leaf value``."""
    out: dict = {}
    for key, value in (preset or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flag_paths(value, path))
        else:
            out[path] = value
    return out


def enabled_flag_paths(preset: dict) -> frozenset:
    """The dotted paths whose leaf value is ``True`` (the "feature set" of
    the §5.1 additive-ladder property)."""
    return frozenset(
        path for path, value in flag_paths(preset).items() if value is True
    )


def virsci_enabled(overlay: dict) -> bool:
    """Whether an expanded overlay switches the VirSci generator on."""
    return (
        ((overlay.get("proposal_router") or {}).get("generators") or {})
        .get("virsci") or {}
    ).get("enabled") is True


#: VirSci transcript artifacts referenced (never copied) from
#: ProposalRecords — Task 03's on-disk layout.
VIRSCI_ARTIFACTS: tuple[str, ...] = ("virsci_logs", "virsci_snapshot")


def virsci_absence_violations(checkpoint_dir: "str | Path") -> list:
    """The §5.2 VirSci-off assertion over a completed checkpoint.

    Empty == VirSci-free: no VirSci prompt use in ``prompt_trace.jsonl``,
    no VirSci transcript artifacts (``virsci_logs/``, ``virsci_snapshot/``),
    and no ``generator: virsci`` ProposalRecord. Pure read-only scan (P2);
    an absent file is VirSci-free by construction; unparseable lines are
    skipped (the trace's absence-tolerant convention).
    """
    ckpt = Path(checkpoint_dir)
    out: list = []
    for name in VIRSCI_ARTIFACTS:
        if (ckpt / name).exists():
            out.append(f"VirSci transcript artifact present: {name}/")

    def _lines(path: Path):
        if not path.is_file():
            return
        for raw in path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(line, dict):
                yield line

    for line in _lines(ckpt / "prompt_trace.jsonl"):
        name = str(line.get("prompt_name") or "")
        if "virsci" in name.lower():
            out.append(f"VirSci prompt use in prompt_trace.jsonl: {name}")
    for line in _lines(ckpt / "proposals" / "proposal_records.jsonl"):
        if str(line.get("generator") or "") == "virsci":
            out.append(
                "VirSci-generated ProposalRecord: "
                f"{line.get('record_id') or '?'}"
            )
    return out


# Backward-compatible import surface: Task-20 conditions live in a separate
# evaluation module so the original B-axis implementation stays compact and
# semantically unchanged.
from ari.rqgm.evaluation.kca_conditions import (  # noqa: E402,F401
    ASSURANCE_CONDITION_IDS,
    FULL_KCA_CONDITION_ALIAS,
    KNOWLEDGE_CAPABILITY_CONDITION_IDS,
    assurance_condition_overlay,
    evaluation_condition_overlay,
    expand_assurance_condition,
    expand_knowledge_capability_condition,
    factorial_condition_id,
    factorial_condition_overlay,
    knowledge_capability_condition_overlay,
    parse_factorial_condition_id,
)
