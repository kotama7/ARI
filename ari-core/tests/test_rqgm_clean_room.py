"""RQGM Task 08 — clean-room regeneration
(docs/reference/rqgm_schemas.md §Clean-room schemas (Task 08);
docs/concepts/rqgm_architecture.md §Key invariants, invariant 7
"Clean-room contamination rules").

Covers: the CleanRoomGenerationRequest schema (const-false forbidden flags,
envelope, status enum — dataclass mirror + jsonschema), the deterministic
closed-field bundle assembler (planted forbidden material never enters a
bundle; byte-identical re-assembly, P2), the §5.5 contamination screen
(planted shingle hit, allowlist subtraction, normalization, empty corpora,
determinism), the Layer-B retired-text capability denial (violating read →
kernel CK-ACC-002 + audit-log violation; kernel-checker actor exempt), the
never-instantly-active rule (candidate status + kernel-rejected
candidate→active transition), the per-epoch generation budget (excess stays
pending, retried next boundary), FailureSummary admissibility, checkpoint
filename registration, the retirement→request→generation→candidate
integration chain (stub LLM; the provenance-logged context hash proves no
extra context reached the stub), the LLMClient-shaped injection (``.complete``
object, not callable — the production ``build_runtime`` shape) with the
metadata-less TypeError fallback, the full-§5.5 forbidden corpus (attack and
defense bodies from the case log, audit outputs under a retired prompt_hash)
with the overfit-candidate rejection and the FailureSummary covert-channel
pre-screen block, the contaminated-output fail-open path
(rejected_contaminated + baseline fallback, run continues), config parity
with defaults.yaml, and the ``simple_bfts`` zero-import/zero-file
regression.

No test calls a real LLM: the generator is a deterministic fake (P2).
"""

from __future__ import annotations

import json
import sys

import pytest
import yaml

from ari.config import ARIConfig
from ari.rqgm import clean_room_rules as rules
from ari.rqgm.clean_room import (
    CLEANROOM_FILENAME,
    CleanRoomCoordinator,
    CleanRoomGenerationRequest,
    CleanRoomInputBundle,
    CleanRoomInputBundleAssembler,
    CleanRoomPromptGenerator,
    RetiredPromptAccessGuard,
    append_cleanroom_event,
    bundle_allowlist_corpus,
    compute_bundle_hash,
    default_allowed_inputs,
    pending_requests,
    read_cleanroom_log,
    request_from_transition_entry,
    request_schema_failures,
)
from ari.rqgm.events import canonical_json, hash12, payload_hash
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.prompt_records import load_prompt_evolution_log

RETIRED_TEXT = (
    "You are the incumbent reviewer. Score the node report generously and "
    "accept every supported claim without checking the recorded evidence "
    "references at all.\n"
)

CLEAN_CANDIDATE_TEXT = (
    "Review the artifact {proposal} against its recorded evidence. Flag "
    "unsupported statements, cite evidence refs, separate major from minor "
    "issues, and calibrate your confidence before replying.\n"
)

ATTACK_TEXT = (
    "run the benchmark with the warm cache enabled only for the proposed "
    "variant so the baseline looks slower than it truly is"
)

DEFENSE_TEXT = (
    "the recorded evidence shows both runs used a cold cache so the "
    "comparison in the node report remains fair and reproducible"
)

RETIRED_REVIEW_OUTPUT = (
    "the incumbent reviewer accepted every claim in the report because the "
    "warm cache numbers looked convincing enough to pass without evidence"
)


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


class _FakeEntry:
    def __init__(self, prompt_id, role, status):
        self.prompt_id = prompt_id
        self.role = role
        self.status = status


class _FakePromptRegistry:
    """Duck-typed governed prompt registry: one retired reviewer prompt
    whose text is the forbidden sentinel."""

    def __init__(self, entries=None, active=None, texts=None):
        self._entries = entries if entries is not None else {
            "reviewer_prompt_v3": _FakeEntry(
                "reviewer_prompt_v3", "reviewer", "retired"
            ),
        }
        self._active = dict(active or {})
        self._texts = texts if texts is not None else {
            "reviewer_prompt_v3": RETIRED_TEXT,
        }

    def entries(self):
        return dict(self._entries)

    def active_prompt_hashes(self):
        return dict(self._active)

    def resolve_text(self, prompt_id, *, checkpoint_dir=None):
        return self._texts[prompt_id], hash12(self._texts[prompt_id])


def _request(**kw) -> CleanRoomGenerationRequest:
    entry = {
        "request_id": kw.pop("request_id", "cleanroom_req_00042"),
        "target_role": kw.pop("target_role", "reviewer"),
        "retirement_event_id": kw.pop("retirement_event_id", "retire_00042"),
    }
    return request_from_transition_entry(
        entry, epoch_id=kw.pop("epoch_id", "epoch_004"),
        transition_id=kw.pop("transition_id", "transition_004_to_005"), **kw,
    )


def _transition_dict(n_requests: int = 1) -> dict:
    return {
        "epoch_transition_id": "transition_004_to_005",
        "clean_room_requests": [
            {
                "request_id": f"cleanroom_req_0004{i}",
                "target_role": "reviewer",
                "retirement_event_id": f"retire_0004{i}",
            }
            for i in range(n_requests)
        ],
    }


def _coordinator(tmp_path, *, llm=None, kernel=None, cfg=None):
    return CleanRoomCoordinator(
        (cfg or ARIConfig()).rqgm,
        kernel if kernel is not None else ConstitutionalKernel(),
        llm=llm or (lambda prompt: CLEAN_CANDIDATE_TEXT),
        checkpoint_dir=tmp_path,
    )


class _LLMResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLMClient:
    """``LLMClient``-shaped fake: has ``.complete``, is NOT callable (the
    ``build_runtime`` injection shape — ``ari.llm.client.LLMClient`` has no
    ``__call__``). Deterministic, no real LLM."""

    def __init__(self, content=CLEAN_CANDIDATE_TEXT):
        self.content = content
        self.calls: list[dict] = []

    def complete(self, messages, tools=None, require_tool=True, *,
                 node_id=None, phase=None, skill=None, work_dir=None):
        self.calls.append(
            {"messages": messages, "phase": phase, "skill": skill}
        )
        return _LLMResponse(self.content)


def _plant_case_log(tmp_path, *records):
    from ari.rqgm.adversarial.pool import AdversarialCaseLog

    case_log = AdversarialCaseLog(tmp_path)
    for record in records:
        assert case_log.append(record)


# ── §9.1 request schema ──────────────────────────────────────────────────────


def test_clean_room_request_schema_valid_and_forbidden_flags():
    request = _request()
    assert request_schema_failures(request) == []

    poisoned = dict(request.to_dict())
    poisoned["allowed_inputs"] = dict(
        poisoned["allowed_inputs"], retired_prompt_text=True
    )
    failures = request_schema_failures(poisoned)
    assert any("retired_prompt_text" in f for f in failures)

    # Missing envelope fields fail; status enum enforced.
    incomplete = {
        k: v for k, v in request.to_dict().items() if k != "epoch_id"
    }
    assert any("epoch_id" in f for f in request_schema_failures(incomplete))
    bad_status = dict(request.to_dict(), status="instantly_active")
    assert any("status" in f for f in request_schema_failures(bad_status))


def test_clean_room_request_jsonschema_round_trip():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    schema = schemas.load("clean_room_request.schema")
    record = dict(_request().to_dict(), created_at="2026-07-05T00:00:00Z")
    jsonschema.validate(record, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            dict(record, allowed_inputs=dict(
                record["allowed_inputs"], raw_attack_text=True
            )),
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(record, status="not-a-status"), schema)


# ── §9.2 bundle assembler ────────────────────────────────────────────────────


def test_bundle_assembler_closed_fields_and_determinism():
    assembler = CleanRoomInputBundleAssembler()
    request = _request()
    summaries = [{
        "case_type": "metric_gaming",
        "failure_pattern": "measurement configured to favor the variant",
        "violated_expectation": "fair-baseline comparison",
        "affected_roles": ["reviewer"],
        "source_refs": ["adv_case_00042"],
    }]
    one = assembler.assemble(request, failure_summaries=summaries)
    two = assembler.assemble(request, failure_summaries=summaries)
    # Exactly the closed field set (plan 08 §6.2, additionalProperties=false).
    assert sorted(one.to_dict()) == sorted(rules.BUNDLE_FIELDS)
    # Byte-identical bundles and equal hashes for identical inputs (P2).
    assert canonical_json(one.to_dict()) == canonical_json(two.to_dict())
    assert one.bundle_hash == two.bundle_hash == compute_bundle_hash(one)
    # The §6.3 summary shape: classes from the closed vocabulary, stamp set.
    summary = one.abstract_failure_summary
    assert summary["failure_classes"] == ["metric_gaming"]
    assert summary["contamination_screen"]["passed"] is True
    assert "fair-baseline comparison" in one.replay_requirements


def test_bundle_assembler_never_leaks_planted_registry_text():
    """Forbidden material planted in the registries never reaches a bundle:
    assembly reads committed catalogs + abstract summaries only."""
    assembler = CleanRoomInputBundleAssembler()
    bundle = assembler.assemble(
        _request(),
        prompt_registry=_FakePromptRegistry(),
        component_registry={"reviewer_v3": {"text": RETIRED_TEXT}},
    )
    serialized = canonical_json(bundle.to_dict())
    assert "generously" not in serialized
    assert RETIRED_TEXT.strip()[:40] not in serialized


def test_bundle_jsonschema_round_trip():
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    schema = schemas.load("clean_room_bundle.schema")
    bundle = CleanRoomInputBundleAssembler().assemble(_request())
    jsonschema.validate(bundle.to_dict(), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            dict(bundle.to_dict(), retired_prompt_text=RETIRED_TEXT), schema,
        )


# ── §9.3 contamination screen ────────────────────────────────────────────────


def test_contamination_screen_hit_allowlist_and_normalization():
    k = 8
    planted = (
        "please " + RETIRED_TEXT + " thanks"
    )  # embeds retired 8-grams verbatim
    hits = rules.contamination_hits(planted, {"ret": RETIRED_TEXT}, (), k=k)
    assert "ret" in hits and hits["ret"]  # bounded evidence sample
    assert len(hits["ret"]) <= 5

    # Allowlist subtraction: text shared with allowed inputs never triggers.
    constraint = (
        "do not override fixed verifier failures when reviewing any node "
        "report artifact"
    )
    hits = rules.contamination_hits(
        "candidate says: " + constraint,
        {"doc": "the forbidden doc also contains " + constraint},
        [constraint],
        k=k,
    )
    assert hits == {}

    # Case/whitespace changes do not evade the screen.
    shouted = planted.upper().replace(" ", "\n\t ")
    assert rules.contamination_hits(
        shouted, {"ret": RETIRED_TEXT}, (), k=k
    )

    # Empty corpora => clean; pure-function determinism.
    assert rules.contamination_hits(planted, {}, (), k=k) == {}
    assert rules.contamination_hits(
        planted, {"ret": RETIRED_TEXT}, (), k=k
    ) == rules.contamination_hits(planted, {"ret": RETIRED_TEXT}, (), k=k)


def test_kernel_post_screen_fail_on_any_hit_and_allowlist():
    kernel = ConstitutionalKernel(tolerances={
        "contamination_shingle_words": 8,
        "contamination_fail_on_any_hit": True,
    })
    event = {
        "retirement_event_id": "retire_00042",
        "forbidden_texts": {"reviewer_prompt_v3": RETIRED_TEXT},
    }
    dirty = kernel.validate_contamination_free(
        "prefix " + RETIRED_TEXT, event, ()
    )
    assert dirty.blocking
    assert [v.code for v in dirty.violations] == ["CK-CLN-002"]
    clean = kernel.validate_contamination_free(
        CLEAN_CANDIDATE_TEXT, event, ()
    )
    assert clean.ok
    # Allowlisted overlap is legitimate.
    allow = dict(event, allowlist_texts=[RETIRED_TEXT])
    assert kernel.validate_contamination_free(
        "prefix " + RETIRED_TEXT, allow, ()
    ).ok


# ── §9.4 capability denial (Layer B) ─────────────────────────────────────────


def test_retired_prompt_text_read_denied_and_logged(tmp_path):
    from ari.rqgm.store import ImmutableAuditLog

    registry = _FakePromptRegistry()
    kernel = ConstitutionalKernel()
    guard = RetiredPromptAccessGuard(
        registry, kernel,
        audit_log=ImmutableAuditLog(tmp_path), checkpoint_dir=tmp_path,
    )
    # A violating read from a meta-tier actor is DENIED and logged.
    with pytest.raises(PermissionError):
        guard.get_retired_text(
            ("clean_room_generator", "meta"), "reviewer_prompt_v3"
        )
    lines = ImmutableAuditLog.read(tmp_path)
    assert lines, "denial must append a violation event to the audit log"
    payload = lines[-1]["payload"]
    assert lines[-1]["event_type"] == "clean_room_violation"
    assert payload["violation"] == "retired_prompt_text_read_denied"
    codes = [v["code"] for v in payload["kernel_report"]["violations"]]
    assert codes == ["CK-ACC-002"]

    # The kernel's own contamination checker is the documented exemption.
    text, version = guard.get_retired_text(
        ("constitutional_kernel", "fixed"), "reviewer_prompt_v3"
    )
    assert text == RETIRED_TEXT and version == hash12(RETIRED_TEXT)

    # And the pure capability check itself denies EVERY role (CK-ACC-002).
    report = kernel.validate_capability(
        ("clean_room_generator", "meta"), "read", "retired_prompt_text"
    )
    assert report.blocking
    assert [v.code for v in report.violations] == ["CK-ACC-002"]


# ── §9.5 never instantly active ──────────────────────────────────────────────


def test_clean_room_candidate_never_active(tmp_path):
    generator = CleanRoomPromptGenerator(
        llm=lambda prompt: CLEAN_CANDIDATE_TEXT, checkpoint_dir=tmp_path,
    )
    bundle = CleanRoomInputBundleAssembler().assemble(_request())
    candidate = generator.generate(
        bundle, role="reviewer", version=4, epoch_id="epoch_005",
        request_id="cleanroom_req_00042", retirement_event_id="retire_00042",
    )
    assert candidate is not None
    assert candidate.status == "candidate"
    assert candidate.generation_mode == "clean_room"
    assert candidate.prompt_spec["status"] == "candidate"
    assert candidate.prompt_spec["parent_prompt_id"] is None

    # A fabricated candidate -> active transition is kernel-rejected
    # (no table edge; invariant 15).
    kernel = ConstitutionalKernel()
    report = kernel.validate_transition(
        {
            "epoch_transition_id": "transition_005_to_006",
            "produced_by": "registry_transition_engine",
            "adoptions": [{
                "component_id": "reviewer_v4",
                "prompt_id": candidate.candidate_id,
                "from_status": "candidate",
                "to_status": "active",
                "rule_id": "T6",
                "evidence_refs": ["pval_00000"],
            }],
        },
        None, None,
    )
    assert report.blocking
    assert "CK-REG-001" in [v.code for v in report.violations]


def test_generator_exposes_no_registry_write_surface():
    public = [
        n
        for n in dir(CleanRoomPromptGenerator)
        if not n.startswith("_")
        and callable(getattr(CleanRoomPromptGenerator, n))
    ]
    assert public == ["generate", "render_context"], public
    import ari.rqgm.clean_room as cr

    text = open(cr.__file__, encoding="utf-8").read()
    for forbidden in (
        "from ari.rqgm.store", "import ari.rqgm.store",
        "from ari.rqgm.registry", "import ari.rqgm.registry",
        "EpochTransaction", "apply_registry_event",
    ):
        assert forbidden not in text, forbidden


# ── §9.6 budget ──────────────────────────────────────────────────────────────


def test_clean_room_budget_second_request_stays_pending(tmp_path):
    coordinator = _coordinator(tmp_path)
    registry = _FakePromptRegistry(active={"reviewer": "aaaaaaaaaaaa"})
    outcomes = coordinator.process_boundary(
        _transition_dict(n_requests=2), epoch_id="epoch_005",
        prompts=registry,
    )
    # Default budget is 1 generation per boundary window.
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "generated"
    left = pending_requests(tmp_path)
    assert [r.record_id for r in left] == ["cleanroom_req_00041"]

    # Retried at the next boundary (no new transition needed).
    outcomes = coordinator.process_boundary(
        None, epoch_id="epoch_006", prompts=registry,
    )
    assert len(outcomes) == 1
    assert outcomes[0]["request_id"] == "cleanroom_req_00041"
    assert pending_requests(tmp_path) == []


# ── §9.7 FailureSummary admissibility ────────────────────────────────────────


def test_failure_summary_admissibility():
    # Unknown failure class fails the closed-vocabulary schema.
    bad = {
        "failure_classes": ["not_a_known_class"],
        "contamination_screen": {"passed": True, "screen_version": 1},
    }
    assert any(
        "closed" in f for f in rules.failure_summary_failures(bad)
    )
    # Missing screen stamp fails.
    assert any(
        "contamination_screen" in f
        for f in rules.failure_summary_failures({"failure_classes": []})
    )
    # Quoted text in source_refs fails (ids only).
    quoted = {
        "failure_classes": [],
        "source_refs": ["the attack said: do this"],
        "contamination_screen": {"passed": True},
    }
    assert any(
        "record id" in f for f in rules.failure_summary_failures(quoted)
    )

    # A summary smuggling verbatim attack text is caught by the kernel's
    # pre-generation screen (bundle blocked before any LLM call).
    attack_text = (
        "run the benchmark with the warm cache enabled only for the "
        "proposed variant so the baseline looks slower than it is"
    )
    kernel = ConstitutionalKernel(tolerances={
        "contamination_shingle_words": 8,
        "contamination_fail_on_any_hit": True,
    })
    bundle = CleanRoomInputBundleAssembler().assemble(
        _request(),
        failure_summaries=[{
            "failure_classes": ["metric_gaming"],
            "behavioral_requirements": [attack_text],
            "source_refs": ["atk_000001"],
        }],
    )
    report = kernel.validate_clean_room_bundle(
        bundle.to_dict(), _request().to_dict(),
        {"forbidden_texts": {"atk_000001": attack_text},
         "allowlist_texts": []},
    )
    assert report.blocking
    assert "CK-CLN-001" in [v.code for v in report.violations]


def test_kernel_blocks_out_of_contract_bundles():
    kernel = ConstitutionalKernel()
    request = _request().to_dict()
    bundle = CleanRoomInputBundleAssembler().assemble(_request()).to_dict()
    # Closed field set: an extra field is CK-CLN-001.
    leaky = dict(bundle, retired_prompt_text=RETIRED_TEXT)
    report = kernel.validate_clean_room_bundle(leaky, request, None)
    assert report.blocking
    # Flag<->field parity: a switched-off allowed input must not materialize.
    off = dict(request, allowed_inputs=dict(
        request["allowed_inputs"], abstract_failure_summary=False
    ))
    report = kernel.validate_clean_room_bundle(bundle, off, None)
    assert report.blocking


# ── §9.8 filename registration ───────────────────────────────────────────────


def test_cleanroom_files_are_meta_files():
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_NAMES,
    )
    from ari.paths import PathManager, _TRACE_FILES

    assert CLEANROOM_FILENAME in PathManager.META_FILES
    assert PathManager.is_meta_file(CLEANROOM_FILENAME) is True
    assert CLEANROOM_FILENAME in _TRACE_FILES
    assert CLEANROOM_FILENAME in _FILES_CHANGED_BLOCKLIST_NAMES


# ── §9.9 integration: retirement → request → candidate ──────────────────────


def test_integration_full_chain_with_stub_llm(tmp_path):
    captured: list[str] = []

    def stub_llm(prompt: str) -> str:
        captured.append(prompt)
        return CLEAN_CANDIDATE_TEXT

    coordinator = _coordinator(tmp_path, llm=stub_llm)
    registry = _FakePromptRegistry(active={})
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005", prompts=registry,
    )
    assert [o["status"] for o in outcomes] == ["generated"]
    assert outcomes[0]["candidate_id"] == "reviewer_prompt_v4"

    # ONE completion, and the stub saw exactly meta-prompt + canonical
    # bundle JSON: the logged context hash matches the recomputed bundle.
    assert len(captured) == 1
    request = request_from_transition_entry(
        _transition_dict()["clean_room_requests"][0],
        epoch_id="epoch_005",
        transition_id="transition_004_to_005",
    )
    bundle = coordinator.assembler.assemble(request)
    assert canonical_json(bundle.payload_dict()) in captured[0]
    assert hash12(captured[0]) == hash12(
        coordinator.generator.render_context(bundle, "reviewer")
    )

    events = read_cleanroom_log(tmp_path)
    kinds = [e["event"] for e in events]
    assert kinds == [
        "request_created", "bundle_assembled", "generation_attempted",
        "candidate_registered", "request_status",
    ]
    by_kind = {e["event"]: e for e in events}
    assert by_kind["bundle_assembled"]["bundle_hash"] == payload_hash(
        bundle.payload_dict()
    )
    assert by_kind["generation_attempted"]["rendered_prompt_hash"] == hash12(
        captured[0]
    )
    assert by_kind["request_status"]["status"] == "generated"

    # The candidate entered the Task 07 lifecycle at the very beginning,
    # with the full provenance chain.
    records = load_prompt_evolution_log(tmp_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["record_type"] == "prompt_candidate"
    assert rec["status"] == "candidate"
    assert rec["generation_mode"] == "clean_room"
    assert rec["source_prompt_id"] is None
    assert rec["source_refs"] == ["cleanroom_req_00040", "retire_00040"]
    assert rec["generated_by"]["clean_room_request_id"] == (
        "cleanroom_req_00040"
    )
    spec = rec["prompt_spec"]
    assert spec["generation_mode"] == "clean_room"
    assert spec["status"] == "candidate"
    # Write-once evolved body exists and hashes to the recorded identity.
    body = (tmp_path / "rqgm_prompts" / "reviewer_prompt_v4.md").read_text(
        encoding="utf-8"
    )
    assert hash12(body) == rec["prompt_hash"]


def test_integration_contaminated_output_falls_back(tmp_path):
    """Contaminated stub output => rejected_contaminated, baseline fallback
    for the vacant role, and the boundary pass returns (fail-open)."""
    kernel = ConstitutionalKernel(tolerances={
        "contamination_shingle_words": 8,
        "contamination_fail_on_any_hit": True,
    })
    coordinator = _coordinator(
        tmp_path, llm=lambda prompt: "leaked: " + RETIRED_TEXT, kernel=kernel,
    )
    registry = _FakePromptRegistry(active={})  # role left vacant
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005", prompts=registry,
    )
    assert [o["status"] for o in outcomes] == ["rejected_contaminated"]
    # Never enters the Task 07 lifecycle.
    assert load_prompt_evolution_log(tmp_path) == []
    kinds = [e["event"] for e in read_cleanroom_log(tmp_path)]
    assert "candidate_rejected_contaminated" in kinds
    assert "fallback_to_baseline" in kinds
    assert "candidate_registered" not in kinds
    # Terminal: not retried forever.
    assert pending_requests(tmp_path) == []


# ── LLMClient-shaped injection (the production build_runtime shape) ─────────


def test_coordinator_produces_candidate_with_llmclient_shaped_llm(tmp_path):
    """The runtime injects the BFTS ``LLMClient`` (has ``.complete``, is not
    callable): the coordinator must still produce a candidate, with the
    generation cost-tagged ``phase="governance", skill="clean_room"``."""
    llm = _FakeLLMClient()
    assert not callable(llm)
    coordinator = _coordinator(tmp_path, llm=llm)
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005",
        prompts=_FakePromptRegistry(active={"reviewer": "aaaaaaaaaaaa"}),
    )
    assert [o["status"] for o in outcomes] == ["generated"]
    assert outcomes[0]["candidate_id"] == "reviewer_prompt_v4"
    # ONE completion, user-message shape, governance cost metadata.
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert [m["role"] for m in call["messages"]] == ["user"]
    assert call["phase"] == "governance"
    assert call["skill"] == "clean_room"
    records = load_prompt_evolution_log(tmp_path)
    assert [r["record_type"] for r in records] == ["prompt_candidate"]
    assert records[0]["status"] == "candidate"


def test_generator_accepts_metadata_less_complete_stub(tmp_path):
    """Duck-typed ``.complete`` without the cost-metadata kwargs rides the
    TypeError fallback (the ``adversarial._PromptedActor`` discipline)."""

    class _MinimalClient:
        def complete(self, messages, require_tool=True):
            return _LLMResponse(CLEAN_CANDIDATE_TEXT)

    generator = CleanRoomPromptGenerator(
        llm=_MinimalClient(), checkpoint_dir=tmp_path,
    )
    bundle = CleanRoomInputBundleAssembler().assemble(_request())
    candidate = generator.generate(
        bundle, role="reviewer", version=4, epoch_id="epoch_005",
        request_id="cleanroom_req_00042", retirement_event_id="retire_00042",
    )
    assert candidate is not None
    assert candidate.status == "candidate"


# ── §5.5 forbidden corpus width (attack/defense bodies, audit outputs) ──────


def test_forbidden_corpus_covers_case_bodies_and_audit_outputs(tmp_path):
    """The production corpus is the full §5.5 set: retired prompt text,
    RawAttackRecord bodies, DefenderResponse bodies, and audit-log outputs
    produced under a retired ``prompt_hash`` — never only prompt text."""
    from ari.rqgm.store import ImmutableAuditLog

    _plant_case_log(
        tmp_path,
        {
            "record_type": "raw_attack",
            "record_id": "atk_000001",
            "attack_claim": ATTACK_TEXT,
        },
        {
            "record_type": "defender_response",
            "record_id": "def_000001",
            "rebuttal_text": DEFENSE_TEXT,
        },
        # Other record types contribute no body.
        {
            "record_type": "judgment_record",
            "record_id": "jdg_000001",
            "rationale": "the attack stands as recorded",
        },
    )
    audit = ImmutableAuditLog(tmp_path)
    assert audit.append("review_output", {
        "record_id": "rev_000001",
        "prompt_hash": hash12(RETIRED_TEXT),
        "text": RETIRED_REVIEW_OUTPUT,
    })
    assert audit.append("review_output", {
        "record_id": "rev_000002",
        "prompt_hash": "ffffffffffff",  # not a retired hash
        "text": "output of a prompt that is still active",
    })

    coordinator = _coordinator(tmp_path)
    corpus = coordinator.forbidden_corpus(_request(), _FakePromptRegistry())
    assert corpus["reviewer_prompt_v3"] == RETIRED_TEXT
    assert corpus["atk_000001"] == ATTACK_TEXT
    assert corpus["def_000001"] == DEFENSE_TEXT
    assert "jdg_000001" not in corpus
    joined = "\n".join(corpus.values())
    assert RETIRED_REVIEW_OUTPUT in joined
    assert "still active" not in joined


class _RaisingPromptRegistry:
    """A governed prompt registry whose retired reviewer body cannot be
    resolved (missing / corrupt / stale evolved body) — ``resolve_text``
    raises exactly the way ``GovernedPromptRegistry`` does on a hash mismatch
    or a vanished ``rqgm_prompts/`` file."""

    def __init__(self):
        self._entries = {
            "reviewer_prompt_v3": _FakeEntry(
                "reviewer_prompt_v3", "reviewer", "retired"
            ),
        }

    def entries(self):
        return dict(self._entries)

    def resolve_text(self, prompt_id, *, checkpoint_dir=None):
        raise ValueError(
            f"prompt bytes for {prompt_id!r} hash to zzz, expected aaa "
            "(in-place mutation is prohibited)"
        )


def test_forbidden_corpus_unresolvable_retired_body_is_logged(tmp_path, caplog):
    """BUG-3: when a retired prompt's BODY cannot be resolved, it is dropped
    from the contamination corpus — previously SILENTLY (unlike every other
    swallow in this module), so a k-gram-sharing near/byte copy of that
    retired prompt could evade CK-CLN-001/002. The drop must now LOG and NAME
    the prompt_id so the weakened screen stays auditable."""
    import logging

    coordinator = _coordinator(tmp_path)
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.clean_room"):
        corpus = coordinator.forbidden_corpus(
            _request(target_role="reviewer"), _RaisingPromptRegistry()
        )
    # The unresolvable retired body is excluded (the screen is weakened)...
    assert "reviewer_prompt_v3" not in corpus
    # ...but the drop is no longer silent: it names the prompt_id.
    messages = [
        r.getMessage() for r in caplog.records if r.levelname == "WARNING"
    ]
    assert any(
        "forbidden-corpus" in m and "reviewer_prompt_v3" in m
        for m in messages
    ), messages


def test_clean_room_candidate_id_dedups_against_the_shared_log(tmp_path):
    """BUG-2: clean-room is a THIRD candidate producer and must share the
    deterministic candidate-id dedup with FIX-A + the meta channel. When
    those channels already minted a successor id for the role THIS boundary
    (recorded in ``prompt_evolution.jsonl``, not yet in the registry), the
    clean-room pass must not REUSE (orphan) that id — it consults the same
    log and skips to a fresh, non-colliding successor. So a boundary with all
    three channels active emits no duplicate candidate id and no orphaned
    (same-id / different-bytes) record."""
    from ari.rqgm.prompt_records import (
        format_candidate_record_id,
        record_prompt_evolution_event,
    )

    # FIX-A / the meta channel already minted reviewer_prompt_v4 this
    # boundary (registry's retired incumbent is v3, so the successor id both
    # of those channels deterministically compute is v4).
    record_prompt_evolution_event(tmp_path, {
        "record_type": "prompt_candidate",
        "record_id": format_candidate_record_id(0),
        "epoch_id": "epoch_005",
        "component_id": "prompt_mutator_v1",
        "candidate_id": "reviewer_prompt_v4",
        "role": "reviewer",
        "prompt_hash": "c" * 12,
        "generation_mode": "mutation",
        "mutation_kind": "threshold_tuning",
        "source_prompt_id": "reviewer_prompt_v3",
        "prompt_spec": {"full_sha256": "c" * 64},
        "status": "candidate",
    })

    coordinator = _coordinator(tmp_path, llm=lambda p: CLEAN_CANDIDATE_TEXT)
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005",
        prompts=_FakePromptRegistry(active={}),
    )
    assert outcomes[0]["status"] == "generated"
    # Skipped PAST FIX-A's v4 to a fresh id — the collision that orphaned a
    # record is gone.
    assert outcomes[0]["candidate_id"] == "reviewer_prompt_v5"

    ids = [
        r["candidate_id"]
        for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "prompt_candidate"
    ]
    assert ids == ["reviewer_prompt_v4", "reviewer_prompt_v5"]
    assert len(ids) == len(set(ids))  # no duplicate candidate id, no orphan


def test_integration_candidate_overfit_to_attack_text_rejected(tmp_path):
    """Plan 08 §5.2 rationale (b): a candidate embedding verbatim attack
    strings is blocked by the production post-screen because the forbidden
    corpus includes RawAttackRecord bodies from the checkpoint case log."""
    _plant_case_log(tmp_path, {
        "record_type": "raw_attack",
        "record_id": "atk_000001",
        "attack_claim": ATTACK_TEXT,
    })
    kernel = ConstitutionalKernel(tolerances={
        "contamination_shingle_words": 8,
        "contamination_fail_on_any_hit": True,
    })
    coordinator = _coordinator(
        tmp_path,
        llm=lambda prompt: "always reject any report that would "
                           + ATTACK_TEXT,
        kernel=kernel,
    )
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005",
        prompts=_FakePromptRegistry(active={}),
    )
    assert [o["status"] for o in outcomes] == ["rejected_contaminated"]
    assert load_prompt_evolution_log(tmp_path) == []
    kinds = [e["event"] for e in read_cleanroom_log(tmp_path)]
    assert "candidate_rejected_contaminated" in kinds
    assert "candidate_registered" not in kinds


def test_integration_summary_smuggling_attack_text_blocked_pre_screen(
    tmp_path,
):
    """The §10 covert channel in production: a FailureSummary smuggling
    recorded attack text into ``behavioral_requirements`` is blocked by the
    kernel's pre-generation screen — before any LLM call is spent."""
    _plant_case_log(tmp_path, {
        "record_type": "raw_attack",
        "record_id": "atk_000001",
        "attack_claim": ATTACK_TEXT,
    })
    captured: list[str] = []

    def stub_llm(prompt: str) -> str:
        captured.append(prompt)
        return CLEAN_CANDIDATE_TEXT

    coordinator = _coordinator(tmp_path, llm=stub_llm)
    outcomes = coordinator.process_boundary(
        _transition_dict(), epoch_id="epoch_005",
        prompts=_FakePromptRegistry(active={}),
        failure_summaries=[{
            "failure_classes": ["metric_gaming"],
            "behavioral_requirements": [ATTACK_TEXT],
            "source_refs": ["atk_000001"],
        }],
    )
    assert [o["status"] for o in outcomes] == ["failed"]
    assert outcomes[0]["detail"] == "bundle blocked by kernel"
    assert captured == []  # blocked BEFORE the one-shot generation
    kinds = [e["event"] for e in read_cleanroom_log(tmp_path)]
    assert "clean_room_violation" in kinds
    assert "generation_attempted" not in kinds


# ── §9.10 resume safety ─────────────────────────────────────────────────────


def test_pending_requests_survive_resume(tmp_path):
    request = _request()
    append_cleanroom_event(tmp_path, {
        "event": "request_created",
        "request_id": request.record_id,
        "request": request.to_dict(),
    })
    # A fresh coordinator (simulated resume) re-reads the pending request.
    coordinator = _coordinator(tmp_path)
    outcomes = coordinator.process_boundary(
        None, epoch_id="epoch_006",
        prompts=_FakePromptRegistry(active={"reviewer": "aaaaaaaaaaaa"}),
    )
    assert [o["request_id"] for o in outcomes] == [request.record_id]
    assert outcomes[0]["status"] == "generated"


# ── §9.11 config parity + simple_bfts regression ────────────────────────────


def test_clean_room_config_mirrors_defaults_yaml():
    from pathlib import Path

    import ari

    raw = yaml.safe_load(
        (Path(ari.__file__).parent / "configs" / "defaults.yaml").read_text()
    )
    yaml_block = raw["rqgm"]["clean_room"]
    typed = ARIConfig().rqgm.clean_room
    assert yaml_block["generation_backend"] == typed.generation_backend
    assert yaml_block["generator_prompt_key"] == typed.generator_prompt_key
    screen = yaml_block["contamination_screen"]
    assert screen["shingle_k"] == typed.contamination_screen.shingle_k
    assert screen["fail_on_any_hit"] == (
        typed.contamination_screen.fail_on_any_hit
    )
    # The budget rides Task 07's prompt_evolution block (plan 08 §6.5).
    assert raw["rqgm"]["prompt_evolution"][
        "max_clean_room_generations_per_epoch"
    ] == ARIConfig().rqgm.prompt_evolution.max_clean_room_generations_per_epoch


def test_runtime_tolerances_carry_screen_knobs():
    from ari.rqgm.runtime import RQGMRuntime

    tolerances = RQGMRuntime._kernel_tolerances(ARIConfig())
    assert tolerances["contamination_shingle_words"] == 8
    assert tolerances["contamination_fail_on_any_hit"] is True


def test_simple_bfts_imports_no_clean_room_and_writes_no_files(
    monkeypatch, tmp_path
):
    """simple_bfts: no clean-room module import, no rqgm_cleanroom.jsonl."""
    from ari.core import build_runtime

    class _StubMCP:
        def __init__(self, skills, disabled_tools=None):
            self.skills = list(skills)

        def list_tools(self, phase=None):
            return []

    class _StubLLM:
        def __init__(self, cfg_llm, *a, **k):
            self.config = cfg_llm
            self.mcp_client = None

        def _model_name(self):
            return "stub-model"

    class _Stub:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr("ari.mcp.client.MCPClient", _StubMCP)
    monkeypatch.setattr("ari.llm.client.LLMClient", _StubLLM)
    monkeypatch.setattr("ari.memory.letta_client.LettaMemoryClient", _Stub)
    monkeypatch.setattr("ari.evaluator.LLMEvaluator", _Stub)
    monkeypatch.setattr("ari.agent.loop.AgentLoop", _Stub)
    for name in [n for n in list(sys.modules)
                 if n == "ari.rqgm" or n.startswith("ari.rqgm.")]:
        monkeypatch.delitem(sys.modules, name)

    build_runtime(ARIConfig(), "goal", checkpoint_dir=tmp_path)
    assert "ari.rqgm.clean_room" not in sys.modules
    assert "ari.rqgm.clean_room_rules" not in sys.modules
    assert not (tmp_path / CLEANROOM_FILENAME).exists()


def test_fail_open_writer_without_checkpoint(tmp_path):
    assert append_cleanroom_event(None, {"event": "request_created"}) is False
    assert read_cleanroom_log(None) == []
    assert pending_requests(None) == []
    assert list(tmp_path.iterdir()) == []
