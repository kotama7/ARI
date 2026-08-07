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
