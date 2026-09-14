"""Legacy-compatible resolved-config reconstruction (gui_refresh task 05
Wave 3a) + new-run preview resolution (Wave 3b).

:func:`resolve_run_config` explains an EXISTING checkpoint post-hoc: it
rebuilds the effective run configuration the legacy imperative chain
(``load_config`` + the ``apply_*_env_overrides`` family in
``ari/cli/run.py:222-232``) would produce, as the plan-05 §Resolved manifest
shape — values + per-leaf provenance + digest + warnings — without running
any of that chain.  ``resolver_version = "legacy-compatible-1"`` (plan 05
§Resolution model: the initial resolver reproduces today's context-specific
precedence; golden parity is pinned by
``tests/test_gui_config_resolver.py``).

Layer order for an existing checkpoint::

    pydantic defaults                         (source "default",  confidence high)
    -> {ckpt}/workflow.yaml model-field keys  (source "workflow", confidence high)
    -> {ckpt}/launch_config.json knobs        (source "launch_config", high)
    -> CURRENT env, documented ARI_* only     (source "env",      confidence LOW)
    -> {ckpt}/rqgm_state.json persisted mode  (source "checkpoint_state", high,
                                               mutable false — a run's mode is
                                               immutable, reconcile_resume_mode)

:func:`resolve_new_run_config` (Wave 3b) previews the plan-05 §Resolution
model / New run chain for a run that does NOT exist yet::

    pydantic defaults                          (source "default")
    -> BUNDLED config/workflow.yaml            (source "workflow")
    -> selected execution profile              (source "profile" — EXACTLY the
       real 4-key ``_apply_profile`` merge: bfts.max_total_nodes,
       bfts.max_parallel_nodes|parallel, hpc.enabled -> resources.hpc_enabled,
       hpc.scheduler -> resources.scheduler; every other profile key is
       ignored WITH a warning listing the ignored keys)
    -> project config values                   (source "project")
    -> run template values                     (source "template")
    -> run draft values                        (source "draft")
    -> documented ARI_* env overrides          (source "env", confidence low)
    -> validated effective (ARIConfig construction; a value pydantic rejects
       reverts to the last VALID layer value with a ``rejected_override``
       provenance annotation + warning — plan 05: rejected/ignored overrides
       are returned as explanations, never silently dropped)
    -> interlock resolution (ari.mode+rqgm.enabled / paper.mode+
       rqgm.paper.enabled — ``resolve_effective_mode`` parity: mismatch is a
       warning + fallback, and the manifest shows the EFFECTIVE mode)

Same manifest shape as the existing-checkpoint mode; ``source_stack`` lists
only the layers actually present (a documented deviation from the
existing-checkpoint mode, whose stack always contains "env").  ``run_id`` is
``None`` (no run exists — the API caller fills it with the draft id).
Provenance sources are the short layer names ``default / workflow / profile
/ project / template / draft / env`` (the plan-05 example's
``run_template``/``run_draft`` spellings are normalized to the
source_stack vocabulary).  ``mutable`` is ``True`` for every non-read_only
field: before launch even ``new_run_only`` fields are still editable.

Design constraints (plan 05 + INDEX.md invariant):

- **Read-only** — reads checkpoint files and (optionally) the environment;
  never writes a file, never touches ``os.environ``, never mutates
  ``ARIConfig``.  ``simple_bfts`` behaviour and checkpoint artifacts are
  untouched; the module is inert unless the GUI calls it.
- **Deterministic** — no clock (``resolved_at`` is ``None``; the API caller
  fills it from source-file mtimes), no randomness.  Two calls with the same
  checkpoint + env mapping return identical manifests; the digest is
  ``sha256:`` over the redacted canonical values JSON only, so env noise
  outside the documented families never moves it.
- **Secrets never in values** — leaves whose ``field_registry`` sensitivity
  is ``secret_reference`` are excluded from ``values``/``provenance``/the
  digest input entirely and surface only as configured-flag entries in
  ``secret_references``.
- **No viz import** — viz may import ``ari.config``; the reverse edge is
  forbidden (``scripts/check_import_boundaries.py``).

Fidelity notes (what is deliberately NOT reconstructed):

- ``skills`` auto-discovery (``_discover_skills``) and the ``allow_web``
  web-skill phase rewrite are runtime-only; a warning marks the gap.
- checkpoint ``settings.json`` is not an overlay layer: it reaches a run
  only via the launch-time env translation, which ``launch_config.json``
  (the launch snapshot) and the env layer already represent.
- Profiles (``--profile``) merge only 4 keys and are not recorded anywhere
  in the checkpoint; their effect is visible only through
  ``launch_config.json``/env.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

import yaml

from . import ARIConfig
from .field_registry import (ENV_OVERRIDES, MODE_INTERLOCK_PAIRS,
                             build_field_registry)

SCHEMA_VERSION = 1
RESOLVER_VERSION = "legacy-compatible-1"

# ── literal transcriptions of the legacy chain's accept-sets ───────────────

_FRONTIER_SCORES = (
    "scientific_plus_diversity", "scientific_only", "depth_penalized",
    "ucb_like",
)
_COMPOSITES = (
    "harmonic_mean", "arithmetic_mean", "weighted_min", "geometric_mean",
)
_AXIS_MODES = ("legacy", "dynamic", "custom")
_TRUE_SET = ("1", "true")
_FALSE_SET = ("0", "false")
_ON_SET = ("1", "true", "yes", "on")

# launch_config.json key -> config leaf path.  Transcribed from the
# ``_launch_cfg`` snapshot writer in ``ari/viz/api_experiment.py::_api_launch``
# (the launcher records the EFFECTIVE ARI_* env values it injected, so this
# layer sits between workflow.yaml and the current-env overlay).
LAUNCH_CONFIG_MAP: tuple[tuple[str, str], ...] = (
    ("llm_model", "llm.model"),
    ("llm_provider", "llm.backend"),
    ("max_nodes", "bfts.max_total_nodes"),
    ("max_depth", "bfts.max_depth"),
    ("max_react", "bfts.max_react_steps"),
    ("timeout_node_s", "bfts.timeout_per_node"),
    ("parallel", "bfts.max_parallel_nodes"),
    ("frontier_score", "bfts.frontier_score"),
    ("composite", "evaluator.composite"),
    ("axis_mode", "evaluator.axis_mode"),
    ("allow_web", "bfts.allow_web"),
)

# The config paths the env overlay may touch — exactly the documented
# ``ENV_OVERRIDES`` families of ``ari.config.field_registry`` (pinned equal
# by tests/test_gui_config_resolver.py so the two transcriptions cannot
# drift apart).
ENV_FAMILY_PATHS: frozenset[str] = frozenset(ENV_OVERRIDES)

# workflow.yaml top-level keys that are NOT ``ARIConfig`` fields but ARE
# consumed by other known readers (pipeline driver, env exporters, claim
# gate, profile merge, ...) — dropping them from the typed config is not a
# silent loss, so they produce no warning.  Anything else outside
# ``ARIConfig.model_fields`` is silently dropped everywhere and IS warned.
KNOWN_NON_CONFIG_TOP_KEYS: frozenset[str] = frozenset({
    "author_name",         # paper metadata (paper pipeline)
    "bfts_pipeline",       # _merge_bfts_disabled_tools + pipeline driver
    "claim_gate_policy",   # Layer-0 claim-evidence gate (raw YAML read)
    "container",           # cli/run.py container setup (raw YAML read)
    "hpc",                 # profile merge (cli/run.py _apply_profile)
    "letta",               # Letta deployment knobs (untyped block)
    "lineage_decision",    # lineage-decision defaults (raw YAML read)
    "memory",              # _apply_memory_section (env export)
    "pipeline",            # ari.pipeline.yaml_loader.load_pipeline
    "plan_promote",        # lineage plan promotion policy
    "retrieval",           # retrieval backend selection
    "root_idea_selection", # root idea selection policy
    "version",             # workflow schema tag
})

# Env keys whose presence marks ``llm.api_key`` as configured-via-env.  A
# deliberate SUBSET of the viz secret allowlist (ari.config must not import
# ari.viz): only the direct LLM-provider keys the agent-loop backends read.
_LLM_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
)

_ENV_VAR_PAT = re.compile(r"\$\{(\w+)\}")


# ── small pure helpers ─────────────────────────────────────────────────────


def _interp_env(data, env: Mapping[str, str]):
    """``${VAR}`` interpolation against *env* — the pure twin of
    ``ari.config._resolve_env_recursive`` (which reads ``os.environ``)."""
    if isinstance(data, dict):
        return {k: _interp_env(v, env) for k, v in data.items()}
    if isinstance(data, list):
        return [_interp_env(v, env) for v in data]
    if isinstance(data, str):
        return _ENV_VAR_PAT.sub(lambda m: env.get(m.group(1), ""), data)
    return data


def _set_leaf(values: dict, path: str, value) -> None:
    node = values
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _yaml_lookup(raw: dict, path: str) -> tuple[bool, object]:
    """``(found, value)`` for a dotted leaf path in a raw YAML dict."""
    node: object = raw
    for p in path.split("."):
        if not isinstance(node, dict) or p not in node:
            return False, None
        node = node[p]
    return True, node


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    """Parse a JSON file; ``(dict-or-None, warning-or-None)``."""
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{path.name}: unreadable/invalid JSON ignored ({e})"
    if not isinstance(data, dict):
        return None, f"{path.name}: expected a JSON object; ignored"
    return data, None


# ── shared layer helpers (both modes; behavior pinned by the Wave 3a tests) ─


def _apply_workflow_layer(
    wf_path: Path,
    env_map: Mapping[str, str],
    registry: dict,
    secret_paths: set[str],
    values: dict,
    warnings: list[str],
    apply,
) -> tuple[bool, dict]:
    """Apply one workflow.yaml as the "workflow" layer (model_fields filter,
    unknown-top-key warnings, ``_merge_bfts_disabled_tools`` parity, skills
    auto-discovery gap warning).  ``apply(path, value)`` writes the leaf with
    source "workflow"; returns ``(wf_present, wf_raw)``."""
    wf_raw: dict = {}
    wf_present = wf_path.exists()
    if not wf_present:
        return False, wf_raw
    try:
        loaded = yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}
        wf_raw = loaded if isinstance(loaded, dict) else {}
    except (OSError, yaml.YAMLError) as e:
        wf_raw = {}
        warnings.append(f"workflow.yaml: unreadable/invalid YAML ignored ({e})")
    wf_raw = _interp_env(wf_raw, env_map)
    for key in sorted(wf_raw):
        if key in ARIConfig.model_fields or key in KNOWN_NON_CONFIG_TOP_KEYS:
            continue
        warnings.append(
            f"workflow.yaml top-level key {key!r} is not an ARIConfig "
            "field — load_config silently drops it (no reader consumes it)"
        )
    for path in registry:
        if path in secret_paths:
            continue
        if path.split(".", 1)[0] not in ARIConfig.model_fields:
            continue
        found, val = _yaml_lookup(wf_raw, path)
        if found:
            apply(path, val)
    # _merge_bfts_disabled_tools parity: disabled bfts_pipeline stages
    # append their tool to disabled_tools (pure over the raw dict).
    merged_tools = list(values.get("disabled_tools") or [])
    for stage in wf_raw.get("bfts_pipeline") or []:
        if isinstance(stage, dict) and not stage.get("enabled", True):
            tool = stage.get("tool", "")
            if tool and tool not in merged_tools:
                merged_tools.append(tool)
    if merged_tools != (values.get("disabled_tools") or []):
        apply("disabled_tools", merged_tools)
    if "skills" not in wf_raw:
        warnings.append(
            "skills: auto-discovered at runtime (_discover_skills scan); "
            "not reconstructed here — the default [] is a placeholder"
        )
    return True, wf_raw


def _apply_env_overlay(
    env_map: Mapping[str, str],
    wf_present: bool,
    env_apply,
    reject,
) -> None:
    """The documented ``ARI_*`` env overlay — a literal transcription of the
    ``apply_*_env_overrides`` family.  ``env_apply(path, value)`` writes one
    leaf with source "env"; ``reject(var, val, expected)`` records a
    rejected-input warning.  ``wf_present`` gates the ARI_LOG_LEVEL quirk
    (honored on the auto_config / no-YAML path only)."""
    # _apply_llm_env_overrides
    _m = env_map.get("ARI_MODEL") or env_map.get("ARI_LLM_MODEL")
    if _m:
        env_apply("llm.model", _m)
    _b = env_map.get("ARI_BACKEND")
    if _b:
        env_apply("llm.backend", _b)
    _u = env_map.get("ARI_LLM_API_BASE")
    if _u is not None and _u != "":
        env_apply("llm.base_url", _u)
    # _apply_checkpoint_env_overrides
    _ckpt_env = (env_map.get("ARI_CHECKPOINT_DIR") or "").strip()
    if _ckpt_env:
        env_apply("checkpoint.dir", _ckpt_env)
    _log = env_map.get("ARI_LOG_DIR", "")
    if _log:
        env_apply("logging.dir", _log)
    elif _ckpt_env:
        env_apply("logging.dir", _ckpt_env)
    # ARI_LOG_LEVEL is honored on the auto_config (no-YAML) path only.
    if not wf_present:
        _lvl = env_map.get("ARI_LOG_LEVEL")
        if _lvl:
            env_apply("logging.level", _lvl)
    # apply_bfts_env_overrides
    for var, path in (
        ("ARI_MAX_NODES", "bfts.max_total_nodes"),
        ("ARI_MAX_DEPTH", "bfts.max_depth"),
        ("ARI_MAX_REACT", "bfts.max_react_steps"),
        ("ARI_PARALLEL", "bfts.max_parallel_nodes"),
        ("ARI_TIMEOUT_NODE", "bfts.timeout_per_node"),
    ):
        raw_v = env_map.get(var)
        if raw_v:
            try:
                env_apply(path, int(raw_v))
            except ValueError:
                reject(var, raw_v, "an integer")
    _fs = env_map.get("ARI_FRONTIER_SCORE")
    if _fs in _FRONTIER_SCORES:
        env_apply("bfts.frontier_score", _fs)
    elif _fs:
        reject("ARI_FRONTIER_SCORE", _fs, f"one of {_FRONTIER_SCORES}")
    _w = env_map.get("ARI_BFTS_ALLOW_WEB")
    if _w is not None:
        env_apply("bfts.allow_web", _w.strip().lower() in _ON_SET)
    # apply_evaluator_env_overrides
    _comp = env_map.get("ARI_COMPOSITE")
    if _comp in _COMPOSITES:
        env_apply("evaluator.composite", _comp)
    elif _comp:
        reject("ARI_COMPOSITE", _comp, f"one of {_COMPOSITES}")
    _am = env_map.get("ARI_AXIS_MODE")
    if _am in _AXIS_MODES:
        env_apply("evaluator.axis_mode", _am)
    elif _am:
        reject("ARI_AXIS_MODE", _am, f"one of {_AXIS_MODES}")
    # apply_rqgm_env_overrides / apply_paper_env_overrides
    for var, path, kind in (
        ("ARI_MODE", "ari.mode", ("simple_bfts", "ari_rqgm")),
        ("ARI_RQGM_ENABLED", "rqgm.enabled", "bool"),
        ("ARI_PAPER_MODE", "paper.mode", ("linear", "rqgm_archive")),
        ("ARI_RQGM_PAPER_ENABLED", "rqgm.paper.enabled", "bool"),
        (
            "ARI_PAPER_AGENT_AS_JUDGE",
            "rqgm.paper.reviewer.agent_as_judge.enabled",
            "bool",
        ),
    ):
        raw_v = env_map.get(var)
        if not raw_v:
            continue
        norm = raw_v.strip().lower()
        if kind == "bool":
            if norm in _TRUE_SET:
                env_apply(path, True)
            elif norm in _FALSE_SET:
                env_apply(path, False)
            else:
                reject(var, raw_v, "a boolean (0/1/true/false)")
        elif norm in kind:
            env_apply(path, norm)
        else:
            reject(var, raw_v, f"one of {kind}")


# ── the resolver ───────────────────────────────────────────────────────────


def resolve_run_config(
    checkpoint_dir: Path, *, env: Mapping[str, str] | None = None
) -> dict:
    """Reconstruct the plan-05 resolved manifest for an existing checkpoint.

    *env* defaults to a read-only snapshot of ``os.environ``; pass a mapping
    for a fully deterministic resolution.  ``resolved_at`` is returned as
    ``None`` — the caller (the ``/api/v1`` handler) fills it from source
    file mtimes so this function never reads a clock.
    """
    checkpoint_dir = Path(checkpoint_dir)
    env_map: Mapping[str, str] = dict(os.environ) if env is None else env

    registry = {e["path"]: e for e in build_field_registry()}
    secret_paths = {
        p for p, e in registry.items() if e["sensitivity"] == "secret_reference"
    }

    def _mutable(path: str) -> bool:
        # Post-hoc view of an existing run: only resume_mutable fields can
        # still change; draft/new_run_only windows are closed, read_only
        # never opens (plan 05 §Resolution model / Resume).
        return registry[path]["mutability"] == "resume_mutable"

    values: dict = {}
    provenance: dict[str, dict] = {}
    warnings: list[str] = [
        "reconstructed post-hoc: no resolved_config.json manifest was stored "
        "at launch; this is a best-effort legacy-compatible-1 reconstruction "
        "from checkpoint files and the current environment",
    ]
    source_stack: list[str] = ["default"]

    # ── layer 0: pydantic defaults ─────────────────────────────────────
    for path, entry in registry.items():
        if path in secret_paths:
            continue
        _set_leaf(values, path, entry["default"])
        provenance[path] = {
            "source": "default", "mutable": _mutable(path), "confidence": "high",
        }

    def _apply(path: str, value, source: str, confidence: str,
               mutable: bool | None = None) -> None:
        if path in secret_paths or path not in registry:
            return
        _set_leaf(values, path, value)
        provenance[path] = {
            "source": source,
            "mutable": _mutable(path) if mutable is None else mutable,
            "confidence": confidence,
        }

    # ── layer 1: {ckpt}/workflow.yaml (model_fields filter) ────────────
    wf_present, wf_raw = _apply_workflow_layer(
        checkpoint_dir / "workflow.yaml", env_map, registry, secret_paths,
        values, warnings, lambda path, val: _apply(path, val, "workflow", "high"),
    )
    if wf_present:
        source_stack.append("workflow")

    # ── layer 2: {ckpt}/launch_config.json ─────────────────────────────
    lc, lc_warn = _read_json(checkpoint_dir / "launch_config.json")
    if lc_warn:
        warnings.append(lc_warn)
    if lc is not None:
        source_stack.append("launch_config")
        for lc_key, path in LAUNCH_CONFIG_MAP:
            if lc_key not in lc:
                continue
            val = lc[lc_key]
            if val in (None, ""):
                continue
            _apply(path, val, "launch_config", "high")

    # ── layer 3: CURRENT env, documented ARI_* families only ───────────
    source_stack.append("env")
    env_hits = 0

    def _env_apply(path: str, value) -> None:
        nonlocal env_hits
        env_hits += 1
        _apply(path, value, "env", "low")

    def _reject(var: str, val: str, expected: str) -> None:
        warnings.append(
            f"env override rejected (legacy chain ignores it): {var}={val!r} "
            f"is not {expected}"
        )

    _apply_env_overlay(env_map, wf_present, _env_apply, _reject)

    if env_hits:
        warnings.append(
            "environment overlay reflects the CURRENT process environment, "
            "which may differ from the launch-time environment "
            "(confidence: low)"
        )

    # ── layer 4: {ckpt}/rqgm_state.json — the persisted mode wins ──────
    st, st_warn = _read_json(checkpoint_dir / "rqgm_state.json")
    if st_warn:
        warnings.append(st_warn)
    if st is not None:
        source_stack.append("checkpoint_state")
        persisted_mode = str(st.get("mode", "simple_bfts"))
        if persisted_mode not in ("simple_bfts", "ari_rqgm"):
            warnings.append(
                f"rqgm_state.json: unknown mode {persisted_mode!r}; treated "
                "as simple_bfts (reconcile_resume_mode parity)"
            )
            persisted_mode = "simple_bfts"
        persisted_enabled = bool(st.get("rqgm_enabled", False))
        prior = (
            values.get("ari", {}).get("mode"),
            values.get("rqgm", {}).get("enabled"),
        )
        if prior != (persisted_mode, persisted_enabled):
            warnings.append(
                "rqgm_state.json persisted mode wins over config/env: "
                f"mode={persisted_mode} rqgm_enabled={persisted_enabled} "
                f"(config/env resolved mode={prior[0]} enabled={prior[1]}); "
                "a run's mode is immutable (reconcile_resume_mode parity)"
            )
        _apply("ari.mode", persisted_mode, "checkpoint_state", "high",
               mutable=False)
        _apply("rqgm.enabled", persisted_enabled, "checkpoint_state", "high",
               mutable=False)

    # ── secret references (configured-only; values NEVER present) ──────
    secret_references: dict[str, dict] = {}
    for path in sorted(secret_paths):
        found, val = _yaml_lookup(wf_raw, path) if wf_raw else (False, None)
        if found and val not in (None, ""):
            secret_references[path] = {"provider": "workflow", "configured": True}
        elif path == "llm.api_key" and any(
            env_map.get(k) for k in _LLM_PROVIDER_ENV_KEYS
        ):
            secret_references[path] = {"provider": "env", "configured": True}

    # ── digest over the REDACTED canonical values JSON only ────────────
    canonical = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {
        "schema_version": SCHEMA_VERSION,
        "resolver_version": RESOLVER_VERSION,
        "run_id": checkpoint_dir.name,
        "resolved_at": None,  # caller fills (determinism: no clock here)
        "digest": digest,
        "source_stack": source_stack,
        "values": values,
        "provenance": provenance,
        "secret_references": secret_references,
        "warnings": warnings,
    }


# ── new-run preview resolution (gui_refresh task 05 Wave 3b) ───────────────

# The only profile keys ``_apply_profile`` (ari/cli/run.py) actually merges.
# ``bfts.parallel`` is the historical spelling of ``bfts.max_parallel_nodes``
# (accepted second when both are present); ``hpc.enabled``/``hpc.scheduler``
# land inside the composite ``resources`` leaf as ``hpc_enabled``/
# ``scheduler`` — exactly what the imperative merge does to ``cfg.resources``.
PROFILE_MERGED_KEYS: frozenset[str] = frozenset({
    "bfts.max_total_nodes",
    "bfts.max_parallel_nodes",
    "bfts.parallel",
    "hpc.enabled",
    "hpc.scheduler",
})

# Layer name -> validate_patch target (the same mutability/scope policy the
# CRUD surface enforces at PATCH time is re-applied defensively at preview).
_LAYER_TARGETS: tuple[tuple[str, str], ...] = (
    ("project", "project_config"),
    ("template", "run_template"),
    ("draft", "run_draft"),
)

# The two warn+fallback interlock pairs (plan 05 §Interlocks):
# (mode path, interlock path, active mode value, fallback mode value).
# Single source of truth: the registry transcription, so the resolver's
# warn+fallback pass and the ADR-09 mode-selection validation can never
# describe different pairs.
INTERLOCK_PAIRS: tuple[tuple[str, str, str, str], ...] = MODE_INTERLOCK_PAIRS

_VALIDATION_MAX_ROUNDS = 8


def _flatten_leaves(data: object, prefix: str = "") -> list[str]:
    """Dotted leaf paths of a nested dict (deterministic, sorted)."""
    if not isinstance(data, dict) or not data:
        return [prefix.rstrip(".")] if prefix else []
    out: list[str] = []
    for k in sorted(data, key=str):
        out.extend(_flatten_leaves(data[k], f"{prefix}{k}."))
    return out


def _leaf_get(values: dict, path: str):
    node: object = values
    for p in path.split("."):
        node = node[p]  # resolver-built dict: every registry path exists
    return node


def resolve_new_run_config(
    *,
    project_values: Mapping | None = None,
    template_values: Mapping | None = None,
    draft_values: Mapping | None = None,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Preview the plan-05 new-run resolution chain (see module docstring).

    Pure and read-only: reads the BUNDLED ``config/workflow.yaml`` +
    ``config/profiles/{profile}.yaml`` (via ``ari.config.finder``) and the
    given ``env`` mapping (default: a read-only ``os.environ`` snapshot);
    never writes a file, never touches ``os.environ``, never reads a clock
    (``resolved_at``/``run_id`` are ``None`` — the API caller fills them).
    The existing-checkpoint mode (:func:`resolve_run_config`) is untouched.
    """
    import copy as _copy

    from pydantic import ValidationError

    from . import finder
    from .field_registry import validate_patch

    env_map: Mapping[str, str] = dict(os.environ) if env is None else env

    registry = {e["path"]: e for e in build_field_registry()}
    secret_paths = {
        p for p, e in registry.items() if e["sensitivity"] == "secret_reference"
    }

    values: dict = {}
    provenance: dict[str, dict] = {}
    warnings: list[str] = []
    source_stack: list[str] = ["default"]
    secret_references: dict[str, dict] = {}
    # Per-leaf (source, value) history — the revert chain for
    # rejected_override annotations ("keeps the last VALID layer value").
    history: dict[str, list[tuple[str, object]]] = {}

    def _mutable(path: str) -> bool:
        # Before launch every non-read_only field is still editable (the
        # draft/new_run_only windows are open — unlike the post-hoc mode).
        return registry[path]["mutability"] != "read_only"

    # ── layer 0: pydantic defaults ─────────────────────────────────────
    for path, entry in registry.items():
        if path in secret_paths:
            continue
        _set_leaf(values, path, _copy.deepcopy(entry["default"]))
        provenance[path] = {
            "source": "default", "mutable": _mutable(path), "confidence": "high",
        }
        history[path] = [("default", _copy.deepcopy(entry["default"]))]

    def _apply(path: str, value, source: str, confidence: str = "high") -> None:
        if path in secret_paths or path not in registry:
            return
        _set_leaf(values, path, _copy.deepcopy(value))
        provenance[path] = {
            "source": source, "mutable": _mutable(path),
            "confidence": confidence,
        }
        history[path].append((source, _copy.deepcopy(value)))

    # ── layer 1: BUNDLED config/workflow.yaml ──────────────────────────
    wf_path = finder.package_config_root() / "workflow.yaml"
    wf_present, wf_raw = _apply_workflow_layer(
        wf_path, env_map, registry, secret_paths, values, warnings,
        lambda path, val: _apply(path, val, "workflow"),
    )
    if wf_present:
        source_stack.append("workflow")

    # ── layer 2: execution profile (EXACT 4-key _apply_profile merge) ──
    if profile:
        p_path = finder.package_config_root() / "profiles" / f"{profile}.yaml"
        if not p_path.exists():
            warnings.append(
                f"profile {profile!r} not found at {p_path} — profile "
                "overrides ignored (_apply_profile parity)"
            )
        else:
            try:
                loaded = yaml.safe_load(p_path.read_text(encoding="utf-8")) or {}
                overrides = loaded if isinstance(loaded, dict) else {}
            except (OSError, yaml.YAMLError) as e:
                overrides = {}
                warnings.append(
                    f"profile {profile!r}: unreadable/invalid YAML ignored ({e})"
                )
            source_stack.append("profile")
            bfts_o = overrides.get("bfts") or {}
            if "max_total_nodes" in bfts_o:
                _apply("bfts.max_total_nodes", bfts_o["max_total_nodes"],
                       "profile")
            if "max_parallel_nodes" in bfts_o:
                _apply("bfts.max_parallel_nodes", bfts_o["max_parallel_nodes"],
                       "profile")
            elif "parallel" in bfts_o:
                _apply("bfts.max_parallel_nodes", bfts_o["parallel"], "profile")
            hpc_o = overrides.get("hpc") or {}
            if "enabled" in hpc_o or "scheduler" in hpc_o:
                res = dict(_leaf_get(values, "resources") or {})
                if "enabled" in hpc_o:
                    res["hpc_enabled"] = hpc_o["enabled"]
                if "scheduler" in hpc_o:
                    res["scheduler"] = hpc_o["scheduler"]
                _apply("resources", res, "profile")
            consumed = {
                k for k in PROFILE_MERGED_KEYS
                if _yaml_lookup(overrides, k)[0]
            }
            if "bfts.max_parallel_nodes" in consumed:
                # the historical spelling is shadowed, not consumed
                consumed.discard("bfts.parallel")
            ignored = sorted(
                leaf for leaf in _flatten_leaves(overrides)
                if leaf not in consumed and leaf != "profile"
            )
            if ignored:
                warnings.append(
                    f"profile {profile!r}: ignored non-merged keys "
                    "(only bfts.max_total_nodes, bfts.max_parallel_nodes/"
                    "parallel, hpc.enabled and hpc.scheduler merge — "
                    f"_apply_profile parity): {ignored}"
                )

    # ── layers 3-5: project / template / draft dotted-value maps ───────
    for source, target, mapping in (
        ("project", "project_config", project_values),
        ("template", "run_template", template_values),
        ("draft", "run_draft", draft_values),
    ):
        if not mapping:
            continue
        source_stack.append(source)
        mapping = dict(mapping)
        errors = {e["path"]: e for e in validate_patch(mapping, target=target)}
        for raw_path in sorted(mapping, key=str):
            value = mapping[raw_path]
            path = raw_path if isinstance(raw_path, str) else str(raw_path)
            err = errors.get(path)
            if err is None:
                _apply(path, value, source)
                continue
            reason = err["reason"]
            if reason == "secret_reference":
                # never in values/provenance/digest — configured flag only,
                # and the raw value is never echoed into a warning.
                secret_references[path] = {
                    "provider": source, "configured": True,
                }
                warnings.append(
                    f"{source} override ignored for secret path {path}: "
                    "secrets never appear in resolved values"
                )
                continue
            warnings.append(
                f"{source} override rejected for {path}: {err['message']}"
            )
            if path in provenance:
                ro: dict = {
                    "source": source, "value": value, "reason": reason,
                }
                if "expected" in err:
                    ro["expected"] = err["expected"]
                provenance[path]["rejected_override"] = ro

    # ── layer 6: documented ARI_* env overrides ────────────────────────
    env_hits = 0

    def _env_apply(path: str, value) -> None:
        nonlocal env_hits
        env_hits += 1
        _apply(path, value, "env", "low")

    def _env_reject(var: str, val: str, expected: str) -> None:
        warnings.append(
            f"env override rejected (legacy chain ignores it): {var}={val!r} "
            f"is not {expected}"
        )

    _apply_env_overlay(env_map, wf_present, _env_apply, _env_reject)
    if env_hits:
        source_stack.append("env")
        warnings.append(
            "environment overlay reflects the CURRENT process environment, "
            "which may differ from the launch-time environment "
            "(confidence: low)"
        )

    # ── validated effective: ARIConfig construction, revert on error ───
    for _round in range(_VALIDATION_MAX_ROUNDS):
        try:
            ARIConfig(**_copy.deepcopy(values))
            break
        except ValidationError as exc:
            progressed = False
            for err in exc.errors():
                loc = [str(x) for x in err["loc"]]
                path = next(
                    (
                        ".".join(loc[:i])
                        for i in range(len(loc), 0, -1)
                        if ".".join(loc[:i]) in registry
                    ),
                    None,
                )
                if path is None or len(history.get(path, [])) < 2:
                    warnings.append(
                        "config validation error at "
                        f"{'.'.join(loc)} could not be attributed to an "
                        f"overridable leaf: {err['msg']}"
                    )
                    continue
                bad_source, bad_value = history[path].pop()
                good_source, good_value = history[path][-1]
                _set_leaf(values, path, _copy.deepcopy(good_value))
                provenance[path]["source"] = good_source
                provenance[path]["confidence"] = (
                    "low" if good_source == "env" else "high"
                )
                provenance[path]["rejected_override"] = {
                    "source": bad_source, "value": bad_value,
                    "reason": "invalid_value",
                }
                warnings.append(
                    f"{bad_source} override rejected for {path}: "
                    f"{err['msg']} — keeping the {good_source} value"
                )
                progressed = True
            if not progressed:
                warnings.append(
                    "config validation errors remain but no overridable "
                    "leaf could be reverted; effective values are best-effort"
                )
                break

    # ── interlock resolution (resolve_effective_mode warn+fallback) ────
    for mode_path, enable_path, active, fallback in INTERLOCK_PAIRS:
        mode_v = _leaf_get(values, mode_path)
        en_v = bool(_leaf_get(values, enable_path))
        if mode_v == active and not en_v:
            # The manifest shows the EFFECTIVE (post-fallback) mode; the
            # requested value survives as the rejected_override explanation.
            warnings.append(
                f"{mode_path}={mode_v} but {enable_path}={en_v}; falling "
                f"back to {fallback} (resolve_effective_mode parity: warn + "
                "fallback, never an error)"
            )
            prov = provenance[mode_path]
            prov["rejected_override"] = {
                "source": prov["source"], "value": mode_v,
                "reason": "interlock_mismatch",
            }
            _set_leaf(values, mode_path, fallback)
        elif en_v and mode_v != active:
            warnings.append(
                f"{enable_path}={en_v} but {mode_path}={mode_v}; the "
                f"interlock is set without its master switch — effective "
                f"mode stays {fallback} (resolve_effective_mode parity)"
            )

    # ── secret references from the bundled workflow / provider env ─────
    for path in sorted(secret_paths):
        if path in secret_references:
            continue  # a layer map already flagged it (provider = layer)
        found, val = _yaml_lookup(wf_raw, path) if wf_raw else (False, None)
        if found and val not in (None, ""):
            secret_references[path] = {"provider": "workflow", "configured": True}
        elif path == "llm.api_key" and any(
            env_map.get(k) for k in _LLM_PROVIDER_ENV_KEYS
        ):
            secret_references[path] = {"provider": "env", "configured": True}

    # ── digest over the REDACTED canonical EFFECTIVE values JSON ───────
    canonical = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {
        "schema_version": SCHEMA_VERSION,
        "resolver_version": RESOLVER_VERSION,
        "run_id": None,  # no run exists yet — the API caller fills draft id
        "resolved_at": None,  # caller fills (determinism: no clock here)
        "digest": digest,
        "source_stack": source_stack,
        "values": values,
        "provenance": provenance,
        "secret_references": dict(sorted(secret_references.items())),
        "warnings": warnings,
    }
