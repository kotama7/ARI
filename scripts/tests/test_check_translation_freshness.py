"""Regression tests for translation-freshness scan boundaries."""

from pathlib import Path

from scripts.docs import check_translation_freshness as freshness


def test_readmes_and_generated_dependency_trees_are_exempt():
    assert freshness.is_exempt("docs/guides/README.md")
    assert freshness.is_exempt("docs/node_modules/pkg/README.md")
    assert freshness.is_exempt("docs/.vitepress/cache/generated.md")


def test_english_docs_scans_only_authored_content(tmp_path: Path, monkeypatch):
    docs = tmp_path / "docs"
    dependency = docs / "node_modules" / "pkg"
    translation = docs / "ja"
    dependency.mkdir(parents=True)
    translation.mkdir(parents=True)
    (docs / "index.md").write_text("---\nlast_verified: 2026-08-02\n---\n")
    (docs / "README.md").write_text("# navigation\n")
    (dependency / "README.md").write_text("# dependency\n")
    (translation / "index.md").write_text("---\nlast_verified: 2026-08-02\n---\n")
    monkeypatch.setattr(freshness, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(freshness, "DOCS", docs)

    assert freshness.english_docs() == [docs / "index.md"]
