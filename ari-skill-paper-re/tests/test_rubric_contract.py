from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rubric_contract import (  # noqa: E402
    LEGACY_V1,
    RUBRIC_V2,
    RubricContractError,
    bind_rubric_digest,
    validate_rubric_document,
)


PAPER = "The benchmark emits results.json after execution."


def _document(*, v2: bool) -> dict:
    document = {
        "version": "3",
        "paper_sha256": hashlib.sha256(PAPER.encode()).hexdigest(),
        "generator": {
            "model": "fixture/model",
            "provider": "fixture",
            "strategy": "hierarchical-v2",
            "calls": [{"label": "fixture-call"}],
        },
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 600,
        },
        "rubric": {
            "id": "root",
            "requirements": "Replicate the benchmark results.",
            "weight": 1,
            "sub_tasks": [
                {
                    "id": "leaf",
                    "requirements": "Emit the benchmark results artifact.",
                    "weight": 1,
                    "sub_tasks": [],
                    "task_category": "Code Execution",
                }
            ],
        },
    }
    if v2:
        document["schema_version"] = RUBRIC_V2
        document["repair_ledger"] = {"actions": [], "dropped_artifacts": []}
    return bind_rubric_digest(document, legacy=not v2)


def test_v2_and_support_window_v1_are_explicitly_negotiated():
    v2 = validate_rubric_document(_document(v2=True), paper_text=PAPER)
    assert v2.schema_version == RUBRIC_V2
    assert v2.migration_required is False

    legacy = validate_rubric_document(_document(v2=False), paper_text=PAPER)
    assert legacy.schema_version == LEGACY_V1
    assert legacy.migration_required is True


def test_legacy_reader_can_be_disabled_by_consumer_policy():
    with pytest.raises(RubricContractError, match="offline migration"):
        validate_rubric_document(_document(v2=False), allow_legacy=False)


def test_unknown_schema_and_digest_tampering_fail_closed():
    unknown = _document(v2=True)
    unknown["schema_version"] = "ari.replication-rubric/v999"
    with pytest.raises(RubricContractError, match="unsupported rubric"):
        validate_rubric_document(unknown)

    tampered = _document(v2=True)
    tampered["rubric"]["requirements"] = "A changed requirement."
    with pytest.raises(RubricContractError, match="does not match"):
        validate_rubric_document(tampered)


def test_paper_digest_mismatch_fails_before_grading():
    with pytest.raises(RubricContractError, match="paper text does not match"):
        validate_rubric_document(_document(v2=True), paper_text="other paper")


class TestJudgeIdentityProvider:
    """The judge's recorded provider must name who served it.

    The ladder this replaces knew the `/` prefix and OpenAI's bare ids, and
    sent everything else to `provider: "litellm"` -- the routing library's own
    name, not anyone who could have answered. Anthropic ids route bare, so
    every Claude judge was recorded that way.
    """

    @staticmethod
    def _provider(model: str) -> str:
        # Loaded under a unique name, the convention this package already uses
        # for server.py: a plain `src.server` import resolves to whichever
        # ari-skill-*/src/server.py pytest imported first.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "paper_re_server_judge", SRC / "server.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("paper_re_server_judge", module)
        spec.loader.exec_module(module)
        return module._judge_identity(model).provider

    @pytest.mark.parametrize(
        "model, expected",
        [
            ("claude-opus-4-7", "anthropic"),
            ("claude-opus-5", "anthropic"),
            ("gpt-4o", "openai"),
            ("gemini/gemini-2.5-pro", "gemini"),
        ],
    )
    def test_the_judge_records_a_real_provider(self, model, expected):
        assert self._provider(model) == expected

    def test_unplaceable_judge_id_degrades_instead_of_raising(self):
        assert self._provider("totally-made-up-model-xyz") == "unknown"
