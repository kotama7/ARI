from __future__ import annotations

import pytest

from src.rubric import RubricError
from src.rubric_migration import migrate_legacy_rubric_selection


def test_migrates_environment_selection_to_explicit_config():
    config, ledger = migrate_legacy_rubric_selection(
        {"paper_venue": "arxiv"},
        legacy_environment={"ARI_RUBRIC": "sc"},
    )
    assert config["paper_rubric"] == "sc"
    assert ledger["source"] == "ARI_RUBRIC"
    assert ledger["rubric_version"]
    assert ledger["rubric_digest"].startswith("sha256:")


def test_migrates_legacy_default_but_rejects_unknown_selection():
    config, ledger = migrate_legacy_rubric_selection({})
    assert config["paper_rubric"] == "neurips"
    assert ledger["source"] == "pre-v1-default"
    with pytest.raises(RubricError):
        migrate_legacy_rubric_selection(
            {},
            legacy_environment={"ARI_RUBRIC": "does-not-exist"},
        )
