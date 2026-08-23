"""Precedence-matrix golden tests for the NEW-RUN resolver (gui_refresh
task 05 Wave 3b) + the draft preview endpoints.

``docs/reference/configuration.md`` §Resolution model (table "B) New run",
plus "The 4-key profile merge caveat"): a table-driven matrix over that
new-run chain, implemented by
``ari.config.resolver.resolve_new_run_config``::

    defaults < bundled workflow.yaml < profile (EXACT 4-key _apply_profile
    merge) < project < template < draft < documented ARI_* env
    -> validated effective (+ interlock warn+fallback)

Covered here:

- each layer alone + every adjacent-pair precedence (frozen expected
  ``{path: (value, source)}`` literals — values + provenance sources only);
- the profile 4-key merge parity: non-merged profile keys are ignored WITH a
  warning listing them (plan 05: never show a field as applied when the
  profile does not merge it);
- documented env families win over the draft; undocumented families are
  inert (values, provenance, digest all unchanged);
- rejected overrides keep the last VALID layer value with a
  ``rejected_override`` provenance annotation + warning;
- secret paths never enter values/provenance/digest (configured-flag only);
- the rqgm interlock intent pair (``resolve_effective_mode`` parity: warn +
  fallback to ``simple_bfts``, the manifest shows the EFFECTIVE mode);
- the resume/existing-checkpoint mode (`resolve_run_config`) is byte-
  identical before/after preview calls — the preview code cannot leak into
  it (INDEX.md invariant);
- the ``POST /api/v1/run-drafts/{draft_id}/resolve-config`` and
  ``.../validate`` endpoints over the real store documents + the REAL
  bundled profiles.

The matrix scenarios monkeypatch ``ari.config.finder.package_config_root``
to a tmp dir so the bundled workflow/profile layers are hermetic literals;
the endpoint tests use the real bundle (repo files are stable goldens).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ari.config import finder
from ari.config.field_registry import ENV_OVERRIDES
from ari.config.resolver import (
    PROFILE_MERGED_KEYS,
    resolve_new_run_config,
    resolve_run_config,
)
from ari.viz.v1.router import dispatch

# Every env var the resolver chain may read — cleared/controlled so
# developer/CI environments cannot leak into the goldens.
_ALL_ENV_VARS = sorted(set(ENV_OVERRIDES.values()) | {"ARI_LLM_MODEL"})


def _leaf(values: dict, path: str):
    node = values
    for p in path.split("."):
        node = node[p]
    return node


@pytest.fixture
def pkg_root(tmp_path, monkeypatch) -> Path:
    """Hermetic bundled-config root: resolve_new_run_config reads
    ``{pkg_root}/workflow.yaml`` and ``{pkg_root}/profiles/*.yaml``."""
    root = tmp_path / "pkgcfg"
    (root / "profiles").mkdir(parents=True)
    monkeypatch.setattr(finder, "package_config_root", lambda: root)
    return root


def _resolve(
    pkg_root: Path,
    *,
    workflow: dict | None = None,
    profiles: dict | None = None,
    profile: str | None = None,
    project: dict | None = None,
    template: dict | None = None,
    draft: dict | None = None,
    env: dict | None = None,
) -> dict:
    if workflow is not None:
        (pkg_root / "workflow.yaml").write_text(yaml.safe_dump(workflow))
    for name, content in (profiles or {}).items():
        (pkg_root / "profiles" / f"{name}.yaml").write_text(
            yaml.safe_dump(content)
        )
    return resolve_new_run_config(
        project_values=project,
        template_values=template,
        draft_values=draft,
        profile=profile,
        env=env or {},
    )


# Literal profile fixtures (hermetic copies of the real 3-profile shape).
_LAPTOP = {
    "profile": "laptop",
    "hpc": {"enabled": False, "scheduler": "none"},
    "bfts": {"max_total_nodes": 8, "parallel": 2},
}
_HPC = {
    "profile": "hpc",
    "hpc": {"enabled": True, "scheduler": "auto", "partition": "gpu"},
    "bfts": {"max_total_nodes": 20, "parallel": 4},
}

# ── the precedence matrix (plan 05 §Validation and tests) ──────────────────
#
# Frozen expected manifests as literal dicts: ``expect`` maps a leaf path to
# ``(effective value, provenance source)``; ``stack`` is the exact
# source_stack; ``rejected`` pins rejected_override annotations verbatim.

MATRIX = [
    dict(
        id="defaults_alone",
        expect={
            "llm.model": ("qwen3:8b", "default"),
            "llm.backend": ("ollama", "default"),
            "bfts.max_total_nodes": (50, "default"),
            "ari.mode": ("simple_bfts", "default"),
            "resources": ({}, "default"),
        },
        stack=["default"],
    ),
    dict(
        id="workflow_alone_over_default",
        workflow={
            "skills": [],
            "llm": {"model": "wf-model"},
            "bfts": {"max_total_nodes": 30},
        },
        expect={
            "llm.model": ("wf-model", "workflow"),
            "bfts.max_total_nodes": (30, "workflow"),
            "llm.backend": ("ollama", "default"),  # untouched leaf
        },
        stack=["default", "workflow"],
    ),
    dict(
        id="profile_alone_4key_merge",
        profiles={"laptop": _LAPTOP},
        profile="laptop",
        expect={
            "bfts.max_total_nodes": (8, "profile"),
            "bfts.max_parallel_nodes": (2, "profile"),  # 'parallel' spelling
            "resources": (
                {"hpc_enabled": False, "scheduler": "none"}, "profile",
            ),
            "llm.model": ("qwen3:8b", "default"),
        },
        stack=["default", "profile"],
    ),
    dict(
        id="profile_over_workflow_nonmerged_ignored_and_warned",
        workflow={
            "skills": [],
            "bfts": {"max_total_nodes": 30, "max_depth": 7},
        },
        profiles={"hpc": _HPC},
        profile="hpc",
        expect={
            "bfts.max_total_nodes": (20, "profile"),
            "bfts.max_depth": (7, "workflow"),  # profile never merges it
            "resources": (
                {"hpc_enabled": True, "scheduler": "auto"}, "profile",
            ),
        },
        stack=["default", "workflow", "profile"],
        warn_substrings=["ignored non-merged keys", "hpc.partition"],
    ),
    dict(
        id="project_alone",
        project={"llm.model": "proj-model"},
        expect={"llm.model": ("proj-model", "project")},
        stack=["default", "project"],
    ),
    dict(
        id="project_over_profile",
        profiles={"laptop": _LAPTOP},
        profile="laptop",
        project={"bfts.max_total_nodes": 25},
        expect={
            "bfts.max_total_nodes": (25, "project"),
            "bfts.max_parallel_nodes": (2, "profile"),  # untouched by project
        },
        stack=["default", "profile", "project"],
    ),
    dict(
        id="template_alone",
        template={"evaluator.composite": "geometric_mean"},
        expect={"evaluator.composite": ("geometric_mean", "template")},
        stack=["default", "template"],
    ),
    dict(
        id="template_over_project",
        project={"llm.model": "proj-model", "bfts.max_depth": 6},
        template={"llm.model": "tmpl-model"},
        expect={
            "llm.model": ("tmpl-model", "template"),
            "bfts.max_depth": (6, "project"),
        },
        stack=["default", "project", "template"],
    ),
    dict(
        id="draft_alone",
        draft={"bfts.allow_web": True},
        expect={"bfts.allow_web": (True, "draft")},
        stack=["default", "draft"],
    ),
    dict(
        id="draft_over_template",
        template={"llm.model": "tmpl-model", "bfts.max_react_steps": 42},
        draft={"llm.model": "draft-model"},
        expect={
            "llm.model": ("draft-model", "draft"),
            "bfts.max_react_steps": (42, "template"),
        },
        stack=["default", "template", "draft"],
    ),
    dict(
        id="env_documented_family_over_draft",
        draft={"llm.model": "draft-model", "bfts.max_total_nodes": 12},
        env={"ARI_MODEL": "env-model"},
        expect={
            "llm.model": ("env-model", "env"),
            "bfts.max_total_nodes": (12, "draft"),
        },
        stack=["default", "draft", "env"],
        warn_substrings=["may differ from the launch-time environment"],
    ),
    dict(
        id="env_undocumented_family_inert",
        draft={"llm.model": "draft-model"},
        env={
            "ARI_SLURM_CPUS": "8",       # exported family, NOT documented
            "ARI_IDEA_VIRSCI_REAL": "1",  # ARI_* but not an override family
            "SOME_RANDOM_VAR": "x",
        },
        expect={
            "llm.model": ("draft-model", "draft"),
            "resources": ({}, "default"),  # ARI_SLURM_* never lands here
        },
        stack=["default", "draft"],  # zero env hits -> no env layer
    ),
    dict(
        id="rejected_type_keeps_prior_layer",
        template={"bfts.max_total_nodes": 33},
        draft={"bfts.max_total_nodes": "many"},
        expect={"bfts.max_total_nodes": (33, "template")},
        stack=["default", "template", "draft"],
        warn_substrings=[
            "draft override rejected for bfts.max_total_nodes",
        ],
        rejected={
            "bfts.max_total_nodes": {
                "source": "draft", "value": "many",
                "reason": "invalid_type", "expected": "int",
            },
        },
    ),
    dict(
        id="rejected_enum_keeps_prior_layer",
        draft={"evaluator.composite": "bogus"},
        expect={"evaluator.composite": ("harmonic_mean", "default")},
        stack=["default", "draft"],
        warn_substrings=["draft override rejected for evaluator.composite"],
        rejected={
            "evaluator.composite": {
                "source": "draft", "value": "bogus",
                "reason": "invalid_enum",
                "expected": [
                    "harmonic_mean", "arithmetic_mean", "weighted_min",
                    "geometric_mean",
                ],
            },
        },
    ),
    dict(
        id="secret_path_never_in_values",
        draft={
            "llm.api_key": "sk-secret-key-000000000000",
            "llm.model": "draft-model",
        },
        expect={"llm.model": ("draft-model", "draft")},
        stack=["default", "draft"],
        warn_substrings=["secrets never appear in resolved values"],
        secret_refs={"llm.api_key": {"provider": "draft", "configured": True}},
        forbid_substring="sk-secret-key",
    ),
    dict(
        id="interlock_mismatch_effective_simple_bfts",
        draft={"ari.mode": "ari_rqgm"},  # interlock twin left False
        expect={
            "ari.mode": ("simple_bfts", "draft"),  # EFFECTIVE mode shown
            "rqgm.enabled": (False, "default"),
        },
        stack=["default", "draft"],
        warn_substrings=[
            "ari.mode=ari_rqgm but rqgm.enabled=False",
            "falling back to simple_bfts",
        ],
        rejected={
            "ari.mode": {
                "source": "draft", "value": "ari_rqgm",
                "reason": "interlock_mismatch",
            },
        },
    ),
    dict(
        id="interlock_pair_consistent_activates",
        draft={"ari.mode": "ari_rqgm", "rqgm.enabled": True},
        expect={
            "ari.mode": ("ari_rqgm", "draft"),
            "rqgm.enabled": (True, "draft"),
        },
        stack=["default", "draft"],
        no_warn_substrings=["falling back to simple_bfts"],
    ),
    dict(
        id="interlock_set_without_master_warns_only",
        draft={"rqgm.enabled": True},
        expect={
            "ari.mode": ("simple_bfts", "default"),
            "rqgm.enabled": (True, "draft"),
        },
        stack=["default", "draft"],
        warn_substrings=["interlock is set without its master switch"],
    ),
]


@pytest.mark.parametrize("case", MATRIX, ids=[c["id"] for c in MATRIX])
def test_precedence_matrix(pkg_root, case):
    m = _resolve(
        pkg_root,
        workflow=case.get("workflow"),
        profiles=case.get("profiles"),
        profile=case.get("profile"),
        project=case.get("project"),
        template=case.get("template"),
        draft=case.get("draft"),
        env=case.get("env"),
    )
    for path, (value, source) in case["expect"].items():
        assert _leaf(m["values"], path) == value, path
        assert m["provenance"][path]["source"] == source, path
    assert m["source_stack"] == case["stack"]
    for sub in case.get("warn_substrings", []):
        assert any(sub in w for w in m["warnings"]), (sub, m["warnings"])
    for sub in case.get("no_warn_substrings", []):
        assert not any(sub in w for w in m["warnings"]), (sub, m["warnings"])
    for path, expected in case.get("rejected", {}).items():
        assert m["provenance"][path]["rejected_override"] == expected, path
    if "secret_refs" in case:
        assert m["secret_references"] == case["secret_refs"]
    if "forbid_substring" in case:
        assert case["forbid_substring"] not in json.dumps(m)


# ── matrix-adjacent unit properties ────────────────────────────────────────


def test_profile_merged_keys_pinned_verbatim():
    # Literal transcription of the _apply_profile merge (ari/cli/run.py) —
    # pinned so a profile-merge change forces a conscious resolver update.
    assert PROFILE_MERGED_KEYS == frozenset({
        "bfts.max_total_nodes", "bfts.max_parallel_nodes", "bfts.parallel",
        "hpc.enabled", "hpc.scheduler",
    })


def test_unknown_profile_warns_and_is_ignored(pkg_root):
    m = _resolve(pkg_root, profile="does-not-exist")
    assert m["source_stack"] == ["default"]
    assert any(
        "profile 'does-not-exist' not found" in w for w in m["warnings"]
    )


def test_unknown_layer_path_warns_and_is_ignored(pkg_root):
    m = _resolve(pkg_root, draft={"nonsense.path": 1, "llm.model": "x"})
    assert _leaf(m["values"], "llm.model") == "x"
    assert "nonsense" not in json.dumps(m["values"])
    assert any(
        "draft override rejected for nonsense.path" in w
        for w in m["warnings"]
    )


def test_env_invalid_value_rejected_with_warning(pkg_root):
    m = _resolve(pkg_root, env={"ARI_MAX_NODES": "not-a-number"})
    assert _leaf(m["values"], "bfts.max_total_nodes") == 50
    assert any("env override rejected" in w for w in m["warnings"])
    assert m["source_stack"] == ["default"]  # zero applied env hits


def test_determinism_and_digest(pkg_root):
    kw = dict(
        profiles={"laptop": _LAPTOP}, profile="laptop",
        draft={"llm.model": "d"}, env={},
    )
    m1 = _resolve(pkg_root, **kw)
    m2 = _resolve(pkg_root, **kw)
    assert m1 == m2  # run_id/resolved_at are None in both — no clock
    assert m1["run_id"] is None and m1["resolved_at"] is None
    assert m1["digest"].startswith("sha256:")
    # a different effective value moves the digest
    m3 = _resolve(pkg_root, **{**kw, "draft": {"llm.model": "other"}})
    assert m3["digest"] != m1["digest"]


def test_manifest_shape_matches_existing_mode(pkg_root):
    m = _resolve(pkg_root, draft={"llm.model": "x"})
    assert set(m.keys()) == {
        "schema_version", "resolver_version", "run_id", "resolved_at",
        "digest", "source_stack", "values", "provenance",
        "secret_references", "warnings",
    }
    assert m["schema_version"] == 1
    assert m["resolver_version"] == "legacy-compatible-1"
    for entry in m["provenance"].values():
        assert set(entry.keys()) - {"rejected_override"} == {
            "source", "mutable", "confidence",
        }
        # pre-launch, every non-read_only leaf is still mutable
        assert entry["mutable"] is True


def test_resume_mode_unchanged_by_preview_code(tmp_path, monkeypatch):
    """The existing-checkpoint resolver (resume view) is byte-identical
    before/after new-run preview calls, and never grows preview layers
    (INDEX.md invariant: simple_bfts behaviour and existing checkpoint
    artifacts unchanged)."""
    ckpt = tmp_path / "20260723000003_resume"
    ckpt.mkdir()
    (ckpt / "workflow.yaml").write_text(
        yaml.safe_dump({"skills": [], "llm": {"model": "resume-model"}})
    )
    (ckpt / "rqgm_state.json").write_text(
        json.dumps({"mode": "ari_rqgm", "rqgm_enabled": True})
    )
    before = resolve_run_config(ckpt, env={})
    root = tmp_path / "pkgcfg2"
    (root / "profiles").mkdir(parents=True)
    monkeypatch.setattr(finder, "package_config_root", lambda: root)
    resolve_new_run_config(draft_values={"ari.mode": "ari_rqgm"}, env={})
    after = resolve_run_config(ckpt, env={})
    assert before == after
    assert after["source_stack"] == [
        "default", "workflow", "env", "checkpoint_state",
    ]
    assert not {"profile", "project", "template", "draft"} & {
        e["source"] for e in after["provenance"].values()
    }
    # the persisted (immutable) checkpoint mode still wins in resume view
    assert _leaf(after["values"], "ari.mode") == "ari_rqgm"


# ── POST /api/v1/run-drafts/{draft_id}/resolve-config + /validate ──────────


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """Tmp workspace via the canonical path policy (ARI_CHECKPOINT_DIR wins);
    all other documented env families cleared so the dev/CI shell cannot
    leak into the resolution."""
    for var in _ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    ckpt = tmp_path / "checkpoints" / "20260723000000_matrix"
    ckpt.mkdir(parents=True)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    return tmp_path


def _call(method: str, path: str, body: dict | None = None,
          if_match: int | None = None) -> dict:
    headers = {"If-Match": f'"{if_match}"'} if if_match is not None else None
    payload = json.dumps(body).encode() if body is not None else b"{}"
    return dispatch(method, path, body=payload, headers=headers)


def _make_draft(values: dict, template_id: str | None = None) -> str:
    body: dict = {"values": values}
    if template_id is not None:
        body["template_id"] = template_id
    r = _call("POST", "/api/v1/run-drafts", body)
    assert r.get("_status") == 201, r
    r.pop("_status")
    return r["draft_id"]


def _store_draft(values: dict, draft_id: str = "draft-000000000001") -> str:
    """Write a draft document straight to the store, bypassing the CRUD
    guards — the only way to build a document the API now refuses to create
    (e.g. an ADR-09 half-set intent pair) so the READ side can be tested."""
    from ari.viz.v1.store import KIND_RUN_DRAFT, GuiStore

    GuiStore.from_env().write(
        KIND_RUN_DRAFT,
        {"template_id": None, "values": values, "goal": None},
        doc_id=draft_id,
    )
    return draft_id


class TestResolveConfigEndpoint:
    def test_layering_project_template_draft(self, workspace):
        _call("PATCH", "/api/v1/projects/default/config",
              {"values": {"llm.model": "proj-model", "llm.backend": "openai"}},
              if_match=0)
        r = _call("POST", "/api/v1/run-templates", {
            "template_id": "t1", "name": "T1",
            "values": {"llm.model": "tmpl-model", "bfts.max_depth": 9},
        })
        assert r.get("_status") == 201
        draft_id = _make_draft({"llm.model": "draft-model"}, template_id="t1")
        m = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config")
        assert "_status" not in m
        assert m["run_id"] == draft_id
        assert m["schema_version"] == 1
        assert m["resolver_version"] == "legacy-compatible-1"
        assert _leaf(m["values"], "llm.model") == "draft-model"
        assert m["provenance"]["llm.model"]["source"] == "draft"
        assert _leaf(m["values"], "llm.backend") == "openai"
        assert m["provenance"]["llm.backend"]["source"] == "project"
        assert _leaf(m["values"], "bfts.max_depth") == 9
        assert m["provenance"]["bfts.max_depth"]["source"] == "template"
        # ARI_CHECKPOINT_DIR (set by the workspace fixture) is a documented
        # family -> the env layer is present and checkpoint.dir is env-sourced.
        for layer in ("default", "workflow", "project", "template", "draft",
                      "env"):
            assert layer in m["source_stack"]
        assert m["provenance"]["checkpoint.dir"]["source"] == "env"

    def test_real_bundled_profile_laptop_and_hpc(self, workspace):
        draft_id = _make_draft({})
        m = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config",
                  {"profile": "laptop"})
        assert _leaf(m["values"], "bfts.max_total_nodes") == 8
        assert _leaf(m["values"], "bfts.max_parallel_nodes") == 2
        assert m["provenance"]["bfts.max_total_nodes"]["source"] == "profile"
        # laptop merges every profile key -> no ignored-keys warning
        assert not any("ignored non-merged" in w for w in m["warnings"])
        m2 = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config",
                   {"profile": "hpc"})
        assert _leaf(m2["values"], "bfts.max_total_nodes") == 20
        res = _leaf(m2["values"], "resources")
        assert res["hpc_enabled"] is True and res["scheduler"] == "auto"
        # the real hpc profile carries non-merged keys -> warned, not applied
        hits = [w for w in m2["warnings"] if "ignored non-merged" in w]
        assert len(hits) == 1 and "hpc.partition" in hits[0]

    def test_resolved_at_mtime_stable_and_deterministic(self, workspace):
        draft_id = _make_draft({"llm.model": "x"})
        r1 = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config")
        r2 = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config")
        r1.pop("request_id"), r2.pop("request_id")
        assert r1 == r2  # mtime-derived resolved_at, no now()

    def test_error_paths(self, workspace):
        draft_id = _make_draft({})
        r = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config",
                  {"profile": "bogus"})
        assert r["_status"] == 400
        assert r["error"]["code"] == "invalid_request"
        r = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config",
                  {"nope": 1})
        assert r["_status"] == 400
        r = _call("POST",
                  "/api/v1/run-drafts/draft-000000000000/resolve-config")
        assert r["_status"] == 404
        r = _call("POST", "/api/v1/run-drafts/not-a-draft/resolve-config")
        assert r["_status"] == 404

    def test_deleted_template_layer_skipped_with_warning(self, workspace):
        r = _call("POST", "/api/v1/run-templates", {
            "template_id": "gone", "name": "Gone",
            "values": {"llm.model": "tmpl-model"},
        })
        assert r.get("_status") == 201
        draft_id = _make_draft({}, template_id="gone")
        _call("DELETE", "/api/v1/run-templates/gone", if_match=1)
        m = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config")
        assert "_status" not in m
        assert any("no longer exists" in w for w in m["warnings"])
        assert "template" not in m["source_stack"]


class TestValidateEndpoint:
    def test_valid_draft(self, workspace):
        draft_id = _make_draft(
            {"llm.model": "x", "ari.mode": "ari_rqgm", "rqgm.enabled": True}
        )
        v = _call("POST", f"/api/v1/run-drafts/{draft_id}/validate")
        assert "_status" not in v
        assert v["draft_id"] == draft_id
        assert v["valid"] is True
        assert v["errors"] == []

    def test_interlock_mismatch_is_an_error(self, workspace):
        # plan 05 §Interlocks: draft validation errors on the inconsistent
        # intent pair even though resolve-config only warns and falls back.
        # ADR-09 made the CRUD surface reject a half-set pair outright
        # (mode_interlock_mismatch), so the inconsistent draft is written
        # straight to the store — /validate must still explain such a
        # document (drafts predating ADR-09, or written out of band).
        draft_id = _store_draft({"ari.mode": "ari_rqgm"})
        v = _call("POST", f"/api/v1/run-drafts/{draft_id}/validate")
        assert v["valid"] is False
        assert [e["reason"] for e in v["errors"]] == ["interlock_mismatch"]
        assert v["errors"][0]["path"] == "ari.mode"
        # ... while the resolve preview is a warning + fallback, never an error
        m = _call("POST", f"/api/v1/run-drafts/{draft_id}/resolve-config")
        assert "_status" not in m
        assert _leaf(m["values"], "ari.mode") == "simple_bfts"

    def test_enabled_without_master_is_an_error(self, workspace):
        draft_id = _store_draft({"rqgm.enabled": True})
        v = _call("POST", f"/api/v1/run-drafts/{draft_id}/validate")
        assert v["valid"] is False
        assert [e["reason"] for e in v["errors"]] == ["interlock_mismatch"]

    def test_half_set_pair_is_rejected_at_create(self, workspace):
        # ADR-09 CRUD guard: the inconsistent intent never reaches the store.
        r = _call("POST", "/api/v1/run-drafts",
                  {"values": {"ari.mode": "ari_rqgm"}})
        assert r["_status"] == 400
        assert [e["reason"] for e in r["error"]["details"]["errors"]] == [
            "mode_interlock_mismatch"
        ]

    def test_unknown_draft_404(self, workspace):
        r = _call("POST", "/api/v1/run-drafts/draft-000000000000/validate")
        assert r["_status"] == 404
        assert r["error"]["code"] == "not_found"
