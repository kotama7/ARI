from __future__ import annotations
"""Tests for the shared no-checkpoint write guard on GUI workflow endpoints.

RR-P0-1 / ADR-10 (gui_refresh Wave 2a): without an active checkpoint the four
workflow-WRITE endpoints (POST /api/workflow, /api/workflow/flow,
/api/workflow/skills, /api/workflow/disabled-tools) must refuse with a frozen
400 payload instead of silently rewriting the bundled
``ari-core/config/workflow.yaml``. With an active checkpoint the write goes to
the per-checkpoint copy as before, leaving the bundled file untouched.

Wave 2b (ADR-10 residual, CoW seeding): when a checkpoint IS active but holds
no ``workflow.yaml`` yet, the ``api_workflow`` write handlers must seed the
per-checkpoint copy from the bundled file (copy-on-write) and apply the edit
to that copy — the bundled file stays byte-identical and the copy is created
with the edit landed (``_checkpoint_workflow_path``).
"""

import json

import yaml

from ari.config.finder import package_config_root
from ari.viz import state as _st
from ari.viz.api_settings import _api_save_workflow
from ari.viz.api_workflow import (
    _NO_ACTIVE_CHECKPOINT_ERROR,
    _api_save_disabled_tools,
    _api_save_skill_phases,
    _api_save_workflow_flow,
    _workflow_write_guard,
    workflow_yaml_to_flow,
)

BUNDLED_WF = package_config_root() / "workflow.yaml"

# Frozen ADR-10 refusal payload — exact dict, no extra keys.
FROZEN_REFUSAL = {
    "ok": False,
    "error": (
        "No active project. Select a checkpoint before editing the workflow "
        "(the bundled default workflow.yaml is read-only from the GUI)."
    ),
    "_status": 400,
}

# Minimal per-checkpoint workflow.yaml exercised by all four write handlers.
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


def _bundled_snapshot() -> tuple[int, bytes]:
    return BUNDLED_WF.stat().st_mtime_ns, BUNDLED_WF.read_bytes()


def _assert_bundled_untouched(before: tuple[int, bytes]) -> None:
    mtime_ns, content = before
    assert BUNDLED_WF.stat().st_mtime_ns == mtime_ns, \
        "bundled config/workflow.yaml mtime changed"
    assert BUNDLED_WF.read_bytes() == content, \
        "bundled config/workflow.yaml content changed"


def _make_checkpoint(tmp_path):
    """Create a tmp checkpoint dir holding a per-checkpoint workflow.yaml."""
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "workflow.yaml").write_text(
        yaml.dump(CKPT_YAML, allow_unicode=True, sort_keys=False))
    return ckpt


def _flow_body(enabled: bool = True) -> bytes:
    flow = workflow_yaml_to_flow(CKPT_YAML)
    for n in flow["nodes"]:
        if n["id"] == "generate_idea":
            n["data"]["enabled"] = enabled
    return json.dumps({"flow": flow}).encode()


# ── (a) No active checkpoint: frozen 400 refusal, bundled file untouched ──


def test_save_workflow_refuses_without_checkpoint(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    before = _bundled_snapshot()
    body = json.dumps({"pipeline": [{"stage": "guard_probe"}]}).encode()
    assert _api_save_workflow(body) == FROZEN_REFUSAL
    _assert_bundled_untouched(before)


def test_save_workflow_flow_refuses_without_checkpoint(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    before = _bundled_snapshot()
    assert _api_save_workflow_flow(_flow_body()) == FROZEN_REFUSAL
    _assert_bundled_untouched(before)


def test_save_skill_phases_refuses_without_checkpoint(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    before = _bundled_snapshot()
    body = json.dumps({"skills": [{"name": "idea-skill", "phase": "bfts"}]}).encode()
    assert _api_save_skill_phases(body) == FROZEN_REFUSAL
    _assert_bundled_untouched(before)


def test_save_disabled_tools_refuses_without_checkpoint(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    before = _bundled_snapshot()
    body = json.dumps({"disabled_tools": ["guard_probe_tool"]}).encode()
    assert _api_save_disabled_tools(body) == FROZEN_REFUSAL
    _assert_bundled_untouched(before)


# ── (b) Active checkpoint: write lands in {ckpt}/workflow.yaml only ──────
# Success payloads are pinned as {ok, revision}: Wave 4d (plan 07 §Workflow
# Studio) added the additive weak ``revision`` of the written bytes so
# revision-aware clients can chain saves; correctness of the value is
# covered by test_gui_workflow_revision.py.


def test_save_workflow_writes_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    body = json.dumps({"pipeline": [{"stage": "guard_probe"}]}).encode()
    r = _api_save_workflow(body)
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    assert saved["pipeline"] == [{"stage": "guard_probe"}]
    _assert_bundled_untouched(before)


def test_save_workflow_flow_writes_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    r = _api_save_workflow_flow(_flow_body(enabled=False))
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    gi = next(s for s in saved["bfts_pipeline"] if s["stage"] == "generate_idea")
    assert gi["enabled"] is False
    _assert_bundled_untouched(before)


def test_save_skill_phases_writes_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    body = json.dumps({"skills": [{"name": "idea-skill", "phase": "bfts"}]}).encode()
    r = _api_save_skill_phases(body)
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    assert saved["skills"][0]["phase"] == "bfts"
    _assert_bundled_untouched(before)


def test_save_disabled_tools_writes_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    body = json.dumps({"disabled_tools": ["guard_probe_tool"]}).encode()
    r = _api_save_disabled_tools(body)
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    saved = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    assert saved["disabled_tools"] == ["guard_probe_tool"]
    _assert_bundled_untouched(before)


# ── (c) Wave 2b CoW seeding: active checkpoint WITHOUT workflow.yaml ─────
# ADR-10 residual: the copy is seeded from the bundled default first, then
# edited — bundled file byte-identical, copy created + edited.


def _make_empty_checkpoint(tmp_path):
    """Checkpoint dir with NO workflow.yaml (forces the CoW seed path)."""
    ckpt = tmp_path / "ckpt_empty"
    ckpt.mkdir()
    return ckpt


def test_checkpoint_workflow_path_seeds_once_and_reuses(monkeypatch, tmp_path):
    from ari.viz.api_workflow import _checkpoint_workflow_path

    ckpt = _make_empty_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    wf = _checkpoint_workflow_path()
    assert wf == ckpt / "workflow.yaml" and wf.exists()
    assert wf.read_bytes() == BUNDLED_WF.read_bytes()  # seeded byte-for-byte
    # Second call reuses the existing copy — no reseed/overwrite.
    wf.write_text("marker: 1\n")
    assert _checkpoint_workflow_path() == wf
    assert wf.read_text() == "marker: 1\n"
    _assert_bundled_untouched(before)


def test_save_workflow_flow_seeds_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_empty_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    r = _api_save_workflow_flow(_flow_body(enabled=False))
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    copy = ckpt / "workflow.yaml"
    assert copy.exists(), "CoW seed did not create the checkpoint copy"
    saved = yaml.safe_load(copy.read_text())
    gi = next(s for s in saved["bfts_pipeline"] if s["stage"] == "generate_idea")
    assert gi["enabled"] is False  # the edit landed on the seeded copy
    _assert_bundled_untouched(before)


def test_save_skill_phases_seeds_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_empty_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    body = json.dumps({"skills": [{"name": "plot-skill", "phase": "bfts"}]}).encode()
    r = _api_save_skill_phases(body)
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    copy = ckpt / "workflow.yaml"
    assert copy.exists(), "CoW seed did not create the checkpoint copy"
    saved = yaml.safe_load(copy.read_text())
    plot = next(s for s in saved["skills"] if s["name"] == "plot-skill")
    assert plot["phase"] == "bfts"
    # Seed really came from the bundled default: full skill roster intact.
    bundled = yaml.safe_load(BUNDLED_WF.read_text())
    assert {s["name"] for s in saved["skills"]} == \
        {s["name"] for s in bundled["skills"]}
    _assert_bundled_untouched(before)


def test_save_disabled_tools_seeds_checkpoint_copy(monkeypatch, tmp_path):
    ckpt = _make_empty_checkpoint(tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)
    before = _bundled_snapshot()
    body = json.dumps({"disabled_tools": ["guard_probe_tool"]}).encode()
    r = _api_save_disabled_tools(body)
    assert r["ok"] is True and set(r) == {"ok", "revision"}
    copy = ckpt / "workflow.yaml"
    assert copy.exists(), "CoW seed did not create the checkpoint copy"
    saved = yaml.safe_load(copy.read_text())
    assert saved["disabled_tools"] == ["guard_probe_tool"]
    # Seeded copy carries the bundled pipelines through the edit.
    bundled = yaml.safe_load(BUNDLED_WF.read_text())
    assert saved["bfts_pipeline"] == bundled["bfts_pipeline"]
    _assert_bundled_untouched(before)


# ── Guard helper semantics ───────────────────────────────────────────────


def test_guard_refuses_when_checkpoint_is_none(monkeypatch):
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    assert _workflow_write_guard() == FROZEN_REFUSAL


def test_guard_refuses_when_checkpoint_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path / "gone")
    assert _workflow_write_guard() == FROZEN_REFUSAL


def test_guard_passes_with_existing_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(_st, "_checkpoint_dir", tmp_path)
    assert _workflow_write_guard() is None


def test_frozen_payload_matches_module_constant():
    assert FROZEN_REFUSAL["error"] == _NO_ACTIVE_CHECKPOINT_ERROR
