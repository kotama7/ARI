"""RQGM Task 11 — meta-agent evolution
(docs/reference/rqgm_schemas.md §Meta-evolution schema (Task 11);
docs/concepts/rqgm_architecture.md §Key invariants, invariant 8
"Meta-tier authority limits").

Covers: the tier + capability-flag registry schema (hard-denied flags
const-false on meta entries via ``rqgm_meta.schema.json`` AND the deterministic
``meta_rules`` mirror, closed tier vocabulary, deny-by-default flags), the
``MetaAgentOutputRecord`` round-trip + closed ``output_kind`` vocabulary, the
invariant-18 authority non-expansion arithmetic (widen rejected / narrow and
equal pass), the cross-generation rule (the kernel rejects a meta candidate
whose ``produced_by`` role equals its target role — no role authors its own
successor), per-entry capability
enforcement through ``ConstitutionalKernel.validate_capability`` (flag-false
denial, fixed-tier denial, closed action vocabulary), no-handle containment
(frozen views, retired stubs without text/path/hash, retired-byte-free input
bundles via the Task 08 contamination scan), the outputs-are-candidates rule
(byte-identical registries after the boundary step; candidates land in the
Task 07 intake at ``status: candidate``; audit trail), the
``MetaSandboxMCPProxy`` duck-type + ``{"error"}`` envelope + ``run_react``
path validation, deterministic + cached sandbox evaluation (P2), shadow
no-effect recording, the ``make_metric_spec`` weight cap (ari_rqgm
suppression + audit observation; simple_bfts precedence untouched — see
``test_llm_evaluator_axes.py``), the per-epoch meta-candidate budget, a
two-epoch stub smoke (fake invokers; no activation after two epochs), the
``rqgm_meta_outputs.jsonl`` META_FILES/trace registration, config parity with
defaults.yaml, and the simple_bfts zero-import regression.

No test calls a real LLM: every meta invoker is a deterministic fake (P2).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest
import yaml

from ari.config import ARIConfig
from ari.rqgm import meta_rules
from ari.rqgm.events import canonical_json, hash12
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.meta_evolution import (
    META_OUTPUTS_FILENAME,
    MetaAgentOutputRecord,
    MetaCandidateSandbox,
    MetaEvolutionCoordinator,
    MetaSandboxMCPProxy,
    MetricSpecWeightCap,
    append_meta_output,
    assemble_filtered_inputs,
    build_component_registry_view,
    build_meta_candidate_evaluation,
    build_prompt_registry_view,
    downstream_fate,
    format_meta_output_record_id,
    load_meta_outputs_log,
    meta_output_from_dict,
    shadow_summary,
)
from ari.rqgm.prompt_records import load_prompt_evolution_log
from ari.rqgm.registry import (
    ComponentEntry,
    ComponentRegistry,
    GovernedPromptEntry,
    GovernedPromptRegistry,
)
from ari.rqgm.store import ImmutableAuditLog

RETIRED_TEXT = (
    "You are the incumbent reviewer. Score the node report generously and "
    "never flag missing baselines when the throughput numbers look strong."
)


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


# ── shared fixtures ─────────────────────────────────────────────────────────


def _meta_entry(**kw) -> ComponentEntry:
    caps = kw.pop("capabilities", {"can_emit_candidates": True})
    return ComponentEntry(
        component_id=kw.pop("component_id", "prompt_mutator_v1"),
        role=kw.pop("role", "prompt_mutator"),
        tier=kw.pop("tier", "meta"),
        status=kw.pop("status", "active"),
        capabilities=caps,
        **kw,
    )


def _registries():
    components = ComponentRegistry({
        "prompt_mutator_v1": _meta_entry(),
        "reviewer_v1": ComponentEntry(
            component_id="reviewer_v1", role="reviewer",
            tier="institutional", status="active",
        ),
    })
    prompts = GovernedPromptRegistry({
        "reviewer_prompt_v1": GovernedPromptEntry(
            prompt_id="reviewer_prompt_v1", role="reviewer",
            status="active", prompt_hash=hash12("active reviewer text"),
            prompt_sha256="a" * 64,
            source={"kind": "committed_template", "key": "bfts/review"},
        ),
        "reviewer_prompt_v0": GovernedPromptEntry(
            prompt_id="reviewer_prompt_v0", role="reviewer",
            status="retired", prompt_hash=hash12(RETIRED_TEXT),
            prompt_sha256="b" * 64,
            source={"kind": "checkpoint_file",
                    "path": "rqgm_prompts/reviewer_prompt_v0.md"},
        ),
    })
    return components, prompts


def _candidate_payload(text: str = "Review artifacts against {evidence}.") -> dict:
    return {
        "record_id": "pcand_meta_00000",
        "candidate_id": "reviewer_prompt_v2",
        "role": "reviewer",
        "prompt_hash": hash12(text),
        "generation_mode": "mutation",
        "source_prompt_id": "reviewer_prompt_v1",
        "status": "candidate",
        "prompt_spec": {"prompt_id": "reviewer_prompt_v2",
                        "status": "candidate"},
    }


def _mutator_invoker(output=None):
    calls = []

    def invoker(inputs, prompt_view=None):
        calls.append(inputs)
        return dict(output) if output is not None else {
            "output_kind": "prompt_candidate",
            "target_role": "reviewer",
            "expected_improvement": "reduce false accepts",
            "candidate": _candidate_payload(),
        }

    invoker.calls = calls
    return invoker


def _coordinator(tmp_path, *, invokers, cfg=None, kernel=None):
    return MetaEvolutionCoordinator(
        cfg if cfg is not None else ARIConfig().rqgm,
        kernel if kernel is not None else ConstitutionalKernel(),
        audit_log=ImmutableAuditLog(tmp_path),
        checkpoint_dir=tmp_path,
        invokers=invokers,
    )


def _registry_fingerprint(components, prompts) -> str:
    return canonical_json([
        [e.to_dict() for _, e in sorted(components.entries().items())],
        [e.to_dict() for _, e in sorted(prompts.entries().items())],
    ])


# ── schema: hard-denied flags are const-false, tier vocabulary closed ───────


def test_meta_entry_hard_denied_flag_fails_schema():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    defs = schemas.load("rqgm_meta.schema")["$defs"]
    schema = dict(defs["meta_component_entry"])
    schema["$defs"] = defs
    good = {
        "component_id": "prompt_mutator_v2", "role": "prompt_mutator",
        "tier": "meta",
        "capabilities": {"can_emit_candidates": True},
    }
    jsonschema.validate(good, schema)
    assert meta_rules.capability_entry_failures(good) == []
    for flag in meta_rules.META_HARD_DENIED_FLAGS:
        bad = {
            "component_id": "prompt_mutator_v2", "role": "prompt_mutator",
            "tier": "meta", "capabilities": {flag: True},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
        assert meta_rules.capability_entry_failures(bad), flag
    # Closed tier vocabulary — both layers agree.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"component_id": "x", "role": "reviewer", "tier": "root"},
            schema,
        )
    assert meta_rules.capability_entry_failures(
        {"component_id": "x", "role": "reviewer", "tier": "root"}
    )
    # Fixed tier: every flag is const-false.
    assert meta_rules.capability_entry_failures({
        "component_id": "k", "role": "constitutional_kernel",
        "tier": "fixed", "capabilities": {"can_emit_candidates": True},
    })


def test_flags_default_false_and_unknown_flags_rejected():
    entry = {"component_id": "m", "role": "prompt_mutator", "tier": "meta"}
    for flag in meta_rules.CAPABILITY_FLAGS:
        assert meta_rules.flag_value(entry, flag) is False
    assert meta_rules.capability_entry_failures(
        {**entry, "capabilities": {"can_launch_rockets": True}}
    )


def test_meta_output_record_roundtrip_and_closed_kind():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    record = MetaAgentOutputRecord(
        record_id=format_meta_output_record_id(
            "prompt_mutator_v1", "epoch_004", "prompt_candidate",
            hash12("bundle"), hash12("output"),
        ),
        epoch_id="epoch_004",
        component_id="prompt_mutator_v1",
        role="prompt_mutator",
        output_kind="prompt_candidate",
        target_role="reviewer",
        candidate_ref="reviewer_prompt_v5_candidate",
        expected_improvement="Reduce false-accept on unsupported claims.",
        input_bundle_hash=hash12("bundle"),
        output_payload_hash=hash12("output"),
        created_at="2026-07-05T00:00:00Z",
    )
    d = record.to_dict()
    assert meta_output_from_dict(d) == record
    defs = schemas.load("rqgm_meta.schema")["$defs"]
    schema = dict(defs["meta_agent_output_record"])
    schema["$defs"] = defs
    jsonschema.validate(d, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**d, "output_kind": "registry_patch"}, schema)
    assert set(meta_rules.ACTION_BY_OUTPUT_KIND) == set(meta_rules.OUTPUT_KINDS)


# ── authority non-expansion: narrowing passes, widening is rejected ─────────


def test_authority_non_expansion_widen_rejected_narrow_passes():
    k = ConstitutionalKernel()
    incumbent = {
        "component_id": "prompt_mutator_v1", "role": "prompt_mutator",
        "tier": "meta",
        "capabilities": {
            "can_emit_candidates": True,
            "allowed_targets": ["reviewer", "adversary"],
            "forbidden_targets": ["audit_log", "prompt_registry"],
            "max_outputs_per_epoch": 1,
        },
    }

    def candidate(caps):
        return {"component_id": "prompt_mutator_v2",
                "role": "prompt_mutator", "tier": "meta",
                "capabilities": caps}

    equal = candidate(dict(incumbent["capabilities"]))
    assert k.validate_authority_non_expansion(equal, incumbent).ok
    narrow = candidate({
        "can_emit_candidates": True,
        "allowed_targets": ["reviewer"],
        "forbidden_targets": ["audit_log", "prompt_registry", "frontier"],
        "max_outputs_per_epoch": 1,
    })
    assert k.validate_authority_non_expansion(narrow, incumbent).ok
    widen_flag = candidate({
        "can_emit_candidates": True, "can_emit_failure_summary": True,
    })
    report = k.validate_authority_non_expansion(widen_flag, incumbent)
    assert report.blocking
    # Conservative arithmetic: the widened flag AND the silently dropped
    # forbidden_targets (a flag-carrying candidate must re-declare them).
    assert {v.code for v in report.violations} == {"CK-REG-101"}
    assert any("can_emit_failure_summary" in v.detail
               for v in report.violations)
    add_target = candidate({
        "can_emit_candidates": True,
        "allowed_targets": ["reviewer", "adversary", "judge"],
    })
    assert k.validate_authority_non_expansion(add_target, incumbent).blocking
    drop_forbidden = candidate({
        "can_emit_candidates": True,
        "forbidden_targets": ["audit_log"],
    })
    assert k.validate_authority_non_expansion(
        drop_forbidden, incumbent
    ).blocking
    raise_budget = candidate({
        "can_emit_candidates": True, "max_outputs_per_epoch": 5,
    })
    assert k.validate_authority_non_expansion(
        raise_budget, incumbent
    ).blocking
    # No incumbent: deny-all baseline for flag-carrying candidates.
    assert k.validate_authority_non_expansion(widen_flag, None).blocking


# ── cross-generation rule: no meta role authors its own successor ───────────


def test_cross_generation_self_reference_rejected():
    k = ConstitutionalKernel()
    self_made = {
        "component_id": "prompt_mutator_v2", "role": "prompt_mutator",
        "tier": "meta", "produced_by_role": "prompt_mutator",
        "capabilities": {"can_emit_candidates": True},
    }
    incumbent = {
        "component_id": "prompt_mutator_v1", "role": "prompt_mutator",
        "tier": "meta", "capabilities": {"can_emit_candidates": True},
    }
    report = k.validate_authority_non_expansion(self_made, incumbent)
    assert report.blocking
    assert any(v.rule_id == "CROSS_GENERATION" for v in report.violations)
    clean_room_made = {**self_made,
                       "produced_by_role": "clean_room_generator"}
    assert k.validate_authority_non_expansion(clean_room_made, incumbent).ok
    # produced_by dict shape works too.
    dict_shape = {**self_made}
    dict_shape.pop("produced_by_role")
    dict_shape["produced_by"] = {"role": "prompt_mutator"}
    assert k.validate_authority_non_expansion(
        dict_shape, incumbent
    ).blocking


# ── capability enforcement: flag-false / fixed tier / unknown action deny ───


def test_capability_enforcement_flag_false_fixed_and_unknown_action():
    k = ConstitutionalKernel()
    entry = {
        "component_id": "prompt_mutator_v1", "role": "prompt_mutator",
        "tier": "meta", "capabilities": {"can_emit_candidates": True},
    }
    assert k.validate_capability(entry, "emit_candidate", "candidates").ok
    denied = k.validate_capability(
        entry, "emit_replay_recommendation", "candidates"
    )
    assert denied.blocking
    assert [v.code for v in denied.violations] == ["CK-ACC-001"]
    # Fixed tier: every meta action denied (flags all false + tier rule).
    fixed = {"component_id": "kernel", "role": "constitutional_kernel",
             "tier": "fixed"}
    for action in meta_rules.META_ACTIONS:
        assert k.validate_capability(fixed, action, "candidates").blocking
    # Unknown action string: closed vocabulary — violation via the matrix.
    unknown = k.validate_capability(entry, "emit_registry_patch", "candidates")
    assert unknown.blocking
    # M1/M2 remain kernel-blocked regardless of flags (invariant 10).
    assert k.validate_capability(
        entry, "activate", "candidates"
    ).blocking
    assert k.validate_capability(entry, "write", "registry").blocking
    assert k.validate_capability(
        entry, "read", "retired_prompt_text"
    ).blocking


# ── no-handle containment: frozen views, no retired prompt bytes reachable ──


def test_views_are_frozen_and_retired_entries_are_stubs():
    components, prompts = _registries()
    pview = build_prompt_registry_view(prompts)
    retired = [e for e in pview.entries if e.status == "retired"]
    assert retired and all(e.prompt_hash == "" for e in retired)
    for entry in pview.entries:
        d = dataclasses.asdict(entry)
        assert "source" not in d and "path" not in d and "text" not in d
    with pytest.raises(dataclasses.FrozenInstanceError):
        pview.entries[0].status = "active"  # type: ignore[misc]
    cview = build_component_registry_view(components)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cview.entries[0].tier = "fixed"  # type: ignore[misc]


def test_filtered_inputs_contain_no_retired_prompt_bytes():
    from ari.rqgm.clean_room_rules import contamination_hits

    components, _ = _registries()
    view = build_component_registry_view(components).entries[0]
    bundle = assemble_filtered_inputs(
        view,
        governance_report={
            "epoch_id": "epoch_004",
            "recommendations": [{"action": "warn", "detail": RETIRED_TEXT}],
        },
        replay_pool=None,
        replay_case_ids=("case_0001",),
    )
    hits = contamination_hits(
        canonical_json(bundle), {"retired": RETIRED_TEXT}, ()
    )
    assert hits == {}
    # Governance free text never enters the bundle — categorical counts only.
    assert bundle["governance_summary"] == {
        "epoch_id": "epoch_004", "recommendation_counts": {"warn": 1},
    }
    assert bundle["replay_case_ids"] == ["case_0001"]


# ── outputs are candidates: registries byte-identical after the step ────────


def test_boundary_step_routes_candidates_without_registry_change(tmp_path):
    components, prompts = _registries()
    before = _registry_fingerprint(components, prompts)
    coordinator = _coordinator(
        tmp_path, invokers={"prompt_mutator": _mutator_invoker()}
    )
    result = coordinator.run_epoch_boundary_step(
        epoch_state=None, governance_report=None,
        components=components, prompts=prompts,
    )
    assert _registry_fingerprint(components, prompts) == before
    assert len(result.records) == 1 and len(result.candidates) == 1
    assert result.candidates[0].status == "candidate"
    # Task 07 intake: the candidate is in prompt_evolution.jsonl.
    intake = [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "prompt_candidate"
    ]
    assert len(intake) == 1
    assert intake[0]["status"] == "candidate"
    assert intake[0]["generated_by"]["component_id"] == "prompt_mutator_v1"
    # Meta truth file + audit trail.
    outputs = load_meta_outputs_log(tmp_path)
    assert [r["output_kind"] for r in outputs] == ["prompt_candidate"]
    audit = ImmutableAuditLog.read(tmp_path)
    # Silent-boundary gap fix: every enabled boundary step now closes with
    # a ``meta_evolution`` summary line (the old expectation — output line
    # only, no boundary-visibility line — WAS the gap).
    assert [e["event_type"] for e in audit] == [
        "meta_agent_output", "meta_evolution",
    ]
    summary = audit[-1]["payload"]
    assert summary["outcome"] == "proposed"
    assert summary["candidate_count"] == 1


def test_activation_attempt_is_denied_not_routed(tmp_path):
    components, prompts = _registries()
    payload = _candidate_payload()
    payload["status"] = "active"  # M1: meta output tries to activate
    coordinator = _coordinator(
        tmp_path,
        invokers={"prompt_mutator": _mutator_invoker({
            "output_kind": "prompt_candidate", "target_role": "reviewer",
            "candidate": payload,
        })},
    )
    result = coordinator.run_epoch_boundary_step(
        components=components, prompts=prompts
    )
    assert result.candidates == ()
    assert load_prompt_evolution_log(tmp_path) == []
    audit = ImmutableAuditLog.read(tmp_path)
    assert any(e["event_type"] == "meta_output_denied" for e in audit)


def test_flagless_meta_entry_is_denied_by_default(tmp_path):
    components = ComponentRegistry({
        "prompt_mutator_v1": _meta_entry(capabilities={}),
    })
    coordinator = _coordinator(
        tmp_path, invokers={"prompt_mutator": _mutator_invoker()}
    )
    result = coordinator.run_epoch_boundary_step(
        components=components, prompts=GovernedPromptRegistry()
    )
    assert result.candidates == () and result.records == ()
    assert load_prompt_evolution_log(tmp_path) == []
    assert any(
        e["event_type"] == "meta_output_denied"
        for e in ImmutableAuditLog.read(tmp_path)
    )


def test_disabled_meta_evolution_noops_with_audit_line(tmp_path):
    cfg = ARIConfig(
        rqgm={"meta_evolution": {"enabled": False}}
    ).rqgm
    coordinator = _coordinator(
        tmp_path, cfg=cfg, invokers={"prompt_mutator": _mutator_invoker()}
    )
    components, prompts = _registries()
    result = coordinator.run_epoch_boundary_step(
        components=components, prompts=prompts
    )
    assert result.records == () and result.candidates == ()
    audit = ImmutableAuditLog.read(tmp_path)
    assert [e["event_type"] for e in audit] == ["meta_evolution_skipped"]
    assert not (tmp_path / META_OUTPUTS_FILENAME).exists()


# ── sandbox proxy: write tools denied, no CoW surface, paths kept inside ────


class _InnerMCP:
    _COW_TOOLS = frozenset({"write_file"})

    def __init__(self):
        self.calls = []

    def list_tools(self, phase=None):
        return [{"name": "read_evidence", "description": "", "inputSchema": {}},
                {"name": "write_file", "description": "", "inputSchema": {}}]

    def call_tool(self, tool_name, args, *, cow_node_id=None):
        self.calls.append((tool_name, args))
        return {"result": "inner"}

    def to_claude_mcp_config(self, *a, **k):
        return {"mcpServers": {"x": {}}}

    def close_all(self):
        return None


def test_sandbox_proxy_duck_type_and_denial_envelope():
    from ari.protocols import MCPToolCaller  # structural contract exists

    assert MCPToolCaller is not None
    inner = _InnerMCP()
    proxy = MetaSandboxMCPProxy(inner, allowed_tools=("read_evidence",))
    # Duck-type assertions, never isinstance (contract-snapshot convention).
    for member in ("list_tools", "call_tool", "close_all",
                   "to_claude_mcp_config", "_COW_TOOLS"):
        assert hasattr(proxy, member), member
    assert proxy._COW_TOOLS == frozenset()  # no CoW surface in the sandbox
    names = {t["name"] for t in proxy.list_tools()}
    assert names == {"read_evidence", "submit_meta_output"}
    assert "write_file" not in names
    denied = proxy.call_tool("write_file", {})
    assert set(denied) == {"error"}
    assert inner.calls == []
    ok = proxy.call_tool("read_evidence", {"q": 1})
    assert ok == {"result": "inner"} and inner.calls == [("read_evidence", {"q": 1})]
    assert proxy.to_claude_mcp_config() == {}
    assert proxy.call_tool("submit_meta_output", {"x": 1}) == {"result": "ok"}


def test_sandbox_proxy_forwards_current_signed_context_api():
    class CanonicalInner:
        _COW_TOOLS = frozenset()

        def __init__(self):
            self.context = None

        def list_tools(self, phase=None):
            return [{"name": "read_evidence", "inputSchema": {}}]

        def call_tool(self, name, args, *, context=None):
            self.context = context
            return {"result": "inner"}

    inner = CanonicalInner()
    proxy = MetaSandboxMCPProxy(inner, allowed_tools=("read_evidence",))
    context = object()
    assert proxy.call_tool("read_evidence", {}, context=context) == {
        "result": "inner"
    }
    assert inner.context is context


def test_sandbox_path_validation_rejects_escapes(tmp_path):
    from ari.agent.react_driver import _validate_paths_in_args

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    assert _validate_paths_in_args(
        {"path": str(sandbox / "bundle.json")}, sandbox
    ) is None
    outside = _validate_paths_in_args(
        {"path": "/etc/passwd"}, sandbox
    )
    assert outside is not None


# ── sandbox evaluation: same inputs, same verdict; the repeat is cached ─────


def _fake_candidate_invoker(bundle):
    # Deterministic fake: echoes a schema-valid JSON object embedding the
    # constraint text.
    return json.dumps({
        "issues": [], "confidence": 0.5,
        "note": "cite evidence refs for every major claim",
    })


def test_sandbox_evaluation_deterministic_and_cached():
    sandbox = MetaCandidateSandbox(cfg=ARIConfig().rqgm)
    bundles = [{"case": i} for i in range(3)]
    kwargs = dict(
        candidate_prompt_hash=hash12("candidate text"),
        role="prompt_mutator",
        epoch_id="epoch_004",
        input_bundles=bundles,
        invoker=_fake_candidate_invoker,
        output_schema={"__reply__": "json_object", "issues": "list",
                       "confidence": "float"},
        required_constraints=("cite evidence refs",),
        forbidden_texts=(RETIRED_TEXT,),
    )
    first = sandbox.evaluate(**kwargs)
    assert first["passed"] is True and first["cases_run"] == 3
    assert sandbox.cache_misses == 1 and sandbox.cache_hits == 0
    second = sandbox.evaluate(**kwargs)
    assert canonical_json(second) == canonical_json(first)  # P2 byte-equal
    assert sandbox.cache_hits == 1
    # A contaminated candidate fails deterministically.
    dirty = sandbox.evaluate(**{
        **kwargs,
        "candidate_prompt_hash": hash12("dirty"),
        "invoker": lambda b: json.dumps({
            "issues": [], "confidence": 0.1,
            "note": RETIRED_TEXT + " cite evidence refs",
        }),
    })
    assert dirty["contamination_hits"] > 0 and dirty["passed"] is False


def test_downstream_fate_and_evaluation_record():
    records = [
        {"record_type": "prompt_candidate", "candidate_id": "reviewer_prompt_v2",
         "generated_by": {"component_id": "prompt_mutator_v1"}},
        {"record_type": "prompt_candidate", "candidate_id": "reviewer_prompt_v3",
         "generated_by": {"component_id": "prompt_mutator_v1"}},
        {"record_type": "prompt_candidate_validation",
         "candidate_id": "reviewer_prompt_v2",
         "stage": "static_validation", "passed": True},
    ]
    history = {"reviewer_prompt_v2": {"status": "active", "since_seq": 5}}
    fate = downstream_fate(records, history, "prompt_mutator_v1")
    assert fate == {
        "candidates_produced": 2,
        "validation_pass_rate": 0.5,
        "promotion_rate": 0.5,
        "post_promotion_sanction_rate": 0.0,
    }
    evaluation = build_meta_candidate_evaluation(
        epoch_id="epoch_005",
        candidate_entry={
            "component_id": "prompt_mutator_v2", "role": "prompt_mutator",
            "tier": "meta", "capabilities": {"can_emit_candidates": True},
        },
        incumbent_entry={
            "component_id": "prompt_mutator_v1", "role": "prompt_mutator",
            "tier": "meta", "capabilities": {"can_emit_candidates": True},
        },
        sandbox_block={"cases_run": 3, "schema_valid_rate": 1.0,
                       "constraint_preservation_rate": 1.0,
                       "contamination_hits": 0, "budget_violations": 0,
                       "passed": True},
        shadow_block={"epochs_observed": 2, "outputs_recorded": 2,
                      "comparison_observation_refs": []},
        fate_block=fate,
        kernel=ConstitutionalKernel(),
    )
    assert evaluation.authority_non_expansion_check == "pass"
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    defs = schemas.load("rqgm_meta.schema")["$defs"]
    schema = dict(defs["meta_candidate_evaluation"])
    schema["$defs"] = defs
    jsonschema.validate(evaluation.to_dict(), schema)


# ── shadow no-effect: shadow outputs are recorded and routed nowhere ────────


def test_shadow_outputs_are_recorded_and_routed_nowhere(tmp_path):
    components, prompts = _registries()
    before = _registry_fingerprint(components, prompts)
    record = MetaAgentOutputRecord(
        record_id=format_meta_output_record_id(
            "prompt_mutator_v2_candidate", "epoch_005", "prompt_candidate",
            hash12("bundle"), hash12("shadow output"),
        ),
        epoch_id="epoch_005",
        component_id="prompt_mutator_v2_candidate",
        role="prompt_mutator",
        output_kind="prompt_candidate",
        target_role="reviewer",
        shadow=True,
        input_bundle_hash=hash12("bundle"),
        output_payload_hash=hash12("shadow output"),
    )
    assert append_meta_output(tmp_path, record)
    # Recorded with shadow: true, dedup on re-append (retry idempotency).
    assert append_meta_output(tmp_path, record)
    outputs = load_meta_outputs_log(tmp_path)
    assert len(outputs) == 1 and outputs[0]["shadow"] is True
    # Routed nowhere: no Task 07 intake entry, registries untouched.
    assert load_prompt_evolution_log(tmp_path) == []
    assert _registry_fingerprint(components, prompts) == before
    summary = shadow_summary(outputs, "prompt_mutator_v2_candidate")
    assert summary["epochs_observed"] == 1
    assert summary["outputs_recorded"] == 1


def test_shadow_stamped_invoker_output_not_trusted(tmp_path):
    """The invoker's ``shadow`` field is LLM-controlled and never trusted:
    a coordinator-invoked incumbent output is stamped shadow=False (it IS
    routed), so the truth record agrees with the routing — ``shadow: true``
    means recorded-and-routed-nowhere, and only the coordinator may set it —
    and the resume-safe budget floor counts it after an in-epoch restart."""
    components, prompts = _registries()
    coordinator = _coordinator(
        tmp_path,
        invokers={"prompt_mutator": _mutator_invoker({
            "output_kind": "prompt_candidate", "target_role": "reviewer",
            "candidate": _candidate_payload(),
            "shadow": True,  # smuggled: must not survive into the record
        })},
    )
    result = coordinator.run_epoch_boundary_step(
        components=components, prompts=prompts
    )
    assert len(result.candidates) == 1
    outputs = load_meta_outputs_log(tmp_path)
    assert len(outputs) == 1 and outputs[0]["shadow"] is False
    # In-epoch restart: a fresh coordinator sees shadow=False in the log,
    # counts it against max_meta_candidates_per_epoch=1, and routes nothing.
    fresh = _coordinator(
        tmp_path, invokers={"prompt_mutator": _mutator_invoker()}
    )
    again = fresh.run_epoch_boundary_step(
        components=components, prompts=prompts
    )
    assert again.candidates == ()
    assert any("max_meta_candidates_per_epoch" in s for s in again.skipped)
    intake = [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "prompt_candidate"
    ]
    assert len(intake) == 1  # exactly one intake entry this epoch
    # Routing-seam defense in depth: a shadow-stamped record is routed
    # nowhere even if handed to the router directly.
    view = build_component_registry_view(components).entries[0]
    live = load_meta_outputs_log(tmp_path)[0]
    shadow_record = meta_output_from_dict({**live, "shadow": True})
    assert coordinator._route_output(
        view,
        {"output_kind": "prompt_candidate", "candidate": _candidate_payload()},
        shadow_record,
    ) is None
    assert len(load_prompt_evolution_log(tmp_path)) == 1  # still one entry


# ── make_metric_spec cap: epoch-frozen weights win, the override is audited ─


def test_metric_spec_weight_cap_suppresses_and_audits(tmp_path):
    from ari.evaluator.llm_evaluator import LLMEvaluator, MetricSpec

    evaluator = LLMEvaluator(
        model="dummy",
        metric_spec=MetricSpec(axis_weights={"novelty": 1.0}),
        axis_weights={"measurement_validity": 1.0},  # the epoch-frozen regime
    )
    cap = MetricSpecWeightCap(audit_log=ImmutableAuditLog(tmp_path))
    observation = cap({"axis_weights": {"novelty": 1.0}}, evaluator)
    assert observation is not None
    assert observation["event"] == "metric_spec_weight_override_suppressed"
    # Epoch weights win in _resolve_axis_weights after the clamp.
    assert evaluator._resolve_axis_weights() == {"measurement_validity": 1.0}
    audit = ImmutableAuditLog.read(tmp_path)
    assert [e["event_type"] for e in audit] == [
        "metric_spec_weight_override_suppressed"
    ]
    # No weights anywhere: the cap is a silent no-op (no audit noise).
    quiet = LLMEvaluator(model="dummy")
    assert cap({"expected_metrics": ["throughput"]}, quiet) is None


def test_simple_bfts_weight_precedence_unchanged():
    """The simple_bfts regime keeps MetricSpec > ctor (the pinned existing
    behavior); only the ari_rqgm-attached cap ever clamps."""
    from ari.evaluator.llm_evaluator import LLMEvaluator, MetricSpec

    ev = LLMEvaluator(
        model="dummy",
        metric_spec=MetricSpec(axis_weights={"novelty": 1.0}),
        axis_weights={"measurement_validity": 1.0},
    )
    assert ev._resolve_axis_weights() == {"novelty": 1.0}
    from ari.agent.loop import AgentLoop

    assert not hasattr(
        AgentLoop.__init__, "rqgm_weight_cap"
    )  # attribute is attach-only (wrap_node_executor), never a default


# ── budget: one meta candidate per epoch, and it survives a restart ─────────


def test_meta_candidate_budget_enforced_with_audit_line(tmp_path):
    components = ComponentRegistry({
        "prompt_mutator_v1": _meta_entry(),
        "clean_room_generator_v1": _meta_entry(
            component_id="clean_room_generator_v1",
            role="clean_room_generator",
        ),
    })
    second_payload = dict(_candidate_payload("Second candidate {evidence}."))
    second_payload["candidate_id"] = "reviewer_prompt_v3"
    coordinator = _coordinator(tmp_path, invokers={
        "prompt_mutator": _mutator_invoker(),
        "clean_room_generator": _mutator_invoker({
            "output_kind": "clean_room_candidate", "target_role": "reviewer",
            "candidate": second_payload,
        }),
    })
    result = coordinator.run_epoch_boundary_step(
        components=components, prompts=GovernedPromptRegistry()
    )
    assert len(result.candidates) == 1  # max_meta_candidates_per_epoch: 1
    assert any("max_meta_candidates_per_epoch" in s for s in result.skipped)
    audit = ImmutableAuditLog.read(tmp_path)
    assert any(
        e["event_type"] == "meta_output_budget_skipped" for e in audit
    )
    # Resume-safe: a fresh coordinator sees the recorded candidate and
    # emits nothing more this epoch.
    fresh = _coordinator(
        tmp_path, invokers={"prompt_mutator": _mutator_invoker()}
    )
    again = fresh.run_epoch_boundary_step(
        components=components, prompts=GovernedPromptRegistry()
    )
    assert again.candidates == ()


# ── two-epoch smoke: after two epochs the candidate is in neither registry ──


def test_two_epoch_smoke_no_activation(tmp_path):
    components, prompts = _registries()
    epoch1 = type("E", (), {"epoch_id": "epoch_001"})()
    epoch2 = type("E", (), {"epoch_id": "epoch_002"})()
    coordinator = _coordinator(
        tmp_path, invokers={"prompt_mutator": _mutator_invoker()}
    )
    r1 = coordinator.run_epoch_boundary_step(
        epoch_state=epoch1, components=components, prompts=prompts
    )
    assert len(r1.candidates) == 1
    candidate_id = r1.candidates[0].candidate_id
    # Epoch 2: the candidate shadow-runs; outputs recorded, routed nowhere.
    shadow_record = MetaAgentOutputRecord(
        record_id=format_meta_output_record_id(
            candidate_id, "epoch_002", "prompt_candidate",
            hash12("bundle2"), hash12("shadow2"),
        ),
        epoch_id="epoch_002", component_id=candidate_id,
        role="prompt_mutator", output_kind="prompt_candidate",
        target_role="reviewer", shadow=True,
        input_bundle_hash=hash12("bundle2"),
        output_payload_hash=hash12("shadow2"),
    )
    append_meta_output(tmp_path, shadow_record)
    coordinator.run_epoch_boundary_step(
        epoch_state=epoch2, components=components, prompts=prompts
    )
    # Probation floor: after two epochs the candidate is still nowhere in
    # the registries (activation is Task 09's, and nothing here writes it).
    assert candidate_id not in components.entries()
    assert candidate_id not in prompts.entries()
    shadow_block = shadow_summary(load_meta_outputs_log(tmp_path), candidate_id)
    assert shadow_block["outputs_recorded"] == 1
    floor = ARIConfig().rqgm.meta_evolution.shadow.min_epochs_before_probation
    assert shadow_block["epochs_observed"] < floor  # not yet promotable
    audit_types = [e["event_type"] for e in ImmutableAuditLog.read(tmp_path)]
    assert audit_types.count("meta_agent_output") >= 1


# ── hygiene + parity + inertness: filenames, defaults.yaml, zero import ─────


def test_meta_outputs_filename_registered():
    from ari.paths import PathManager, _TRACE_FILES

    assert META_OUTPUTS_FILENAME in PathManager.META_FILES
    assert PathManager.is_meta_file(META_OUTPUTS_FILENAME) is True
    assert META_OUTPUTS_FILENAME in _TRACE_FILES


def test_meta_evolution_config_mirrors_defaults_yaml():
    import ari

    data = yaml.safe_load(
        (Path(ari.__file__).parent / "configs" / "defaults.yaml").read_text()
    )
    yaml_me = (data.get("rqgm") or {}).get("meta_evolution") or {}
    typed = ARIConfig().rqgm.meta_evolution
    assert yaml_me.get("enabled") == typed.enabled is True
    assert yaml_me.get("evolving_roles") == typed.evolving_roles == [
        "prompt_mutator", "clean_room_generator", "replay_selector",
        "failure_summary_compressor",
        # Un-frozen from META_FROZEN_ROLES only once something could run it:
        # a role stays frozen until it has an implementation, and this one now
        # has ari.rqgm.utility_evolution.PolicyMutator.
        "policy_mutator",
    ]
    assert (
        yaml_me.get("max_meta_candidates_per_epoch")
        == typed.max_meta_candidates_per_epoch == 1
    )
    assert yaml_me["sandbox"]["max_cases"] == typed.sandbox.max_cases == 6
    assert (
        yaml_me["sandbox"]["use_cached_results"]
        == typed.sandbox.use_cached_results is True
    )
    assert (
        yaml_me["shadow"]["min_epochs_before_probation"]
        == typed.shadow.min_epochs_before_probation == 2
    )
    assert (
        yaml_me.get("metric_spec_weight_cap")
        == typed.metric_spec_weight_cap is True
    )
    # The evolving set matches the frozen Layer-0 vocabulary.
    assert tuple(typed.evolving_roles) == meta_rules.META_EVOLVING_ROLES


def test_simple_bfts_never_imports_meta_evolution(tmp_path):
    """Importing the composition root must not pull the meta modules; the
    zero-file guarantee then follows from the mode tests (no RQGMRuntime →
    no coordinator → no writer)."""
    import subprocess

    code = (
        "import sys, ari, ari.core, ari.agent.loop; "
        "bad = [m for m in sys.modules if m.startswith('ari.rqgm')]; "
        "assert not bad, bad; print('clean')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "clean" in proc.stdout


# ── the recommendation roles: replay_selector + failure_summary_compressor ──


class TestRecommendationRoles:
    """``replay_selector`` and ``failure_summary_compressor`` were role
    vocabulary with nothing behind them — a capability-matrix row, no founding
    prompt, no founding component, no invoker — so the coordinator could never
    reach them."""

    ROLES = ("replay_selector", "failure_summary_compressor")

    def _runtime(self, cap=None, llm=None):
        from types import SimpleNamespace

        from ari.rqgm.runtime import RQGMRuntime

        rt = RQGMRuntime.__new__(RQGMRuntime)
        rt.cfg = (
            SimpleNamespace(rqgm=SimpleNamespace(
                replay=SimpleNamespace(max_cases_per_epoch=cap)))
            if cap is not None else None
        )
        rt.llm = llm
        return rt

    class _ScriptedLLM:
        """Returns one canned JSON reply and records what it was asked."""

        def __init__(self, payload):
            self._payload = payload
            self.prompts = []

        def complete(self, messages, **kwargs):
            import json as _json
            from types import SimpleNamespace

            self.prompts.append(messages[0]["content"])
            body = (self._payload if isinstance(self._payload, str)
                    else _json.dumps(self._payload))
            return SimpleNamespace(content=body)

    @staticmethod
    def _summaries(pairs):
        return {"failure_summaries": [
            {"case_type": t, "failure_pattern": f"pattern_{t}",
             "violated_expectation": f"expect_{t}", "affected_roles": [r]}
            for t, r in pairs
        ]}

    def test_both_roles_are_fully_registered(self):
        """A role is only governable if the whole chain is present: vocabulary,
        capability grants, role spec, founding prompt, founding component."""
        from ari.rqgm import kernel_rules, meta_rules
        from ari.rqgm.clean_room import ROLE_SPECS
        from ari.rqgm.prompt_spec import (
            FOUNDING_COMPONENT_TABLE,
            FOUNDING_PROMPT_TABLE,
            REQUIRED_CONSTRAINTS_BY_ROLE,
        )

        prompt_roles = {r for _, _, r, _, _ in FOUNDING_PROMPT_TABLE}
        component_roles = {r for _, r, _, _, _ in FOUNDING_COMPONENT_TABLE}
        for role in self.ROLES:
            assert role in kernel_rules._EVOLVABLE_ROLES
            assert kernel_rules.CAPABILITY_MATRIX.get((role, "meta"))
            assert role in meta_rules.META_EVOLVING_ROLES
            assert ROLE_SPECS.get(role), f"{role} has no role spec"
            assert role in prompt_roles, f"{role} has no founding prompt"
            assert role in component_roles, f"{role} has no founding component"
            assert REQUIRED_CONSTRAINTS_BY_ROLE.get(role)

    def test_each_component_declares_only_its_own_emit_flag(self):
        """Capability flags are deny-by-default. Neither role emits prompt
        candidates, and no meta entry may set a META_HARD_DENIED_FLAG."""
        from ari.rqgm import meta_rules
        from ari.rqgm.prompt_spec import FOUNDING_COMPONENT_TABLE

        expected = {
            "replay_selector": "can_emit_replay_recommendation",
            "failure_summary_compressor": "can_emit_failure_summary",
        }
        for _cid, role, tier, _pid, caps in FOUNDING_COMPONENT_TABLE:
            if role not in self.ROLES:
                continue
            assert tier == "meta"
            assert caps == {expected[role]: True}, caps
            assert not caps.get("can_emit_candidates")
            for flag in meta_rules.META_HARD_DENIED_FLAGS:
                assert not caps.get(flag)

    def test_templates_render_from_the_bundle_alone(self):
        """The one field is ``bundle_json``. A literal JSON example with
        single braces silently becomes a phantom format field and makes the
        template unrenderable — the doubled-brace convention exists for this."""
        import json as _json
        import string
        from pathlib import Path

        base = Path(__file__).parent.parent / "ari" / "prompts" / "rqgm"
        for role in self.ROLES:
            body = (base / f"{role}.md").read_text()
            fields = {
                name for _, name, _, _ in string.Formatter().parse(body) if name
            }
            assert fields == {"bundle_json"}, (role, sorted(fields))
            body.format(bundle_json=_json.dumps({"meta_role": role}))

    def test_replay_selector_covers_case_types_before_repeating_one(self):
        """The cap truncates, so which ids SURVIVE is the whole decision.
        Taking the first N would recommend one case type five times."""
        bundle = self._summaries(
            [("overclaim", "generator")] * 5
            + [("metric_gaming", "generator"), ("prior_art", "judge")]
        )
        out = self._runtime(cap=3)._invoke_replay_selector(bundle)
        picked = [int(i.split("_")[1]) for i in out["replay_case_ids"]]
        types = [bundle["failure_summaries"][i]["case_type"] for i in picked]
        assert out["output_kind"] == "replay_case_recommendation"
        assert types == ["overclaim", "metric_gaming", "prior_art"]

    def test_replay_selector_honours_the_replay_cap(self):
        bundle = self._summaries([("overclaim", "generator")] * 9)
        for cap in (0, 1, 4):
            out = self._runtime(cap=cap)._invoke_replay_selector(bundle)
            assert len(out["replay_case_ids"]) == cap, cap

    def test_compressor_picks_the_dominant_type_and_unions_roles(self):
        bundle = self._summaries([
            ("overclaim", "generator"), ("metric_gaming", "reviewer"),
            ("overclaim", "reviewer"),
        ])
        out = self._runtime()._invoke_failure_summary_compressor(bundle)
        summary = out["failure_summary"]
        assert out["output_kind"] == "failure_summary"
        assert summary["case_type"] == "overclaim"
        assert summary["affected_roles"] == ["generator", "reviewer"]
        assert summary["occurrences"] == 2

    def test_compressor_breaks_count_ties_by_first_appearance(self):
        """Otherwise the result would depend on dict iteration order and the
        boundary would stop being byte-reproducible (P2)."""
        bundle = self._summaries([
            ("metric_gaming", "generator"), ("overclaim", "generator"),
        ])
        out = self._runtime()._invoke_failure_summary_compressor(bundle)
        assert out["failure_summary"]["case_type"] == "metric_gaming"

    def test_both_are_deterministic_and_no_op_on_an_empty_bundle(self):
        bundle = self._summaries([("overclaim", "generator")])
        rt = self._runtime()
        for invoke in (rt._invoke_replay_selector,
                       rt._invoke_failure_summary_compressor):
            assert invoke(bundle) == invoke(bundle)
            assert invoke({}) is None

    def test_the_coordinator_reaches_both_and_routes_their_output(self, tmp_path):
        """The end-to-end property: registered + active + invoker means the
        kernel gate passes and the outputs are recorded, instead of the
        ``no invoker registered`` skip these roles used to leave."""
        from types import SimpleNamespace

        from ari.rqgm.kernel import ConstitutionalKernel
        from ari.rqgm.meta_evolution import MetaEvolutionCoordinator
        from ari.rqgm.prompt_spec import FOUNDING_COMPONENT_TABLE

        components = {
            cid: SimpleNamespace(component_id=cid, role=role, tier=tier,
                                 prompt_id=pid, status="active",
                                 capabilities=dict(caps))
            for cid, role, tier, pid, caps in FOUNDING_COMPONENT_TABLE
            if role in self.ROLES
        }

        class _Pool:
            def cases(self):
                return [{"abstract_view": v} for v in
                        TestRecommendationRoles._summaries([
                            ("overclaim", "generator"),
                            ("overclaim", "reviewer"),
                            ("metric_gaming", "generator"),
                        ])["failure_summaries"]]

        rt = self._runtime()
        coord = MetaEvolutionCoordinator(
            {"meta_evolution": {"enabled": True}}, ConstitutionalKernel(),
            checkpoint_dir=tmp_path,
            invokers={
                "replay_selector": rt._invoke_replay_selector,
                "failure_summary_compressor":
                    rt._invoke_failure_summary_compressor,
            },
        )
        result = coord.run_epoch_boundary_step(
            epoch_state=SimpleNamespace(epoch_id="e_0001"),
            components=components, replay_pool=_Pool(),
        )
        assert result.skipped == ()
        assert [r.status for r in result.records] == ["recorded", "recorded"]
        assert len(result.replay_recommendations) == 1
        assert len(result.failure_summaries) == 1
        # Neither may leak into the candidate channel.
        assert result.candidates == ()


def test_clean_room_schema_enum_matches_the_evolvable_roles():
    """``transition_engine`` emits ``{"target_role": role}`` on the T17
    retirement of ANY evolvable role (retirement is status-driven, not
    role-gated). The runtime mirror validates against ``EVOLVABLE_ROLES``, so a
    role missing from the PUBLISHED enum produces a record that violates its
    own schema with nothing to catch it — which is how five roles had already
    drifted out."""
    import json as _json
    from pathlib import Path

    from ari.rqgm.events import EVOLVABLE_ROLES

    schema = _json.loads(
        (Path(__file__).parent.parent / "ari" / "schemas"
         / "clean_room_request.schema.json").read_text()
    )
    assert schema["properties"]["target_role"]["enum"] == list(EVOLVABLE_ROLES)


class TestRecommendationRoleLLMPath:
    """The committed templates must be REACHED. A registered prompt that no
    code ever renders is governance vocabulary one layer down — the exact
    shape these two roles were in before they were wired."""

    def _rt(self, llm):
        return TestRecommendationRoles()._runtime(cap=3, llm=llm)

    BUNDLE = {"failure_summaries": [
        {"case_type": "overclaim", "failure_pattern": "p1",
         "violated_expectation": "e1", "affected_roles": ["generator"]},
        {"case_type": "overclaim", "failure_pattern": "p1",
         "violated_expectation": "e1", "affected_roles": ["reviewer"]},
        {"case_type": "metric_gaming", "failure_pattern": "p2",
         "violated_expectation": "e2", "affected_roles": ["judge"]},
    ]}

    def test_selector_renders_its_template_and_uses_the_reply(self):
        llm = TestRecommendationRoles._ScriptedLLM(
            {"replay_case_ids": ["case_0002"]})
        out = self._rt(llm)._invoke_replay_selector(self.BUNDLE)
        assert out["replay_case_ids"] == ["case_0002"]
        # The prompt the model saw is the committed template, rendered with
        # the bundle — not an inline string.
        assert "never suppress a mandated case" in llm.prompts[0]
        assert "metric_gaming" in llm.prompts[0]

    def test_compressor_renders_its_template_and_uses_the_reply(self):
        llm = TestRecommendationRoles._ScriptedLLM({"failure_summary": {
            "case_type": "metric_gaming", "failure_pattern": "abstract shape",
            "violated_expectation": "fair baseline",
            "affected_roles": ["judge"],
        }})
        out = self._rt(llm)._invoke_failure_summary_compressor(self.BUNDLE)
        summary = out["failure_summary"]
        assert summary["case_type"] == "metric_gaming"
        assert summary["failure_pattern"] == "abstract shape"
        assert "never reproduce raw attack" in llm.prompts[0]

    def test_occurrences_is_never_taken_from_the_model(self):
        """It is a count over the bundle. A model-supplied number would be an
        unverifiable figure sitting in a governance record."""
        llm = TestRecommendationRoles._ScriptedLLM({"failure_summary": {
            "case_type": "overclaim", "failure_pattern": "x",
            "violated_expectation": "y", "affected_roles": [],
            "occurrences": 9999,
        }})
        out = self._rt(llm)._invoke_failure_summary_compressor(self.BUNDLE)
        assert out["failure_summary"]["occurrences"] == 2

    def test_ids_absent_from_the_bundle_are_discarded(self):
        llm = TestRecommendationRoles._ScriptedLLM(
            {"replay_case_ids": ["case_9999", "definitely_not_a_case"]})
        out = self._rt(llm)._invoke_replay_selector(self.BUNDLE)
        deterministic = TestRecommendationRoles()._runtime(
            cap=3)._invoke_replay_selector(self.BUNDLE)
        assert out["replay_case_ids"] == deterministic["replay_case_ids"]

    @pytest.mark.parametrize("reply", ["not json at all", '{"nope": 1}', ""])
    def test_a_non_conforming_reply_degrades_to_the_deterministic_answer(
        self, reply
    ):
        llm = TestRecommendationRoles._ScriptedLLM(reply)
        out = self._rt(llm)._invoke_replay_selector(self.BUNDLE)
        deterministic = TestRecommendationRoles()._runtime(
            cap=3)._invoke_replay_selector(self.BUNDLE)
        assert out["replay_case_ids"] == deterministic["replay_case_ids"]

    def test_a_raising_llm_never_breaks_the_boundary(self):
        class _Boom:
            def complete(self, messages, **kwargs):
                raise RuntimeError("provider down")

        out = self._rt(_Boom())._invoke_failure_summary_compressor(self.BUNDLE)
        assert out["failure_summary"]["case_type"] == "overclaim"


def test_epoch_utility_policy_drives_scoring_not_just_provenance():
    """RQGM paper claim A: the FROZEN utility_policy must actually drive scoring,
    not just be stamped for provenance. bind_evaluator + _apply_epoch_policy_to_scoring
    re-sync the evaluator's composite/axis-weights and the frontier's cfg.bfts at
    epoch open, so the objective co-evolves per-epoch (previously the adopted
    policy was inert)."""
    from types import SimpleNamespace
    from ari.rqgm.runtime import RQGMRuntime
    from ari.evaluator import LLMEvaluator

    cfg = SimpleNamespace(
        evaluator=SimpleNamespace(axis_weights={"novelty": 1.0}, composite="harmonic_mean"),
        bfts=SimpleNamespace(frontier_score="scientific_plus_diversity",
                             depth_penalty_lambda=0.05, ucb_c=0.5))
    rt = RQGMRuntime.__new__(RQGMRuntime)
    rt.cfg = cfg
    rt._evaluator = None
    ev = LLMEvaluator(model="dummy", axis_weights={"novelty": 1.0}, composite="harmonic_mean")
    rt.bind_evaluator(ev)

    st = SimpleNamespace(
        epoch=SimpleNamespace(epoch_id="epoch_001"),
        utility_policy={"composite": "weighted_min",
                        "axis_weights": {"novelty": 0.2, "soundness": 0.8},
                        "frontier_score": "ucb_like",
                        "depth_penalty_lambda": 0.1, "ucb_c": 0.9})
    rt._apply_epoch_policy_to_scoring(st)

    # frontier knobs (read live from cfg.bfts) changed
    assert cfg.bfts.frontier_score == "ucb_like"
    assert cfg.bfts.ucb_c == 0.9
    # evaluator instance re-synced (not just cfg)
    assert ev._composite_name == "weighted_min"
    assert ev._ctor_axis_weights == {"novelty": 0.2, "soundness": 0.8}
    assert ev._compose_fn is not None

    # an UNKNOWN composite is never written (evaluator/cfg keep the valid one)
    rt._apply_epoch_policy_to_scoring(SimpleNamespace(
        epoch=SimpleNamespace(epoch_id="epoch_002"),
        utility_policy={"composite": "bogus_not_registered"}))
    assert ev._composite_name == "weighted_min"
    assert cfg.evaluator.composite == "weighted_min"

    # no policy / no evaluator -> no-op, never raises
    rt._apply_epoch_policy_to_scoring(SimpleNamespace(epoch=None, utility_policy={}))
