"""Tests for the ``/api/v1`` read-only platform (gui_refresh Wave 2a).

ADR-02/ADR-08: declarative router matching + param extraction, the frozen
typed 404 envelope, ``request_id`` correlation, the five GET resources
(projects / runs / detail / summary / tree) against a deterministic synthetic
checkpoint from ``tests/fixtures/gui_refresh/run_fixture_factory.py``, tree
byte-parity vs ``ari.checkpoint.load_nodes_tree``, GET side-effect-freeness
(no ``viz.state`` mutation, no ``os.environ`` writes, no file writes), and
the committed ``ari/viz/v1/openapi.json`` drift guard.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

from ari.checkpoint import load_nodes_tree
from ari.viz import api_state
from ari.viz import state as _st
from ari.viz.v1 import openapi as v1_openapi
from ari.viz.v1 import queries as v1_queries
from ari.viz.v1.errors import ERROR_CODES, error_response
from ari.viz.v1.router import (
    ROUTES,
    _handle_get_run,
    _handle_get_run_summary,
    _handle_list_projects,
    dispatch,
    match,
)

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

RUN_ID = "20260723000000_v1fixture"
_REQUEST_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")


@pytest.fixture
def ckpt_base(tmp_path, monkeypatch):
    """One synthetic run checkpoint under a monkeypatched search base."""
    base = tmp_path / "checkpoints"
    base.mkdir()
    make_run_checkpoint(base / RUN_ID, nodes=10, seed=0)
    # checkpoint_finder/checkpoint_api defer the base lookup to the api_state
    # facade at call time; v1.queries follows the same pattern.
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    return base


def _assert_404_envelope(r: dict, code: str = "not_found") -> None:
    """The frozen typed-error shape (ADR-02): exact keys, no extras."""
    assert set(r.keys()) == {"error", "_status"}
    assert r["_status"] == 404
    err = r["error"]
    assert set(err.keys()) == {"code", "message", "details", "request_id", "retryable"}
    assert err["code"] == code
    assert err["details"] is None
    assert err["retryable"] is False
    assert _REQUEST_ID_RE.match(err["request_id"])


# ── router table + matching ──────────────────────────────────────────────


def test_route_table_is_the_pinned_get_resources():
    # Wave 3a (RR-P0-2 / ADR-11 / MN-2) added the secret readiness resource
    # (behavior in tests/test_gui_secret_readiness.py); task 05 Wave 3a added
    # the config schema resource (tests/test_gui_config_field_registry.py).
    # ... and the resolved-config manifest resource (same task 05 wave;
    # behavior in tests/test_gui_config_resolver.py).  Task 05 Wave 3b added
    # the config CRUD block (behavior in tests/test_gui_v1_config_crud.py)
    # and the new-run preview POSTs resolve-config/validate (behavior in
    # tests/test_gui_config_precedence_matrix.py).  Task 08 Wave 4a added
    # the read-only RQGM governance block (behavior in
    # tests/test_gui_v1_rqgm.py) — GET-only by plan 08 (no governance
    # mutation endpoint may ever appear under /rqgm/).  Task 08 Wave 4b
    # added the remaining RQGM read models (epochs / epoch detail /
    # evolution / paper-archive; behavior in tests/test_gui_v1_rqgm.py) —
    # still GET-only.  Wave 4c added the idea read model (pure
    # {ckpt}/idea.json read; behavior in this module).  Task 07 Wave 4d
    # added the results / EAR read models (bounded paper/review/ORS/EAR
    # scalars + ear listing metadata; behavior in
    # tests/test_gui_v1_results.py).  Task 06 Wave 4d added the ADR-05
    # canonical secret assignment PUT (write-only; behavior in
    # tests/test_gui_v1_secret_put_and_catalogs.py) and the model catalog
    # GET (legacy /api/models parity + per-provider env keys; same test
    # module).  Task 09 Wave 5a (MN-6, RR-P0-6/RR-P0-9) added the
    # confirmation-challenge POST (behavior in
    # tests/test_gui_confirmation_challenges.py).  Task 09 Wave 5b (MN-9)
    # added the bounded operational-diagnostics GET (behavior in
    # tests/test_gui_health_diagnostics.py).  Tasks 04/06 Wave 4e (MN-10)
    # added the canonical idempotent launch POST /api/v1/runs (behavior in
    # tests/test_gui_v1_launch.py; the legacy POST /api/launch runs
    # unchanged in parallel).  The task 07 tail added the cursor log
    # explorer GET runs/{run_id}/logs (bounded byte-offset pages over
    # {ckpt}/ari.log; behavior in tests/test_gui_v1_logs.py).
    assert [(m, t) for m, t, _h in ROUTES] == [
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/projects/{project_id}/runs"),
        ("GET", "/api/v1/config/schema"),
        ("GET", "/api/v1/runs/{run_id}/resolved-config"),
        ("GET", "/api/v1/runs/{run_id}/summary"),
        ("GET", "/api/v1/runs/{run_id}/tree"),
        ("GET", "/api/v1/runs/{run_id}/idea"),
        ("GET", "/api/v1/runs/{run_id}/results"),
        ("GET", "/api/v1/runs/{run_id}/ear"),
        ("GET", "/api/v1/runs/{run_id}/logs"),
        ("GET", "/api/v1/runs/{run_id}"),
        ("POST", "/api/v1/runs"),
        ("GET", "/api/v1/secrets/status"),
        ("POST", "/api/v1/challenges"),
        ("PUT", "/api/v1/secrets/{secret_id}"),
        ("GET", "/api/v1/config/catalogs/models"),
        ("GET", "/api/v1/projects/{project_id}/config"),
        ("PATCH", "/api/v1/projects/{project_id}/config"),
        ("GET", "/api/v1/run-templates"),
        ("POST", "/api/v1/run-templates"),
        ("GET", "/api/v1/run-templates/{template_id}"),
        ("PATCH", "/api/v1/run-templates/{template_id}"),
        ("DELETE", "/api/v1/run-templates/{template_id}"),
        ("POST", "/api/v1/run-drafts"),
        ("GET", "/api/v1/run-drafts/{draft_id}"),
        ("PATCH", "/api/v1/run-drafts/{draft_id}"),
        ("POST", "/api/v1/run-drafts/{draft_id}/resolve-config"),
        ("POST", "/api/v1/run-drafts/{draft_id}/validate"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/capabilities"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/overview"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/registry"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/transitions"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/audit"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/policies"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/score-rewrites"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/epochs"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/evolution"),
        ("GET", "/api/v1/runs/{run_id}/rqgm/paper-archive"),
        ("GET", "/api/v1/diagnostics"),
    ]


def test_match_extracts_params_and_urldecodes():
    handler, params, template = match("/api/v1/runs/abc%20d/summary")
    assert handler is _handle_get_run_summary
    assert params == {"run_id": "abc d"}
    assert template == "/api/v1/runs/{run_id}/summary"


def test_match_distinguishes_run_detail_from_subresources():
    handler, params, _ = match("/api/v1/runs/abc")
    assert handler is _handle_get_run and params == {"run_id": "abc"}
    handler, _, _ = match("/api/v1/runs/abc/tree")
    assert handler.__name__ == "_handle_get_run_tree"


def test_match_strips_query_string_and_rejects_unknown():
    handler, params, _ = match("/api/v1/projects?probe=1")
    assert handler is _handle_list_projects and params == {}
    assert match("/api/v1/nope") is None
    assert match("/api/v1/runs/a/b/c") is None
    assert match("/api/v1/projects", method="POST") is None


# ── error envelope (frozen shape) + request correlation ──────────────────


def test_dispatch_unknown_path_returns_frozen_404_envelope():
    _assert_404_envelope(dispatch("GET", "/api/v1/nope"))


def test_dispatch_unknown_method_returns_404_envelope():
    _assert_404_envelope(dispatch("POST", "/api/v1/projects"))


def test_unknown_run_returns_404_envelope(ckpt_base):
    r = dispatch("GET", "/api/v1/runs/20990101000000_missing")
    _assert_404_envelope(r)
    assert "20990101000000_missing" in r["error"]["message"]


def test_unknown_project_returns_404_envelope(ckpt_base):
    _assert_404_envelope(dispatch("GET", "/api/v1/projects/other/runs"))


def test_request_id_format_and_uniqueness_on_success(ckpt_base):
    r1 = dispatch("GET", "/api/v1/projects")
    r2 = dispatch("GET", "/api/v1/projects")
    assert _REQUEST_ID_RE.match(r1["request_id"])
    assert _REQUEST_ID_RE.match(r2["request_id"])
    assert r1["request_id"] != r2["request_id"]
    assert "_status" not in r1  # success rides the _json default-200 path


def test_error_codes_frozen_and_unknown_code_rejected():
    # Additive-only vocabulary (plan 04 §API principles): Wave 3b (task 05
    # config CRUD) appended the two 409 codes.
    assert ERROR_CODES == (
        "not_found",
        "invalid_request",
        "internal",
        "revision_conflict",
        "already_exists",
    )
    with pytest.raises(ValueError):
        error_response("nonsense", "x", request_id="req-0", status=400)


# ── happy paths against the synthetic checkpoint ─────────────────────────


def test_projects_happy_path(ckpt_base):
    r = dispatch("GET", "/api/v1/projects")
    assert r["schema_version"] == 1
    assert len(r["projects"]) == 1
    p = r["projects"][0]
    assert p["schema_version"] == 1
    assert p["project_id"] == "default"  # ADR-08 virtual project
    assert p["run_count"] == 1
    assert str(ckpt_base) in p["checkpoint_roots"]


def test_runs_happy_path(ckpt_base):
    r = dispatch("GET", "/api/v1/projects/default/runs")
    assert r["schema_version"] == 1 and r["project_id"] == "default"
    assert len(r["runs"]) == 1
    run = r["runs"][0]
    assert run["run_id"] == RUN_ID  # checkpoint-dir-name identity (ADR-08)
    assert run["project_id"] == "default"
    assert run["display_name"] == "v1fixture"  # timestamp prefix stripped
    assert run["node_count"] == 10
    assert run["review_score"] is None  # no review_report.json in fixture
    assert run["checkpoint_path"] == str(ckpt_base / RUN_ID)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", run["mtime_utc"])
    # Status must agree with the tree the canonical loader sees: an orphaned
    # "running" node (no live pid) reads as "stopped", else "completed".
    nodes = load_nodes_tree(ckpt_base / RUN_ID)["nodes"]
    expected = (
        "stopped"
        if any(n["status"] == "running" for n in nodes)
        else "completed"
    )
    assert run["status"] == expected
    # best_metric surfaces the best _scientific_score across nodes.
    sci = [
        n["metrics"]["_scientific_score"]
        for n in nodes
        if n["metrics"].get("_scientific_score") is not None
    ]
    assert run["best_metric"] == round(max(sci), 4)


def test_run_detail_happy_path_and_rqgm_capability(ckpt_base):
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}")
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    assert r["has_paper"] is False
    assert r["phase"] == "bfts"  # fixture writes idea.json, no paper/review
    assert r["capabilities"] == {"rqgm": False}
    # rqgm capability flips on rqgm_state.json existence alone (no ari.rqgm
    # import) — write the artifact and re-read.
    (ckpt_base / RUN_ID / "rqgm_state.json").write_text("{}", encoding="utf-8")
    r2 = dispatch("GET", f"/api/v1/runs/{RUN_ID}")
    assert r2["capabilities"] == {"rqgm": True}


def test_run_summary_matches_list_entry(ckpt_base):
    listed = dispatch("GET", "/api/v1/projects/default/runs")["runs"][0]
    summary = dispatch("GET", f"/api/v1/runs/{RUN_ID}/summary")
    assert _REQUEST_ID_RE.match(summary.pop("request_id"))
    assert summary == listed


def test_tree_byte_parity_and_revision(ckpt_base):
    ckpt = ckpt_base / RUN_ID
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/tree")
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    expected = load_nodes_tree(ckpt)["nodes"]
    # Byte-preserving pass-through: identical serialization, key order included.
    assert json.dumps(r["nodes"], ensure_ascii=False) == json.dumps(
        expected, ensure_ascii=False
    )
    # revision = resolved tree file mtime (ns); precedence picks tree.json.
    assert r["revision"] == (ckpt / "tree.json").stat().st_mtime_ns


# ── idea read model (Wave 4c: pure {ckpt}/idea.json read) ────────────────


def test_idea_present_passes_factory_ideas_through(ckpt_base):
    """The fixture factory writes idea.json ({"ideas": [...]}) — the
    endpoint serves those dicts verbatim with present=True."""
    ckpt = ckpt_base / RUN_ID
    on_disk = json.loads((ckpt / "idea.json").read_text(encoding="utf-8"))
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/idea")
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    assert r["present"] is True
    assert r["ideas"] == on_disk["ideas"]
    assert r["ideas"][0]["idea_id"] == "idea_0"
    # Fields absent from the file stay None — never fabricated "".
    assert r["gap_analysis"] is None
    assert r["primary_metric"] is None
    assert r["metric_rationale"] is None
    assert r["degraded_reasons"] == []
    assert _REQUEST_ID_RE.match(r["request_id"])


def test_idea_gap_analysis_fields_pass_through(ckpt_base):
    """The exact keys the legacy IdeaPage /state injection reads
    (state_service: gap_analysis / primary_metric / metric_rationale)."""
    ckpt = ckpt_base / RUN_ID
    (ckpt / "idea.json").write_text(
        json.dumps({
            "ideas": [{"title": "T", "novelty_score": 7}],
            "gap_analysis": "prior work ignores X",
            "primary_metric": "accuracy",
            "metric_rationale": "matches the baseline papers",
        }),
        encoding="utf-8",
    )
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/idea")
    assert r["present"] is True
    assert r["ideas"] == [{"title": "T", "novelty_score": 7}]
    assert r["gap_analysis"] == "prior work ignores X"
    assert r["primary_metric"] == "accuracy"
    assert r["metric_rationale"] == "matches the baseline papers"


def test_idea_absent_file_reports_present_false(ckpt_base):
    (ckpt_base / RUN_ID / "idea.json").unlink()
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/idea")
    assert r["present"] is False
    assert r["ideas"] == []
    # Honest absence: no fabricated empty strings.
    assert r["gap_analysis"] is None
    assert r["primary_metric"] is None
    assert r["metric_rationale"] is None
    assert r["degraded_reasons"] == []


def test_idea_malformed_json_degrades_not_500(ckpt_base):
    (ckpt_base / RUN_ID / "idea.json").write_text("{torn", encoding="utf-8")
    r = dispatch("GET", f"/api/v1/runs/{RUN_ID}/idea")
    assert "_status" not in r  # 200, not an error envelope
    assert r["present"] is False
    assert r["ideas"] == []
    assert any("not valid JSON" in reason for reason in r["degraded_reasons"])


def test_idea_unknown_run_returns_404_envelope(ckpt_base):
    _assert_404_envelope(
        dispatch("GET", "/api/v1/runs/20990101000000_missing/idea")
    )


# ── GET side-effect-freeness ─────────────────────────────────────────────


def _fs_snapshot(root: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(p), p.stat().st_mtime_ns, p.stat().st_size)
        for p in root.rglob("*")
        if p.is_file()
    )


def test_gets_are_side_effect_free(ckpt_base):
    fs_before = _fs_snapshot(ckpt_base)
    env_before = dict(os.environ)
    st_before = {
        "_checkpoint_dir": _st._checkpoint_dir,
        "_last_proc": _st._last_proc,
        "_last_experiment_md": _st._last_experiment_md,
        "_running_procs": copy.copy(_st._running_procs),
    }
    for path in (
        "/api/v1/projects",
        "/api/v1/projects/default/runs",
        f"/api/v1/runs/{RUN_ID}",
        f"/api/v1/runs/{RUN_ID}/summary",
        f"/api/v1/runs/{RUN_ID}/tree",
        f"/api/v1/runs/{RUN_ID}/idea",  # Wave 4c idea read model
        f"/api/v1/runs/{RUN_ID}/results",  # Wave 4d results read model
        f"/api/v1/runs/{RUN_ID}/ear",  # Wave 4d EAR read model
        "/api/v1/runs/20990101000000_missing",
        "/api/v1/secrets/status",  # Wave 3a readiness GET (ADR-11)
        "/api/v1/config/schema",  # Wave 3a config schema GET (task 05)
    ):
        dispatch("GET", path)
    assert _fs_snapshot(ckpt_base) == fs_before, "v1 GET wrote into the checkpoint base"
    assert dict(os.environ) == env_before, "v1 GET mutated os.environ"
    assert _st._checkpoint_dir is st_before["_checkpoint_dir"]
    assert _st._last_proc is st_before["_last_proc"]
    assert _st._last_experiment_md == st_before["_last_experiment_md"]
    assert _st._running_procs == st_before["_running_procs"]


def test_queries_module_holds_no_mutable_module_state(ckpt_base):
    def _mutables() -> dict:
        return {
            k: v
            for k, v in vars(v1_queries).items()
            if not k.startswith("__") and isinstance(v, (dict, list, set))
        }

    before = _mutables()
    snapshot = copy.deepcopy(before)
    dispatch("GET", "/api/v1/projects/default/runs")
    after = _mutables()
    assert list(after.keys()) == list(before.keys())
    assert after == snapshot


# ── OpenAPI drift guard ──────────────────────────────────────────────────


def test_openapi_committed_matches_generated():
    committed = v1_openapi.OPENAPI_PATH.read_text(encoding="utf-8")
    fresh = v1_openapi.dumps(v1_openapi.build_openapi())
    assert committed == fresh, (
        "ari/viz/v1/openapi.json drifted from the route table / DTO schemas — "
        "regenerate with `python -m ari.viz.v1.openapi --update` if intentional"
    )


def test_openapi_covers_every_route_and_is_deterministic():
    doc = v1_openapi.build_openapi()
    assert set(doc["paths"].keys()) == {t for _m, t, _h in ROUTES}
    # Every (method, template) route appears exactly once, and vice versa.
    generated = {
        (m.upper(), t) for t, item in doc["paths"].items() for m in item
    }
    assert generated == {(m, t) for m, t, _h in ROUTES}
    for template, item in doc["paths"].items():
        for method, op in item.items():
            success = "201" if op["responses"].get("201") else "200"
            assert {success, "404", "500"} <= set(op["responses"].keys())
            if method in ("patch", "delete"):
                # Wave 3b mutations: documented If-Match + 400/409 envelopes.
                assert any(
                    p["name"] == "If-Match" and p["in"] == "header"
                    for p in op.get("parameters", [])
                )
                assert {"400", "409"} <= set(op["responses"].keys())
    # Deterministic (P2): two builds serialize identically, no timestamps.
    assert v1_openapi.dumps(doc) == v1_openapi.dumps(v1_openapi.build_openapi())
