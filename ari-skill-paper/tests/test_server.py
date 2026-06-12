"""Tests for the ari-skill-paper MCP server."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server import (
    TEMPLATES_DIR,
    VENUES,
    _count_pdf_pages,
    check_format,
    compile_paper,
    generate_section,
    get_template,
    list_venues,
    merge_reviews,
    paper_refine,
)


def _mock_resp(content: str):
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    return r


# --- paper_refine: S2P refiner = global role, DIFF (find/replace) output ---

@pytest.mark.asyncio
async def test_paper_refine_applies_targeted_diff_edits(tmp_path):
    tex = ("\\section{Results}\n% CLAIM:C1:NC1\n"
           "We achieve a speedup of 2x here.\n\\end{document}\n")
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    import json as _j
    edits = '```json\n[{"find": "We achieve a speedup of 2x here.", "replace": "We achieve a speedup of 2.5x here."}]\n```'
    revs = _j.dumps([{"section": "results", "instruction": "correct the speedup"}])
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp(edits)):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert out["applied_revisions"] == 1
    assert "2.5x" in out["latex"]
    assert "% CLAIM:C1:NC1" in out["latex"]          # untouched anchor preserved


@pytest.mark.asyncio
async def test_paper_refine_skips_nonunique_find(tmp_path):
    tex = "\\section{R}\n% CLAIM:C1:NC1\nThe value is X. The value is X.\n"
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    edits = '[{"find":"The value is X.","replace":"The value is Y."}]'  # occurs twice
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp(edits)):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]')
    assert out["refined"] is False            # ambiguous find -> never guessed
    assert out["applied_revisions"] == 0
    assert out["latex"] == tex                # unchanged


@pytest.mark.asyncio
async def test_paper_refine_rejects_anchor_dropping_edit(tmp_path):
    tex = "\\section{R}\nFoo % CLAIM:C1:NC1 bar baz.\n"
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    edits = '[{"find":"Foo % CLAIM:C1:NC1 bar baz.","replace":"Foo bar baz revised."}]'  # drops anchor
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp(edits)):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]')
    assert out["refined"] is False
    assert "% CLAIM:C1:NC1" in out["latex"]   # anchor never dropped


@pytest.mark.asyncio
async def test_paper_refine_uses_diff_not_full_rewrite(tmp_path):
    """Guard the S2P-faithful design: bounded diff output, not whole-document regen."""
    tex = "\\section{R}\n% CLAIM:C1:NC1\nText here.\n"
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    captured: dict = {}

    async def _cap(**kw):
        captured.update(kw)
        return _mock_resp("[]")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        await paper_refine(tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]')
    sysmsg = next(m for m in captured["messages"] if m["role"] == "system")["content"]
    assert "JSON array" in sysmsg
    assert "Do NOT rewrite the whole document" in sysmsg
    assert captured["max_tokens"] <= 8192     # bounded => no full-document regeneration


@pytest.mark.asyncio
async def test_paper_refine_applies_deterministic_substitution(tmp_path):
    # (b) an explicit `replace "X" with "Y"` review instruction is applied
    # DETERMINISTICALLY even when the LLM returns NO edits — the prior single pass
    # left such concrete overclaim fixes (e.g. the title) in place.
    import json as _j
    tex = ('\\title{Roofline/Loopline Validation}\n% CLAIM:C1:NC1\n'
           'We report results.\n\\end{document}\n')
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    revs = _j.dumps([{"section": "title",
        "instruction": 'Soften it, e.g. replace "Roofline/Loopline Validation" with "Roofline/Loopline Context".'}])
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp("[]")):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert "Roofline/Loopline Context" in out["latex"]
    assert "Roofline/Loopline Validation" not in out["latex"]
    assert out["deterministic_substitutions"] == 1
    assert out["unaddressed_substitutions"] == []
    assert "% CLAIM:C1:NC1" in out["latex"]          # anchor preserved


@pytest.mark.asyncio
async def test_paper_refine_reports_unaddressed_nonunique_substitution(tmp_path):
    # an explicit replacement whose OLD (a phrase) is NON-UNIQUE is never guessed; it
    # is REPORTED under unaddressed_substitutions rather than silently dropped.
    import json as _j
    tex = ("\\section{R}\n% CLAIM:C1:NC1\n"
           "The method is robust here. The method is robust there.\n\\end{document}\n")
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    revs = _j.dumps([{"instruction": 'replace "method is robust" with "method shows limited sensitivity"'}])
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp("[]")):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is False                    # non-unique phrase never guessed
    assert any(u["old"] == "method is robust" for u in out["unaddressed_substitutions"])


@pytest.mark.asyncio
async def test_paper_refine_expand_substitution_not_falsely_unaddressed(tmp_path):
    # regression (review finding): an EXPAND edit (OLD substring of NEW, e.g.
    # "Roofline Validation" -> "Roofline Validation Context") lands but must NOT be
    # reported unaddressed -- verify keys on the apply outcome, not `old in refined`.
    import json as _j
    tex = ("\\title{Roofline Validation}\n% CLAIM:C1:NC1\nText.\n\\end{document}\n")
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    revs = _j.dumps([{"instruction": 'replace "Roofline Validation" with "Roofline Validation Context"'}])
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp("[]")):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert "Roofline Validation Context" in out["latex"]
    assert out["deterministic_substitutions"] == 1
    assert out["unaddressed_substitutions"] == []     # applied, not falsely flagged


@pytest.mark.asyncio
async def test_paper_refine_bare_word_substitution_routed_to_llm(tmp_path):
    # review finding: a single-word OLD (no whitespace) could be globally unique by
    # accident and rewritten in the wrong span -> it is NOT a deterministic sub.
    import json as _j
    tex = ("\\title{Validation}\n% CLAIM:C2:NC2\nT.\n\\end{document}\n")
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    revs = _j.dumps([{"instruction": 'replace "Validation" with "Context"'}])
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=_mock_resp("[]")):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["deterministic_substitutions"] == 0    # bare word not auto-applied


@pytest.mark.asyncio
async def test_paper_refine_multipass_applies_across_passes(tmp_path):
    # (b) the bounded loop gives the LLM multiple passes: an edit the 2nd pass produces
    # (after the 1st changed the doc) is still applied — the old single pass missed it.
    tex = ("\\section{R}\n% CLAIM:C1:NC1\nAlpha. Beta.\n\\end{document}\n")
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    resp = [_mock_resp('[{"find":"Alpha.","replace":"Alpha-edited."}]'),
            _mock_resp('[{"find":"Beta.","replace":"Beta-edited."}]'),
            _mock_resp("[]")]
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, side_effect=resp):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]')
    assert out["refined"] is True
    assert "Alpha-edited." in out["latex"] and "Beta-edited." in out["latex"]
    assert out["applied_revisions"] == 2
    assert out["refine_passes"] == 2


# --- list_venues ---

@pytest.mark.asyncio
async def test_list_venues_returns_all():
    result = await list_venues()
    assert len(result) == 6


@pytest.mark.asyncio
async def test_list_venues_has_required_fields():
    result = await list_venues()
    for venue in result:
        assert "id" in venue
        assert "name" in venue
        assert "deadline" in venue
        assert "pages" in venue


@pytest.mark.asyncio
async def test_list_venues_contains_neurips():
    result = await list_venues()
    ids = [v["id"] for v in result]
    assert "neurips" in ids


# --- get_template ---

@pytest.mark.asyncio
async def test_get_template_neurips():
    result = await get_template("neurips")
    assert "files" in result
    assert "main.tex" in result["files"]
    assert "refs.bib" in result["files"]
    assert "\\documentclass" in result["files"]["main.tex"]


@pytest.mark.asyncio
async def test_get_template_all_venues():
    for venue in VENUES:
        result = await get_template(venue["id"])
        assert "files" in result
        assert "main.tex" in result["files"]


@pytest.mark.asyncio
async def test_get_template_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await get_template("nonexistent")


# --- generate_section ---

@pytest.mark.asyncio
async def test_generate_section_invalid_section():
    with pytest.raises(ValueError, match="Unknown section"):
        await generate_section("garbage_section", "some context", "neurips")


@pytest.mark.asyncio
async def test_generate_section_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await generate_section("introduction", "some context", "nonexistent")


@pytest.mark.asyncio
async def test_generate_section_calls_litellm():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "\\section{Introduction}\nTest content."

    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await generate_section("introduction", "We tested X and got Y.", "neurips")
        assert "latex" in result
        assert "Introduction" in result["latex"]


@pytest.mark.asyncio
async def test_generate_section_injects_sc_author_hint():
    """SC's reviewer_rubrics yaml ships an author_hint; generate_section
    must inject it into the system prompt so paper drafting is
    venue-conditioned at the same strength as peer review."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "\\section{X}\nbody"
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return mock_response

    with patch("src.server.litellm.acompletion", side_effect=_capture):
        await generate_section("introduction", "ctx", "sc")

    system_msg = next(m for m in captured["messages"] if m["role"] == "system")["content"]
    # The block header MUST appear so the LLM sees a clearly-delimited
    # venue-conditioning section.
    assert "VENUE-SPECIFIC AUTHOR GUIDANCE" in system_msg
    # SC-specific signals from sc.yaml's author_hint must be threaded in.
    assert "scaling" in system_msg.lower()
    # The drafter should also see the reviewer's score dimensions.
    assert "reproducibility" in system_msg.lower()


@pytest.mark.asyncio
async def test_generate_section_no_hint_for_venue_without_rubric():
    """Venues without a reviewer_rubrics yaml (arxiv, icpp, isc, acm)
    must still work — author_hint injection silently no-ops."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "\\section{X}\nbody"
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return mock_response

    with patch("src.server.litellm.acompletion", side_effect=_capture):
        await generate_section("introduction", "ctx", "arxiv")

    system_msg = next(m for m in captured["messages"] if m["role"] == "system")["content"]
    assert "VENUE-SPECIFIC AUTHOR GUIDANCE" not in system_msg
    # The legacy "Target venue: arXiv" weak hint must still be present.
    assert "arXiv" in system_msg


# --- compile_paper ---

@pytest.mark.asyncio
async def test_compile_paper_missing_dir():
    result = await compile_paper("/nonexistent/dir")
    assert result["success"] is False
    assert "not found" in result["log"].lower()


@pytest.mark.asyncio
async def test_compile_paper_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await compile_paper(tmpdir, "missing.tex")
        assert result["success"] is False
        assert "not found" in result["log"].lower()


# --- check_format ---

@pytest.mark.asyncio
async def test_check_format_missing_pdf():
    result = await check_format("neurips", "/nonexistent/paper.pdf")
    assert result["ok"] is False
    assert len(result["issues"]) > 0


@pytest.mark.asyncio
async def test_check_format_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await check_format("nonexistent", "/some/path.pdf")


@pytest.mark.asyncio
async def test_check_format_small_pdf():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 tiny")
        f.flush()
        result = await check_format("neurips", f.name)
        assert result["ok"] is False
        assert any("too small" in i for i in result["issues"])


# --- _count_pdf_pages ---

def test_count_pdf_pages_none_on_missing():
    result = _count_pdf_pages(Path("/nonexistent/file.pdf"))
    assert result is None


# --- template directory structure ---

def test_templates_dir_exists():
    assert TEMPLATES_DIR.is_dir()


def test_all_venue_templates_exist():
    for venue in VENUES:
        venue_dir = TEMPLATES_DIR / venue["id"]
        assert venue_dir.is_dir(), f"Missing template dir for {venue['id']}"
        assert (venue_dir / "main.tex").is_file()
        assert (venue_dir / "refs.bib").is_file()


# --- review_compiled_paper: N resolution + ensemble/meta integration ---
#
# Guards the GUI → env → skill chain: the Wizard stuffs N into
# ARI_NUM_REVIEWS_ENSEMBLE via _api_launch (covered in
# ari-core/tests/test_wizard.py); these tests verify the skill side
# consumes that env and drives run_ensemble + run_meta_review accordingly.

import json as _jsn  # noqa: E402


def _canned_review_json() -> str:
    return _jsn.dumps({
        "soundness": 3, "presentation": 3, "contribution": 3,
        "overall": 6, "confidence": 3,
        "strengths": "S", "weaknesses": "W", "questions": "Q",
        "decision": "accept",
    })


@pytest.mark.asyncio
async def test_review_compiled_paper_env_drives_n(tmp_path, monkeypatch):
    """ARI_NUM_REVIEWS_ENSEMBLE=3 must route through run_ensemble with N=3
    and trigger run_meta_review (N>1), without the caller passing N."""
    from src import server as _srv
    from src.review_engine import FewshotExample

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"A minimal but non-empty paper body for the extractor to return."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "3")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    # num_reflections=0 keeps each reviewer to a single LLM call so we can
    # count total calls deterministically: 3 ensemble + 1 meta = 4.
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    calls: list[dict] = []

    async def fake_llm(messages, temperature, model=None):
        calls.append({"temperature": temperature, "model": model})
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(tex_path=str(tex), rubric_id="neurips")

    # Ensemble ran N=3 times; meta-review aggregated → +1 call
    assert out.get("n") == 3, f"expected n=3, got {out.get('n')}"
    assert len(out.get("ensemble_reviews", [])) == 3
    assert isinstance(out.get("meta_review"), dict)
    assert len(calls) == 4
    # Temperature jitter across ensemble members (at least two distinct)
    ensemble_temps = {c["temperature"] for c in calls[:3]}
    assert len(ensemble_temps) > 1, f"expected jittered temps, got {ensemble_temps}"


@pytest.mark.asyncio
async def test_review_compiled_paper_n1_no_ensemble_or_meta(tmp_path, monkeypatch):
    """N=1 (the default) must NOT attach ensemble_reviews or meta_review —
    otherwise the frontend renders a spurious ensemble badge for a single review."""
    from src import server as _srv

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"Another minimal non-empty paper body for the extractor."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "1")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    calls: list[dict] = []

    async def fake_llm(messages, temperature, model=None):
        calls.append({"temperature": temperature, "model": model})
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(tex_path=str(tex), rubric_id="neurips")

    assert out.get("n") == 1
    assert "ensemble_reviews" not in out
    assert "meta_review" not in out
    assert len(calls) == 1  # single review, no meta aggregation


@pytest.mark.asyncio
async def test_review_compiled_paper_arg_beats_env(tmp_path, monkeypatch):
    """Explicit num_reviews_ensemble arg must override the env var."""
    from src import server as _srv

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"Non-empty body so the extractor returns text."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "5")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    async def fake_llm(messages, temperature, model=None):
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(
        tex_path=str(tex), rubric_id="neurips", num_reviews_ensemble=2,
    )
    assert out.get("n") == 2, f"arg=2 must win over env=5, got n={out.get('n')}"


# --- merge_reviews: semantic warnings must reach the refiner ---

def _write_merge_inputs(tmp_path, semantic: dict):
    import json as _j
    rr = tmp_path / "review_report.json"
    rr.write_text(_j.dumps({"scores": {}}))
    sem = tmp_path / "semantic_review.json"
    sem.write_text(_j.dumps(semantic))
    return rr, sem


@pytest.mark.asyncio
async def test_merge_reviews_forwards_warnings_as_advisory_revisions(tmp_path):
    rr, sem = _write_merge_inputs(tmp_path, {
        "status": "ok",
        "warnings": [
            {"type": "overclaim", "section": "abstract",
             "message": "The robustness wording reads broader than the tested scope."},
            {"type": "interpretation", "section": "results",
             "message": "The mechanism is asserted but not directly measured."},
        ],
        "suggested_revisions": [
            {"section": "abstract",
             "instruction": 'replace "robust" with "stable under the tested ablation"'},
        ],
    })
    out = await merge_reviews(review_report_path=str(rr), semantic_review_path=str(sem))
    revs = out["suggested_revisions"]
    from_warnings = [r for r in revs if r.get("source") == "semantic_warning"]
    assert len(from_warnings) == 2, "every counted warning must become a revision entry"
    assert {r["warning_type"] for r in from_warnings} == {"overclaim", "interpretation"}
    # paper_refine._collect harvests entries via their `instruction` key
    assert all(r.get("instruction") for r in from_warnings)
    assert from_warnings[0]["instruction"].startswith("The robustness wording")
    # the original explicit revision is still first (deterministic path priority)
    assert revs[0]["instruction"].startswith('replace "robust"')


@pytest.mark.asyncio
async def test_merge_reviews_warning_identical_to_revision_not_duplicated(tmp_path):
    instr = "Scope the conclusion to the tested configurations."
    rr, sem = _write_merge_inputs(tmp_path, {
        "status": "ok",
        "warnings": [{"type": "overgeneralization", "section": "conclusion",
                      "message": instr}],
        "suggested_revisions": [{"section": "conclusion", "instruction": instr}],
    })
    out = await merge_reviews(review_report_path=str(rr), semantic_review_path=str(sem))
    matching = [r for r in out["suggested_revisions"]
                if (r.get("instruction") or "").strip() == instr]
    assert len(matching) == 1, "exact-duplicate warning text must not be re-added"


@pytest.mark.asyncio
async def test_merge_reviews_warning_entries_collected_by_paper_refine(tmp_path):
    rr, sem = _write_merge_inputs(tmp_path, {
        "status": "ok",
        "warnings": [{"type": "overclaim", "section": "abstract",
                      "message": "Qualify the headline claim to the tested setup."}],
        "suggested_revisions": [],
    })
    out = await merge_reviews(review_report_path=str(rr), semantic_review_path=str(sem))
    merged = tmp_path / "review_merge_log.json"
    import json as _j
    merged.write_text(_j.dumps(out))

    tex = "\\section{Abstract}\n% CLAIM:C1:NC1\nOur kernel is fast.\n\\end{document}\n"
    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    edits = ('```json\n[{"find": "Our kernel is fast.", '
             '"replace": "Our kernel is fast in the tested setup."}]\n```')
    with patch("src.server.litellm.acompletion", new_callable=AsyncMock,
               return_value=_mock_resp(edits)) as mocked:
        ref = await paper_refine(tex_path=str(p), merged_review_path=str(merged))
    assert ref["refined"] is True, (
        "a warning-only review must still drive a refine pass (was: no-op)"
    )
    # the warning text reached the refiner prompt
    sent = mocked.call_args.kwargs.get("messages") or mocked.call_args.args[0]
    joined = " ".join(str(m) for m in sent)
    assert "Qualify the headline claim" in joined
