"""Unit tests for ari/viz/api_paperbench.py — PaperBench GUI backend.

Covers paper registry CRUD, license classification, run-launch validation,
and cost estimation. The HTTP dispatch layer in routes.py is exercised
indirectly via the dispatch-string assertions; full HTTP integration
testing of the viz server lives in test_event_loop_and_csv.py and is out
of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.viz import api_paperbench as P


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Redirect the registry dir to a tmp path so tests don't touch ~/."""
    monkeypatch.setenv("ARI_PAPER_REGISTRY_DIR", str(tmp_path / "registry"))
    # Reset any jobs left over from previous tests
    P._JOBS.clear()
    yield


# ── license classification ───────────────────────────────────────────────


def test_classify_license_cc_by_is_usable():
    info = P._classify_license("CC BY 4.0")
    assert info["permissive"] is True
    assert info["redistributable"] is True
    assert info["usable"] is True
    assert "permissive" in info["note"].lower()


def test_classify_license_cc_by_nc_is_not_usable():
    """PLAN_GUI_PAPERBENCH §8#3: CC BY-NC must warn 'NOT usable' because
    ARI is intended for commercial reuse downstream. The license is
    still permissive in the academic-redistribution sense, but the
    non-commercial clause blocks ARI's intended workflow."""
    info = P._classify_license("CC BY-NC 4.0")
    assert info["permissive"] is True
    assert info["modifiable"] is False
    assert info["usable"] is False
    assert "non-commercial" in info["note"]
    assert "NOT usable" in info["note"]


def test_classify_license_unknown_is_not_usable():
    info = P._classify_license("Some Proprietary License")
    assert info["permissive"] is False
    assert info["usable"] is False
    assert "NOT usable" in info["note"]


def test_classify_license_empty_string_is_unknown():
    info = P._classify_license("")
    assert info["usable"] is False
    assert "license unknown" in info["note"]


def test_classify_license_case_insensitive():
    a = P._classify_license("CC BY 4.0")
    b = P._classify_license("cc by 4.0")
    c = P._classify_license("  cc by 4.0  ")
    assert a["usable"] is b["usable"] is c["usable"] is True


# ── paper_id normalization ───────────────────────────────────────────────


def test_normalize_paper_id_allows_safe_chars():
    assert P._normalize_paper_id("sc24-00018") == "sc24-00018"
    assert P._normalize_paper_id("paper.v2_final") == "paper.v2_final"


def test_normalize_paper_id_strips_unsafe_chars():
    assert P._normalize_paper_id("foo/bar baz!?") == "foo-bar-baz--"


def test_normalize_paper_id_empty_yields_random():
    a = P._normalize_paper_id("")
    b = P._normalize_paper_id("")
    assert a != b
    assert len(a) == 12


def test_normalize_paper_id_truncates_to_64():
    long_id = "a" * 100
    assert len(P._normalize_paper_id(long_id)) == 64


# ── list / import / delete / patch round-trip ─────────────────────────────


def test_list_papers_empty_initially():
    res = P._api_list_papers()
    assert res == {"papers": []}


def test_import_paper_writes_manifest_and_returns_entry():
    res = P._api_import_paper({
        "source_type": "arxiv",
        "source": "2404.14193",
        "title": "LLAMP: Assessing Network Latency Tolerance",
        "license": "CC BY 4.0",
        "authors": ["A", "B"],
        "year": 2024,
        "artifact_url": "https://github.com/spcl/llamp",
    })
    assert "error" not in res
    assert res["paper_id"] == "2404.14193"
    assert res["title"] == "LLAMP: Assessing Network Latency Tolerance"
    assert res["license"] == "cc by 4.0"
    assert res["license_assessment"]["usable"] is True

    # Round-trip through manifest:
    listed = P._api_list_papers()["papers"]
    assert len(listed) == 1
    assert listed[0]["paper_id"] == "2404.14193"


def test_import_paper_rejects_missing_fields():
    bad = P._api_import_paper({"source_type": "arxiv"})
    assert "error" in bad
    assert "source" in bad["error"] or "title" in bad["error"]


def test_import_paper_rejects_unknown_source_type():
    res = P._api_import_paper({
        "source_type": "twitter",  # nope
        "source": "x",
        "title": "y",
    })
    assert "error" in res
    assert "source_type" in res["error"]


def test_import_paper_blocks_duplicate_without_overwrite():
    payload = {
        "source_type": "arxiv",
        "source": "2404.14193",
        "title": "LLAMP",
        "license": "CC BY 4.0",
    }
    P._api_import_paper(payload)
    res = P._api_import_paper(payload)
    assert "error" in res
    assert "already registered" in res["error"]
    # With overwrite=True, succeeds
    payload2 = dict(payload, overwrite=True, title="LLAMP v2")
    res2 = P._api_import_paper(payload2)
    assert "error" not in res2
    assert res2["title"] == "LLAMP v2"
    # Manifest still has exactly 1 entry
    assert len(P._api_list_papers()["papers"]) == 1


def test_import_paper_copies_pdf_when_pdf_path_given(tmp_path):
    src = tmp_path / "src.pdf"
    src.write_bytes(b"%PDF-1.4\n...")
    res = P._api_import_paper({
        "source_type": "upload",
        "source": "local-upload",
        "title": "Local Paper",
        "license": "CC BY 4.0",
        "paper_id": "loc-01",
        "pdf_path": str(src),
    })
    assert "error" not in res
    copied = Path(res["registry_dir"]) / "paper.pdf"
    assert copied.is_file()
    assert copied.read_bytes() == src.read_bytes()


def test_delete_paper_removes_manifest_entry_and_dir():
    P._api_import_paper({
        "source_type": "arxiv", "source": "x", "title": "X",
        "license": "MIT", "paper_id": "p1",
    })
    paper_dir = P._papers_dir() / "p1"
    assert paper_dir.is_dir()
    res = P._api_delete_paper("p1")
    assert res["deleted"] is True
    assert not paper_dir.exists()
    assert P._api_list_papers()["papers"] == []


def test_delete_paper_idempotent_when_missing():
    res = P._api_delete_paper("no-such-id")
    assert res["deleted"] is False
    assert res["reason"] == "not found"


def test_patch_paper_metadata_updates_and_reclassifies_license():
    P._api_import_paper({
        "source_type": "arxiv", "source": "x", "title": "X",
        "license": "CC BY 4.0", "paper_id": "p2",
    })
    patched = P._api_patch_paper_metadata("p2", {
        "venue": "SC24",
        "license": "Proprietary X",  # changing license
    })
    assert "error" not in patched
    assert patched["venue"] == "SC24"
    assert patched["license"] == "proprietary x"
    assert patched["license_assessment"]["usable"] is False
    # paper_id immutable
    spoof = P._api_patch_paper_metadata("p2", {"paper_id": "evil-spoof"})
    assert spoof["paper_id"] == "p2"


def test_paper_license_endpoint_returns_assessment():
    P._api_import_paper({
        "source_type": "arxiv", "source": "x", "title": "X",
        "license": "CC BY 4.0", "paper_id": "p3",
    })
    info = P._api_paper_license("p3")
    assert info["usable"] is True


def test_paper_license_endpoint_missing_paper():
    info = P._api_paper_license("nope")
    assert "error" in info


# ── launch + cost estimate ───────────────────────────────────────────────


def test_launch_dry_run_returns_cost_estimate():
    P._api_import_paper({
        "source_type": "arxiv", "source": "x", "title": "X",
        "license": "MIT", "paper_id": "p4",
    })
    res = P._api_launch_run({
        "paper_ids": ["p4"],
        "rubric_config": {"two_stage": True},
        "reproduce_config": {"time_limit_sec": 3600},
        "judge_config": {"n_runs": 1},
        "dry_run": True,
    })
    assert res["dry_run"] is True
    assert res["estimated_cost"]["llm_cost_usd"] > 0
    assert res["estimated_cost"]["wall_time_sec"] > 0
    assert res["papers"] == 1


def test_launch_creates_one_job_per_paper():
    for pid in ("a", "b"):
        P._api_import_paper({
            "source_type": "arxiv", "source": pid, "title": pid,
            "license": "MIT", "paper_id": pid,
        })
    res = P._api_launch_run({
        "paper_ids": ["a", "b"],
        "rubric_config": {},
        "reproduce_config": {"time_limit_sec": 3600},
        "judge_config": {"n_runs": 1},
    })
    assert res["dry_run"] is False
    assert len(res["job_ids"]) == 2
    for jid in res["job_ids"]:
        snap = P._api_run_status(jid)
        assert snap["status"] == "queued"
        assert snap["paper_id"] in {"a", "b"}


def test_launch_rejects_unknown_paper_id():
    res = P._api_launch_run({"paper_ids": ["ghost"], "dry_run": False})
    assert "error" in res
    assert "not in registry" in res["error"]


def test_launch_rejects_empty_paper_ids():
    res = P._api_launch_run({"paper_ids": [], "dry_run": False})
    assert "error" in res


def test_run_results_unavailable_until_completed():
    P._api_import_paper({
        "source_type": "arxiv", "source": "p5", "title": "P5",
        "license": "MIT", "paper_id": "p5",
    })
    r = P._api_launch_run({
        "paper_ids": ["p5"],
        "reproduce_config": {"time_limit_sec": 60},
    })
    jid = r["job_ids"][0]
    res = P._api_run_results(jid)
    assert "error" in res
    assert res["status"] == "queued"

    # Simulate worker progress + completion
    P._set_job_field(jid, status="completed", results={"score": 0.42})
    res2 = P._api_run_results(jid)
    assert res2 == {"score": 0.42}


def test_cost_estimate_scales_with_n_runs():
    base = P._api_cost_estimate({
        "rubric_config": {"two_stage": True},
        "reproduce_config": {"time_limit_sec": 3600},
        "judge_config": {"n_runs": 1},
    })
    n5 = P._api_cost_estimate({
        "rubric_config": {"two_stage": True},
        "reproduce_config": {"time_limit_sec": 3600},
        "judge_config": {"n_runs": 5},
    })
    # judge wall_time + cost increase linearly with n_runs
    assert n5["breakdown"]["judge"]["wall_time_sec"] == 5 * base["breakdown"]["judge"]["wall_time_sec"]
    assert n5["breakdown"]["judge"]["cost_usd"] == 5 * base["breakdown"]["judge"]["cost_usd"]


def test_cost_estimate_honors_reproduce_time_limit():
    short = P._api_cost_estimate({
        "reproduce_config": {"time_limit_sec": 600},
    })
    long = P._api_cost_estimate({
        "reproduce_config": {"time_limit_sec": 12 * 3600},
    })
    assert long["wall_time_sec"] > short["wall_time_sec"]


# ── manifest persistence + reload ────────────────────────────────────────


# ── Job log buffer + SSE primitives ──────────────────────────────────────


def test_append_job_log_records_to_buffer():
    P._api_import_paper({
        "source_type": "arxiv", "source": "log1", "title": "L",
        "license": "MIT", "paper_id": "log1",
    })
    r = P._api_launch_run({"paper_ids": ["log1"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    P.append_job_log(jid, "starting rubric gen")
    P.append_job_log(jid, "done", level="success")
    snap = P._api_run_status(jid)
    assert len(snap["logs"]) == 2
    assert snap["logs"][0]["msg"] == "starting rubric gen"
    assert snap["logs"][1]["level"] == "success"


def test_append_job_log_silent_for_unknown_job():
    """Calling append on a non-existent job must NOT raise — the worker
    code may race with job teardown."""
    P.append_job_log("ghost-id", "this should be dropped")
    # No exception, no side effect


def test_job_logs_since_returns_slice():
    P._api_import_paper({
        "source_type": "arxiv", "source": "log2", "title": "L2",
        "license": "MIT", "paper_id": "log2",
    })
    r = P._api_launch_run({"paper_ids": ["log2"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    for i in range(5):
        P.append_job_log(jid, f"line {i}")
    assert len(P._job_logs_since(jid, 0)) == 5
    assert len(P._job_logs_since(jid, 3)) == 2
    assert P._job_logs_since(jid, 3)[0]["msg"] == "line 3"


def test_job_logs_buffer_capped_at_2000():
    P._api_import_paper({
        "source_type": "arxiv", "source": "log3", "title": "L3",
        "license": "MIT", "paper_id": "log3",
    })
    r = P._api_launch_run({"paper_ids": ["log3"], "reproduce_config": {}})
    jid = r["job_ids"][0]
    for i in range(2500):
        P.append_job_log(jid, f"line {i}")
    snap = P._api_run_status(jid)
    assert len(snap["logs"]) == 2000
    # Oldest entries dropped; tail is preserved
    assert snap["logs"][-1]["msg"] == "line 2499"


# ── arXiv ID normalization + auto-fetch ──────────────────────────────────


def test_normalize_arxiv_id_new_style():
    # YYMM.NNNN (4-digit suffix, pre-2015)
    assert P._normalize_arxiv_id("2404.1419") == "2404.1419"
    # YYMM.NNNNN (5-digit suffix, post-2015)
    assert P._normalize_arxiv_id("2404.14193") == "2404.14193"
    assert P._normalize_arxiv_id("2404.14193v2") == "2404.14193"
    assert P._normalize_arxiv_id("arxiv:2404.14193") == "2404.14193"


def test_normalize_arxiv_id_legacy_style():
    assert P._normalize_arxiv_id("cs.LG/0102030") == "cs.LG/0102030"
    assert P._normalize_arxiv_id("hep-th/9901001") == "hep-th/9901001"


def test_normalize_arxiv_id_rejects_garbage():
    assert P._normalize_arxiv_id("") is None
    assert P._normalize_arxiv_id("not-an-id") is None
    assert P._normalize_arxiv_id("10.1109/SC.2024.42") is None  # DOI, not arXiv
    # Suffix length 6 is outside arXiv's spec (max 5 digits)
    assert P._normalize_arxiv_id("2404.123456") is None


_ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>LLAMP: assessing latency tolerance</title>
    <summary>An MPI / network-latency-tolerance benchmark.</summary>
    <published>2024-04-22T00:00:00Z</published>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2404.14193v1.pdf"/>
  </entry>
</feed>
"""


def test_api_arxiv_fetch_returns_normalised_metadata(monkeypatch):
    """End-to-end: parse a synthetic Atom feed via the public endpoint."""
    class _FakeResp:
        status = 200
        def __init__(self, body): self._body = body
        def read(self): return self._body.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *args): return None

    def _fake_urlopen(url, timeout=None):
        assert "id_list=2404.14193" in url
        return _FakeResp(_ATOM_FIXTURE)

    monkeypatch.setattr(P.urllib.request, "urlopen", _fake_urlopen)
    res = P._api_arxiv_fetch("2404.14193v1")
    assert "error" not in res
    assert res["arxiv_id"] == "2404.14193"
    assert res["title"] == "LLAMP: assessing latency tolerance"
    assert res["authors"] == ["Alice", "Bob"]
    assert res["year"] == 2024
    assert res["license"] == "arXiv non-exclusive"
    assert res["license_assessment"]["usable"] is True
    assert res["pdf_url"].endswith("2404.14193v1.pdf")
    assert res["abs_url"] == "https://arxiv.org/abs/2404.14193"


def test_api_arxiv_fetch_rejects_bad_id():
    res = P._api_arxiv_fetch("not-a-valid-id")
    assert "error" in res
    assert "not a valid arXiv id" in res["error"]


def test_api_arxiv_fetch_handles_network_failure(monkeypatch):
    import urllib.error
    def _fail_urlopen(url, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(P.urllib.request, "urlopen", _fail_urlopen)
    res = P._api_arxiv_fetch("2404.14193")
    assert "error" in res
    assert "arXiv fetch failed" in res["error"]


def test_run_report_blocked_when_job_not_completed():
    P._api_import_paper({
        "source_type": "arxiv", "source": "pa", "title": "P", "license": "MIT",
        "paper_id": "pa",
    })
    r = P._api_launch_run({"paper_ids": ["pa"], "reproduce_config": {"time_limit_sec": 60}})
    jid = r["job_ids"][0]
    res = P._api_run_report(jid, {})
    assert "error" in res
    assert res["status"] == "queued"


def test_run_report_invokes_renderer(tmp_path, monkeypatch):
    """When the job is completed and has a checkpoint_dir, the endpoint
    delegates to paperbench_report.generate_paper_report and returns the
    download_urls map."""
    P._api_import_paper({
        "source_type": "arxiv", "source": "pb", "title": "PB",
        "license": "MIT", "paper_id": "pb",
    })
    r = P._api_launch_run({"paper_ids": ["pb"], "reproduce_config": {"time_limit_sec": 60}})
    jid = r["job_ids"][0]
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    P._set_job_field(jid, status="completed", checkpoint_dir=str(ckpt))

    out_root = tmp_path / "report-out"
    res = P._api_run_report(jid, {
        "languages": ["en"],
        "formats": ["tex"],
        "output_root": str(out_root),
    })
    assert res.get("status") == "ok"
    assert res["job_id"] == jid
    # paperbench_report wrote at least main.tex
    assert (out_root / "en" / "main.tex").is_file()
    assert "en/tex" in res["download_urls"]


def test_run_report_unknown_job():
    res = P._api_run_report("nope", {})
    assert "error" in res
    assert res["job_id"] == "nope"


def test_manifest_is_jsonl_one_object_per_line(tmp_path):
    P._api_import_paper({
        "source_type": "arxiv", "source": "a", "title": "A",
        "license": "MIT", "paper_id": "a",
    })
    P._api_import_paper({
        "source_type": "arxiv", "source": "b", "title": "B",
        "license": "CC BY 4.0", "paper_id": "b",
    })
    raw = P._manifest_path().read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        obj = json.loads(ln)
        assert "paper_id" in obj


def test_registry_root_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_PAPER_REGISTRY_DIR", str(tmp_path / "custom"))
    assert P._registry_root() == (tmp_path / "custom").resolve()
