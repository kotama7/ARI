"""ADR-09 mode selection for a NEW run — ``POST /api/v1/runs`` + the config
CRUD guards (handlers ``ari/viz/v1/launch.py`` / ``ari/viz/v1/config_api.py``).

ADR-09 (accepted 2026-07-27) supersedes the "no GUI toggle" statement in
``docs/guides/execution_modes.md`` for exactly TWO orthogonal intents, each a
mode leaf plus its interlock twin:

    execution mode   ari.mode: ari_rqgm     + rqgm.enabled: true
    paper mode       paper.mode: rqgm_archive + rqgm.paper.enabled: true

Everything else stays as it was.  Covered here (``subprocess.Popen`` is
ALWAYS mocked — no test starts a real run):

- **default path byte-identical**: a draft that selects nothing and a draft
  that explicitly restates ``simple_bfts``/``linear`` both launch a run whose
  checkpoint is indistinguishable from the pre-ADR-09 baseline — the
  ``workflow.yaml`` copy is byte-equal to the bundled seed (no ``ari:`` /
  ``rqgm:`` / ``paper:`` block), NONE of the four ``ARI_*`` mode vars is
  exported, the artifact set is unchanged and the resolved values/digest are
  identical;
- **selection is materialized twice**: a non-default intent writes the
  minimal blocks into the per-checkpoint ``workflow.yaml`` (never the bundled
  file) AND exports the documented env vars, with ``resolved_config.json``
  carrying ``draft``/``template`` provenance for the mode leaves;
- **the two axes are orthogonal** (all four 2x2 combinations);
- **the pair is one intent**: a half-set / disagreeing pair is a typed 400
  ``mode_interlock_mismatch`` at create, at PATCH and at launch — with ZERO
  filesystem mutation on the launch path;
- **nothing else opened**: a non-mode ``rqgm.*`` path is still 400
  ``mode_locked``, and a mode path in the PROJECT config is still 400
  ``not_project_scope``;
- **resume is untouched**: ``reconcile_resume_mode`` still lets the persisted
  ``{ckpt}/rqgm_state.json`` win (downgrade-only), and no GUI launch path
  writes that file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.config.finder import package_config_root
from ari.viz.v1 import events, launch
from ari.viz.v1.router import dispatch
from ari.viz.v1.store import KIND_RUN_DRAFT, GuiStore

GOAL = "# Goal\nSelect the execution mode from the GUI.\n"

MODE_ENV_VARS = (
    "ARI_MODE", "ARI_RQGM_ENABLED", "ARI_PAPER_MODE", "ARI_RQGM_PAPER_ENABLED",
)

# The four mode leaves as one GUI control writes them (both keys, always).
DEFAULT_PAIRS = {
    "ari.mode": "simple_bfts", "rqgm.enabled": False,
    "paper.mode": "linear", "rqgm.paper.enabled": False,
}
RQGM_PAIR = {"ari.mode": "ari_rqgm", "rqgm.enabled": True}
ARCHIVE_PAIR = {"paper.mode": "rqgm_archive", "rqgm.paper.enabled": True}


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """Tmp workspace via the canonical path policy (ARI_CHECKPOINT_DIR wins),
    with every documented ``ARI_*`` family cleared so a dev/CI shell cannot
    leak a mode into the resolution (the same isolation the launch suite
    uses)."""
    ckpt = tmp_path / "checkpoints" / "20260727000000_seed"
    ckpt.mkdir(parents=True)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    from ari.config.field_registry import ENV_OVERRIDES

    for var in sorted(set(ENV_OVERRIDES.values()) | {"ARI_LLM_MODEL"}):
        if var != "ARI_CHECKPOINT_DIR":
            monkeypatch.delenv(var, raising=False)
    events._reset_for_tests()
    launch._reset_for_tests()
    yield tmp_path
    events._reset_for_tests()
    launch._reset_for_tests()


class FakeProc:
    def __init__(self, pid: int = 5150) -> None:
        self.pid = pid

    def poll(self):  # pragma: no cover - parity with Popen
        return None


@pytest.fixture
def fake_popen(monkeypatch):
    """Record every would-be spawn; never start a process."""
    calls: list[dict] = []

    def _fake(cmd, **kwargs):
        calls.append({"cmd": list(cmd), **kwargs})
        return FakeProc(pid=5150 + len(calls))

    monkeypatch.setattr(launch.subprocess, "Popen", _fake)
    return calls


def _call(method: str, path: str, body: dict | None = None,
          if_match: int | None = None) -> dict:
    headers = {"If-Match": f'"{if_match}"'} if if_match is not None else None
    payload = None if body is None else json.dumps(body).encode("utf-8")
    return dispatch(method, path, body=payload, headers=headers)


def _make_draft(values: dict | None = None, template_id: str | None = None,
                goal: str | None = GOAL) -> str:
    body: dict = {"values": values or {}}
    if template_id is not None:
        body["template_id"] = template_id
    if goal is not None:
        body["goal"] = goal
    r = _call("POST", "/api/v1/run-drafts", body)
    assert r.get("_status") == 201, r
    return r["draft_id"]


def _store_draft(values: dict, draft_id: str) -> str:
    """Write a draft straight to the store, bypassing the CRUD guards — the
    only way to obtain a document the API refuses to create (an inconsistent
    intent pair, e.g. a draft written before ADR-09)."""
    GuiStore.from_env().write(
        KIND_RUN_DRAFT,
        {"template_id": None, "values": values, "goal": GOAL},
        doc_id=draft_id,
    )
    return draft_id


def _launch(draft_id: str, **body) -> dict:
    r = _call("POST", "/api/v1/runs", {"draft_id": draft_id, **body})
    assert "_status" not in r, r
    return r


def _run_dirs(workspace: Path) -> set[str]:
    return {d.name for d in (workspace / "checkpoints").iterdir() if d.is_dir()}


def _wf_text(ckpt: Path) -> str:
    return (ckpt / "workflow.yaml").read_text(encoding="utf-8")


def _bundled_wf_bytes() -> bytes:
    return (package_config_root() / "workflow.yaml").read_bytes()


def _mode_env(call: dict) -> dict[str, str]:
    return {v: call["env"][v] for v in MODE_ENV_VARS if v in call["env"]}


def _manifest(ckpt: Path) -> dict:
    return json.loads((ckpt / "resolved_config.json").read_text("utf-8"))


def _leaf(values: dict, path: str):
    node = values
    for part in path.split("."):
        node = node[part]
    return node


# ── the default path stays byte-identical ──────────────────────────────────


class TestDefaultPathUnchanged:
    def test_baseline_and_explicit_defaults_are_indistinguishable(
        self, workspace, fake_popen
    ):
        # "baseline" = a pre-ADR-09 draft: it CANNOT carry a mode leaf (they
        # were mode_locked), so it carries none.  "explicit" = an ADR-09 GUI
        # leaving both controls at their defaults, writing all four keys.
        baseline = _launch(_make_draft({"bfts.max_total_nodes": 5}))
        explicit = _launch(
            _make_draft({"bfts.max_total_nodes": 5, **DEFAULT_PAIRS})
        )
        b_ckpt, e_ckpt = Path(baseline["checkpoint_path"]), Path(
            explicit["checkpoint_path"]
        )
        # 1. the checkpoint workflow.yaml is the untouched CoW seed
        for ckpt in (b_ckpt, e_ckpt):
            assert (ckpt / "workflow.yaml").read_bytes() == _bundled_wf_bytes()
            text = _wf_text(ckpt)
            for key in ("\nari:", "\nrqgm:", "\npaper:"):
                assert key not in "\n" + text, key
        # 2. NO mode env var is exported for either run
        assert _mode_env(fake_popen[0]) == {}
        assert _mode_env(fake_popen[1]) == {}
        # 3. identical artifact set (nothing new appears on the default path)
        assert {p.name for p in b_ckpt.iterdir() if p.suffix != ".log"} == {
            p.name for p in e_ckpt.iterdir() if p.suffix != ".log"
        } == {
            "experiment.md", "workflow.yaml", "launch_config.json",
            "resolved_config.json", "launch_events.jsonl",
        }
        # 4. identical effective values and digest
        b_m, e_m = _manifest(b_ckpt), _manifest(e_ckpt)
        assert b_m["values"] == e_m["values"]
        assert b_m["digest"] == e_m["digest"]
        assert b_m["warnings"] == e_m["warnings"]
        # 5. the ONLY difference in the manifest is the provenance layer of
        #    the four mode leaves (draft vs default) — nothing else moved.
        differing = {
            p for p in b_m["provenance"]
            if b_m["provenance"][p] != e_m["provenance"][p]
        }
        assert differing == set(DEFAULT_PAIRS)
        for path in DEFAULT_PAIRS:
            assert b_m["provenance"][path]["source"] == "default"
            assert e_m["provenance"][path]["source"] == "draft"
        # 6. legacy launch_config.json identical modulo the draft identity
        b_lc = json.loads((b_ckpt / "launch_config.json").read_text("utf-8"))
        e_lc = json.loads((e_ckpt / "launch_config.json").read_text("utf-8"))
        b_lc.pop("draft_id")
        e_lc.pop("draft_id")
        assert b_lc == e_lc

    def test_default_path_writes_no_rqgm_state(self, workspace, fake_popen):
        r = _launch(_make_draft(dict(DEFAULT_PAIRS)))
        ckpt = Path(r["checkpoint_path"])
        # P5 absence-is-default: rqgm_state.json is written by the CLI at run
        # start for an ari_rqgm run only, and never by the GUI launch.
        assert not (ckpt / "rqgm_state.json").exists()


# ── a non-default intent is materialized BOTH ways ─────────────────────────


class TestExecutionModeSelection:
    def test_blocks_env_and_provenance(self, workspace, fake_popen):
        draft_id = _make_draft({**DEFAULT_PAIRS, **RQGM_PAIR})
        r = _launch(draft_id)
        ckpt = Path(r["checkpoint_path"])
        # (a) the per-checkpoint workflow.yaml copy carries the intent ...
        import yaml

        raw = yaml.safe_load(_wf_text(ckpt))
        assert raw["ari"] == {"mode": "ari_rqgm"}
        assert raw["rqgm"] == {"enabled": True}
        assert "paper" not in raw  # the paper axis was left at its default
        # ... merged into the seed, which keeps every unknown key it had
        seed = yaml.safe_load(_bundled_wf_bytes().decode("utf-8"))
        for key, value in seed.items():
            assert raw[key] == value, key
        # (b) ... and the documented env vars are exported for the spawn
        assert _mode_env(fake_popen[0]) == {
            "ARI_MODE": "ari_rqgm", "ARI_RQGM_ENABLED": "1",
        }
        # (c) resolved_config.json shows the mode leaves with draft provenance
        m = _manifest(ckpt)
        assert _leaf(m["values"], "ari.mode") == "ari_rqgm"
        assert _leaf(m["values"], "rqgm.enabled") is True
        assert m["provenance"]["ari.mode"]["source"] == "draft"
        assert m["provenance"]["rqgm.enabled"]["source"] == "draft"
        assert not any("falling back" in w for w in m["warnings"])

    def test_both_materializations_resolve_through_the_real_authorities(
        self, workspace, fake_popen, monkeypatch
    ):
        # End-to-end semantics: whichever channel a later phase reads — the
        # per-checkpoint workflow.yaml or the exported env — must land on the
        # SAME effective modes, per resolve_effective_mode/resolve_paper_mode.
        from ari.config import (ARIConfig, apply_paper_env_overrides,
                                apply_rqgm_env_overrides, load_config)
        from ari.rqgm.mode import EffectiveMode, resolve_effective_mode
        from ari.rqgm.paper_mode import PaperMode, resolve_paper_mode

        r = _launch(_make_draft({**DEFAULT_PAIRS, **RQGM_PAIR,
                                 **ARCHIVE_PAIR}))
        ckpt = Path(r["checkpoint_path"])
        cfg = load_config(str(ckpt / "workflow.yaml"))
        assert resolve_effective_mode(cfg) is EffectiveMode.ARI_RQGM
        assert resolve_paper_mode(cfg) is PaperMode.RQGM_ARCHIVE
        # the env channel the spawned CLI actually reads
        for var, value in _mode_env(fake_popen[0]).items():
            monkeypatch.setenv(var, value)
        env_cfg = ARIConfig()
        apply_rqgm_env_overrides(env_cfg)
        apply_paper_env_overrides(env_cfg)
        assert resolve_effective_mode(env_cfg) is EffectiveMode.ARI_RQGM
        assert resolve_paper_mode(env_cfg) is PaperMode.RQGM_ARCHIVE

    def test_bundled_workflow_is_never_written(self, workspace, fake_popen):
        before = _bundled_wf_bytes()
        _launch(_make_draft({**DEFAULT_PAIRS, **RQGM_PAIR}))
        assert _bundled_wf_bytes() == before

    def test_merge_keeps_unknown_keys_when_a_block_exists(self, tmp_path):
        # Direct unit test of the merge helper's round-trip branch: a copy
        # that ALREADY has an ari: block keeps its unknown neighbours.
        wf = tmp_path / "workflow.yaml"
        wf.write_text(
            "ari:\n  other: keep-me\nllm:\n  model: m\ndisabled_tools: []\n",
            encoding="utf-8",
        )
        launch._merge_mode_blocks(wf, {"ari.mode": "ari_rqgm",
                                       "rqgm.enabled": True})
        import yaml

        raw = yaml.safe_load(wf.read_text(encoding="utf-8"))
        assert raw["ari"] == {"other": "keep-me", "mode": "ari_rqgm"}
        assert raw["rqgm"] == {"enabled": True}
        assert raw["llm"] == {"model": "m"}
        assert raw["disabled_tools"] == []

    def test_empty_selection_never_touches_the_file(self, tmp_path):
        wf = tmp_path / "workflow.yaml"
        wf.write_text("llm:\n  model: m  # comment kept\n", encoding="utf-8")
        before = wf.read_bytes()
        launch._merge_mode_blocks(wf, {})
        assert wf.read_bytes() == before


class TestPaperModeIsOrthogonal:
    @pytest.mark.parametrize(
        "exec_rqgm,paper_archive",
        [(False, False), (True, False), (False, True), (True, True)],
    )
    def test_2x2_matrix(self, workspace, fake_popen, exec_rqgm, paper_archive):
        values = dict(DEFAULT_PAIRS)
        if exec_rqgm:
            values.update(RQGM_PAIR)
        if paper_archive:
            values.update(ARCHIVE_PAIR)
        r = _launch(_make_draft(values))
        ckpt = Path(r["checkpoint_path"])
        import yaml

        raw = yaml.safe_load(_wf_text(ckpt))
        expected_env: dict[str, str] = {}
        if exec_rqgm:
            assert raw["ari"] == {"mode": "ari_rqgm"}
            expected_env |= {"ARI_MODE": "ari_rqgm", "ARI_RQGM_ENABLED": "1"}
        else:
            assert "ari" not in raw
        if paper_archive:
            assert raw["paper"] == {"mode": "rqgm_archive"}
            expected_env |= {"ARI_PAPER_MODE": "rqgm_archive",
                             "ARI_RQGM_PAPER_ENABLED": "1"}
        else:
            assert "paper" not in raw
        rqgm_block = raw.get("rqgm")
        if exec_rqgm and paper_archive:
            assert rqgm_block == {"enabled": True, "paper": {"enabled": True}}
        elif exec_rqgm:
            assert rqgm_block == {"enabled": True}
        elif paper_archive:
            assert rqgm_block == {"paper": {"enabled": True}}
        else:
            assert rqgm_block is None
            assert (ckpt / "workflow.yaml").read_bytes() == _bundled_wf_bytes()
        assert _mode_env(fake_popen[0]) == expected_env


# ── the pair is ONE intent ─────────────────────────────────────────────────


class TestInterlockMismatch:
    @pytest.mark.parametrize(
        "values,offender",
        [
            ({"ari.mode": "ari_rqgm"}, "ari.mode"),
            ({"rqgm.enabled": True}, "ari.mode"),
            ({"ari.mode": "ari_rqgm", "rqgm.enabled": False}, "ari.mode"),
            ({"paper.mode": "rqgm_archive"}, "paper.mode"),
            ({"rqgm.paper.enabled": True}, "paper.mode"),
            ({"paper.mode": "linear", "rqgm.paper.enabled": True},
             "paper.mode"),
        ],
    )
    def test_create_rejects_an_inconsistent_pair(
        self, workspace, values, offender
    ):
        r = _call("POST", "/api/v1/run-drafts", {"values": values})
        assert r["_status"] == 400
        errors = r["error"]["details"]["errors"]
        assert [(e["path"], e["reason"]) for e in errors] == [
            (offender, "mode_interlock_mismatch")
        ]
        # the details name the two consistent alternatives verbatim
        assert len(errors[0]["expected"]) == 2
        assert all(len(alt) == 2 for alt in errors[0]["expected"])

    def test_reason_vocabulary_stays_closed(self):
        from ari.config.field_registry import PATCH_REASONS

        assert PATCH_REASONS == (
            "unknown_path", "secret_reference", "read_only",
            "not_project_scope", "invalid_enum", "invalid_type",
            "mode_interlock_mismatch",
        )

    def test_patch_rejects_a_merge_that_breaks_the_pair(self, workspace):
        draft_id = _make_draft({**DEFAULT_PAIRS, **RQGM_PAIR})
        r = _call("PATCH", f"/api/v1/run-drafts/{draft_id}",
                  {"values": {"rqgm.enabled": False}}, if_match=1)
        assert r["_status"] == 400
        assert r["error"]["details"]["errors"][0]["reason"] == (
            "mode_interlock_mismatch"
        )
        # the stored document is untouched (the write never ran)
        doc = _call("GET", f"/api/v1/run-drafts/{draft_id}")
        assert doc["values"]["rqgm.enabled"] is True

    def test_patch_accepts_a_merge_that_keeps_the_pair(self, workspace):
        draft_id = _make_draft({**DEFAULT_PAIRS, **RQGM_PAIR})
        r = _call("PATCH", f"/api/v1/run-drafts/{draft_id}",
                  {"values": {"ari.mode": "simple_bfts",
                              "rqgm.enabled": False}}, if_match=1)
        assert "_status" not in r
        assert r["values"]["ari.mode"] == "simple_bfts"

    def test_launch_rejects_an_inconsistent_pair_with_zero_mutation(
        self, workspace, fake_popen
    ):
        # Only reachable for a document written out of band (pre-ADR-09 or
        # store-direct) — the launch re-validates rather than trusting it.
        draft_id = _store_draft({"ari.mode": "ari_rqgm"},
                                "draft-00000000ad09")
        before = _run_dirs(workspace)
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert r["_status"] == 400
        assert r["error"]["code"] == "invalid_request"
        reasons = [
            e["reason"] for e in r["error"]["details"]["errors"]
            if e["path"] == "ari.mode"
        ]
        assert reasons == ["mode_interlock_mismatch"]  # reported ONCE
        assert _run_dirs(workspace) == before  # NO dir created
        assert not fake_popen  # NO spawn
        assert not (workspace / "gui_store" / "launches").exists()


# ── nothing else opened ────────────────────────────────────────────────────


class TestScopeIsExactlyFourLeaves:
    def test_non_mode_rqgm_path_is_still_mode_locked(
        self, workspace, fake_popen
    ):
        draft_id = _make_draft({"rqgm.epoch.nodes_per_epoch": 4})
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert r["_status"] == 400
        assert any(
            e["path"] == "rqgm.epoch.nodes_per_epoch"
            and e["reason"] == "mode_locked"
            for e in r["error"]["details"]["errors"]
        )
        assert not fake_popen

    def test_locked_set_is_the_registry_minus_the_four(self, workspace):
        from ari.config.field_registry import (MODE_SELECTION_PATHS,
                                               build_field_registry)

        locked = launch.locked_launch_paths()
        governance = {
            e["path"] for e in build_field_registry()
            if e["category"] == "Execution mode"
            or e["path"].startswith("rqgm.")
        }
        assert locked == governance - MODE_SELECTION_PATHS
        assert len(MODE_SELECTION_PATHS) == 4
        assert locked  # the other ~96 leaves are still locked

    @pytest.mark.parametrize("path,value", sorted(DEFAULT_PAIRS.items()))
    def test_project_config_still_rejects_mode_paths(
        self, workspace, path, value
    ):
        r = _call("PATCH", "/api/v1/projects/default/config",
                  {"values": {path: value}}, if_match=0)
        assert r["_status"] == 400
        assert [(e["path"], e["reason"])
                for e in r["error"]["details"]["errors"]] == [
            (path, "not_project_scope")
        ]


class TestTemplateCarriesTheIntent:
    def test_template_pair_is_accepted_and_honored_at_launch(
        self, workspace, fake_popen
    ):
        r = _call("POST", "/api/v1/run-templates", {
            "template_id": "rqgm-run", "name": "RQGM run",
            "values": {**RQGM_PAIR, "bfts.max_total_nodes": 6},
        })
        assert r.get("_status") == 201, r
        draft_id = _make_draft({}, template_id="rqgm-run")
        launched = _launch(draft_id)
        ckpt = Path(launched["checkpoint_path"])
        import yaml

        raw = yaml.safe_load(_wf_text(ckpt))
        assert raw["ari"] == {"mode": "ari_rqgm"}
        assert raw["rqgm"] == {"enabled": True}
        assert _mode_env(fake_popen[0]) == {
            "ARI_MODE": "ari_rqgm", "ARI_RQGM_ENABLED": "1",
        }
        m = _manifest(ckpt)
        assert m["provenance"]["ari.mode"]["source"] == "template"
        assert m["provenance"]["rqgm.enabled"]["source"] == "template"

    def test_template_patch_accepts_the_pair(self, workspace):
        r = _call("POST", "/api/v1/run-templates", {
            "template_id": "t1", "name": "T1",
            "values": {"bfts.max_total_nodes": 6},
        })
        assert r.get("_status") == 201, r
        patched = _call("PATCH", "/api/v1/run-templates/t1",
                        {"values": dict(RQGM_PAIR)}, if_match=1)
        assert "_status" not in patched, patched
        assert patched["values"]["ari.mode"] == "ari_rqgm"
        assert patched["values"]["rqgm.enabled"] is True
        # ... and a template PATCH that would break the pair is rejected
        broken = _call("PATCH", "/api/v1/run-templates/t1",
                       {"values": {"ari.mode": "simple_bfts"}}, if_match=2)
        assert broken["_status"] == 400
        assert broken["error"]["details"]["errors"][0]["reason"] == (
            "mode_interlock_mismatch"
        )

    def test_draft_can_override_the_template_intent_as_one_pair(
        self, workspace, fake_popen
    ):
        r = _call("POST", "/api/v1/run-templates", {
            "template_id": "rqgm-run", "name": "RQGM run",
            "values": dict(RQGM_PAIR),
        })
        assert r.get("_status") == 201, r
        draft_id = _make_draft(
            {"ari.mode": "simple_bfts", "rqgm.enabled": False},
            template_id="rqgm-run",
        )
        launched = _launch(draft_id)
        ckpt = Path(launched["checkpoint_path"])
        assert (ckpt / "workflow.yaml").read_bytes() == _bundled_wf_bytes()
        assert _mode_env(fake_popen[0]) == {}


# ── the resolver's warn+fallback is surfaced, not re-derived ───────────────


class TestResolverWarningIsSurfaced:
    def test_env_broken_interlock_shows_the_resolved_value(
        self, workspace, fake_popen, monkeypatch
    ):
        # The env layer wins over the draft in the resolver; with the twin
        # forced off the runtime falls back, and the manifest must SHOW the
        # resolved value plus the resolver's own warning.
        monkeypatch.setenv("ARI_RQGM_ENABLED", "0")
        draft_id = _make_draft({**DEFAULT_PAIRS, **RQGM_PAIR})
        preview = _call(
            "POST", f"/api/v1/run-drafts/{draft_id}/resolve-config", {}
        )
        assert _leaf(preview["values"], "ari.mode") == "simple_bfts"
        assert preview["provenance"]["ari.mode"]["rejected_override"] == {
            "source": "draft", "value": "ari_rqgm",
            "reason": "interlock_mismatch", "expected": None,
        }
        assert any(
            "falling back to simple_bfts" in w for w in preview["warnings"]
        )
        # /validate turns that residual resolver warning into a review-time
        # error (the document pair is consistent — the ENV broke it), so ...
        v = _call("POST", f"/api/v1/run-drafts/{draft_id}/validate", {})
        assert v["valid"] is False
        assert [(e["path"], e["reason"]) for e in v["errors"]] == [
            ("ari.mode", "interlock_mismatch")
        ]
        # ... the launch refuses rather than silently running the fallback.
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert r["_status"] == 400
        assert [(e["path"], e["reason"])
                for e in r["error"]["details"]["errors"]] == [
            ("ari.mode", "interlock_mismatch")
        ]
        assert not fake_popen


# ── resume is untouched ────────────────────────────────────────────────────


class TestResumeUnaffected:
    def test_persisted_state_wins_over_a_gui_selected_mode(self, tmp_path):
        from ari.config import ARIConfig
        from ari.rqgm.state import reconcile_resume_mode

        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        (ckpt / "rqgm_state.json").write_text(
            json.dumps({"mode": "simple_bfts", "rqgm_enabled": False}),
            encoding="utf-8",
        )
        cfg = ARIConfig()
        cfg.ari.mode = "ari_rqgm"  # what a GUI selection would have set
        cfg.rqgm.enabled = True
        reconcile_resume_mode(cfg, ckpt)
        assert cfg.ari.mode == "simple_bfts"  # downgrade-only, persisted wins
        assert cfg.rqgm.enabled is False

    def test_no_state_file_never_upgrades(self, tmp_path):
        from ari.config import ARIConfig
        from ari.rqgm.state import reconcile_resume_mode

        ckpt = tmp_path / "ckpt"
        ckpt.mkdir()
        cfg = ARIConfig()
        cfg.ari.mode = "ari_rqgm"
        cfg.rqgm.enabled = True
        reconcile_resume_mode(cfg, ckpt)
        assert cfg.ari.mode == "simple_bfts"
        assert cfg.rqgm.enabled is False

    def test_launch_never_writes_an_existing_runs_state(
        self, workspace, fake_popen
    ):
        existing = workspace / "checkpoints" / "20260727000000_seed"
        (existing / "rqgm_state.json").write_text(
            json.dumps({"mode": "ari_rqgm", "rqgm_enabled": True}),
            encoding="utf-8",
        )
        before = (existing / "rqgm_state.json").read_bytes()
        before_files = {p.name for p in existing.iterdir()}
        r = _launch(_make_draft({**DEFAULT_PAIRS, **RQGM_PAIR}))
        # a new run gets a NEW directory; the existing run's persisted mode
        # (and every other file it owns) is never rewritten by a launch.
        assert Path(r["checkpoint_path"]) != existing
        assert (existing / "rqgm_state.json").read_bytes() == before
        assert {p.name for p in existing.iterdir()} == before_files
