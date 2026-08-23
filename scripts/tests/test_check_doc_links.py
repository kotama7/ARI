"""Regression tests for the VitePress-aware documentation link checker."""

from pathlib import Path

from scripts.docs import check_doc_links as links


def test_clean_target_skips_external_site_root():
    assert links._clean_target("/ARI/") is None


def test_markdown_links_accept_clean_urls_and_public_assets(
    tmp_path: Path, monkeypatch,
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    public_report = docs / "public" / "report"
    public_report.mkdir(parents=True)
    (public_report / "en.pdf").write_bytes(b"%PDF")
    (docs / "index.md").write_text(
        "[guide](guide) [report](report/en.pdf) [site](/ARI/)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(links, "DOCS", docs)

    findings: list[dict] = []
    links.check_markdown(findings)

    assert findings == []


def test_markdown_scan_ignores_dependency_docs(tmp_path: Path, monkeypatch):
    docs = tmp_path / "docs"
    dependency = docs / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (docs / "index.md").write_text("# Docs\n", encoding="utf-8")
    (dependency / "README.md").write_text("[missing](nope)\n", encoding="utf-8")
    monkeypatch.setattr(links, "DOCS", docs)

    assert links._markdown_files() == [docs / "index.md"]


# ── heading slugs ────────────────────────────────────────────────────────────
# The anchor half of this gate is only as good as `slugify`. A rule that is too
# lax passes broken anchors silently; one that is too strict fails good ones and
# gets switched off. Each case below is a rule confirmed against the built site
# (docs/.vitepress/dist), so a change that breaks one is a change that has
# stopped matching what VitePress actually emits.

import pytest  # noqa: E402


@pytest.mark.parametrize("heading,slug", [
    # ASCII punctuation becomes '-', it is NOT deleted. `_` counts, which is the
    # single most common way a hand-written anchor goes wrong.
    ("ARI_CHECKPOINT_DIR is not set", "ari-checkpoint-dir-is-not-set"),
    ("`proposal_summary_view.schema.json`", "proposal-summary-view-schema-json"),
    ("exit_code=127 from a build step", "exit-code-127-from-a-build-step"),
    # runs collapse and the ends are trimmed
    ("--account rejected", "account-rejected"),
    ("Memory backend (Letta)", "memory-backend-letta"),
    # an id cannot start with a digit, so VitePress prefixes '_'
    ("1. Environment", "_1-environment"),
    ("8. Run end", "_8-run-end"),
    # non-ASCII survives...
    ("Skills と core", "skills-と-core"),
    ("Skill 与 core", "skill-与-core"),
    # ...but full-width punctuation is NFKD-normalised to ASCII first, so it
    # separates. `、` and `・` have no ASCII form and stay.
    ("2. 利用可能なパーティション（テンプレート）", "_2-利用可能なパーティション-テンプレート"),
    ("Pip（開発用、コンテナなし）", "pip-開発用、コンテナなし"),
    ("Research Goal（任意・推奨）", "research-goal-任意・推奨"),
])
def test_slugify_matches_the_built_site(heading, slug):
    # Compared NFKD-normalised, and that is not a convenience: `パ` in the
    # expectation above is composed (U+30D1) while slugify — like VitePress —
    # emits it decomposed (ハ + U+309A). Writing the decomposed form literally
    # here would make the test unreadable and unmaintainable, since the two are
    # indistinguishable on screen. A no-op for the ASCII cases.
    import unicodedata
    assert links.slugify(heading) == unicodedata.normalize("NFKD", slug)


def test_slugify_decomposes_dakuten():
    """NFKD splits the voiced mark off, and it is NOT a U+0300-U+036F combining
    mark, so it stays in the slug. The built site emits the decomposed form, so
    an anchor typed with composed kana does not match it -- a byte difference
    that is invisible in a diff, an editor and a review."""
    composed = "ドキュメント"
    assert links.slugify(composed) != composed
    assert "゙" in links.slugify(composed)


def test_heading_slugs_are_fence_aware_and_numbered(tmp_path: Path):
    md = tmp_path / "a.md"
    md.write_text(
        "# Title\n"
        "## Configuration\n"
        "```bash\n"
        "# not a heading, it is a shell comment\n"
        "```\n"
        "## Configuration\n"
        "## See [the guide](guide.md)\n",
        encoding="utf-8",
    )
    slugs = links.heading_slugs(md)
    assert "configuration" in slugs and "configuration-1" in slugs
    assert "not-a-heading-it-is-a-shell-comment" not in slugs
    # a link inside a heading contributes its TEXT, not its target
    assert "see-the-guide" in slugs


# ── anchors ──────────────────────────────────────────────────────────────────

def _docs_with(tmp_path: Path, monkeypatch, body: str) -> list[dict]:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "target.md").write_text("# T\n\n## Real Section\n", encoding="utf-8")
    (docs / "index.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(links, "DOCS", docs)
    links._HEADINGS_CACHE.clear()
    findings: list[dict] = []
    links.check_markdown(findings)
    return findings


def test_good_anchor_passes(tmp_path, monkeypatch):
    assert _docs_with(tmp_path, monkeypatch,
                      "[x](target.md#real-section)\n") == []


def test_anchor_to_a_missing_heading_is_reported(tmp_path, monkeypatch):
    f = _docs_with(tmp_path, monkeypatch, "[x](target.md#imaginary)\n")
    assert len(f) == 1 and f[0]["kind"] == "anchor"


def test_in_page_anchor_is_checked(tmp_path, monkeypatch):
    """These were skipped entirely before -- ~650 of them in the real tree."""
    f = _docs_with(tmp_path, monkeypatch, "# H\n\n## Here\n\n[a](#here) [b](#gone)\n")
    assert [x["target"] for x in f] == ["#gone"]


def test_a_broken_file_is_reported_once_not_twice(tmp_path, monkeypatch):
    """A missing FILE is one finding; its fragment is not also checked, because
    there is nothing to check it against."""
    f = _docs_with(tmp_path, monkeypatch, "[x](nope.md#whatever)\n")
    assert len(f) == 1 and f[0]["kind"] == "file"
