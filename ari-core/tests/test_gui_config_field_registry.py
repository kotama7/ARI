"""Tests for the canonical config field registry (gui_refresh task 05 Wave 3a).

Plan ``docs/plans/gui_refresh/05`` §Canonical field metadata / §Configuration
scopes / §Completion criteria:

- coverage invariant — 100% of walked ``ARIConfig`` leaves carry FIELD_META
  (``get_uncovered() == []``) and ``build_field_registry`` raises otherwise;
- frozen leaf count (ratchets UP as config grows — see
  ``EXPECTED_LEAF_COUNT``);
- spot-checks of ten known paths' hand-authored metadata;
- determinism (two builds byte-identical, no shared mutable state);
- the ``ENV_OVERRIDES`` literal map pinned verbatim against the
  ``apply_*_env_overrides`` family;
- ``GET /api/v1/config/schema`` happy path + secret metadata-only redaction;
- read-only guarantee: building the registry never mutates ``ARIConfig``
  class state, ``os.environ``, or instance defaults.
"""

from __future__ import annotations

import copy
import json
import os
import re

import pytest

from ari.config import ARIConfig
from ari.config.field_registry import (
    ENV_OVERRIDES,
    FIELD_META,
    LEVELS,
    MUTABILITIES,
    SCOPES,
    SENSITIVITIES,
    build_field_registry,
    get_uncovered,
    walk_config_leaves,
)
from ari.viz.v1.router import dispatch

_REQUEST_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")

# Frozen leaf count. This number only RATCHETS UP: adding a config field to
# ARIConfig (or typing a previously-untyped extra='allow' block) adds leaves.
# When this assertion fails after a config change, (1) bump the count and
# (2) add/extend a FIELD_META prefix or exact entry for the new path(s) —
# the coverage test below will name exactly which paths are missing.
EXPECTED_LEAF_COUNT = 144

# The wire keys of one registry entry / ConfigFieldV1 (metadata only — a
# "value" channel must never appear here).
_ENTRY_KEYS = {
    "path", "value_type", "default", "enum", "required", "category",
    "level", "scope", "sensitivity", "mutability", "applies_when",
    "notes", "source", "env_override",
}


# ── coverage invariant (plan 05 §Completion criteria) ──────────────────────


def test_coverage_100_percent():
    """Every walked leaf has FIELD_META coverage — the completion criterion.

    If this fails, a config field was added without registry metadata: add a
    prefix (``"block."``) or exact-path entry to
    ``ari.config.field_registry.FIELD_META`` for each listed path.
    """
    assert get_uncovered() == [], (
        "config leaves without FIELD_META coverage — add a prefix or exact "
        f"entry to ari.config.field_registry.FIELD_META for: {get_uncovered()}"
    )


def test_leaf_count_frozen():
    leaves = walk_config_leaves()
    assert len(leaves) >= 120, "sanity floor: ARIConfig has >=120 leaves"
    assert len(leaves) == EXPECTED_LEAF_COUNT, (
        f"ARIConfig leaf count changed ({len(leaves)} != "
        f"{EXPECTED_LEAF_COUNT}). This ratchets UP when config grows: bump "
        "EXPECTED_LEAF_COUNT and add FIELD_META coverage for any new paths "
        "(test_coverage_100_percent names the uncovered ones)."
    )


def test_registry_covers_every_leaf_exactly_once():
    reg = build_field_registry()
    paths = [e["path"] for e in reg]
    assert len(paths) == len(set(paths)), "duplicate registry paths"
    assert paths == [leaf["path"] for leaf in walk_config_leaves()]


def test_every_entry_has_closed_vocabulary_metadata():
    for e in build_field_registry():
        assert set(e.keys()) == _ENTRY_KEYS, e["path"]
        assert e["category"], e["path"]
        assert e["level"] in LEVELS, e["path"]
        assert e["scope"] in SCOPES, e["path"]
        assert e["sensitivity"] in SENSITIVITIES, e["path"]
        assert e["mutability"] in MUTABILITIES, e["path"]
        assert e["source"] == "pydantic", e["path"]


def test_uncovered_leaf_fails_loudly(monkeypatch):
    """A leaf without coverage must raise LookupError, never ship silently."""
    trimmed = {k: v for k, v in FIELD_META.items() if not k.startswith("llm")}
    monkeypatch.setattr("ari.config.field_registry.FIELD_META", trimmed)
    assert "llm.model" in get_uncovered()
    with pytest.raises(LookupError, match="llm.model"):
        build_field_registry()


# ── spot-checks: ten known paths (plan 05 scope table) ─────────────────────


def _by_path() -> dict[str, dict]:
    return {e["path"]: e for e in build_field_registry()}


@pytest.mark.parametrize(
    "path,expected",
    [
        # Execution-mode switches are immutable per run (plan 05 interlocks).
        ("ari.mode", {"category": "Execution mode", "mutability": "new_run_only",
                      "env_override": "ARI_MODE", "enum": ["simple_bfts", "ari_rqgm"]}),
        ("paper.mode", {"category": "Execution mode", "mutability": "new_run_only",
                        "env_override": "ARI_PAPER_MODE"}),
        # ADR-09: the interlock twin still does NOT inherit the
        # ari.mode=ari_rqgm gate (that would make the interlock self-gating);
        # its applies_when is the paired-intent note the GUI renders.
        ("rqgm.enabled", {"category": "Execution mode", "mutability": "new_run_only",
                          "env_override": "ARI_RQGM_ENABLED",
                          "applies_when":
                              "paired with ari.mode (one intent — set both)"}),
        # Secrets: reference-only, never a value/default.
        ("llm.api_key", {"category": "Models", "sensitivity": "secret_reference",
                         "scope": "installation", "default": None}),
        # Models: project-scoped drafts with the GUI env bridge.
        ("llm.model", {"category": "Models", "level": "basic", "scope": "project",
                       "mutability": "draft", "env_override": "ARI_MODEL"}),
        # BFTS core knobs: env-hooked, draft mutability.
        ("bfts.max_total_nodes", {"category": "Search (BFTS)", "level": "basic",
                                  "mutability": "draft",
                                  "env_override": "ARI_MAX_NODES"}),
        ("bfts.ucb_c", {"level": "expert", "env_override": None,
                        "applies_when": "bfts.frontier_score=ucb_like"}),
        # Evaluator: draft, env-hooked composite.
        ("evaluator.composite", {"category": "Evaluation", "mutability": "draft",
                                 "env_override": "ARI_COMPOSITE"}),
        # RQGM subtree: Governance / expert / new-run-only / mode-gated.
        ("rqgm.epoch.nodes_per_epoch", {"category": "Governance", "level": "expert",
                                        "mutability": "new_run_only",
                                        "applies_when": "ari.mode=ari_rqgm"}),
        # rqgm.paper.* is gated on the PAPER mode axis, not ari.mode.
        ("rqgm.paper.archive.width", {"category": "Governance",
                                      "applies_when": "paper.mode=rqgm_archive"}),
    ],
)
def test_known_path_metadata(path, expected):
    entry = _by_path()[path]
    for key, want in expected.items():
        assert entry[key] == want, f"{path}.{key}: {entry[key]!r} != {want!r}"


def test_rqgm_prefix_default_applies_when():
    """Every rqgm.* leaf outside rqgm.paper.* inherits the ari_rqgm gate;
    the two interlock twins (``rqgm.enabled`` / ``rqgm.paper.enabled``) are
    the deliberate exception — they carry the ADR-09 paired-intent note
    instead of a gate that would make the interlock gate itself."""
    for e in build_field_registry():
        p = e["path"]
        if not p.startswith("rqgm.") or p == "rqgm.enabled":
            continue
        if p.startswith("rqgm.paper."):
            if p == "rqgm.paper.enabled":
                assert e["applies_when"] == (
                    "paired with paper.mode (one intent — set both)"
                ), p
            else:
                assert e["applies_when"] == "paper.mode=rqgm_archive", p
        else:
            assert e["applies_when"] == "ari.mode=ari_rqgm", p
        assert e["mutability"] == "new_run_only", p


def test_env_overrides_pinned_verbatim():
    """The literal transcription of the apply_*_env_overrides family
    (ari/config/__init__.py). Changing an env hook means updating BOTH."""
    assert ENV_OVERRIDES == {
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
    # Every env-mapped path must be a walked leaf (no dangling map entries).
    leaf_paths = {leaf["path"] for leaf in walk_config_leaves()}
    assert set(ENV_OVERRIDES) <= leaf_paths


# ── determinism (P2) ───────────────────────────────────────────────────────


def test_two_builds_identical():
    r1 = build_field_registry()
    r2 = build_field_registry()
    assert r1 == r2
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_returned_defaults_are_isolated_copies():
    """Mutating a returned mutable default must not leak into later builds."""
    reg = _by_path()
    weights = reg["rqgm.adversarial.penalty.severity_weights"]["default"]
    assert isinstance(weights, dict)
    weights["critical"] = 999.0
    fresh = _by_path()["rqgm.adversarial.penalty.severity_weights"]["default"]
    assert fresh["critical"] != 999.0


# ── endpoint: GET /api/v1/config/schema ────────────────────────────────────


def test_endpoint_happy_path():
    r = dispatch("GET", "/api/v1/config/schema")
    assert set(r.keys()) == {
        "schema_version", "resolver_version", "fields", "request_id",
    }
    assert r["schema_version"] == 1
    assert r["resolver_version"] == "legacy-compatible-1"
    assert _REQUEST_ID_RE.match(r["request_id"])
    assert len(r["fields"]) == EXPECTED_LEAF_COUNT
    assert {f["path"] for f in r["fields"]} == {
        leaf["path"] for leaf in walk_config_leaves()
    }
    json.dumps(r)  # wire-serializable as-is


def test_endpoint_secret_fields_metadata_only():
    """secret_reference fields never carry defaults/values on the wire."""
    r = dispatch("GET", "/api/v1/config/schema")
    secrets = [f for f in r["fields"] if f["sensitivity"] == "secret_reference"]
    assert secrets, "expected at least one secret_reference field (llm.api_key)"
    assert {f["path"] for f in secrets} == {"llm.api_key"}
    for f in secrets:
        assert f["default"] is None
        assert "value" not in f
        assert set(f.keys()) <= _ENTRY_KEYS
    # No plaintext key material anywhere in the payload.
    assert "sk-" not in json.dumps(r)


# ── read-only guarantee (INDEX.md invariant: inert unless GUI calls it) ────


def test_build_mutates_no_class_state_or_environ():
    fields_before = {
        name: (repr(f.default), f.default_factory)
        for name, f in ARIConfig.model_fields.items()
    }
    defaults_before = ARIConfig().model_dump()
    environ_before = dict(os.environ)

    build_field_registry()
    walk_config_leaves()
    get_uncovered()
    dispatch("GET", "/api/v1/config/schema")

    fields_after = {
        name: (repr(f.default), f.default_factory)
        for name, f in ARIConfig.model_fields.items()
    }
    assert fields_after == fields_before
    assert ARIConfig().model_dump() == defaults_before
    assert dict(os.environ) == environ_before


def test_field_meta_untouched_by_build():
    snapshot = copy.deepcopy(FIELD_META)
    build_field_registry()
    assert FIELD_META == snapshot
