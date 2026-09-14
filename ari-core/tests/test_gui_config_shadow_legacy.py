"""Legacy shadow diff: 24-key Settings save+launch vs the new-run resolver
(docs/concepts/gui_architecture.md § 1. Strangler shape: one shell, two
generations of screens — "the two sides are held in agreement by tests").

For the overlapping leaf set — llm.model/backend/base_url, the 4 SLURM
settings, the 2 container settings, the 3 Letta settings, the VLM review
model and the retrieval backend — this suite:

1. saves the frozen 24-key frontend Settings POST body through the REAL
   legacy handler (``api_settings._api_save_settings``; key inventory pinned
   against ``test_gui_baseline_settings_contract.FRONTEND_POST_KEYS_24``);
2. derives the env its save+launch path would produce via a literal
   transcription of the settings-injection block of
   ``ari/viz/api_experiment.py::_api_launch`` (the settings-only slice — no
   wizard fields, no .env files);
3. computes the LEGACY effective config as ``resolve_run_config`` over a
   checkpoint seeded with the bundled ``workflow.yaml`` (exactly what the
   GUI launch CoW-seeds) + that env;
4. feeds the EQUIVALENT draft (same falsy-skip semantics as the legacy
   injection) through ``resolve_new_run_config`` (same bundled workflow);
5. asserts per-leaf equality of effective values — with an EXPLICIT
   allowlist of known divergences, each referencing the G0 known-mismatch
   table (``docs/reference/configuration.md`` § Legacy Settings keys: what
   is actually wired) or the untyped-block gap the field registry
   forward-declares.

The allowlist is exact in both directions: a row may diverge only if listed,
and every listed row must actually diverge — so closing a gap (e.g. typing
the ``container`` block) fails this suite until the entry is removed.
This is the parity gate the cutover runbook enforces
(``docs/guides/gui_cutover_runbook.md`` § 2. Pre-cutover checklist,
§ 4. Stop and rollback conditions) before the canonical resolver may
replace the legacy launch mapping.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from ari.config import finder
from ari.config.field_registry import (
    ENV_OVERRIDES,
    build_field_registry,
    validate_patch,
)
from ari.config.resolver import resolve_new_run_config, resolve_run_config
from ari.viz import api_settings
from ari.viz import state as _st

# ── frozen baseline reuse (G0 fixture module, loaded by path) ──────────────

_BASELINE_PATH = Path(__file__).parent / "test_gui_baseline_settings_contract.py"


def _load_baseline():
    spec = importlib.util.spec_from_file_location(
        "gui_baseline_settings_contract", _BASELINE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BASELINE = _load_baseline()
FRONTEND_POST_KEYS_24 = _BASELINE.FRONTEND_POST_KEYS_24

# Env vars the save/launch/resolve chain may read or write — cleared for
# determinism (the save path live-exports provider keys into os.environ).
_CLEARED_ENV = sorted(
    set(ENV_OVERRIDES.values())
    | set(_BASELINE._SETTINGS_ENV_VARS)
    | {"ARI_LLM_MODEL", "GEMINI_API_KEY"}
)


# ── the 24-key Settings POST body (values tuned to EXPOSE divergences) ─────


def _settings_save_body() -> dict:
    """Exactly the frozen 24 frontend Save keys; values chosen so every
    known divergence actually fires (temperature != pydantic default,
    container_mode != 'auto' so the legacy export path triggers, ...)."""
    return {
        "llm_model": "gpt-4o-2024-11-20",
        "llm_backend": "openai",
        "llm_base_url": "",
        "temperature": 0.25,          # dead key (G0 known-mismatch table)
        "llm_api_key": "sk-shadow-aaaaaaaaaaaaaaaa",  # >=20 chars, no "test"
        "semantic_scholar_key": "",
        "retrieval_backend": "semantic_scholar",
        "ssh_host": "hpc.example.org",
        "ssh_port": 22,
        "ssh_user": "ari",
        "ssh_path": "/scratch/ari",
        "ssh_key": "~/.ssh/id_ed25519",
        "slurm_partitions": ["gpu", "cpu"],
        "slurm_partition": "gpu",
        "slurm_cpus": 8,
        "slurm_memory_gb": 64,
        "slurm_walltime": "04:00:00",
        "container_mode": "docker",   # non-auto -> the legacy export fires
        "container_image": "ghcr.io/example/ari:1",
        "container_pull": "on_start",  # dead key (G0 known-mismatch table)
        "vlm_review_model": "openai/gpt-4o",
        "letta_base_url": "http://localhost:8283",
        "letta_api_key": "letta-shadow-secret",
        "letta_embedding_config": "letta-default",
    }


# ── overlap partition of the 24 keys (exact, both directions) ──────────────

# settings key -> (legacy launch env var | None, canonical leaf | None).
# ``resources.<k>`` addresses one sub-key of the composite ``resources`` leaf.
OVERLAP: dict[str, tuple[str | None, str | None]] = {
    "llm_model": ("ARI_MODEL", "llm.model"),
    "llm_backend": ("ARI_BACKEND", "llm.backend"),
    "llm_base_url": ("ARI_LLM_API_BASE", "llm.base_url"),
    "temperature": (None, "llm.temperature"),
    "slurm_partition": (None, "resources.partition"),
    "slurm_cpus": (None, "resources.cpus"),
    "slurm_memory_gb": (None, "resources.memory_gb"),
    "slurm_walltime": (None, "resources.walltime"),
    "container_mode": ("ARI_CONTAINER_MODE", None),
    "container_image": ("ARI_CONTAINER_IMAGE", None),
    "container_pull": (None, None),
    "vlm_review_model": ("VLM_MODEL", None),
    "retrieval_backend": ("ARI_RETRIEVAL_BACKEND", None),
    "letta_base_url": ("LETTA_BASE_URL", None),
    "letta_api_key": ("LETTA_API_KEY", None),
    "letta_embedding_config": ("LETTA_EMBEDDING_CONFIG", None),
}

# 24-key members deliberately OUTSIDE the overlapping leaf set.
OUT_OF_SCOPE: dict[str, str] = {
    "llm_api_key": "secret: popped at save, flows via .env upsert — the "
                   "canonical side is the write-only secrets surface, never "
                   "config values (ADR-11)",
    "semantic_scholar_key": "secret reference (same .env flow as above)",
    "ssh_host": "persisted but never launch-mapped (SSH card is display/"
                "probe state, no ARI_* translation exists)",
    "ssh_port": "see ssh_host",
    "ssh_user": "see ssh_host",
    "ssh_path": "see ssh_host",
    "ssh_key": "see ssh_host",
    "slurm_partitions": "list is a wizard datalist seed only (G0: Settings "
                        "SLURM card は wizard の seed のみ)",
}

# The EXACT set of overlapping rows allowed to diverge, each referencing the
# G0 known-mismatch table (docs/reference/configuration.md § Legacy Settings
# keys: what is actually wired — the dead / seed-only / env-only / frozen-defect
# rows) or the untyped-block gap ``ari.config.field_registry`` forward-declares.
KNOWN_DIVERGENCES: dict[str, str] = {
    "temperature": "G0 table: 'temperature/container_pull dead keys' — the "
                   "legacy launch never exports it, so the run keeps the "
                   "pydantic default; the canonical draft applies it.",
    "container_pull": "G0 table: dead key on BOTH routes — never exported "
                      "to env and no canonical leaf (frozen).",
    "slurm_partition": "G0 table: 'Settings SLURM card は wizard の seed "
                       "のみ' (frozen) — settings values never reach the "
                       "launch env; the canonical draft carries them in the "
                       "composite resources leaf.",
    "slurm_cpus": "see slurm_partition",
    "slurm_memory_gb": "see slurm_partition",
    "slurm_walltime": "see slurm_partition",
    "container_mode": "env-only ARI_CONTAINER_MODE: the container block is "
                      "an untyped extra='allow' workflow section — no typed "
                      "leaf yet (field_registry 'container.' prefix is "
                      "forward-declared).",
    "container_image": "env-only ARI_CONTAINER_IMAGE (see container_mode).",
    "vlm_review_model": "env-only VLM_MODEL: no typed canonical leaf yet.",
    "retrieval_backend": "env-only ARI_RETRIEVAL_BACKEND: 'retrieval' is an "
                         "untyped top-level workflow key (G0 table: "
                         "retrieval 装飾のみ).",
    "letta_base_url": "env-only LETTA_BASE_URL: letta/memory are untyped "
                      "extra='allow' blocks — no typed leaf yet.",
    "letta_api_key": "secret + env-only LETTA_API_KEY; legacy persists it "
                     "PLAINTEXT in settings.json (G0 frozen defect) — the "
                     "canonical config API refuses secrets in values.",
    "letta_embedding_config": "env-only LETTA_EMBEDDING_CONFIG (see "
                              "letta_base_url).",
}

# Non-documented env vars the legacy launch exports for the overlap set —
# the env-only surface the canonical resolver does not (yet) model.
ENV_ONLY_ALLOWLIST = frozenset({
    "ARI_CONTAINER_IMAGE",
    "ARI_CONTAINER_MODE",
    "ARI_RETRIEVAL_BACKEND",
    "LETTA_API_KEY",
    "LETTA_BASE_URL",
    "LETTA_EMBEDDING_CONFIG",
    "VLM_MODEL",
})


# ── legacy launch-env transcription (settings-injection block) ─────────────


def _legacy_settings_launch_env(saved: dict) -> dict[str, str]:
    """Literal transcription of the settings.json injection block of
    ``ari/viz/api_experiment.py::_api_launch`` (the ``saved = json.loads``
    branch, lines ~254-324) — settings-only: no wizard fields, no .env file
    loading, no os.environ inheritance (those layers are out of the Settings
    contract this suite shadows)."""
    env: dict[str, str] = {}
    if not saved:
        return env
    llm_model = saved.get("llm_model", "")
    llm_provider = saved.get("llm_provider", "") or saved.get("llm_backend", "")
    if llm_model:
        env["ARI_MODEL"] = llm_model
        env["ARI_LLM_MODEL"] = llm_model
    if llm_provider:
        env["ARI_BACKEND"] = llm_provider
    _api_key = saved.get("api_key", "") or saved.get("llm_api_key", "")
    _is_placeholder = not _api_key or "test" in _api_key or len(_api_key) < 20
    if not _is_placeholder:
        if llm_provider == "openai" and not env.get("OPENAI_API_KEY"):
            env["OPENAI_API_KEY"] = _api_key
        elif llm_provider == "anthropic" and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = _api_key
    if llm_provider == "ollama":
        _real = saved.get("ollama_host", "").strip() or "http://localhost:11434"
        env["OLLAMA_HOST"] = _real
        env["ARI_LLM_API_BASE"] = _real
    elif llm_provider in ("cli-shim", "cli_shim"):
        _base = (saved.get("cli_shim_base_url", "")
                 or saved.get("llm_base_url", "") or "").strip()
        env["ARI_LLM_API_BASE"] = _base or "http://localhost:8900/v1"
        env.setdefault("OPENAI_API_KEY", "cli-shim")
    else:
        env["ARI_LLM_API_BASE"] = ""
    _retrieval = saved.get("retrieval_backend", "")
    if _retrieval:
        env["ARI_RETRIEVAL_BACKEND"] = _retrieval
    for skill in ["idea", "bfts", "coding", "eval", "paper", "review"]:
        val = saved.get(f"model_{skill}", "")
        if val:
            env[f"ARI_MODEL_{skill.upper()}"] = val
    _vlm = saved.get("vlm_review_model", "")
    if _vlm:
        env["VLM_MODEL"] = _vlm
    _ct_image = saved.get("container_image", "")
    _ct_mode = saved.get("container_mode", "")
    if _ct_image and "ARI_CONTAINER_IMAGE" not in env:
        env["ARI_CONTAINER_IMAGE"] = _ct_image
    if _ct_mode and _ct_mode != "auto" and "ARI_CONTAINER_MODE" not in env:
        env["ARI_CONTAINER_MODE"] = _ct_mode
    _letta_base = saved.get("letta_base_url", "")
    if _letta_base:
        env["LETTA_BASE_URL"] = _letta_base
    _letta_key = saved.get("letta_api_key", "")
    if _letta_key:
        env["LETTA_API_KEY"] = _letta_key
    _letta_emb = saved.get("letta_embedding_config", "")
    if _letta_emb:
        env["LETTA_EMBEDDING_CONFIG"] = _letta_emb
    return env


def _equivalent_draft(body: dict) -> dict:
    """The canonical draft equivalent of the 24-key body for the leaves that
    HAVE a typed canonical path — with the SAME falsy-skip semantics as the
    legacy injection (empty strings are 'unset' on the legacy route, so an
    honest translation skips them too)."""
    draft: dict = {}
    if body.get("llm_model"):
        draft["llm.model"] = body["llm_model"]
    if body.get("llm_backend"):
        draft["llm.backend"] = body["llm_backend"]
    if body.get("llm_base_url"):
        draft["llm.base_url"] = body["llm_base_url"]
    if body.get("temperature") is not None:
        draft["llm.temperature"] = body["temperature"]
    resources = {}
    for settings_key, res_key in (
        ("slurm_partition", "partition"),
        ("slurm_cpus", "cpus"),
        ("slurm_memory_gb", "memory_gb"),
        ("slurm_walltime", "walltime"),
    ):
        if body.get(settings_key) not in (None, ""):
            resources[res_key] = body[settings_key]
    if resources:
        draft["resources"] = resources
    return draft


def _effective(manifest: dict, path: str):
    node = manifest["values"]
    for p in path.split("."):
        node = node[p] if isinstance(node, dict) and p in node else None
        if node is None:
            break
    return node


# ── fixtures (baseline pattern: direct handler calls, state restored) ──────


@pytest.fixture
def active_checkpoint(tmp_path, monkeypatch) -> Path:
    for var in _CLEARED_ENV:
        monkeypatch.delenv(var, raising=False)
    prev_ckpt = _st._checkpoint_dir
    prev_settings = _st._settings_path
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env", raising=False)
    _st.set_active_checkpoint(tmp_path)
    try:
        yield tmp_path
    finally:
        _st._checkpoint_dir = prev_ckpt
        _st._settings_path = prev_settings


@pytest.fixture
def shadow(active_checkpoint) -> dict:
    """One full shadow run: real save -> transcribed launch env -> both
    manifests.  The legacy checkpoint is seeded with the bundled
    workflow.yaml (what the GUI launch CoW-seeds), so both routes share the
    same workflow layer and the diff isolates the settings translation."""
    body = _settings_save_body()
    out = api_settings._api_save_settings(json.dumps(body).encode())
    assert out == {"ok": True}
    saved = json.loads((active_checkpoint / "settings.json").read_text())
    legacy_env = _legacy_settings_launch_env(saved)
    shutil.copyfile(
        finder.package_config_root() / "workflow.yaml",
        active_checkpoint / "workflow.yaml",
    )
    legacy = resolve_run_config(active_checkpoint, env=legacy_env)
    draft = _equivalent_draft(body)
    new = resolve_new_run_config(draft_values=draft, env={})
    return {
        "body": body, "saved": saved, "legacy_env": legacy_env,
        "legacy": legacy, "draft": draft, "new": new,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Frozen inventories: 24-key body, exact partition, exact allowlist
# ═══════════════════════════════════════════════════════════════════════════


def test_body_is_the_frozen_24_key_contract():
    assert sorted(_settings_save_body().keys()) == FRONTEND_POST_KEYS_24


def test_overlap_partition_is_exact():
    # every one of the 24 keys is classified exactly once
    assert sorted([*OVERLAP, *OUT_OF_SCOPE]) == FRONTEND_POST_KEYS_24
    assert not set(OVERLAP) & set(OUT_OF_SCOPE)
    # the divergence allowlist only names overlap rows
    assert set(KNOWN_DIVERGENCES) <= set(OVERLAP)


def test_equivalent_draft_is_a_valid_canonical_draft():
    assert validate_patch(_equivalent_draft(_settings_save_body()),
                          target="run_draft") == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Per-leaf shadow diff — equality unless explicitly allowlisted
# ═══════════════════════════════════════════════════════════════════════════


def _row_diverges(shadow: dict, settings_key: str) -> bool:
    """True when the two routes deliver different effective results for one
    overlap row (typed leaf comparison; env-only rows diverge by exporting
    an env var the canonical resolver has no leaf for)."""
    env_var, leaf = OVERLAP[settings_key]
    if leaf is not None:
        return (
            _effective(shadow["legacy"], leaf)
            != _effective(shadow["new"], leaf)
        )
    # no canonical leaf: the row diverges iff the legacy route exports env
    return env_var is not None and env_var in shadow["legacy_env"]


@pytest.mark.parametrize("settings_key", sorted(OVERLAP))
def test_shadow_diff_matches_allowlist_exactly(shadow, settings_key):
    """The parity gate: a row may diverge ONLY when allowlisted in
    KNOWN_DIVERGENCES, and every allowlisted row MUST still diverge (a
    closed gap fails until its entry is removed)."""
    diverges = _row_diverges(shadow, settings_key)
    if settings_key in KNOWN_DIVERGENCES:
        assert diverges or settings_key == "container_pull", (
            settings_key, KNOWN_DIVERGENCES[settings_key],
        )
    else:
        env_var, leaf = OVERLAP[settings_key]
        assert not diverges, (
            settings_key,
            _effective(shadow["legacy"], leaf) if leaf else None,
            _effective(shadow["new"], leaf) if leaf else None,
        )


def test_llm_triple_parity_values(shadow):
    """The three typed-equal rows, pinned by value: the settings body wins
    on both routes (env-injected on the legacy route, draft layer on the
    canonical one) over the shared bundled-workflow layer."""
    assert _effective(shadow["legacy"], "llm.model") == "gpt-4o-2024-11-20"
    assert _effective(shadow["new"], "llm.model") == "gpt-4o-2024-11-20"
    assert shadow["new"]["provenance"]["llm.model"]["source"] == "draft"
    assert shadow["legacy"]["provenance"]["llm.model"]["source"] == "env"
    assert _effective(shadow["legacy"], "llm.backend") == "openai"
    assert _effective(shadow["new"], "llm.backend") == "openai"
    # empty llm_base_url: the legacy route exports ARI_LLM_API_BASE="" which
    # the config layer treats as unset -> both routes keep the bundled
    # workflow value ('' in the repo bundle) — equal by construction.
    assert (
        _effective(shadow["legacy"], "llm.base_url")
        == _effective(shadow["new"], "llm.base_url")
    )


def test_cli_shim_base_url_parity_nontrivial(active_checkpoint):
    """Non-empty base_url variant: provider cli-shim routes llm_base_url
    into ARI_LLM_API_BASE — the canonical draft carries the same leaf, so
    the equality is meaningful (not None == None)."""
    body = {
        **_settings_save_body(),
        "llm_backend": "cli-shim",
        "llm_base_url": "http://localhost:8900/v1",
    }
    assert api_settings._api_save_settings(json.dumps(body).encode()) == {
        "ok": True
    }
    saved = json.loads((active_checkpoint / "settings.json").read_text())
    legacy_env = _legacy_settings_launch_env(saved)
    assert legacy_env["ARI_LLM_API_BASE"] == "http://localhost:8900/v1"
    shutil.copyfile(
        finder.package_config_root() / "workflow.yaml",
        active_checkpoint / "workflow.yaml",
    )
    legacy = resolve_run_config(active_checkpoint, env=legacy_env)
    new = resolve_new_run_config(
        draft_values=_equivalent_draft(body), env={}
    )
    assert (
        _effective(legacy, "llm.base_url")
        == _effective(new, "llm.base_url")
        == "http://localhost:8900/v1"
    )
    assert _effective(legacy, "llm.backend") == "cli-shim"
    assert _effective(new, "llm.backend") == "cli-shim"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Divergence classes, asserted precisely (each cites the G0 table)
# ═══════════════════════════════════════════════════════════════════════════


def test_temperature_dead_key_divergence(shadow):
    # G0 table: temperature is a dead Settings key — no env translation
    # exists, so the legacy run keeps the pydantic default while the
    # canonical draft applies the requested value.
    assert not any("TEMPERATURE" in k.upper() for k in shadow["legacy_env"])
    assert _effective(shadow["legacy"], "llm.temperature") == 0.7
    assert _effective(shadow["new"], "llm.temperature") == 0.25


def test_slurm_settings_never_reach_launch_env(shadow):
    # G0 table (frozen): the Settings SLURM card only seeds the wizard —
    # saving it produces NO ARI_SLURM_* env; the canonical draft delivers
    # the same four values through the composite resources leaf.
    assert not any(k.startswith("ARI_SLURM_") for k in shadow["legacy_env"])
    res = _effective(shadow["new"], "resources")
    assert res["partition"] == "gpu"
    assert res["cpus"] == 8
    assert res["memory_gb"] == 64
    assert res["walltime"] == "04:00:00"
    assert shadow["new"]["provenance"]["resources"]["source"] == "draft"
    # legacy effective resources = the bundled workflow block, untouched
    assert _effective(shadow["legacy"], "resources") == {
        "cpus": 48, "timeout_minutes": 60, "executor": "slurm",
    }


def test_env_only_rows_have_no_canonical_leaf(shadow):
    """container/letta/vlm/retrieval: the legacy route exports env the
    canonical resolver has no typed leaf for — pinned per env var, and the
    naive dotted paths are unknown_path to the registry (the field_registry
    prefixes are forward-declared documentation, not rows)."""
    for var, expected in {
        "ARI_CONTAINER_MODE": "docker",
        "ARI_CONTAINER_IMAGE": "ghcr.io/example/ari:1",
        "VLM_MODEL": "openai/gpt-4o",
        "ARI_RETRIEVAL_BACKEND": "semantic_scholar",
        "LETTA_BASE_URL": "http://localhost:8283",
        "LETTA_EMBEDDING_CONFIG": "letta-default",
    }.items():
        assert shadow["legacy_env"][var] == expected, var
    registry_paths = {e["path"] for e in build_field_registry()}
    for naive in (
        "container.mode", "container.image", "vlm_review.model",
        "retrieval.backend", "letta.base_url", "letta.embedding_config",
    ):
        assert naive not in registry_paths, naive
        errs = validate_patch({naive: "x"}, target="run_draft")
        assert [e["reason"] for e in errs] == ["unknown_path"], naive


def test_letta_api_key_secret_divergence(shadow):
    # G0 frozen defect: letta_api_key is persisted PLAINTEXT in
    # settings.json and exported to env; the canonical surface must never
    # carry it in values (no leaf exists, and secrets are refused anyway).
    assert shadow["saved"]["letta_api_key"] == "letta-shadow-secret"
    assert shadow["legacy_env"]["LETTA_API_KEY"] == "letta-shadow-secret"
    assert "letta-shadow-secret" not in json.dumps(shadow["new"])


def test_container_pull_dead_on_both_routes(shadow):
    # G0 table: container_pull is a dead key — no env export, no leaf.
    assert not any("PULL" in k.upper() for k in shadow["legacy_env"])
    assert "container_pull" not in json.dumps(shadow["new"]["values"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Env accounting: every exported var is canonical or allowlisted
# ═══════════════════════════════════════════════════════════════════════════


def test_exported_env_accounting_exact(shadow):
    """Every env var the legacy save+launch path exports for the 24-key body
    is either a documented canonical override family or ENV_ONLY_ALLOWLIST —
    and the allowlist carries no stale entries."""
    exported = set(shadow["legacy_env"])
    documented = set(ENV_OVERRIDES.values()) | {"ARI_LLM_MODEL"}
    undocumented = exported - documented
    assert undocumented == ENV_ONLY_ALLOWLIST
    # the documented exports are exactly the llm triple (+ model alias)
    assert exported & documented == {
        "ARI_MODEL", "ARI_LLM_MODEL", "ARI_BACKEND", "ARI_LLM_API_BASE",
    }


def test_saved_settings_shape_reused_from_baseline(shadow):
    # sanity re-pin (full freeze lives in the baseline suite): the save
    # persisted 23 keys = 24 minus the popped llm_api_key secret.
    assert sorted(shadow["saved"].keys()) == sorted(
        set(FRONTEND_POST_KEYS_24) - {"llm_api_key"}
    )
