from __future__ import annotations
"""Tests for the weak-revision opt-in on GUI workflow endpoints.

gui_refresh task 07 Wave 4d (plan 07 §Workflow Studio — autosave must use a
revision instead of the 2s blind overwrite):

- ``GET /api/workflow`` gains an additive ``revision`` key: sha256[:12] of the
  served ``workflow.yaml`` bytes (legacy consumers unaffected).
- The four write endpoints (POST /api/workflow, /api/workflow/flow,
  /api/workflow/skills, /api/workflow/disabled-tools) accept an OPTIONAL
  ``base_revision``. When present and stale they refuse with the frozen
  409 payload WITHOUT writing (the CoW seed must not run either); when it
  matches, the write succeeds and returns the new revision. Callers that
  send no ``base_revision`` keep last-write-wins (additive opt-in).
- The Wave-2a no-checkpoint 400 guard still wins over the revision check.
"""

import hashlib
import json

import yaml

from ari.config.finder import package_config_root
from ari.viz import state as _st
from ari.viz.api_settings import _api_get_workflow, _api_save_workflow
from ari.viz.api_workflow import (
    _REVISION_MISMATCH_ERROR,
    _api_save_disabled_tools,
    _api_save_skill_phases,
    _api_save_workflow_flow,
    _workflow_revision_guard,
    workflow_revision,
    workflow_yaml_to_flow,
)

BUNDLED_WF = package_config_root() / "workflow.yaml"

# Frozen Wave-4d refusal payload — exact dict, no extra keys.
FROZEN_409 = {
    "ok": False,
    "error": (
        "workflow changed on disk since you loaded it (revision mismatch); "
        "reload before saving"
    ),
    "_status": 409,
}

CKPT_YAML = {
    "bfts_pipeline": [
        {"stage": "generate_idea", "skill": "idea-skill", "tool": "t",
         "description": "d", "depends_on": [], "enabled": True, "phase": "bfts"},
    ],
    "pipeline": [
        {"stage": "write_paper", "skill": "paper-skill", "tool": "t2",
         "description": "d2", "depends_on": [], "enabled": True, "phase": "paper"},
    ],
    "skills": [{"name": "idea-skill", "path": "/x/idea", "phase": "none"}],
}


def _make_checkpoint(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir(parents=True)
    (ckpt / "workflow.yaml").write_text(
        yaml.dump(CKPT_YAML, allow_unicode=True, sort_keys=False))
    return ckpt


def _current_rev(ckpt) -> str:
    return workflow_revision((ckpt / "workflow.yaml").read_bytes())


def _flow_body(enabled: bool = True, base_revision: str | None = None) -> bytes:
    flow = workflow_yaml_to_flow(CKPT_YAML)
    for n in flow["nodes"]:
        if n["id"] == "generate_idea":
            n["data"]["enabled"] = enabled
    payload: dict = {"flow": flow}
    if base_revision is not None:
        payload["base_revision"] = base_revision
    return json.dumps(payload).encode()


def _body(base: dict, base_revision: str | None) -> bytes:
    payload = dict(base)
    if base_revision is not None:
        payload["base_revision"] = base_revision
    return json.dumps(payload).encode()


# The four write handlers, each as (callable, legacy body builder).
WRITE_HANDLERS = [
    ("workflow", _api_save_workflow,
     lambda rev: _body({"pipeline": [{"stage": "rev_probe"}]}, rev)),
    ("flow", _api_save_workflow_flow,
     lambda rev: _flow_body(enabled=False, base_revision=rev)),
    ("skills", _api_save_skill_phases,
     lambda rev: _body({"skills": [{"name": "idea-skill", "phase": "bfts"}]}, rev)),
    ("disabled-tools", _api_save_disabled_tools,
     lambda rev: _body({"disabled_tools": ["rev_probe_tool"]}, rev)),
]


# ── revision primitive ───────────────────────────────────────────────────


def test_workflow_revision_is_sha256_prefix():
    data = b"pipeline: []\n"
    assert workflow_revision(data) == hashlib.sha256(data).hexdigest()[:12]
    assert len(workflow_revision(data)) == 12


def test_frozen_409_matches_module_constant():
    assert FROZEN_409["error"] == _REVISION_MISMATCH_ERROR


# ── GET /api/workflow serves the revision of the served bytes ────────────


def test_get_workflow_includes_checkpoint_revision(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    r = _api_get_workflow()
    assert r["ok"] is True
    assert r["path"] == str(ckpt / "workflow.yaml")
    assert r["revision"] == _current_rev(ckpt)


def test_get_workflow_bundled_fallback_revision(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    r = _api_get_workflow()
    assert r["ok"] is True
    assert r["revision"] == workflow_revision(BUNDLED_WF.read_bytes())


# ── stale base_revision: frozen 409, nothing written ─────────────────────


def test_all_writes_refuse_stale_revision_without_writing(monkeypatch, tmp_path):
    for name, handler, make_body in WRITE_HANDLERS:
        ckpt = _make_checkpoint(tmp_path / name)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        before = (ckpt / "workflow.yaml").read_bytes()
        r = handler(make_body("000000000000"))
        assert r == FROZEN_409, f"{name}: expected the frozen 409 payload"
        assert (ckpt / "workflow.yaml").read_bytes() == before, \
            f"{name}: stale-revision refusal must not write"


def test_stale_revision_refusal_skips_cow_seed(monkeypatch, tmp_path):
    # Checkpoint WITHOUT workflow.yaml: a stale base_revision (checked
    # against the bundled default that seeding would copy) must refuse
    # BEFORE the CoW seed runs — no checkpoint copy may appear.
    ckpt = tmp_path / "ckpt_empty"
    ckpt.mkdir()
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    r = _api_save_workflow_flow(_flow_body(base_revision="000000000000"))
    assert r == FROZEN_409
    assert not (ckpt / "workflow.yaml").exists(), \
        "409 refusal must not CoW-seed the checkpoint copy"


# ── matching base_revision: write succeeds, new revision returned ────────


def test_all_writes_succeed_with_matching_revision(monkeypatch, tmp_path):
    for name, handler, make_body in WRITE_HANDLERS:
        ckpt = _make_checkpoint(tmp_path / name)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        r = handler(make_body(_current_rev(ckpt)))
        assert r["ok"] is True, f"{name}: matching revision must save"
        # The response reports the revision of the just-written bytes, so a
        # revision-aware client can chain saves without a refetch race.
        assert r["revision"] == _current_rev(ckpt), \
            f"{name}: response revision != on-disk revision"


def test_matching_revision_write_lands(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    r = _api_save_workflow_flow(_flow_body(enabled=False,
                                           base_revision=_current_rev(ckpt)))
    assert r["ok"] is True
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    gi = next(s for s in saved["bfts_pipeline"] if s["stage"] == "generate_idea")
    assert gi["enabled"] is False
    # GET now serves exactly the revision the write reported.
    assert _api_get_workflow()["revision"] == r["revision"]


def test_matching_revision_on_cow_seed_uses_bundled_hash(monkeypatch, tmp_path):
    # Empty checkpoint: GET serves the bundled file, so its hash is the
    # correct base_revision and the seeded write must succeed.
    ckpt = tmp_path / "ckpt_empty"
    ckpt.mkdir()
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    bundled_rev = workflow_revision(BUNDLED_WF.read_bytes())
    body = _body({"disabled_tools": ["rev_probe_tool"]}, bundled_rev)
    r = _api_save_disabled_tools(body)
    assert r["ok"] is True
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    assert saved["disabled_tools"] == ["rev_probe_tool"]


# ── absent base_revision: legacy last-write-wins unchanged ───────────────


def test_all_writes_keep_last_write_wins_without_base_revision(monkeypatch, tmp_path):
    for name, handler, make_body in WRITE_HANDLERS:
        ckpt = _make_checkpoint(tmp_path / name)
        monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
        # File changes on disk after the client "loaded" it…
        wf = ckpt / "workflow.yaml"
        data = yaml.safe_load(wf.read_text())
        data["concurrent_marker"] = 1
        wf.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        # …but a legacy body (no base_revision) still wins.
        r = handler(make_body(None))
        assert r["ok"] is True, f"{name}: legacy caller must keep last-write-wins"


# ── guard precedence + helper semantics ──────────────────────────────────


def test_no_checkpoint_400_wins_over_stale_revision(monkeypatch):
    # Wave-2a guard runs first: no active checkpoint refuses with the frozen
    # 400 payload even when a (stale) base_revision is supplied.
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    r = _api_save_workflow_flow(_flow_body(base_revision="000000000000"))
    assert r["ok"] is False and r["_status"] == 400


def test_revision_guard_skips_when_absent(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    assert _workflow_revision_guard(None) is None
    assert _workflow_revision_guard("") is None
    assert _workflow_revision_guard(_current_rev(ckpt)) is None
    assert _workflow_revision_guard("000000000000") == FROZEN_409
