"""Tests for the legacy-compatible resolved-config resolver (gui_refresh
task 05 Wave 3a).

Plan ``docs/plans/gui_refresh/05`` §Resolution model / §Resolved manifest:

- layer order on an existing checkpoint — pydantic defaults < workflow.yaml
  (model_fields filter) < launch_config.json knobs < CURRENT env (documented
  ``ARI_*`` families only, confidence low) < rqgm_state.json persisted mode
  (immutable, ``reconcile_resume_mode`` parity);
- per-leaf provenance (source / mutable / confidence) and warnings for every
  silently-dropped or rejected input;
- determinism — no clock reads (``resolved_at`` is ``None`` from the
  resolver; the endpoint derives it from source-file mtimes), identical
  manifests across calls, digest invariant under env noise outside the
  documented families;
- secret redaction — ``secret_reference`` leaves never in ``values``/
  ``provenance``/the digest input; configured-only ``secret_references``;
- ``GET /api/v1/runs/{run_id}/resolved-config`` happy path + typed 404;
- golden parity — the resolver output matches what the REAL legacy chain
  (``load_config`` + ``apply_*_env_overrides``) produces for the same
  workflow.yaml + env on the overlapping leaf set.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest
import yaml

from ari.config import (
    apply_bfts_env_overrides,
    apply_evaluator_env_overrides,
    apply_rqgm_env_overrides,
    load_config,
)
from ari.config.field_registry import ENV_OVERRIDES
from ari.config.resolver import (
    ENV_FAMILY_PATHS,
    LAUNCH_CONFIG_MAP,
    RESOLVER_VERSION,
    resolve_run_config,
)
from ari.viz import api_state
from ari.viz.v1.router import dispatch

_FACTORY_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "gui_refresh"
    / "run_fixture_factory.py"
)


def _load_factory():
    spec = importlib.util.spec_from_file_location(
        "gui_refresh_run_fixture_factory", _FACTORY_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


make_run_checkpoint = _load_factory().make_run_checkpoint

RUN_ID = "20260723000000_resolvefixture"
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Every env var the resolver/legacy chain may read — cleared before parity
# and endpoint tests so developer/CI environments cannot leak in.
_ALL_ENV_VARS = sorted(set(ENV_OVERRIDES.values()) | {"ARI_LLM_MODEL"})

_WORKFLOW = {
    "llm": {"model": "wf-model", "temperature": 0.5},
    "bfts": {"max_total_nodes": 30},
    "ari": {"mode": "simple_bfts"},
    "totally_unknown_key": {"x": 1},
}
_LAUNCH_CONFIG = {
    "llm_model": "claude-sonnet-4-5",
    "llm_provider": "anthropic",
    "max_nodes": 40,
    "max_depth": 4,
    "max_react": 60,
    "timeout_node_s": 3600,
    "parallel": 2,
    "frontier_score": "depth_penalized",
    "composite": "geometric_mean",
    "axis_mode": "legacy",
    "allow_web": False,
}
_RQGM_STATE = {
    "schema_version": 1,
    "mode": "ari_rqgm",
    "rqgm_enabled": True,
    "mode_source": "config",
}


def _leaf(values: dict, path: str):
    node = values
    for p in path.split("."):
        node = node[p]
    return node


def _clear_env(monkeypatch) -> None:
    for var in _ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def ckpt(tmp_path) -> Path:
    """Factory checkpoint + the three resolver source files."""
    d = tmp_path / "checkpoints" / RUN_ID
    make_run_checkpoint(d, nodes=5, seed=0)
    (d / "workflow.yaml").write_text(yaml.safe_dump(_WORKFLOW))
    (d / "launch_config.json").write_text(json.dumps(_LAUNCH_CONFIG, indent=2))
    (d / "rqgm_state.json").write_text(json.dumps(_RQGM_STATE, indent=2))
    return d


# ── manifest shape + layer precedence ──────────────────────────────────────


def test_manifest_shape(ckpt):
    m = resolve_run_config(ckpt, env={})
    assert set(m.keys()) == {
        "schema_version", "resolver_version", "run_id", "resolved_at",
        "digest", "source_stack", "values", "provenance",
        "secret_references", "warnings",
    }
    assert m["schema_version"] == 1
    assert m["resolver_version"] == RESOLVER_VERSION == "legacy-compatible-1"
    assert m["run_id"] == RUN_ID
    assert m["resolved_at"] is None  # caller fills — the resolver has no clock
    assert m["digest"].startswith("sha256:") and len(m["digest"]) == 71
    assert m["source_stack"] == [
        "default", "workflow", "launch_config", "env", "checkpoint_state",
    ]
    for entry in m["provenance"].values():
        assert set(entry.keys()) == {"source", "mutable", "confidence"}
        assert entry["confidence"] in ("high", "low")


def test_layer_precedence_and_provenance(ckpt):
    m = resolve_run_config(ckpt, env={})
    v, p = m["values"], m["provenance"]
    # launch_config wins over workflow.yaml (max_total_nodes 30 -> 40).
    assert _leaf(v, "bfts.max_total_nodes") == 40
    assert p["bfts.max_total_nodes"]["source"] == "launch_config"
    assert _leaf(v, "llm.model") == "claude-sonnet-4-5"
    assert p["llm.model"]["source"] == "launch_config"
    assert _leaf(v, "llm.backend") == "anthropic"
    assert _leaf(v, "bfts.frontier_score") == "depth_penalized"
    assert _leaf(v, "evaluator.composite") == "geometric_mean"
    # workflow.yaml wins over the pydantic default (temperature 0.7 -> 0.5).
    assert _leaf(v, "llm.temperature") == 0.5
    assert p["llm.temperature"] == {
        "source": "workflow", "mutable": False, "confidence": "high",
    }
    # untouched leaf keeps its pydantic default.
    assert _leaf(v, "bfts.ucb_c") == 0.5
    assert p["bfts.ucb_c"]["source"] == "default"


def test_rqgm_state_mode_wins(ckpt):
    # workflow.yaml requested simple_bfts; the persisted checkpoint state is
    # ari_rqgm and wins with mutable=false (reconcile_resume_mode parity).
    m = resolve_run_config(ckpt, env={"ARI_MODE": "simple_bfts"})
    assert _leaf(m["values"], "ari.mode") == "ari_rqgm"
    assert _leaf(m["values"], "rqgm.enabled") is True
    assert m["provenance"]["ari.mode"] == {
        "source": "checkpoint_state", "mutable": False, "confidence": "high",
    }
    assert m["provenance"]["rqgm.enabled"]["source"] == "checkpoint_state"
    assert any("persisted mode wins" in w for w in m["warnings"])


def test_unknown_workflow_top_level_key_warns(ckpt):
    m = resolve_run_config(ckpt, env={})
    hits = [w for w in m["warnings"] if "totally_unknown_key" in w]
    assert len(hits) == 1 and "silently drops" in hits[0]
    # known non-config keys (consumed by other readers) do NOT warn.
    (ckpt / "workflow.yaml").write_text(
        yaml.safe_dump({**_WORKFLOW, "memory": {"backend": "letta"}})
    )
    m2 = resolve_run_config(ckpt, env={})
    assert not any("'memory'" in w for w in m2["warnings"])


# ── env overlay: documented families only, confidence low ──────────────────


def test_env_family_paths_pinned_to_registry():
    # The resolver's env overlay and the field-registry ENV_OVERRIDES map are
    # two transcriptions of the same apply_*_env_overrides family — pin them
    # equal so they cannot drift apart.
    assert ENV_FAMILY_PATHS == frozenset(ENV_OVERRIDES)


def test_launch_config_map_pinned_verbatim():
    # Literal transcription of the ``_launch_cfg`` snapshot writer in
    # ``ari/viz/api_experiment.py::_api_launch`` — pinned so a launcher key
    # rename/addition forces a conscious resolver update.
    assert dict(LAUNCH_CONFIG_MAP) == {
        "llm_model": "llm.model",
        "llm_provider": "llm.backend",
        "max_nodes": "bfts.max_total_nodes",
        "max_depth": "bfts.max_depth",
        "max_react": "bfts.max_react_steps",
        "timeout_node_s": "bfts.timeout_per_node",
        "parallel": "bfts.max_parallel_nodes",
        "frontier_score": "bfts.frontier_score",
        "composite": "evaluator.composite",
        "axis_mode": "evaluator.axis_mode",
        "allow_web": "bfts.allow_web",
    }


def test_env_overlay_applies_documented_families(ckpt):
    m = resolve_run_config(
        ckpt, env={"ARI_MAX_NODES": "77", "ARI_COMPOSITE": "weighted_min"}
    )
    assert _leaf(m["values"], "bfts.max_total_nodes") == 77
    assert m["provenance"]["bfts.max_total_nodes"] == {
        "source": "env", "mutable": False, "confidence": "low",
    }
    assert _leaf(m["values"], "evaluator.composite") == "weighted_min"
    assert any("may differ from the launch-time environment" in w
               for w in m["warnings"])


def test_env_invalid_values_rejected_with_warning(ckpt):
    m = resolve_run_config(
        ckpt,
        env={
            "ARI_MAX_NODES": "not-a-number",
            "ARI_FRONTIER_SCORE": "bogus",
            "ARI_RQGM_ENABLED": "maybe",
        },
    )
    # values keep the lower layer (legacy chain ignores invalid env input).
    assert _leaf(m["values"], "bfts.max_total_nodes") == 40
    assert _leaf(m["values"], "bfts.frontier_score") == "depth_penalized"
    assert m["provenance"]["bfts.max_total_nodes"]["source"] == "launch_config"
    rejected = [w for w in m["warnings"] if "env override rejected" in w]
    assert len(rejected) == 3


def test_log_level_env_is_auto_config_path_only(ckpt, tmp_path):
    # With workflow.yaml present ARI_LOG_LEVEL is NOT applied (load_config
    # never env-overrides logging.level); without it the auto_config path is.
    m = resolve_run_config(ckpt, env={"ARI_LOG_LEVEL": "DEBUG"})
    assert _leaf(m["values"], "logging.level") == "INFO"
    bare = tmp_path / "checkpoints" / "20260723000001_bare"
    bare.mkdir(parents=True)
    m2 = resolve_run_config(bare, env={"ARI_LOG_LEVEL": "DEBUG"})
    assert _leaf(m2["values"], "logging.level") == "DEBUG"
    assert m2["provenance"]["logging.level"]["source"] == "env"


# ── determinism + digest ───────────────────────────────────────────────────


def test_determinism_two_calls_identical(ckpt):
    m1 = resolve_run_config(ckpt, env={})
    m2 = resolve_run_config(ckpt, env={})
    assert m1 == m2  # whole-manifest equality, resolved_at None in both


def test_digest_invariant_under_undocumented_env(ckpt):
    base = resolve_run_config(ckpt, env={})
    noisy = resolve_run_config(
        ckpt,
        env={
            "SOME_RANDOM_VAR": "x",
            "OPENAI_API_KEY": "sk-test-secret-0123456789abcdef",
            "ARI_IDEA_VIRSCI_REAL": "1",  # ARI_* but NOT a documented family
        },
    )
    assert noisy["digest"] == base["digest"]
    assert noisy["values"] == base["values"]
    # ... while a documented family does move the digest.
    moved = resolve_run_config(ckpt, env={"ARI_MAX_NODES": "77"})
    assert moved["digest"] != base["digest"]


# ── secret redaction ───────────────────────────────────────────────────────


def test_secret_never_in_values_or_digest_input(ckpt):
    secret = "sk-test-secret-0123456789abcdef"
    m = resolve_run_config(ckpt, env={"OPENAI_API_KEY": secret})
    payload = json.dumps(m)
    assert secret not in payload
    assert "api_key" not in m["values"].get("llm", {})
    assert "llm.api_key" not in m["provenance"]
    assert m["secret_references"] == {
        "llm.api_key": {"provider": "env", "configured": True}
    }
    # digest input is the redacted values JSON — planting the key moves
    # nothing (same digest as a resolution without any key).
    assert m["digest"] == resolve_run_config(ckpt, env={})["digest"]


def test_workflow_secret_redacted_but_flagged(ckpt):
    wf = copy.deepcopy(_WORKFLOW)
    wf["llm"]["api_key"] = "sk-from-yaml-000000000000"
    (ckpt / "workflow.yaml").write_text(yaml.safe_dump(wf))
    m = resolve_run_config(ckpt, env={})
    assert "sk-from-yaml" not in json.dumps(m)
    assert m["secret_references"]["llm.api_key"] == {
        "provider": "workflow", "configured": True,
    }


# ── read-only guarantee (INDEX.md invariant) ───────────────────────────────


def test_resolver_writes_nothing_and_leaves_environ_alone(ckpt):
    before_env = dict(os.environ)
    before_files = {
        p.name: p.stat().st_mtime_ns for p in ckpt.iterdir() if p.is_file()
    }
    resolve_run_config(ckpt)  # env=None -> reads (never writes) os.environ
    assert dict(os.environ) == before_env
    after_files = {
        p.name: p.stat().st_mtime_ns for p in ckpt.iterdir() if p.is_file()
    }
    assert after_files == before_files


# ── GET /api/v1/runs/{run_id}/resolved-config ──────────────────────────────


@pytest.fixture
def api_base(ckpt, monkeypatch):
    _clear_env(monkeypatch)
    base = ckpt.parent
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    return base


def test_endpoint_happy_path(api_base):
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/resolved-config")
    assert "_status" not in r
    assert re.match(r"^req-[0-9a-f]{12}$", r["request_id"])
    assert r["schema_version"] == 1
    assert r["resolver_version"] == "legacy-compatible-1"
    assert r["run_id"] == RUN_ID
    assert _leaf(r["values"], "ari.mode") == "ari_rqgm"
    assert r["warnings"]  # at least the reconstruction notice surfaces


def test_endpoint_resolved_at_stable_from_mtimes(api_base):
    r1 = dispatch("GET", f"/api/v1/runs/{RUN_ID}/resolved-config")
    r2 = dispatch("GET", f"/api/v1/runs/{RUN_ID}/resolved-config")
    assert _ISO_RE.match(r1["resolved_at"])
    assert r1["resolved_at"] == r2["resolved_at"]  # mtime-derived, no now()
    assert r1["digest"] == r2["digest"]


def test_endpoint_unknown_run_404(api_base):
    r = dispatch("GET", "/api/v1/runs/nope/resolved-config")
    assert r["_status"] == 404
    assert r["error"]["code"] == "not_found"


# ── golden parity vs the REAL legacy chain (plan 05 'golden parity') ───────


def test_golden_parity_with_legacy_chain(tmp_path, monkeypatch):
    """legacy-compatible-1 tracks load_config + apply_*_env_overrides on the
    overlapping leaf set for the same workflow.yaml + env inputs."""
    wf = {
        # skills: [] keeps load_config off the _discover_skills branch so
        # the comparison stays hermetic.
        "skills": [],
        "llm": {"model": "wf-parity-model", "backend": "ollama",
                "temperature": 0.3},
        "bfts": {"max_total_nodes": 9, "max_depth": 3, "max_react_steps": 11,
                 "max_parallel_nodes": 2, "timeout_per_node": 60,
                 "frontier_score": "scientific_only", "allow_web": False},
        "evaluator": {"composite": "arithmetic_mean", "axis_mode": "legacy"},
        "ari": {"mode": "simple_bfts"},
        "rqgm": {"enabled": False},
    }
    env = {
        "ARI_MODEL": "env-parity-model",
        "ARI_BACKEND": "openai",
        "ARI_LLM_API_BASE": "http://localhost:9999/v1",
        "ARI_MAX_NODES": "21",
        "ARI_PARALLEL": "3",
        "ARI_FRONTIER_SCORE": "ucb_like",
        "ARI_COMPOSITE": "weighted_min",
        "ARI_AXIS_MODE": "dynamic",
        "ARI_MODE": "ari_rqgm",
        "ARI_RQGM_ENABLED": "1",
    }
    ckpt = tmp_path / "20260723000002_parity"
    ckpt.mkdir()
    (ckpt / "workflow.yaml").write_text(yaml.safe_dump(wf))
    # no launch_config.json / rqgm_state.json: the bare CLI chain reads
    # neither, so the parity surface is defaults + workflow + env.

    # 1) the REAL chain, with os.environ pinned to exactly `env`.
    _clear_env(monkeypatch)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = load_config(str(ckpt / "workflow.yaml"))
    apply_bfts_env_overrides(cfg)
    apply_evaluator_env_overrides(cfg)
    apply_rqgm_env_overrides(cfg)

    # 2) the resolver, fed the same env mapping.
    m = resolve_run_config(ckpt, env=env)
    v, p = m["values"], m["provenance"]

    overlap = [
        ("llm.model", cfg.llm.model, "env"),
        ("llm.backend", cfg.llm.backend, "env"),
        ("llm.base_url", cfg.llm.base_url, "env"),
        ("llm.temperature", cfg.llm.temperature, "workflow"),
        ("bfts.max_total_nodes", cfg.bfts.max_total_nodes, "env"),
        ("bfts.max_depth", cfg.bfts.max_depth, "workflow"),
        ("bfts.max_react_steps", cfg.bfts.max_react_steps, "workflow"),
        ("bfts.max_parallel_nodes", cfg.bfts.max_parallel_nodes, "env"),
        ("bfts.timeout_per_node", cfg.bfts.timeout_per_node, "workflow"),
        ("bfts.frontier_score", cfg.bfts.frontier_score, "env"),
        ("bfts.allow_web", cfg.bfts.allow_web, "workflow"),
        ("evaluator.composite", cfg.evaluator.composite, "env"),
        ("evaluator.axis_mode", cfg.evaluator.axis_mode, "env"),
        ("ari.mode", cfg.ari.mode, "env"),
        ("rqgm.enabled", cfg.rqgm.enabled, "env"),
    ]
    for path, legacy_value, expected_source in overlap:
        assert _leaf(v, path) == legacy_value, path
        assert p[path]["source"] == expected_source, path
    # sanity: the env really did win where it should (not defaults parity).
    assert cfg.llm.model == "env-parity-model"
    assert cfg.bfts.max_total_nodes == 21
    assert cfg.ari.mode == "ari_rqgm" and cfg.rqgm.enabled is True
