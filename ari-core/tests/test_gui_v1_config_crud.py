"""Tests for the ``/api/v1`` config CRUD surface (gui_refresh task 05 Wave 3b).

Covers the plan-05 §Configuration API endpoints served by
``ari/viz/v1/config_api.py`` through the declarative router:

- project config GET/PATCH (revision-0 read for a missing document, If-Match
  create/merge, the frozen 400/404/409 envelopes);
- registry-backed patch validation (unknown path / wrong type / enum /
  secret_reference / read_only / new_run_only-scope rejections, with the
  offending paths in ``details.errors``) plus the pure
  ``ari.config.field_registry.validate_patch`` helper directly;
- run template lifecycle (create-only POST + 409 ``already_exists``, list
  with mtime-derived ``updated_at``, values-merge PATCH, If-Match DELETE);
- run drafts (server-generated ``draft-<12 hex>`` IDs, optional immutable
  template link, values-merge PATCH);
- atomicity (a 409 conflict leaves the stored document byte-intact) and
  determinism (``updated_at`` comes from the file mtime, never ``now()``).

The workspace is a tmp dir wired through the canonical
``ARI_CHECKPOINT_DIR`` policy (same fixture pattern as
``test_gui_v1_store.py``), so the store root is ``{tmp}/gui_store/``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ari.config import field_registry
from ari.config.field_registry import validate_patch, value_matches_type
from ari.viz.v1.router import dispatch

_REQUEST_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")
_DRAFT_ID_RE = re.compile(r"^draft-[0-9a-f]{12}$")


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    """Tmp workspace via the canonical path policy (ARI_CHECKPOINT_DIR wins);
    the GUI store lands at ``{tmp_path}/gui_store/``."""
    ckpt = tmp_path / "checkpoints" / "20260723000000_crud"
    ckpt.mkdir(parents=True)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
    return tmp_path


def _call(
    method: str,
    path: str,
    body: dict | None = None,
    if_match: int | str | None = None,
    raw_body: bytes | None = None,
) -> dict:
    headers = {}
    if if_match is not None:
        headers["If-Match"] = (
            if_match if isinstance(if_match, str) else f'"{if_match}"'
        )
    payload = raw_body
    if payload is None and body is not None:
        payload = json.dumps(body).encode("utf-8")
    return dispatch(method, path, body=payload, headers=headers or None)


def _assert_error(r: dict, status: int, code: str) -> dict:
    """The frozen typed-error shape (ADR-02): exact keys, no extras."""
    assert set(r.keys()) == {"error", "_status"}
    assert r["_status"] == status
    err = r["error"]
    assert set(err.keys()) == {
        "code",
        "message",
        "details",
        "request_id",
        "retryable",
    }
    assert err["code"] == code
    assert _REQUEST_ID_RE.match(err["request_id"])
    return err


def _store_file(workspace: Path, *parts: str) -> Path:
    return workspace.joinpath("gui_store", *parts)


# ── project config ─────────────────────────────────────────────────────────


class TestProjectConfig:
    def test_get_missing_reads_as_revision_zero(self, workspace):
        r = _call("GET", "/api/v1/projects/default/config")
        assert r["schema_version"] == 1
        assert r["revision"] == 0
        assert r["values"] == {}
        assert r["updated_paths_count"] == 0
        assert _REQUEST_ID_RE.match(r["request_id"])
        # The revision-0 read is virtual — nothing was written.
        assert not _store_file(workspace, "project_config.json").exists()

    def test_patch_creates_with_if_match_zero(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match=0,
        )
        assert r["revision"] == 1
        assert r["values"] == {"bfts.max_depth": 4}
        assert r["updated_paths_count"] == 1
        got = _call("GET", "/api/v1/projects/default/config")
        assert got["revision"] == 1
        assert got["values"] == {"bfts.max_depth": 4}

    def test_patch_merges_and_bumps_revision(self, workspace):
        _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match=0,
        )
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"llm.model": "test-model"}},
            if_match=1,
        )
        assert r["revision"] == 2
        assert r["values"] == {"bfts.max_depth": 4, "llm.model": "test-model"}
        assert r["updated_paths_count"] == 2

    def test_patch_missing_if_match_is_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
        )
        err = _assert_error(r, 400, "invalid_request")
        assert "If-Match" in err["message"]

    def test_patch_malformed_if_match_is_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match='"one"',
        )
        err = _assert_error(r, 400, "invalid_request")
        assert "If-Match" in err["message"]

    def test_patch_stale_if_match_is_frozen_409(self, workspace):
        _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match=0,
        )
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 9}},
            if_match=0,
        )
        err = _assert_error(r, 409, "revision_conflict")
        assert err["details"] == {"expected": 0, "actual": 1}

    def test_conflict_leaves_document_byte_intact(self, workspace):
        _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match=0,
        )
        doc = _store_file(workspace, "project_config.json")
        before = doc.read_bytes()
        _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 9}},
            if_match=5,
        )
        assert doc.read_bytes() == before

    def test_patch_unknown_path_is_400_with_details(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"nope.nope": 1}},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"]["errors"][0]["path"] == "nope.nope"
        assert err["details"]["errors"][0]["reason"] == "unknown_path"

    def test_patch_wrong_type_is_400_with_expected_type(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": "four"}},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        e = err["details"]["errors"][0]
        assert e["path"] == "bfts.max_depth"
        assert e["reason"] == "invalid_type"
        assert e["expected"] == "int"

    def test_patch_enum_violation_is_400_with_allowed_values(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"evaluator.axis_mode": "bogus"}},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        e = err["details"]["errors"][0]
        assert e["reason"] == "invalid_enum"
        assert isinstance(e["expected"], list) and e["expected"]

    def test_patch_secret_reference_is_rejected(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"llm.api_key": "sk-nope"}},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"]["errors"][0]["reason"] == "secret_reference"
        # The secret value must not be echoed into the message.
        assert "sk-nope" not in err["message"]

    def test_patch_new_run_only_non_project_scope_is_rejected(self, workspace):
        # ari.mode is new_run_only with scope=run: templates/drafts own it.
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"ari.mode": "ari_rqgm"}},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"]["errors"][0]["reason"] == "not_project_scope"

    def test_unknown_project_is_404(self, workspace):
        _assert_error(
            _call("GET", "/api/v1/projects/other/config"), 404, "not_found"
        )
        _assert_error(
            _call(
                "PATCH",
                "/api/v1/projects/other/config",
                body={"values": {"bfts.max_depth": 4}},
                if_match=0,
            ),
            404,
            "not_found",
        )

    def test_invalid_json_body_is_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            raw_body=b"{nope",
            if_match=0,
        )
        _assert_error(r, 400, "invalid_request")

    def test_non_object_body_is_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            raw_body=b"[1, 2]",
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        assert "JSON object" in err["message"]

    def test_empty_values_is_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {}},
            if_match=0,
        )
        _assert_error(r, 400, "invalid_request")

    def test_unknown_body_keys_are_400(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}, "surprise": 1},
            if_match=0,
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"] == {"unknown_keys": ["surprise"]}

    def test_unrouted_method_is_404(self, workspace):
        _assert_error(
            _call("DELETE", "/api/v1/projects/default/config", if_match=1),
            404,
            "not_found",
        )


# ── run templates ──────────────────────────────────────────────────────────


def _create_template(template_id="tmpl-a", name="Template A", values=None):
    return _call(
        "POST",
        "/api/v1/run-templates",
        body={
            "template_id": template_id,
            "name": name,
            "values": values if values is not None else {"bfts.max_depth": 3},
        },
    )


class TestRunTemplates:
    def test_create_and_get_roundtrip(self, workspace):
        r = _create_template()
        assert r["_status"] == 201
        assert r["template_id"] == "tmpl-a"
        assert r["name"] == "Template A"
        assert r["revision"] == 1
        assert r["values"] == {"bfts.max_depth": 3}
        got = _call("GET", "/api/v1/run-templates/tmpl-a")
        assert got["values"] == {"bfts.max_depth": 3}
        assert got["revision"] == 1
        assert got["updated_at"] == r["updated_at"]

    def test_create_duplicate_is_409_already_exists(self, workspace):
        _create_template()
        r = _create_template()
        err = _assert_error(r, 409, "already_exists")
        assert err["details"] == {"template_id": "tmpl-a"}

    def test_create_invalid_id_is_400(self, workspace):
        for bad in ("UPPER", "has.dot", "-lead", "", "a" * 65):
            r = _call(
                "POST",
                "/api/v1/run-templates",
                body={"template_id": bad, "name": "x", "values": {}},
            )
            err = _assert_error(r, 400, "invalid_request")
            assert err["details"] == {"template_id": bad}

    def test_create_missing_name_is_400(self, workspace):
        r = _call(
            "POST",
            "/api/v1/run-templates",
            body={"template_id": "tmpl-a", "values": {}},
        )
        _assert_error(r, 400, "invalid_request")

    def test_new_run_only_fields_are_allowed_in_templates(self, workspace):
        # The exact fields the project config rejects (scope=run,
        # new_run_only) are legitimate template content — they configure
        # future runs (plan 05 §Configuration scopes).
        r = _create_template(
            values={"ari.mode": "ari_rqgm", "rqgm.enabled": True}
        )
        assert r["_status"] == 201
        assert r["values"] == {"ari.mode": "ari_rqgm", "rqgm.enabled": True}

    def test_create_values_are_registry_validated(self, workspace):
        r = _create_template(values={"nope.nope": 1})
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"]["errors"][0]["path"] == "nope.nope"

    def test_list_is_id_sorted_with_mtime_updated_at(self, workspace):
        _create_template("tmpl-b", "B")
        _create_template("tmpl-a", "A")
        r = _call("GET", "/api/v1/run-templates")
        rows = r["templates"]
        assert [t["template_id"] for t in rows] == ["tmpl-a", "tmpl-b"]
        assert [t["name"] for t in rows] == ["A", "B"]
        for t in rows:
            path = _store_file(
                workspace, "run_templates", f"{t['template_id']}.json"
            )
            expected = datetime.fromtimestamp(
                int(path.stat().st_mtime), tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            assert t["updated_at"] == expected

    def test_patch_merges_values_and_keeps_name(self, workspace):
        _create_template()
        r = _call(
            "PATCH",
            "/api/v1/run-templates/tmpl-a",
            body={"values": {"llm.model": "m2"}},
            if_match=1,
        )
        assert r["revision"] == 2
        assert r["name"] == "Template A"
        assert r["values"] == {"bfts.max_depth": 3, "llm.model": "m2"}

    def test_patch_accepts_bare_integer_if_match(self, workspace):
        _create_template()
        r = _call(
            "PATCH",
            "/api/v1/run-templates/tmpl-a",
            body={"values": {"llm.model": "m2"}},
            if_match="1",  # unquoted ETag form
        )
        assert r["revision"] == 2

    def test_patch_missing_if_match_is_400(self, workspace):
        _create_template()
        r = _call(
            "PATCH",
            "/api/v1/run-templates/tmpl-a",
            body={"values": {"llm.model": "m2"}},
        )
        _assert_error(r, 400, "invalid_request")

    def test_patch_stale_is_409_and_file_unchanged(self, workspace):
        _create_template()
        doc = _store_file(workspace, "run_templates", "tmpl-a.json")
        before = doc.read_bytes()
        r = _call(
            "PATCH",
            "/api/v1/run-templates/tmpl-a",
            body={"values": {"llm.model": "m2"}},
            if_match=7,
        )
        err = _assert_error(r, 409, "revision_conflict")
        assert err["details"] == {"expected": 7, "actual": 1}
        assert doc.read_bytes() == before

    def test_patch_unknown_template_is_404(self, workspace):
        r = _call(
            "PATCH",
            "/api/v1/run-templates/ghost",
            body={"values": {"llm.model": "m2"}},
            if_match=0,
        )
        _assert_error(r, 404, "not_found")

    def test_delete_requires_if_match(self, workspace):
        _create_template()
        r = _call("DELETE", "/api/v1/run-templates/tmpl-a")
        _assert_error(r, 400, "invalid_request")
        assert _store_file(workspace, "run_templates", "tmpl-a.json").exists()

    def test_delete_lifecycle(self, workspace):
        _create_template()
        r = _call("DELETE", "/api/v1/run-templates/tmpl-a", if_match=1)
        assert r["deleted"] is True and r["template_id"] == "tmpl-a"
        assert not _store_file(
            workspace, "run_templates", "tmpl-a.json"
        ).exists()
        _assert_error(
            _call("GET", "/api/v1/run-templates/tmpl-a"), 404, "not_found"
        )
        _assert_error(
            _call("DELETE", "/api/v1/run-templates/tmpl-a", if_match=1),
            404,
            "not_found",
        )
        assert _call("GET", "/api/v1/run-templates")["templates"] == []

    def test_delete_stale_is_409(self, workspace):
        _create_template()
        r = _call("DELETE", "/api/v1/run-templates/tmpl-a", if_match=3)
        _assert_error(r, 409, "revision_conflict")
        assert _store_file(workspace, "run_templates", "tmpl-a.json").exists()

    def test_get_unknown_or_foreign_grammar_is_404(self, workspace):
        _assert_error(
            _call("GET", "/api/v1/run-templates/ghost"), 404, "not_found"
        )
        # Store grammar superset (uppercase) is a 404, never a 500.
        _assert_error(
            _call("GET", "/api/v1/run-templates/UPPER"), 404, "not_found"
        )


# ── run drafts ─────────────────────────────────────────────────────────────


class TestRunDrafts:
    def test_create_generates_server_side_id(self, workspace):
        r = _call(
            "POST",
            "/api/v1/run-drafts",
            body={"values": {"llm.model": "m1"}},
        )
        assert r["_status"] == 201
        assert _DRAFT_ID_RE.match(r["draft_id"])
        assert r["template_id"] is None
        assert r["revision"] == 1
        assert r["values"] == {"llm.model": "m1"}

    def test_create_empty_body_makes_blank_draft(self, workspace):
        r = _call("POST", "/api/v1/run-drafts", body={})
        assert r["_status"] == 201
        assert r["values"] == {}

    def test_create_with_template_link(self, workspace):
        _create_template()
        r = _call(
            "POST",
            "/api/v1/run-drafts",
            body={"template_id": "tmpl-a", "values": {}},
        )
        assert r["_status"] == 201
        assert r["template_id"] == "tmpl-a"
        got = _call("GET", f"/api/v1/run-drafts/{r['draft_id']}")
        assert got["template_id"] == "tmpl-a"

    def test_create_unknown_template_is_400(self, workspace):
        r = _call(
            "POST",
            "/api/v1/run-drafts",
            body={"template_id": "ghost", "values": {}},
        )
        err = _assert_error(r, 400, "invalid_request")
        assert err["details"] == {"template_id": "ghost"}

    def test_new_run_only_fields_are_allowed_in_drafts(self, workspace):
        r = _call(
            "POST",
            "/api/v1/run-drafts",
            body={"values": {"ari.mode": "ari_rqgm", "rqgm.enabled": True}},
        )
        assert r["_status"] == 201

    def test_patch_merges_and_keeps_template_link(self, workspace):
        _create_template()
        created = _call(
            "POST",
            "/api/v1/run-drafts",
            body={"template_id": "tmpl-a", "values": {"llm.model": "m1"}},
        )
        did = created["draft_id"]
        r = _call(
            "PATCH",
            f"/api/v1/run-drafts/{did}",
            body={"values": {"bfts.allow_web": True}},
            if_match=1,
        )
        assert r["revision"] == 2
        assert r["template_id"] == "tmpl-a"
        assert r["values"] == {"llm.model": "m1", "bfts.allow_web": True}

    def test_patch_stale_is_409(self, workspace):
        created = _call("POST", "/api/v1/run-drafts", body={})
        r = _call(
            "PATCH",
            f"/api/v1/run-drafts/{created['draft_id']}",
            body={"values": {"llm.model": "m2"}},
            if_match=9,
        )
        _assert_error(r, 409, "revision_conflict")

    def test_unknown_draft_is_404(self, workspace):
        _assert_error(
            _call("GET", "/api/v1/run-drafts/draft-000000000000"),
            404,
            "not_found",
        )
        # Non-server-shaped IDs (incl. traversal-ish input) are 404 too.
        _assert_error(
            _call("GET", "/api/v1/run-drafts/not-a-draft"), 404, "not_found"
        )


# ── determinism ────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_updated_at_is_mtime_derived_not_clock(self, workspace):
        _create_template()
        path = _store_file(workspace, "run_templates", "tmpl-a.json")
        os.utime(path, (1750000000, 1750000000))  # 2025-06-15T15:06:40Z
        r = _call("GET", "/api/v1/run-templates/tmpl-a")
        assert r["updated_at"] == "2025-06-15T15:06:40Z"

    def test_repeated_get_is_stable_modulo_request_id(self, workspace):
        _create_template()
        _call(
            "PATCH",
            "/api/v1/projects/default/config",
            body={"values": {"bfts.max_depth": 4}},
            if_match=0,
        )
        for path in (
            "/api/v1/projects/default/config",
            "/api/v1/run-templates",
            "/api/v1/run-templates/tmpl-a",
        ):
            r1 = _call("GET", path)
            r2 = _call("GET", path)
            r1.pop("request_id"), r2.pop("request_id")
            assert r1 == r2

    def test_gets_never_write(self, workspace):
        _create_template()
        store_root = _store_file(workspace)
        snap = sorted(
            (str(p), p.stat().st_mtime_ns, p.stat().st_size)
            for p in store_root.rglob("*")
            if p.is_file()
        )
        _call("GET", "/api/v1/projects/default/config")
        _call("GET", "/api/v1/run-templates")
        _call("GET", "/api/v1/run-templates/tmpl-a")
        _call("GET", "/api/v1/run-drafts/draft-000000000000")
        after = sorted(
            (str(p), p.stat().st_mtime_ns, p.stat().st_size)
            for p in store_root.rglob("*")
            if p.is_file()
        )
        assert after == snap


# ── validate_patch (pure helper) ───────────────────────────────────────────


class TestValidatePatchPure:
    def test_valid_patch_is_empty(self):
        assert validate_patch({"bfts.max_depth": 3, "llm.model": "m"}) == []

    def test_unknown_path(self):
        errs = validate_patch({"nope": 1})
        assert [e["reason"] for e in errs] == ["unknown_path"]

    def test_errors_are_path_sorted_and_deterministic(self):
        patch = {"zzz.zzz": 1, "aaa.aaa": 2}
        errs = validate_patch(patch)
        assert [e["path"] for e in errs] == ["aaa.aaa", "zzz.zzz"]
        assert errs == validate_patch(patch)
        assert patch == {"zzz.zzz": 1, "aaa.aaa": 2}  # input untouched

    def test_secret_reference_rejected_everywhere(self):
        for target in field_registry.PATCH_TARGETS:
            errs = validate_patch({"llm.api_key": "x"}, target=target)
            assert [e["reason"] for e in errs] == ["secret_reference"]

    def test_read_only_rejected_everywhere(self, monkeypatch):
        # No shipped field is read_only today — force one through the
        # overlay merge to prove the enforcement path.
        monkeypatch.setitem(
            field_registry.FIELD_META,
            "llm.temperature",
            {"level": "advanced", "mutability": "read_only"},
        )
        for target in field_registry.PATCH_TARGETS:
            errs = validate_patch({"llm.temperature": 0.2}, target=target)
            assert [e["reason"] for e in errs] == ["read_only"]

    def test_new_run_only_scope_matrix(self):
        patch = {"ari.mode": "ari_rqgm"}
        assert validate_patch(patch, target="run_template") == []
        assert validate_patch(patch, target="run_draft") == []
        errs = validate_patch(patch, target="project_config")
        assert [e["reason"] for e in errs] == ["not_project_scope"]

    def test_enum_violation_carries_allowed_values(self):
        errs = validate_patch({"ari.mode": "bogus"})
        assert errs[0]["reason"] == "invalid_enum"
        assert errs[0]["expected"] == ["simple_bfts", "ari_rqgm"]

    def test_type_matrix(self):
        # int rejects bool and str; float accepts int; unions accept None.
        assert validate_patch({"bfts.max_depth": True})[0]["reason"] == (
            "invalid_type"
        )
        assert validate_patch({"bfts.max_depth": "3"})[0]["reason"] == (
            "invalid_type"
        )
        assert validate_patch({"llm.temperature": 1}) == []  # int-as-float
        assert validate_patch({"bfts.allow_web": True}) == []
        assert validate_patch({"bfts.allow_web": 1})[0]["reason"] == (
            "invalid_type"
        )

    def test_invalid_target_and_values_raise(self):
        with pytest.raises(ValueError):
            validate_patch({}, target="nope")
        with pytest.raises(ValueError):
            validate_patch(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_value_matches_type_grammar(self):
        assert value_matches_type(None, "str | None")
        assert value_matches_type("x", "str | None")
        assert not value_matches_type(3, "str | None")
        assert value_matches_type(["a", "b"], "list[str]")
        assert not value_matches_type(["a", 3], "list[str]")
        assert value_matches_type({"a": 0.5, "b": 1}, "dict[str, float]")
        assert not value_matches_type({"a": "x"}, "dict[str, float]")
        assert value_matches_type([{"name": "s"}], "list[SkillConfig]")
        assert not value_matches_type(["s"], "list[SkillConfig]")
