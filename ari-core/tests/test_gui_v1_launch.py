"""Tests for ``POST /api/v1/runs`` — the idempotent launch (gui_refresh
tasks 04/06 Wave 4e; handler ``ari/viz/v1/launch.py``).

The CLI subprocess spawn is ALWAYS mocked (``subprocess.Popen`` monkey-
patched to a recording fake) — no test here starts a real run.  Covered:

- happy path: validation-first, server-minted ``<UTC ts>_<slug>-<6 hex>``
  run id, checkpoint materialization (experiment.md from the draft goal,
  bundled workflow.yaml CoW seed, legacy-compatible launch_config.json,
  resolved_config.json whose digest matches the resolve-config preview),
  launch_events.jsonl lifecycle (draft→validating→accepted→spawned with
  monotonic ids), GUI-layer ``ARI_*`` env translation +
  ``ARI_CHECKPOINT_DIR`` pinning, response shape, ``run`` bus event;
- idempotency: duplicate key → SAME run_id + ``idempotent_replay: true`` +
  exactly one Popen call (double-click safety, in-process cache cleared to
  prove the on-disk ``gui_store/launches/`` record alone suffices);
  distinct keys / no key → distinct run_ids and dirs;
- validation failure (bad draft value) → typed 400 + NO dir + NO spawn +
  NO idempotency record;
- governance-locked draft fields (``ari.mode`` / ``rqgm.*`` — ADR-09
  pending) → 400 ``mode_locked``; missing goal → 400 ``missing_goal``;
- unknown draft → typed 404; spawn failure → typed 500 with the partial-
  materialization details and a released idempotency claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ari.viz.v1 import events, launch
from ari.viz.v1.router import dispatch

_RUN_ID_RE = re.compile(r"^\d{14}_[A-Za-z0-9_-]+-[0-9a-f]{6}$")

GOAL = "# Research Goal\nStudy the effect of X on Y.\nMore context here.\n"


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """Tmp workspace via the canonical path policy (ARI_CHECKPOINT_DIR wins);
    checkpoints land at ``{tmp_path}/checkpoints/`` and the GUI store at
    ``{tmp_path}/gui_store/`` — same fixture pattern as the config CRUD
    tests.  The events bus and the launch replay cache are reset."""
    ckpt = tmp_path / "checkpoints" / "20260726000000_seed"
    ckpt.mkdir(parents=True)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    # Isolation: earlier suites may leave documented ARI_* overrides in
    # os.environ (e.g. test_config.py writes ARI_LLM_MODEL); the resolver
    # would then attribute the leaf to the env layer and the launch would
    # correctly skip the GUI-layer translation — hiding what this suite
    # asserts.  Clear the whole documented family (except the checkpoint
    # pin this fixture owns) plus the ARI_MODEL alias.
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
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid

    def poll(self):  # pragma: no cover - parity with Popen
        return None


@pytest.fixture
def fake_popen(monkeypatch):
    """Record every would-be spawn; never start a process."""
    calls: list[dict] = []

    def _fake(cmd, **kwargs):
        calls.append({"cmd": list(cmd), **kwargs})
        return FakeProc(pid=4242 + len(calls))

    monkeypatch.setattr(launch.subprocess, "Popen", _fake)
    return calls


def _call(method: str, path: str, body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    return dispatch(method, path, body=payload)


def _make_draft(values: dict | None = None, goal: str | None = GOAL) -> str:
    body: dict = {"values": values or {}}
    if goal is not None:
        body["goal"] = goal
    r = _call("POST", "/api/v1/run-drafts", body)
    assert r.get("_status") == 201, r
    return r["draft_id"]


def _assert_error(r: dict, status: int, code: str) -> dict:
    assert set(r.keys()) == {"error", "_status"}, r
    assert r["_status"] == status
    assert r["error"]["code"] == code
    return r["error"]


def _run_dirs(workspace: Path) -> set[str]:
    root = workspace / "checkpoints"
    return {d.name for d in root.iterdir() if d.is_dir()}


# ── happy path ─────────────────────────────────────────────────────────────


class TestLaunchHappyPath:
    def test_response_shape_and_run_id(self, workspace, fake_popen):
        draft_id = _make_draft({"bfts.max_total_nodes": 7})
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert "_status" not in r  # 200 via the default status convention
        assert r["schema_version"] == 1
        assert r["accepted"] is True
        assert r["idempotent_replay"] is False
        assert _RUN_ID_RE.fullmatch(r["run_id"]), r["run_id"]
        assert r["status_url"] == f"/api/v1/runs/{r['run_id']}"
        assert r["checkpoint_path"] == str(
            workspace / "checkpoints" / r["run_id"]
        )
        assert re.fullmatch(r"req-[0-9a-f]{12}", r["request_id"])

    def test_display_name_seeds_the_slug(self, workspace, fake_popen):
        draft_id = _make_draft()
        r = _call(
            "POST",
            "/api/v1/runs",
            {"draft_id": draft_id, "display_name": "My Great Run"},
        )
        assert r["run_id"][15:].startswith("My_Great_Run-")

    def test_goal_first_content_line_seeds_the_slug(self, workspace, fake_popen):
        draft_id = _make_draft()  # goal's first non-heading line wins
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert "Study_the_effect_of_X_on_Y" in r["run_id"]

    def test_materialization(self, workspace, fake_popen):
        draft_id = _make_draft({"bfts.max_total_nodes": 7})
        r = _call(
            "POST",
            "/api/v1/runs",
            {"draft_id": draft_id, "display_name": "Mat Run"},
        )
        ckpt = Path(r["checkpoint_path"])
        assert ckpt.is_dir()
        assert (ckpt / "experiment.md").read_text(encoding="utf-8") == GOAL
        # workflow.yaml CoW-seeded byte-identical from the bundled copy.
        from ari.config.finder import package_config_root

        assert (ckpt / "workflow.yaml").read_bytes() == (
            package_config_root() / "workflow.yaml"
        ).read_bytes()
        lc = json.loads((ckpt / "launch_config.json").read_text())
        assert lc["max_nodes"] == 7  # draft override reached the manifest
        assert lc["draft_id"] == draft_id
        assert lc["display_name"] == "Mat Run"
        for legacy_key in (
            "llm_model", "llm_provider", "profile", "max_depth", "max_react",
            "timeout_node_s", "parallel", "frontier_score", "composite",
            "axis_mode", "allow_web",
        ):
            assert legacy_key in lc

    def test_resolved_config_digest_matches_preview(self, workspace, fake_popen):
        draft_id = _make_draft({"bfts.max_total_nodes": 9})
        preview = _call(
            "POST", f"/api/v1/run-drafts/{draft_id}/resolve-config", {}
        )
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        manifest = json.loads(
            (Path(r["checkpoint_path"]) / "resolved_config.json").read_text()
        )
        assert manifest["digest"] == preview["digest"]
        assert manifest["run_id"] == r["run_id"]  # real identity, not draft id
        assert manifest["values"]["bfts"]["max_total_nodes"] == 9

    def test_spawn_cmd_env_and_registration(self, workspace, fake_popen):
        draft_id = _make_draft(
            {"bfts.max_total_nodes": 7, "llm.model": "m-test",
             "llm.backend": "ollama"}
        )
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert len(fake_popen) == 1
        call = fake_popen[0]
        ckpt = Path(r["checkpoint_path"])
        assert call["cmd"] == [
            "python3", "-m", "ari.cli", "run", str(ckpt / "experiment.md")
        ]
        env = call["env"]
        assert env["ARI_CHECKPOINT_DIR"] == str(ckpt)
        # GUI-layer (draft) values ride the documented ARI_* family.
        assert env["ARI_MAX_NODES"] == "7"
        assert env["ARI_MODEL"] == "m-test"
        assert env["ARI_BACKEND"] == "ollama"
        assert call["cwd"] == str(workspace)
        assert call["start_new_session"] is True
        from ari.viz import state as _st

        assert str(ckpt.resolve()) in _st._running_procs
        _st._running_procs.pop(str(ckpt.resolve()), None)

    def test_profile_flag_passthrough(self, workspace, fake_popen):
        draft_id = _make_draft()
        _call(
            "POST", "/api/v1/runs", {"draft_id": draft_id, "profile": "laptop"}
        )
        assert fake_popen[0]["cmd"][-2:] == ["--profile", "laptop"]

    def test_lifecycle_events_monotonic(self, workspace, fake_popen):
        draft_id = _make_draft()
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        lines = [
            json.loads(ln)
            for ln in (Path(r["checkpoint_path"]) / "launch_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert [e["state"] for e in lines] == [
            "draft", "validating", "accepted", "spawned"
        ]
        assert [e["event_id"] for e in lines] == [1, 2, 3, 4]
        assert lines[3]["pid"] == 4243  # the fake proc's pid

    def test_run_event_published_on_bus(self, workspace, fake_popen):
        draft_id = _make_draft()
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        published = events.replay_since(0, run_id=r["run_id"], topics=("run",))
        assert len(published) == 1
        ev = published[0]
        assert ev["resource"] == f"/api/v1/runs/{r['run_id']}"
        assert ev["payload"] == {"lifecycle": "spawned"}


# ── idempotency ────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_duplicate_key_replays_same_run_and_spawns_once(
        self, workspace, fake_popen
    ):
        draft_id = _make_draft()
        body = {"draft_id": draft_id, "idempotency_key": "click-1"}
        first = _call("POST", "/api/v1/runs", body)
        second = _call("POST", "/api/v1/runs", body)
        assert second["run_id"] == first["run_id"]
        assert second["checkpoint_path"] == first["checkpoint_path"]
        assert first["idempotent_replay"] is False
        assert second["idempotent_replay"] is True
        assert len(fake_popen) == 1  # double-click spawned exactly one proc
        assert len(_run_dirs(workspace)) == 2  # seed + the single run

    def test_replay_survives_in_process_cache_loss(self, workspace, fake_popen):
        draft_id = _make_draft()
        body = {"draft_id": draft_id, "idempotency_key": "durable-key"}
        first = _call("POST", "/api/v1/runs", body)
        launch._reset_for_tests()  # simulate a server restart
        second = _call("POST", "/api/v1/runs", body)
        assert second["run_id"] == first["run_id"]
        assert second["idempotent_replay"] is True
        assert len(fake_popen) == 1
        # The on-disk record is where the plan says it is.
        assert (
            workspace / "gui_store" / "launches" / "durable-key.json"
        ).is_file()

    def test_distinct_keys_get_distinct_runs(self, workspace, fake_popen):
        draft_id = _make_draft()
        r1 = _call(
            "POST", "/api/v1/runs",
            {"draft_id": draft_id, "idempotency_key": "k-a"},
        )
        r2 = _call(
            "POST", "/api/v1/runs",
            {"draft_id": draft_id, "idempotency_key": "k-b"},
        )
        assert r1["run_id"] != r2["run_id"]
        assert r1["checkpoint_path"] != r2["checkpoint_path"]
        assert len(fake_popen) == 2

    def test_missing_key_always_launches_new(self, workspace, fake_popen):
        draft_id = _make_draft()
        r1 = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        r2 = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        assert r1["run_id"] != r2["run_id"]
        assert len(fake_popen) == 2

    def test_bad_key_grammar_is_400(self, workspace, fake_popen):
        draft_id = _make_draft()
        r = _call(
            "POST", "/api/v1/runs",
            {"draft_id": draft_id, "idempotency_key": "../escape"},
        )
        _assert_error(r, 400, "invalid_request")
        assert not fake_popen


# ── validation-first rejections ────────────────────────────────────────────


class TestLaunchValidation:
    def test_invalid_draft_value_400_no_dir_no_spawn(
        self, workspace, fake_popen
    ):
        # Bypass the CRUD guard to store a value the resolver will reject
        # (wrong type), proving the LAUNCH validates rather than trusting
        # the store.
        from ari.viz.v1.store import KIND_RUN_DRAFT, GuiStore

        draft_id = "draft-aaaaaaaaaaaa"
        GuiStore.from_env().write(
            KIND_RUN_DRAFT,
            {"template_id": None,
             "values": {"bfts.max_total_nodes": "not-an-int"},
             "goal": GOAL},
            doc_id=draft_id,
        )
        before = _run_dirs(workspace)
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        err = _assert_error(r, 400, "invalid_request")
        assert any(
            e["path"] == "bfts.max_total_nodes"
            for e in err["details"]["errors"]
        )
        assert _run_dirs(workspace) == before  # NO dir created
        assert not fake_popen  # NO spawn
        assert not (workspace / "gui_store" / "launches").exists()

    @pytest.mark.parametrize(
        "path,value",
        [("rqgm.epoch.nodes_per_epoch", 3),
         ("rqgm.governance.enabled", False),
         ("rqgm.paper.archive.width", 2)],
    )
    def test_governance_fields_stay_locked_after_adr09(
        self, workspace, fake_popen, path, value
    ):
        # ADR-09 opened ONLY the two mode+interlock pairs (covered by
        # tests/test_gui_v1_mode_selection.py); every other rqgm.* tuning /
        # governance leaf still rejects mode_locked with zero mutation.
        draft_id = _make_draft({path: value})
        before = _run_dirs(workspace)
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        err = _assert_error(r, 400, "invalid_request")
        assert any(
            e["path"] == path and e["reason"] == "mode_locked"
            for e in err["details"]["errors"]
        )
        assert _run_dirs(workspace) == before
        assert not fake_popen

    def test_missing_goal_is_a_launch_error(self, workspace, fake_popen):
        draft_id = _make_draft(goal=None)
        r = _call("POST", "/api/v1/runs", {"draft_id": draft_id})
        err = _assert_error(r, 400, "invalid_request")
        assert any(
            e["reason"] == "missing_goal" for e in err["details"]["errors"]
        )
        assert not fake_popen

    def test_unknown_draft_404(self, workspace, fake_popen):
        r = _call(
            "POST", "/api/v1/runs", {"draft_id": "draft-000000000000"}
        )
        _assert_error(r, 404, "not_found")
        assert not fake_popen

    def test_unknown_body_key_400(self, workspace, fake_popen):
        r = _call(
            "POST", "/api/v1/runs",
            {"draft_id": "draft-000000000000", "experiment_md": "sneaky"},
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"]["unknown_keys"] == ["experiment_md"]

    def test_bad_profile_400(self, workspace, fake_popen):
        draft_id = _make_draft()
        r = _call(
            "POST", "/api/v1/runs",
            {"draft_id": draft_id, "profile": "mainframe"},
        )
        _assert_error(r, 400, "invalid_request")
        assert not fake_popen


# ── spawn failure ──────────────────────────────────────────────────────────


class TestSpawnFailure:
    def test_typed_500_and_claim_release(self, workspace, monkeypatch):
        def _boom(cmd, **kwargs):
            raise OSError("no such interpreter")

        monkeypatch.setattr(launch.subprocess, "Popen", _boom)
        draft_id = _make_draft()
        r = _call(
            "POST", "/api/v1/runs",
            {"draft_id": draft_id, "idempotency_key": "retry-me"},
        )
        err = _assert_error(r, 500, "internal")
        assert err["retryable"] is True
        assert err["details"]["partial_materialization"] is True
        ckpt = Path(err["details"]["checkpoint_path"])
        states = [
            json.loads(ln)["state"]
            for ln in (ckpt / "launch_events.jsonl")
            .read_text(encoding="utf-8").splitlines()
        ]
        assert states[-1] == "failed"
        # The idempotency claim was released: a retry launches fresh.
        assert not (
            workspace / "gui_store" / "launches" / "retry-me.json"
        ).exists()


# ── draft goal round-trip (the additive Wave 4e draft field) ───────────────


class TestDraftGoalField:
    def test_goal_round_trips_and_survives_patch(self, workspace):
        draft_id = _make_draft({"bfts.max_depth": 3})
        got = _call("GET", f"/api/v1/run-drafts/{draft_id}")
        assert got["goal"] == GOAL
        patched = dispatch(
            "PATCH",
            f"/api/v1/run-drafts/{draft_id}",
            body=json.dumps({"values": {"bfts.max_depth": 4}}).encode(),
            headers={"If-Match": '"1"'},
        )
        assert patched["goal"] == GOAL  # values-merge preserves the goal
        assert patched["values"]["bfts.max_depth"] == 4

    def test_non_string_goal_rejected_at_create(self, workspace):
        r = _call("POST", "/api/v1/run-drafts", {"goal": 42})
        _assert_error(r, 400, "invalid_request")
