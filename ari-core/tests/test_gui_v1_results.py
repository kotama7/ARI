"""Tests for the ``/api/v1`` results / EAR read models (gui_refresh task 07
Wave 4d — plan 07 §Evidence, Results, and PaperBench).

``GET /api/v1/runs/{run_id}/results`` (paper/review/ORS/EAR presence +
bounded scalars) and ``GET /api/v1/runs/{run_id}/ear`` (listing metadata +
publish lineage scalars, no file contents) over the deterministic
``run_fixture_factory`` variants: bare run / reviewed / ORS-graded /
EAR-published.  Truth rules pinned here: absent artifacts are never
fabricated into empty-but-healthy scalars, parse failures degrade (200 +
``degraded_reasons``) instead of 500ing, the ORS verdict is byte-consistent
with the legacy ``ari.viz.ear._synth_repro_report_from_ors`` synthesis, and
GETs are side-effect-free.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from ari.viz import api_state
from ari.viz.v1 import results as v1_results
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


_factory = _load_factory()
make_run_checkpoint = _factory.make_run_checkpoint
EAR_STAGES = _factory.EAR_STAGES

RUN_ID = "20260723000000_resultsfx"
_REQUEST_ID_RE = re.compile(r"^req-[0-9a-f]{12}$")


@pytest.fixture
def ckpt_base(tmp_path, monkeypatch):
    """Empty search base; each test writes its own fixture variant."""
    base = tmp_path / "checkpoints"
    base.mkdir()
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    return base


def _results(run_id: str = RUN_ID) -> dict:
    return dispatch("GET", f"/api/v1/runs/{run_id}/results")


def _ear(run_id: str = RUN_ID) -> dict:
    return dispatch("GET", f"/api/v1/runs/{run_id}/ear")


# ── bare run: honest absence everywhere ──────────────────────────────────


def test_bare_run_reports_all_absent_flags(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0)
    r = _results()
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    assert _REQUEST_ID_RE.match(r["request_id"])
    assert r["paper"] == {"pdf_present": False, "tex_present": False}
    assert r["review"]["report_present"] is False
    # Absent report ⇒ every scalar stays None — never fabricated zeros.
    assert r["review"]["overall_score"] is None
    assert r["review"]["decision"] is None
    assert r["review"]["dimensions"] == []
    assert r["ors"]["chain_present"] is False
    assert r["ors"]["verdict"] is None
    assert r["ear"] == {
        "present": False,
        "curated": False,
        "published": False,
        "visibility": None,
        "visibility_source": None,
        "dry_run": None,
        "promoted_at": None,
    }
    assert r["degraded_reasons"] == []


def test_bare_run_ear_endpoint_reports_absence(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0)
    r = _ear()
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    assert r["present"] is False
    assert r["publish_yaml_present"] is False
    assert r["files"] == [] and r["file_count"] == 0
    assert r["truncated"] is False
    assert r["curated"]["manifest_present"] is False
    assert r["published"]["record_present"] is False
    assert r["degraded_reasons"] == []


# ── reviewed variant: paper + review scalars ─────────────────────────────


def test_reviewed_run_serves_review_scalars_and_paper_flags(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, paper=True, review=True)
    on_disk = json.loads(
        (ckpt_base / RUN_ID / "review_report.json").read_text(encoding="utf-8")
    )
    r = _results()
    assert r["paper"] == {"pdf_present": True, "tex_present": True}
    rv = r["review"]
    assert rv["report_present"] is True
    assert rv["overall_score"] == on_disk["overall_score"]
    assert rv["abstract_score"] == on_disk["abstract_score"]
    assert rv["body_score"] == on_disk["body_score"]
    assert rv["decision"] == on_disk["decision"]
    assert rv["confidence"] == on_disk["confidence"]
    assert rv["rubric_id"] == "neurips"
    assert [d["name"] for d in rv["dimensions"]] == ["soundness", "novelty"]
    for dim, src in zip(rv["dimensions"], on_disk["score_dimensions"]):
        assert dim["value"] == src["value"]
        assert (dim["scale_min"], dim["scale_max"]) == (0.0, 10.0)
    assert r["degraded_reasons"] == []


def test_legacy_review_score_fallbacks(ckpt_base):
    """Pre-rubric reports (score / scores.abstract / scores.body) pass
    through the ReviewScoresSection fallback chain."""
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0)
    (ckpt_base / RUN_ID / "review_report.json").write_text(
        json.dumps({"score": 7.5, "scores": {"abstract": 6, "body": 8}}),
        encoding="utf-8",
    )
    rv = _results()["review"]
    assert rv["report_present"] is True
    assert rv["overall_score"] == 7.5
    assert rv["abstract_score"] == 6.0
    assert rv["body_score"] == 8.0
    assert rv["rubric_id"] is None and rv["dimensions"] == []


def test_corrupt_review_report_degrades_not_500(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0)
    (ckpt_base / RUN_ID / "review_report.json").write_text("{torn", encoding="utf-8")
    r = _results()
    assert "_status" not in r  # 200, not an error envelope
    # Presence and readability are separate facts.
    assert r["review"]["report_present"] is True
    assert r["review"]["overall_score"] is None
    assert any("review_report.json" in x for x in r["degraded_reasons"])


# ── ORS-graded variant: chain flags + synth-parity verdict ───────────────


def test_ors_graded_run_matches_legacy_synthesis(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ors=True)
    grade = json.loads(
        (ckpt_base / RUN_ID / "ors_grade.json").read_text(encoding="utf-8")
    )
    r = _results()["ors"]
    assert r["chain_present"] is True
    assert r["rubric_present"] is True
    assert r["replicator_present"] is True
    assert r["seed_present"] is False  # factory writes no ors_seed.json
    assert r["phase1_present"] is True
    assert r["grade_present"] is True
    assert r["ors_score"] == round(grade["ors_score"], 4)
    assert r["raw_score"] == round(grade["raw_score"], 4)
    assert r["passed_leaves"] == 3 and r["total_leaves"] == 4
    assert r["judge_model"] == "claude-haiku-4-5"
    # Verdict parity with the legacy ear.py synthesis (READ-ONLY reuse).
    from ari.viz.ear import _synth_repro_report_from_ors

    synth = _synth_repro_report_from_ors(ckpt_base / RUN_ID)
    assert r["verdict"] == synth["verdict"]
    assert r["summary"] == synth["summary"]
    assert r["verdict"] in ("REPRODUCED", "PARTIAL")  # factory score >= 0.5


def test_ors_intermediate_chain_reports_pending_not_fabricated(ckpt_base):
    """A replicator-only chain (no grade yet) is PENDING with no scores."""
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0)
    (ckpt_base / RUN_ID / "ors_replicator.json").write_text(
        json.dumps({"populated": True, "files": ["reproduce.sh"]}),
        encoding="utf-8",
    )
    r = _results()["ors"]
    assert r["chain_present"] is True and r["replicator_present"] is True
    assert r["grade_present"] is False
    assert r["verdict"] == "PENDING"
    assert r["ors_score"] is None and r["passed_leaves"] is None


# ── EAR lineage variants: bare / curated / published / promoted ──────────


def test_ear_stage_vocabulary_is_pinned():
    assert EAR_STAGES == ("bare", "curated", "published", "promoted")


def test_ear_bare_stage(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="bare")
    r = _results()["ear"]
    assert r["present"] is True
    assert r["curated"] is False and r["published"] is False
    assert r["visibility"] is None and r["visibility_source"] is None

    e = _ear()
    assert e["present"] is True and e["publish_yaml_present"] is True
    assert [f["path"] for f in e["files"]] == [
        "README.md", "publish.yaml", "reproduce.sh",
    ]
    assert all(f["kind"] == "file" and f["size"] > 0 for f in e["files"])
    assert e["file_count"] == 3 and e["truncated"] is False


def test_ear_curated_stage_serves_bundle_digest(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="curated")
    manifest = json.loads(
        (ckpt_base / RUN_ID / "ear_published" / "manifest.lock").read_text(
            encoding="utf-8"
        )
    )
    r = _results()["ear"]
    assert r["curated"] is True and r["published"] is False
    # Declared (curate-time) visibility, attributed to the manifest.
    assert r["visibility"] == "staged"
    assert r["visibility_source"] == "manifest_lock"

    c = _ear()["curated"]
    assert c["manifest_present"] is True
    assert c["bundle_sha256"] == manifest["bundle_sha256"]
    assert c["file_count"] == 2 and c["excluded_count"] == 1
    assert c["visibility"] == "staged"
    assert c["created_at"] == "2026-07-23T00:00:00Z"
    # Digest scalars only — the manifest's file entries are never inlined.
    assert "files" not in c


def test_ear_published_and_promoted_stages(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="published")
    r = _results()["ear"]
    assert r["curated"] is True and r["published"] is True
    assert r["visibility"] == "staged"
    assert r["visibility_source"] == "publish_record"
    assert r["dry_run"] is False and r["promoted_at"] is None
    p = _ear()["published"]
    assert p["record_present"] is True
    assert p["backend"] == "local_tarball"
    assert p["ref"].startswith("ear://fixture/")
    assert p["bundle_sha256"] == _ear()["curated"]["bundle_sha256"]
    assert p["timestamp"] == "2026-07-23T00:00:00Z"

    # Promote flips visibility to public and stamps promoted_at.
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="promoted")
    r2 = _results()["ear"]
    assert r2["visibility"] == "public"
    assert r2["promoted_at"] == "2026-07-23T01:00:00Z"


def test_corrupt_manifest_lock_degrades_not_500(ckpt_base):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="curated")
    (ckpt_base / RUN_ID / "ear_published" / "manifest.lock").write_text(
        "{torn", encoding="utf-8"
    )
    r = _results()
    assert "_status" not in r
    assert r["ear"]["curated"] is True  # the artifact exists
    assert r["ear"]["visibility"] is None  # but nothing readable is claimed
    assert any("manifest.lock" in x for x in r["degraded_reasons"])
    e = _ear()
    assert e["curated"]["manifest_present"] is True
    assert e["curated"]["bundle_sha256"] is None


def test_ear_listing_is_bounded(ckpt_base, monkeypatch):
    make_run_checkpoint(ckpt_base / RUN_ID, nodes=4, seed=0, ear="bare")
    monkeypatch.setattr(v1_results, "_MAX_EAR_FILES", 2)
    e = _ear()
    assert len(e["files"]) == 2 and e["truncated"] is True
    assert e["file_count"] == 3  # the count still covers every file


# ── error envelopes + side-effect-freeness + determinism ─────────────────


def test_unknown_run_returns_404_envelope(ckpt_base):
    for r in (_results("20990101000000_missing"), _ear("20990101000000_missing")):
        assert r["_status"] == 404
        assert r["error"]["code"] == "not_found"


def test_gets_are_side_effect_free_and_deterministic(ckpt_base):
    make_run_checkpoint(
        ckpt_base / RUN_ID, nodes=4, seed=0, paper=True, review=True,
        ors=True, ear="promoted",
    )

    def _snapshot():
        return sorted(
            (str(p), p.stat().st_mtime_ns, p.stat().st_size)
            for p in ckpt_base.rglob("*")
            if p.is_file()
        )

    before = _snapshot()
    r1, e1 = _results(), _ear()
    r2, e2 = _results(), _ear()
    assert _snapshot() == before, "results/ear GET wrote into the checkpoint"
    # Byte-stable modulo the per-request correlation id (P2).
    for a, b in ((r1, r2), (e1, e2)):
        a, b = dict(a), dict(b)
        assert a.pop("request_id") != b.pop("request_id")
        assert a == b
