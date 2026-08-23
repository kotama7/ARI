"""RQGM Task 07 — prompt-evolution persistence + filename hygiene
(docs/reference/rqgm_schemas.md §Prompt-evolution schemas (Task 07)).

Covers: the fail-open append-only writer (no checkpoint → no-op, never
raises; env run-pin resolution), record schema round-trip + jsonschema
validation for the three record shapes, deterministic rollup derivation
(JSONL is truth, ``prompt_specs.json`` is derived), the checkpoint store
method + module shim, and META_FILES / _TRACE_FILES / node-report blocklist
registration for every new filename (the ``test_new_filenames_are_meta_files``
pattern from ``test_prompt_provenance.py``).

No test calls a real LLM (P2).
"""

from __future__ import annotations

import json

import pytest

from ari.paths import PathManager
from ari.rqgm.prompt_evolution import (
    PROMPT_EVOLUTION_FILENAME,
    PROMPT_SPECS_FILENAME,
    STAGES,
    ComparisonObservation,
    PromptCandidate,
    PromptCandidateValidation,
    build_prompt_specs_rollup,
    candidate_from_dict,
    load_prompt_evolution_log,
    record_prompt_evolution_event,
    save_prompt_specs_snapshot,
)


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _candidate(**overrides) -> PromptCandidate:
    base = dict(
        record_id="pcand_00017",
        epoch_id="epoch_004",
        component_id="prompt_mutator_v2",
        prompt_hash="a1b2c3d4e5f6",
        candidate_id="reviewer_prompt_v4",
        role="reviewer",
        generated_by={"component_id": "prompt_mutator_v2",
                      "prompt_hash": "0" * 12},
        generation_mode="mutation",
        mutation_kind="schema_tightening",
        source_prompt_id="reviewer_prompt_v3",
        failure_summary_refs=("fsum_00042",),
        rationale="Reviewer missed unsupported speedup claims.",
        prompt_spec={"prompt_id": "reviewer_prompt_v4"},
        created_at="2026-01-01T00:00:00Z",
        source_refs=("adv_case_00042",),
    )
    base.update(overrides)
    return PromptCandidate(**base)


def _validation(stage: str = "replay_evaluation", **overrides):
    base = dict(
        record_id="pval_00058",
        epoch_id="epoch_004",
        component_id="governance_orchestrator",
        candidate_id="reviewer_prompt_v4",
        role="reviewer",
        prompt_hash="a1b2c3d4e5f6",
        stage=stage,
        passed=True,
        evaluated_by="governance_orchestrator",
        case_results=({"case_id": "adv_case_00042",
                       "expected": "flag unfair baseline", "met": True,
                       "cache_key": "c" * 12, "cached": False},),
        metrics={"replay_pass_rate": 0.875, "incumbent_pass_rate": 0.75},
        created_at="2026-01-01T00:00:00Z",
        source_refs=("pcand_00017",),
    )
    base.update(overrides)
    return PromptCandidateValidation(**base)


def _observation(**overrides):
    base = dict(
        record_id="cobs_00203",
        epoch_id="epoch_004",
        component_id="governance_orchestrator",
        candidate_id="reviewer_prompt_v4",
        incumbent_id="reviewer_prompt_v3",
        role="reviewer",
        prompt_hash="a1b2c3d4e5f6",
        input_context_hash="b" * 12,
        node_id="node_017",
        candidate_output_hash="c" * 12,
        incumbent_output_hash="d" * 12,
        divergence={"recommended_action": ["revise", "accept"],
                    "confidence_delta": -0.2},
        created_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return ComparisonObservation(**base)


# ── record shapes: round-trip + jsonschema validation ────────────────────────


def test_candidate_round_trip():
    cand = _candidate()
    clone = candidate_from_dict(json.loads(json.dumps(cand.to_dict())))
    assert clone == cand


def test_records_validate_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    schema = schemas.load("rqgm_prompt_evolution.schema")
    jsonschema.validate(_candidate().to_dict(), schema)
    jsonschema.validate(_validation().to_dict(), schema)
    jsonschema.validate(_observation().to_dict(), schema)
    # An unknown lifecycle stage is rejected structurally.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            _validation(stage="instant_activation").to_dict(), schema
        )
    # A non-candidate status on a PromptCandidate line is rejected.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_candidate(status="active").to_dict(), schema)


# ── fail-open writer: a missing or unwritable checkpoint never raises ────────


def test_writer_is_noop_without_checkpoint(tmp_path):
    record_prompt_evolution_event(None, _candidate())  # must not raise
    assert list(tmp_path.iterdir()) == []
    assert load_prompt_evolution_log(None) == []


def test_writer_appends_jsonl_and_fills_created_at(tmp_path):
    record_prompt_evolution_event(tmp_path, _candidate())
    record_prompt_evolution_event(
        tmp_path, {**_validation().to_dict(), "created_at": ""}
    )
    lines = (
        (tmp_path / PROMPT_EVOLUTION_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 2
    rows = [json.loads(ln) for ln in lines]
    assert rows[0]["record_type"] == "prompt_candidate"
    assert rows[1]["record_type"] == "prompt_candidate_validation"
    assert rows[1]["created_at"]  # filled at append time
    assert load_prompt_evolution_log(tmp_path) == rows


def test_writer_resolves_env_run_pin(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    record_prompt_evolution_event(None, _candidate())
    assert (tmp_path / PROMPT_EVOLUTION_FILENAME).exists()


def test_writer_never_raises_on_io_failure(tmp_path):
    blocker = tmp_path / PROMPT_EVOLUTION_FILENAME
    blocker.mkdir()  # a directory where the file should be → open() fails
    record_prompt_evolution_event(tmp_path, _candidate())  # must not raise


# ── derived rollup: JSONL is truth, prompt_specs.json is a pure fold ─────────


def test_rollup_is_deterministic_and_derived_from_jsonl(tmp_path):
    records = [_candidate().to_dict()]
    records += [
        _validation(stage=stage, record_id=f"pval_{i:05d}").to_dict()
        for i, stage in enumerate(STAGES[:3])
    ]
    records.append(
        _validation(stage="schema_dry_run", passed=False,
                    record_id="pval_00099").to_dict()
    )
    rollup = build_prompt_specs_rollup(records)
    assert rollup == build_prompt_specs_rollup(records)  # pure fold
    entry = rollup["specs"]["reviewer_prompt_v4"]
    assert entry["stages_passed"] == list(STAGES[:3])
    assert entry["rejected"] is True  # failed dry-run is terminal
    # Snapshot writing goes through the checkpoint store method.
    for rec in records:
        record_prompt_evolution_event(tmp_path, rec)
    save_prompt_specs_snapshot(tmp_path)
    from ari.checkpoint import load_prompt_specs_json

    assert load_prompt_specs_json(tmp_path) == build_prompt_specs_rollup(
        load_prompt_evolution_log(tmp_path)
    )


def test_checkpoint_shim_round_trip(tmp_path):
    from ari.checkpoint import load_prompt_specs_json, save_prompt_specs_json

    payload = {"schema_version": 1, "specs": {}}
    save_prompt_specs_json(tmp_path, payload)
    assert (tmp_path / PROMPT_SPECS_FILENAME).exists()
    assert load_prompt_specs_json(tmp_path) == payload
    assert load_prompt_specs_json(tmp_path / "missing") is None


# ── filename hygiene (test_new_filenames_are_meta_files pattern) ─────────────


def test_new_filenames_are_meta_files():
    assert PROMPT_EVOLUTION_FILENAME in PathManager.META_FILES
    assert PROMPT_SPECS_FILENAME in PathManager.META_FILES


def test_evolution_log_is_a_trace_file():
    from ari.paths import _TRACE_FILES

    assert PROMPT_EVOLUTION_FILENAME in _TRACE_FILES


def test_node_report_blocklists_cover_prompt_evolution_files():
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_DIRS,
        _FILES_CHANGED_BLOCKLIST_NAMES,
    )
    from ari.rqgm.prompt_loader import RQGM_PROMPTS_DIRNAME
    from ari.rqgm.store import RQGM_PROMPTS_DIRNAME as STORE_DIRNAME

    assert PROMPT_EVOLUTION_FILENAME in _FILES_CHANGED_BLOCKLIST_NAMES
    assert PROMPT_SPECS_FILENAME in _FILES_CHANGED_BLOCKLIST_NAMES
    assert RQGM_PROMPTS_DIRNAME in _FILES_CHANGED_BLOCKLIST_DIRS
    # Single spelling across Task 02's reservation and Task 07's use.
    assert RQGM_PROMPTS_DIRNAME == STORE_DIRNAME
