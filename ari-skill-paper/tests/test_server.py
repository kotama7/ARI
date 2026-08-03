"""Tests for the ari-skill-paper MCP server."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari.public.paper import parse_paper_model_call_batch

from src.server import (
    TEMPLATES_DIR,
    VENUES,
    _count_pdf_pages,
    check_format,
    compile_paper,
    get_template,
    link_paper_claims,
    list_venues,
    merge_reviews,
    paper_refine,
)


def _mock_resp(content: str):
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    return r


def test_paper_and_rubric_models_have_independent_phase_overrides(monkeypatch):
    from src import server as _srv

    monkeypatch.setenv("ARI_LLM_MODEL", "shared")
    monkeypatch.setenv("ARI_MODEL_PAPER", "openai/claude-cli:sonnet")
    monkeypatch.setenv("ARI_MODEL_RUBRIC", "openai/codex-cli:gpt-5-codex")
    assert _srv._get_model() == "openai/claude-cli:sonnet"
    assert _srv._get_model("rubric") == "openai/codex-cli:gpt-5-codex"


@pytest.mark.asyncio
async def test_panel_seed_reaches_rubric_completion(monkeypatch):
    from src import server as _srv

    captured = {}

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return _mock_resp("{}")

    monkeypatch.setenv("ARI_MODEL_RUBRIC", "openai/codex-cli")
    monkeypatch.setenv("ARI_PANEL_SEED", "43")
    monkeypatch.setattr(_srv.litellm, "acompletion", fake_completion)
    await _srv._litellm_caller(
        [{"role": "user", "content": "review"}], 0.2
    )
    assert captured["model"] == "openai/codex-cli"
    assert captured["seed"] == 43


# --- paper_refine: S2P refiner = global role, DIFF (find/replace) output ---


@pytest.mark.asyncio
async def test_paper_refine_applies_targeted_diff_edits(tmp_path):
    tex = (
        "\\section{Results}\n% CLAIM:C1:NC1\n"
        "We achieve a speedup of 2x here.\n\\end{document}\n"
    )
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    import json as _j

    edits = '```json\n[{"find": "We achieve a speedup of 2x here.", "replace": "We achieve a speedup of 2.5x here."}]\n```'
    revs = _j.dumps([{"section": "results", "instruction": "correct the speedup"}])
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp(edits),
    ):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert out["applied_revisions"] == 1
    assert "2.5x" in out["latex"]
    assert "% CLAIM:C1:NC1" in out["latex"]  # untouched anchor preserved
    batch = parse_paper_model_call_batch(
        json.loads((tmp_path / out["refinement_call_path"]).read_text())
    )
    assert [call.call_id for call in batch.calls] == [
        "refinement-001",
        "refinement-002",
    ]
    assert all(
        (tmp_path / call.prompt_artifact.relative_path).is_file()
        and (tmp_path / call.raw_response_artifact.relative_path).is_file()
        for call in batch.calls
    )


@pytest.mark.asyncio
async def test_paper_refine_skips_nonunique_find(tmp_path):
    tex = "\\section{R}\n% CLAIM:C1:NC1\nThe value is X. The value is X.\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    edits = '[{"find":"The value is X.","replace":"The value is Y."}]'  # occurs twice
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp(edits),
    ):
        out = await paper_refine(
            tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]'
        )
    assert out["refined"] is False  # ambiguous find -> never guessed
    assert out["applied_revisions"] == 0
    assert out["latex"] == tex  # unchanged


@pytest.mark.asyncio
async def test_paper_refine_rejects_anchor_dropping_edit(tmp_path):
    tex = "\\section{R}\nFoo % CLAIM:C1:NC1 bar baz.\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    edits = '[{"find":"Foo % CLAIM:C1:NC1 bar baz.","replace":"Foo bar baz revised."}]'  # drops anchor
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp(edits),
    ):
        out = await paper_refine(
            tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]'
        )
    assert out["refined"] is False
    assert "% CLAIM:C1:NC1" in out["latex"]  # anchor never dropped


@pytest.mark.asyncio
async def test_paper_refine_uses_diff_not_full_rewrite(tmp_path):
    """Guard the S2P-faithful design: bounded diff output, not whole-document regen."""
    tex = "\\section{R}\n% CLAIM:C1:NC1\nText here.\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    captured: dict = {}

    async def _cap(**kw):
        captured.update(kw)
        return _mock_resp("[]")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        await paper_refine(
            tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]'
        )
    sysmsg = next(m for m in captured["messages"] if m["role"] == "system")["content"]
    assert "JSON array" in sysmsg
    assert "Do NOT rewrite the whole document" in sysmsg
    assert captured["max_tokens"] <= 8192  # bounded => no full-document regeneration


@pytest.mark.asyncio
async def test_paper_refine_applies_deterministic_substitution(tmp_path):
    # (b) an explicit `replace "X" with "Y"` review instruction is applied
    # DETERMINISTICALLY even when the LLM returns NO edits — the prior single pass
    # left such concrete overclaim fixes (e.g. the title) in place.
    import json as _j

    tex = (
        "\\title{Roofline/Loopline Validation}\n% CLAIM:C1:NC1\n"
        "We report results.\n\\end{document}\n"
    )
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    revs = _j.dumps(
        [
            {
                "section": "title",
                "instruction": 'Soften it, e.g. replace "Roofline/Loopline Validation" with "Roofline/Loopline Context".',
            }
        ]
    )
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp("[]"),
    ):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert "Roofline/Loopline Context" in out["latex"]
    assert "Roofline/Loopline Validation" not in out["latex"]
    assert out["deterministic_substitutions"] == 1
    assert out["unaddressed_substitutions"] == []
    assert "% CLAIM:C1:NC1" in out["latex"]  # anchor preserved


@pytest.mark.asyncio
async def test_paper_refine_reports_unaddressed_nonunique_substitution(tmp_path):
    # an explicit replacement whose OLD (a phrase) is NON-UNIQUE is never guessed; it
    # is REPORTED under unaddressed_substitutions rather than silently dropped.
    import json as _j

    tex = (
        "\\section{R}\n% CLAIM:C1:NC1\n"
        "The method is robust here. The method is robust there.\n\\end{document}\n"
    )
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    revs = _j.dumps(
        [
            {
                "instruction": 'replace "method is robust" with "method shows limited sensitivity"'
            }
        ]
    )
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp("[]"),
    ):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is False  # non-unique phrase never guessed
    assert any(u["old"] == "method is robust" for u in out["unaddressed_substitutions"])


@pytest.mark.asyncio
async def test_paper_refine_expand_substitution_not_falsely_unaddressed(tmp_path):
    # regression (review finding): an EXPAND edit (OLD substring of NEW, e.g.
    # "Roofline Validation" -> "Roofline Validation Context") lands but must NOT be
    # reported unaddressed -- verify keys on the apply outcome, not `old in refined`.
    import json as _j

    tex = "\\title{Roofline Validation}\n% CLAIM:C1:NC1\nText.\n\\end{document}\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    revs = _j.dumps(
        [
            {
                "instruction": 'replace "Roofline Validation" with "Roofline Validation Context"'
            }
        ]
    )
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp("[]"),
    ):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["refined"] is True
    assert "Roofline Validation Context" in out["latex"]
    assert out["deterministic_substitutions"] == 1
    assert out["unaddressed_substitutions"] == []  # applied, not falsely flagged


@pytest.mark.asyncio
async def test_paper_refine_bare_word_substitution_routed_to_llm(tmp_path):
    # review finding: a single-word OLD (no whitespace) could be globally unique by
    # accident and rewritten in the wrong span -> it is NOT a deterministic sub.
    import json as _j

    tex = "\\title{Validation}\n% CLAIM:C2:NC2\nT.\n\\end{document}\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    revs = _j.dumps([{"instruction": 'replace "Validation" with "Context"'}])
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp("[]"),
    ):
        out = await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert out["deterministic_substitutions"] == 0  # bare word not auto-applied


@pytest.mark.asyncio
async def test_paper_refine_multipass_applies_across_passes(tmp_path):
    # (b) the bounded loop gives the LLM multiple passes: an edit the 2nd pass produces
    # (after the 1st changed the doc) is still applied — the old single pass missed it.
    tex = "\\section{R}\n% CLAIM:C1:NC1\nAlpha. Beta.\n\\end{document}\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    resp = [
        _mock_resp('[{"find":"Alpha.","replace":"Alpha-edited."}]'),
        _mock_resp('[{"find":"Beta.","replace":"Beta-edited."}]'),
        _mock_resp("[]"),
    ]
    with patch(
        "src.server.litellm.acompletion", new_callable=AsyncMock, side_effect=resp
    ):
        out = await paper_refine(
            tex_path=str(p), suggested_revisions_json='[{"instruction":"x"}]'
        )
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
    return _jsn.dumps(
        {
            "soundness": 3,
            "presentation": 3,
            "contribution": 3,
            "overall": 6,
            "confidence": 3,
            "strengths": "S",
            "weaknesses": "W",
            "questions": "Q",
            "decision": "accept",
        }
    )


@pytest.mark.asyncio
async def test_review_compiled_paper_env_drives_n(tmp_path, monkeypatch):
    """ARI_NUM_REVIEWS_ENSEMBLE=3 must route through run_ensemble with N=3
    and trigger run_meta_review (N>1), without the caller passing N."""
    from src import server as _srv

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
        tex_path=str(tex),
        rubric_id="neurips",
        num_reviews_ensemble=2,
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
    rr, sem = _write_merge_inputs(
        tmp_path,
        {
            "status": "ok",
            "warnings": [
                {
                    "type": "overclaim",
                    "section": "abstract",
                    "message": "The robustness wording reads broader than the tested scope.",
                },
                {
                    "type": "interpretation",
                    "section": "results",
                    "message": "The mechanism is asserted but not directly measured.",
                },
            ],
            "suggested_revisions": [
                {
                    "section": "abstract",
                    "instruction": 'replace "robust" with "stable under the tested ablation"',
                },
            ],
        },
    )
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
    rr, sem = _write_merge_inputs(
        tmp_path,
        {
            "status": "ok",
            "warnings": [
                {
                    "type": "overgeneralization",
                    "section": "conclusion",
                    "message": instr,
                }
            ],
            "suggested_revisions": [{"section": "conclusion", "instruction": instr}],
        },
    )
    out = await merge_reviews(review_report_path=str(rr), semantic_review_path=str(sem))
    matching = [
        r
        for r in out["suggested_revisions"]
        if (r.get("instruction") or "").strip() == instr
    ]
    assert len(matching) == 1, "exact-duplicate warning text must not be re-added"


@pytest.mark.asyncio
async def test_merge_reviews_warning_entries_collected_by_paper_refine(tmp_path):
    rr, sem = _write_merge_inputs(
        tmp_path,
        {
            "status": "ok",
            "warnings": [
                {
                    "type": "overclaim",
                    "section": "abstract",
                    "message": "Qualify the headline claim to the tested setup.",
                }
            ],
            "suggested_revisions": [],
        },
    )
    out = await merge_reviews(review_report_path=str(rr), semantic_review_path=str(sem))
    merged = tmp_path / "review_merge_log.json"
    import json as _j

    merged.write_text(_j.dumps(out))

    tex = "\\section{Abstract}\n% CLAIM:C1:NC1\nOur kernel is fast.\n\\end{document}\n"
    p = tmp_path / "full_paper.tex"
    p.write_text(tex)
    edits = (
        '```json\n[{"find": "Our kernel is fast.", '
        '"replace": "Our kernel is fast in the tested setup."}]\n```'
    )
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_mock_resp(edits),
    ) as mocked:
        ref = await paper_refine(tex_path=str(p), merged_review_path=str(merged))
    assert ref["refined"] is True, (
        "a warning-only review must still drive a refine pass (was: no-op)"
    )
    # the warning text reached the refiner prompt
    sent = mocked.call_args.kwargs.get("messages") or mocked.call_args.args[0]
    joined = " ".join(str(m) for m in sent)
    assert "Qualify the headline claim" in joined


# --- _escape_text_underscores: \(...\) / \[...\] math must survive ---


def test_escape_underscores_skips_inline_paren_math():
    from src.server import _escape_text_underscores as esc

    # the run-replay corruption case: subscript in plain prose math
    assert esc(r"blocking factor \(k_p\) here") == r"blocking factor \(k_p\) here"
    # text-mode underscores around the math span are still escaped
    assert esc(r"see run_log and \(k_p\)") == r"see run\_log and \(k_p\)"


def test_escape_underscores_skips_display_bracket_math():
    from src.server import _escape_text_underscores as esc

    assert esc(r"\[x_i = y_j\]") == r"\[x_i = y_j\]"


def test_escape_underscores_dollar_math_unchanged():
    from src.server import _escape_text_underscores as esc

    assert esc(r"$k_p$ and a_b") == r"$k_p$ and a\_b"


def test_escape_underscores_unclosed_paren_math_falls_back():
    from src.server import _escape_text_underscores as esc

    # unclosed \( is broken LaTeX anyway; must not crash or eat text
    out = esc(r"oops \(k_p never closes")
    assert "k\\_p" in out and out.startswith("oops \\(")


def test_escape_underscores_skips_math_environment_bodies():
    from src.server import _escape_text_underscores as esc

    s = "\\begin{equation}\nx_i = y_j\n\\end{equation}"
    assert esc(s) == s
    # starred variants too
    s2 = "\\begin{align*}\na_1 &= b_2\n\\end{align*}"
    assert esc(s2) == s2
    # text around the environment is still escaped
    assert esc("run_log\n" + s) == "run\\_log\n" + s


def test_escape_underscores_non_math_environment_still_escaped():
    from src.server import _escape_text_underscores as esc

    out = esc("\\begin{itemize}\n\\item a_b\n\\end{itemize}")
    assert "a\\_b" in out  # prose env bodies keep escaping


def test_escape_underscores_unclosed_math_environment_falls_back():
    from src.server import _escape_text_underscores as esc

    out = esc("\\begin{equation}\nx_i never closes")
    assert "x\\_i" in out and out.startswith("\\begin{equation}")


# --- decode_seed: additive, gated on non-zero (linear stays byte-identical) ---

def _capture_payloads(tmp_path, tex="\\section{R}\n% CLAIM:C1:NC1\nThe value is X.\n"):
    """Run paper_refine and return every litellm payload it sent."""
    import json as _j

    p = tmp_path / "full_paper.tex"; p.write_text(tex)
    revs = _j.dumps([{"section": "results", "instruction": "tighten the claim"}])
    sent = []

    async def _spy(**kwargs):
        sent.append(kwargs)
        return _mock_resp('```json\n[{"find": "The value is X.", "replace": "The value is Y."}]\n```')

    return p, revs, sent, _spy


@pytest.mark.asyncio
async def test_decode_seed_zero_leaves_the_payload_byte_identical(tmp_path):
    """The linear on-ramp invariant: the default (0) must send NO `seed` key, so
    linear mode's payloads are byte-identical to before the parameter existed.
    Same shape as the writer_prompt_override="" precedent."""
    p, revs, sent, _spy = _capture_payloads(tmp_path)
    with patch("src.server.litellm.acompletion", new=_spy):
        await paper_refine(tex_path=str(p), suggested_revisions_json=revs)
    assert sent, "no LLM payload was sent"
    assert all("seed" not in kw for kw in sent)

    # And an explicit 0 is the same as omitting it entirely.
    second = tmp_path / "explicit_zero"; second.mkdir()
    p2, revs2, sent2, _spy2 = _capture_payloads(second)
    with patch("src.server.litellm.acompletion", new=_spy2):
        await paper_refine(tex_path=str(p2), suggested_revisions_json=revs2,
                           decode_seed=0)
    assert all("seed" not in kw for kw in sent2)
    assert [kw["messages"] for kw in sent] == [kw["messages"] for kw in sent2]


@pytest.mark.asyncio
async def test_a_non_zero_decode_seed_reaches_the_payload(tmp_path):
    """Non-zero => the sample IS seeded, so distinct seeds give distinct drafts
    (docs/plans/ari_rqgm_paper/02 §5.4 decision 5). Recording a seed the payload
    never carried is what made 8 seeds collapse to 1 draft."""
    p, revs, sent, _spy = _capture_payloads(tmp_path)
    with patch("src.server.litellm.acompletion", new=_spy):
        await paper_refine(tex_path=str(p), suggested_revisions_json=revs,
                           decode_seed=1234)
    assert sent and all(kw["seed"] == 1234 for kw in sent)


# --- H6/H7: review/gate load failures must not read as "nothing requested" ---

@pytest.mark.asyncio
async def test_merge_reviews_flags_a_corrupt_hard_gate_file(tmp_path):
    """Binding the load error to `_` made a truncated hard-gate file (the file
    carrying the blocking findings) indistinguishable from one never
    configured: review_merge_log.json read ok:true, status:null, and the gate's
    suggested_revisions vanished from what paper_refine received."""
    import json

    rr = tmp_path / "review_report.json"
    rr.write_text(json.dumps({"overall_score": 3}))
    hg = tmp_path / "hard_gate.json"
    hg.write_text('{"status": "failed", "should_block": tru')   # truncated

    out = await merge_reviews(review_report_path=str(rr), hard_gate_path=str(hg))
    assert out["ok"] is False
    assert out["load_errors"] and "claim_evidence_hard_gate" in out["load_errors"]
    status = out["evidence_grounded_reviews"]["claim_evidence_hard_gate_status"]
    assert status is not None and str(status).startswith("load_error:")


@pytest.mark.asyncio
async def test_paper_refine_errors_when_every_review_source_is_unreadable(tmp_path):
    """`paper_refine` swallowed the review-payload parse and early-returned
    'no actionable suggested_revisions; paper returned unchanged' — a note that
    ASSERTS the reviewers requested nothing. A retracted claim then shipped
    unchanged with no error key."""
    p = tmp_path / "full_paper.tex"
    p.write_text("\\section{Results}\n% CLAIM:C1:NC1\nWe report 3.2 GFLOP/s.\n",
                 encoding="utf-8")
    bad = tmp_path / "merged_review.json"
    bad.write_text('{"suggested_revisions": [')   # truncated; the only source

    out = await paper_refine(tex_path=str(p), merged_review_path=str(bad))
    assert out.get("error") and "unreadable" in out["error"]
    assert out["refined"] is False
    assert "no actionable" not in str(out.get("note", ""))
    assert out.get("warnings")


# --- M9: a science_data source that exists but won't parse is surfaced -------
@pytest.mark.asyncio
async def test_link_paper_claims_surfaces_corrupt_science_data(tmp_path):
    """M9: a science_data file that EXISTS but does not decode must set
    `science_data_load_error`, not silently proceed with an empty registry
    (which makes 0 resolved anchors read as 'the writer invented claim ids')."""
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\documentclass{article}\begin{document}x\end{document}",
                   encoding="utf-8")
    bad = tmp_path / "science_data.json"
    bad.write_text('{"claims": [ this is not json', encoding="utf-8")

    out = await link_paper_claims(tex_path=str(tex), science_data_json=str(bad))
    assert "science_data_load_error" in out
    assert "science_data.json" in out["science_data_load_error"]


@pytest.mark.asyncio
async def test_link_paper_claims_no_science_data_has_no_load_error(tmp_path):
    """M9 corollary: a genuinely absent science_data stays silent (no error key)
    so absence and corruption never look alike."""
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\documentclass{article}\begin{document}x\end{document}",
                   encoding="utf-8")
    out = await link_paper_claims(tex_path=str(tex), science_data_json="")
    assert "science_data_load_error" not in out
