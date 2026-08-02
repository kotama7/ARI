"""Schema validation tests for replication_rubric.schema.json."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "replication_rubric.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _hex64(seed: int = 0) -> str:
    return (
        ("a" * 64)
        if seed == 0
        else format((seed * 0x1234567890ABCDEF) & ((1 << 256) - 1), "064x")
    )


def _leaf(
    category: str = "Code Development",
    requirements: str = "The MaskNetwork class outputs 0 for critical states.",
    quote: str = "the mask network outputs 0 for critical steps and 1 otherwise",
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": requirements,
        "weight": 2,
        "sub_tasks": [],
        "task_category": category,
        "finegrained_task_category": "Method Implementation",
        "rationale_from_paper": {"section": "§3.1", "quote": quote},
        "evidence_span": {
            "kind": "paper-span",
            "section": "§3.1",
            "quote": quote,
            "start_char": 0,
            "end_char": len(quote),
            "paper_sha256": _hex64(1),
        },
        "verification": {"kind": "artifact", "relative_path": "reproduce.sh"},
    }


def _root(children: list[dict]) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "requirements": "Replication of the paper's main contribution.",
        "weight": 1,
        "sub_tasks": children,
    }


def _envelope(rubric: dict) -> dict:
    return {
        "schema_version": "ari.replication-rubric/v2",
        "version": "3",
        "paper_sha256": _hex64(1),
        "rubric_sha256": _hex64(3),
        "generator": {
            "model": "gemini/gemini-2.5-pro",
            "model_revision": "fixture-r1",
            "provider": "fixture",
            "prompt_sha256": _hex64(2),
            "generated_at": "2026-04-30T12:00:00Z",
            "temperature": 0.0,
            "strategy": "hierarchical-v2",
            "quality_profile": "calibrated",
            "max_model_calls": 64,
            "subtree_concurrency": 4,
            "calls": [],
            "partial_failures": [],
        },
        "repair_ledger": {"actions": [], "dropped_artifacts": []},
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 21600,
        },
        "rubric": rubric,
    }


# ── valid ──


def test_schema_is_draft202012_valid(schema):
    Draft202012Validator.check_schema(schema)


def test_minimal_valid_envelope(validator):
    env = _envelope(_root([_leaf()]))
    validator.validate(env)


def test_paperbench_style_three_categories(validator):
    children = [
        _leaf(
            category="Code Development",
            requirements="The MaskNetwork outputs 0 for critical inputs.",
        ),
        _leaf(
            category="Code Execution",
            requirements="The reproduce.sh runs Experiment II for the selfish mining environment.",
        ),
        _leaf(
            category="Result Analysis",
            requirements="In reproduce.log, 'Ours' achieves strictly higher cumulative reward than JSRL.",
        ),
    ]
    env = _envelope(_root(children))
    validator.validate(env)


def test_nested_subtasks(validator):
    leaf = _leaf()
    mid = {
        "id": str(uuid.uuid4()),
        "requirements": "Mid-level grouping of method implementation.",
        "weight": 3,
        "sub_tasks": [leaf],
    }
    env = _envelope(_root([mid]))
    validator.validate(env)


# ── reject ──


def test_missing_required_envelope_field(validator):
    env = _envelope(_root([_leaf()]))
    del env["paper_sha256"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_bad_paper_sha256_pattern(validator):
    env = _envelope(_root([_leaf()]))
    env["paper_sha256"] = "not-hex"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_bad_version(validator):
    env = _envelope(_root([_leaf()]))
    env["version"] = "2"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_bad_task_category(validator):
    leaf = _leaf()
    leaf["task_category"] = "Frobnication"
    env = _envelope(_root([leaf]))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_negative_weight_rejected(validator):
    leaf = _leaf()
    leaf["weight"] = -1
    env = _envelope(_root([leaf]))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_max_runtime_out_of_range(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["max_runtime_sec"] = 50
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_invalid_flag_value(validator):
    leaf = _leaf()
    leaf["flags"] = ["something_else"]
    env = _envelope(_root([leaf]))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_short_quote_rejected(validator):
    leaf = _leaf(quote="too short")
    env = _envelope(_root([leaf]))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


# ── execution_profile (HPC hints) ──


def test_execution_profile_omitted_is_valid(validator):
    """Backward compat: rubric without execution_profile must still validate."""
    env = _envelope(_root([_leaf()]))
    assert "execution_profile" not in env["reproduce_contract"]
    validator.validate(env)


def test_execution_profile_minimal(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {"kind": "gpu_single"}
    validator.validate(env)


def test_execution_profile_full(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi_gpu",
        "paper_max_ranks": 65536,
        "paper_max_nodes": 8192,
        "min_ranks": 4,
        "min_nodes": 1,
        "result_aggregation": "rank0_csv",
        "metric_columns": ["nodes", "ranks", "runtime_sec", "gflops"],
        "accepts_reduced_scale": True,
        "requested_nodes": 4,
        "ntasks_per_node": 8,
        "requested_nodelist": "node[01-04]",
        "exclude_nodes": "badnode01",
        "exclusive": True,
        "requested_gpus_per_task": 1,
        "gpu_type": "v100",
        "memory_gb_per_node": 256,
        "constraint": "skylake",
        "cpu_bind": "cores",
        "mem_bind": "local",
        "hint": "nomultithread",
        "account": "projX",
        "qos": "normal",
        "reservation": "paperbench",
        "module_loads": ["cuda/12.4", "openmpi/4.1"],
    }
    validator.validate(env)


def test_execution_profile_bad_kind_rejected(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {"kind": "warp_drive"}
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_execution_profile_negative_ranks_rejected(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi",
        "paper_max_ranks": 0,
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_execution_profile_bad_aggregation_rejected(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi",
        "result_aggregation": "broadcast",
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_execution_profile_module_loads_array_of_strings(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi",
        "module_loads": [123],  # not a string
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


def test_execution_profile_rejects_arbitrary_scheduler_escape(validator):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi",
        "extra_sbatch_args": ["--dependency=afterok:123"],
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


@pytest.mark.parametrize(
    "fields",
    [
        {"memory_gb_per_node": 8, "memory_gb_per_cpu": 2},
        {"requested_gpus_per_node": 1, "requested_gpus_per_task": 1},
    ],
)
def test_execution_profile_rejects_contradictory_resources(validator, fields):
    env = _envelope(_root([_leaf()]))
    env["reproduce_contract"]["execution_profile"] = {
        "kind": "mpi_gpu",
        **fields,
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(env)


# ── PaperBench rice/rubric.json fixture round-trip ──

PB_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "paperbench_rubric_sample.json"
)


def _coerce_pb_node_to_schema(node: dict) -> dict:
    """PaperBench's raw TaskNode is almost compatible with our $defs/task_node;
    a few rough edges need coercion before validation:

      - Their `task_category` enum includes "Subtree", which we don't accept.
        We map "Subtree" / unknown values to None on internal nodes.
      - They sometimes use non-UUID ids. We rewrite those to UUIDs.
      - rationale_from_paper is not used in PaperBench rice; that field is
        only required by *our* generator policy at leaf time, and our
        schema marks it optional structurally.
    """
    out = dict(node)
    cat = out.get("task_category")
    if cat not in {"Code Development", "Code Execution", "Result Analysis", None}:
        out["task_category"] = None
    nid = out.get("id")
    try:
        if not isinstance(nid, str):
            raise ValueError
        uuid.UUID(nid)
    except (ValueError, AttributeError):
        out["id"] = str(uuid.uuid4())
    out["weight"] = int(out.get("weight", 1))
    out["sub_tasks"] = [
        _coerce_pb_node_to_schema(c) for c in (out.get("sub_tasks") or [])
    ]
    if not out["sub_tasks"]:
        out["task_category"] = out.get("task_category") or "Code Development"
        out["finegrained_task_category"] = (
            out.get("finegrained_task_category") or "Method Implementation"
        )
        out["rationale_from_paper"] = {
            "external_prerequisite": {
                "description": "Migrated PaperBench fixture without embedded paper evidence.",
                "source": "paperbench-rice-fixture",
            }
        }
        out["evidence_span"] = {
            "kind": "external-prerequisite",
            "description": "Migrated PaperBench fixture without embedded paper evidence.",
            "source": "paperbench-rice-fixture",
        }
        out["verification"] = {
            "kind": "artifact",
            "relative_path": "reproduce.sh",
        }
    return out


@pytest.mark.skipif(not PB_FIXTURE.is_file(), reason="PaperBench fixture missing")
def test_paperbench_rice_rubric_fits_in_envelope(validator):
    """PaperBench's raw rubric, after light coercion, must be valid as the
    `rubric` root of our envelope. This is the §5.1 DoD for Step 1."""
    pb_root = json.loads(PB_FIXTURE.read_text())
    coerced = _coerce_pb_node_to_schema(pb_root)
    env = _envelope(coerced)
    validator.validate(env)
