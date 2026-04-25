"""Tests for ari-core/ari/viz/api_fewshot.py (v0.6.0 rubric management)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import state as _st
from ari.viz.api_fewshot import (
    _api_fewshot_delete,
    _api_fewshot_list,
    _api_fewshot_upload,
    _rubric_is_known,
    _safe_rubric_id,
)


@pytest.fixture(autouse=True)
def _isolate_ari_root(tmp_path, monkeypatch):
    """Pin _ari_root to a temp repo with a minimal reviewer_rubrics/ layout."""
    root = tmp_path / "repo"
    rubrics_dir = root / "ari-core" / "config" / "reviewer_rubrics"
    rubrics_dir.mkdir(parents=True)
    # Minimal valid rubric YAML
    (rubrics_dir / "neurips.yaml").write_text(
        "id: neurips\nvenue: NeurIPS\nscore_dimensions:\n  - {name: overall, scale: [1, 10]}\n"
    )
    (rubrics_dir / "sc.yaml").write_text(
        "id: sc\nvenue: SC\nscore_dimensions:\n  - {name: overall, scale: [1, 5]}\n"
    )
    # Pre-existing fewshot example
    ex_dir = rubrics_dir / "fewshot_examples" / "neurips"
    ex_dir.mkdir(parents=True)
    (ex_dir / "attention.json").write_text(
        json.dumps({
            "_source": "test fixture",
            "soundness": 4, "overall": 8, "decision": "accept",
        })
    )
    (ex_dir / "attention.txt").write_text("paper excerpt")
    (ex_dir / "README.md").write_text("# should be ignored\n")
    monkeypatch.setattr(_st, "_ari_root", root)


# ─── _safe_rubric_id ───────────────────────────────────────────────

def test_safe_rubric_id_strips_traversal():
    assert _safe_rubric_id("../../etc") == "etc"
    assert _safe_rubric_id("foo/bar") == "foobar"
    assert _safe_rubric_id("ok_rubric-1") == "ok_rubric-1"
    assert _safe_rubric_id("") == ""


# ─── _rubric_is_known ──────────────────────────────────────────────

def test_rubric_is_known_accepts_existing():
    assert _rubric_is_known("neurips") is True
    assert _rubric_is_known("sc") is True


def test_rubric_is_known_rejects_missing():
    assert _rubric_is_known("chi") is False
    assert _rubric_is_known("etc") is False
    assert _rubric_is_known("") is False


# ─── listing ───────────────────────────────────────────────────────

def test_list_returns_fewshot_examples():
    r = _api_fewshot_list("neurips")
    assert r["rubric_id"] == "neurips"
    assert r["count"] == 1
    assert r["examples"][0]["id"] == "attention"
    assert r["examples"][0]["decision"] == "accept"
    assert r["examples"][0]["overall"] == 8


def test_list_ignores_readme_and_non_allowed_ext():
    r = _api_fewshot_list("neurips")
    assert all(e["id"] != "README" for e in r["examples"])
    # .md not in allowed_exts, so README.md is excluded from file listing
    files = r["examples"][0]["files"]
    exts = {f["ext"] for f in files}
    assert exts == {"json", "txt"}


def test_list_empty_for_rubric_without_fewshot():
    r = _api_fewshot_list("sc")
    assert r["count"] == 0
    assert r["examples"] == []


# ─── upload ────────────────────────────────────────────────────────

def test_upload_creates_json():
    payload = {
        "example_id": "new_example",
        "review_json": json.dumps({
            "soundness": 3, "overall": 6, "decision": "accept",
        }),
        "paper_txt": "abstract text",
    }
    r = _api_fewshot_upload("neurips", payload)
    assert r["ok"] is True
    listing = _api_fewshot_list("neurips")
    ids = {e["id"] for e in listing["examples"]}
    assert "new_example" in ids


def test_upload_requires_example_id():
    r = _api_fewshot_upload("neurips", {"review_json": "{}"})
    assert "error" in r


def test_upload_requires_review_json():
    r = _api_fewshot_upload("neurips", {"example_id": "x"})
    assert "error" in r


def test_upload_rejects_unknown_rubric():
    r = _api_fewshot_upload("completely_unknown_xyz", {
        "example_id": "x", "review_json": "{}",
    })
    assert "error" in r
    assert "unknown rubric" in r["error"]


def test_upload_rejects_traversal_rubric():
    # `../../etc` → `etc` after safe strip. `etc` is not a known rubric, so rejected.
    r = _api_fewshot_upload("../../etc", {
        "example_id": "x", "review_json": "{}",
    })
    assert "error" in r


def test_upload_rejects_malformed_json():
    r = _api_fewshot_upload("neurips", {
        "example_id": "x", "review_json": "not-json-at-all",
    })
    assert "error" in r


def test_upload_tags_provenance():
    r = _api_fewshot_upload("neurips", {
        "example_id": "prov_test",
        "review_json": json.dumps({"overall": 5, "decision": "accept"}),
    })
    assert r["ok"]
    # Re-read the JSON to confirm _source was added
    listing = _api_fewshot_list("neurips")
    entry = next(e for e in listing["examples"] if e["id"] == "prov_test")
    # Use the file directly to inspect provenance
    p = _st._ari_root / "ari-core" / "config" / "reviewer_rubrics" / "fewshot_examples" / "neurips" / "prov_test.json"
    data = json.loads(p.read_text())
    assert data.get("_source", "").startswith("GUI upload")


# ─── delete ────────────────────────────────────────────────────────

def test_delete_removes_all_extensions():
    r = _api_fewshot_delete("neurips", "attention")
    assert r["ok"] is True
    assert set(r["removed"]) == {"attention.json", "attention.txt"}
    assert _api_fewshot_list("neurips")["count"] == 0


def test_delete_rejects_unknown_rubric():
    r = _api_fewshot_delete("completely_unknown_xyz", "attention")
    assert "error" in r


def test_delete_rejects_traversal_example():
    r = _api_fewshot_delete("neurips", "../../../etc/passwd")
    # After _safe_rubric_id, example_id becomes "etcpasswd". That file doesn't
    # exist, so no files are removed (no escape occurred).
    assert r.get("removed", []) == []
    # Verify original example survived.
    assert _api_fewshot_list("neurips")["count"] == 1


# ─── round-trip ────────────────────────────────────────────────────

def test_upload_then_delete_roundtrip():
    _api_fewshot_upload("neurips", {
        "example_id": "rt_test",
        "review_json": json.dumps({"overall": 7, "decision": "accept"}),
        "paper_txt": "excerpt",
    })
    assert any(e["id"] == "rt_test" for e in _api_fewshot_list("neurips")["examples"])
    rm = _api_fewshot_delete("neurips", "rt_test")
    assert "rt_test.json" in rm["removed"]
    assert not any(e["id"] == "rt_test" for e in _api_fewshot_list("neurips")["examples"])
