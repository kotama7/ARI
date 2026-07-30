"""RQGM Task 02 — persistence, transactions, and compatibility
(docs/plans/ari_rqgm/02 §5.1, §5.6-§5.9, §9 tests 1, 5-10 + smoke).

Covers ``ari.rqgm.store``: event append/replay round-trip, hash-chain
discipline over canonical payloads, prepare-without-commit crash recovery,
snapshot rebuild on mismatch, the EpochTransaction / emergency write paths,
the ImmutableAuditLog file, filename-hygiene registration, the
``rqgm.enabled=false`` zero-file regression, resume reconstruction,
prompt/cost stamping, schema validation, and the 2-epoch mini-run boundary
smoke shared with Task 01's mode test.

No test calls a real LLM: strategies/agents are deterministic mocks (P2).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ari.config import ARIConfig
from ari.rqgm.events import (
    TransitionEvent,
    expected_event_hash,
)
from ari.rqgm.registry import build_prompt_registration_payload
from ari.rqgm.store import (
    EPOCH_STATE_FILENAME,
    RQGM_AUDIT_FILENAME,
    RQGM_REGISTRY_FILENAME,
    RQGM_TRANSITIONS_FILENAME,
    ImmutableAuditLog,
    RqgmStateStore,
    committed_events,
)

RQGM_FILES = (
    RQGM_TRANSITIONS_FILENAME,
    RQGM_AUDIT_FILENAME,
    EPOCH_STATE_FILENAME,
    RQGM_REGISTRY_FILENAME,
)


@pytest.fixture(autouse=True)
def _isolate_rqgm_globals(monkeypatch):
    """No env run pin leaking in; no cost-epoch default leaking out."""
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    yield
    from ari import cost_tracker

    cost_tracker.set_default_metadata(epoch=None)


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _registration_events() -> list[TransitionEvent]:
    return [
        TransitionEvent(
            event_type="component_registered",
            payload={"component_id": "reviewer_v1", "role": "reviewer",
                     "tier": "institutional", "status": "active",
                     "prompt_id": "reviewer_prompt_v1",
                     "epoch_id": "epoch_001"},
        ),
        TransitionEvent(
            event_type="prompt_registered",
            payload=build_prompt_registration_payload(
                "reviewer_prompt_v1", "reviewer",
                source_key="orchestrator/lineage_decision",
                status="active", epoch_id="epoch_001",
            ),
        ),
    ]


# ── round-trip + crash recovery (§9 test 1) ──────────────────────────────────


def test_open_boundary_replay_roundtrip(tmp_path):
    store = RqgmStateStore()
    st0 = store.open_epoch(tmp_path, ARIConfig(), node_count=1, run_id="r1")
    assert st0.epoch.epoch_id == "epoch_000"
    assert st0.epoch.status == "open"
    assert st0.epoch.node_count_at_open == 1
    assert st0.epoch.run_id == "r1"

    st1 = store.run_boundary(
        tmp_path, st0, ARIConfig(), node_count=11,
        registry_events=_registration_events(),
    )
    assert st1.epoch.epoch_id == "epoch_001"
    assert st1.epoch.previous_epoch_id == "epoch_000"
    assert st1.epoch.opened_by_transition_id == "transition_000_to_001"
    assert st1.components.get("reviewer_v1").status == "active"
    assert st1.epoch.active_components == {"reviewer": "reviewer_v1"}
    assert st1.epoch.active_prompt_hashes.keys() == {"reviewer"}

    replayed = store.replay(tmp_path)
    assert replayed.epoch.epoch_fingerprint == st1.epoch.epoch_fingerprint
    assert replayed.prompts.registry_version() == \
        st1.prompts.registry_version()
    loaded = store.load_state(tmp_path)
    assert loaded.epoch.epoch_fingerprint == st1.epoch.epoch_fingerprint


def test_prepare_without_commit_is_discarded_on_load(tmp_path):
    store = RqgmStateStore()
    st0 = store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    # Simulate a crash mid-transaction: prepare + events but no commit.
    tx = store.begin_transaction(tmp_path, "transition_000_to_001")
    tx.__enter__()
    tx.add(TransitionEvent(
        event_type="prompt_registered",
        payload={"prompt_id": "p1", "role": "reviewer", "status": "shadow",
                 "prompt_hash": "1" * 12, "prompt_sha256": "1" * 64,
                 "source": {"kind": "committed_template", "key": "k"}},
    ))
    tx.add(TransitionEvent(event_type="epoch_close",
                           payload={"epoch_id": "epoch_000"}))
    # NO commit. Replay must see the previous epoch still open, no prompt.
    st = store.load_state(tmp_path)
    assert st.epoch.epoch_id == "epoch_000"
    assert st.epoch.status == "open"
    assert st.prompts.get("p1") is None
    assert st.epoch.epoch_fingerprint == st0.epoch.epoch_fingerprint
    # A later completed transaction supersedes the abandoned tail.
    st2 = store.run_boundary(tmp_path, st, ARIConfig(), node_count=12)
    assert st2.epoch.epoch_id == "epoch_001"
    assert st2.prompts.get("p1") is None  # abandoned event stays dead


def test_snapshots_rebuilt_on_mismatch_and_deletion(tmp_path):
    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    snap_path = tmp_path / EPOCH_STATE_FILENAME
    good = json.loads(snap_path.read_text())
    # Torn/diverged snapshot: replay wins and the rollup is rewritten.
    bad = dict(good)
    bad["epoch_fingerprint"] = "f" * 12
    snap_path.write_text(json.dumps(bad))
    loaded = store.load_state(tmp_path)
    assert loaded.epoch.epoch_fingerprint == st.epoch.epoch_fingerprint
    assert json.loads(snap_path.read_text())["epoch_fingerprint"] == \
        st.epoch.epoch_fingerprint
    # Deleted snapshots: replay-only reconstruction equals the fast path.
    snap_path.unlink()
    (tmp_path / RQGM_REGISTRY_FILENAME).unlink()
    loaded2 = store.load_state(tmp_path)
    assert loaded2.epoch.epoch_fingerprint == st.epoch.epoch_fingerprint
    assert snap_path.exists()  # rebuilt
    assert (tmp_path / RQGM_REGISTRY_FILENAME).exists()


def test_non_rqgm_checkpoint_loads_as_none(tmp_path):
    store = RqgmStateStore()
    assert store.load_state(tmp_path) is None
    assert store.replay(tmp_path) is None
    assert list(tmp_path.iterdir()) == []  # reading created nothing


# ── hash-chain discipline (§9 test 2) ────────────────────────────────────────


def test_event_chain_hashes_and_ids(tmp_path):
    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    store.run_boundary(tmp_path, st, ARIConfig(), node_count=11,
                       registry_events=_registration_events())
    lines = _read_lines(tmp_path / RQGM_TRANSITIONS_FILENAME)
    assert [d["event_type"] for d in lines] == [
        "epoch_open",
        "epoch_transaction_prepare",
        "component_registered",
        "prompt_registered",
        "epoch_close",
        "epoch_open",
        "epoch_transaction_commit",
    ]
    prev = ""
    for i, d in enumerate(lines):
        assert d["schema_version"] == 2
        assert d["event_id"] == "evt_%06d" % i
        assert d["event_hash"] == expected_event_hash(d)
        assert len(d["event_hash"]) == 64
        assert d["prev_event_hash"] == prev
        assert "ts" not in d["payload"] and "ts_iso" not in d["payload"]
        assert isinstance(d["ts"], float) and d["ts_iso"]
        prev = d["event_hash"]


def test_hashes_deterministic_across_two_processes(tmp_path):
    """P2: registry_version / epoch_fingerprint identical in a fresh process."""
    code = (
        "from types import SimpleNamespace\n"
        "from ari.rqgm.registry import (ComponentRegistry,\n"
        "    GovernedPromptRegistry, apply_registry_event)\n"
        "from ari.rqgm.state import freeze_epoch\n"
        "comps, prompts = {}, {}\n"
        "apply_registry_event(comps, prompts, 'component_registered',\n"
        "    {'component_id': 'reviewer_v1', 'role': 'reviewer',\n"
        "     'tier': 'institutional', 'status': 'active',\n"
        "     'prompt_id': 'reviewer_prompt_v1', 'epoch_id': 'epoch_000'})\n"
        "apply_registry_event(comps, prompts, 'prompt_registered',\n"
        "    {'prompt_id': 'reviewer_prompt_v1', 'role': 'reviewer',\n"
        "     'status': 'active', 'prompt_hash': 'a'*12,\n"
        "     'prompt_sha256': 'a'*64,\n"
        "     'source': {'kind': 'committed_template',\n"
        "                'key': 'evaluator/peer_review'},\n"
        "     'epoch_id': 'epoch_000'})\n"
        "regs = SimpleNamespace(components=ComponentRegistry(comps),\n"
        "                       prompts=GovernedPromptRegistry(prompts))\n"
        "cfg = SimpleNamespace(evaluator=SimpleNamespace(\n"
        "        composite='harmonic_mean', axis_weights={'novelty': 1.0}),\n"
        "    bfts=SimpleNamespace(frontier_score='scientific_plus_diversity',\n"
        "        depth_penalty_lambda=0.05, ucb_c=0.5))\n"
        "st = freeze_epoch(regs, cfg, epoch_seq=3, node_count=17,\n"
        "                  run_id='fixed_run')\n"
        "print(regs.prompts.registry_version(), st.epoch_fingerprint)\n"
    )
    import ari

    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        cwd=str(Path(ari.__file__).resolve().parents[1]),
    ).stdout.split()
    assert out == ["852526c4b2fa", "746c074fd2fc"]


# ── write-path policy (§9 test 5) ────────────────────────────────────────────


def test_transaction_rejects_managed_and_unknown_event_types(tmp_path):
    store = RqgmStateStore()
    store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    with store.begin_transaction(tmp_path, "transition_000_to_001") as tx:
        with pytest.raises(ValueError):
            tx.add(TransitionEvent(event_type="epoch_transaction_prepare",
                                   payload={}))
        with pytest.raises(ValueError):
            tx.add(TransitionEvent(event_type="epoch_transaction_commit",
                                   payload={}))
        with pytest.raises(ValueError):
            tx.add(TransitionEvent(event_type="frontier_rebuilt", payload={}))
        tx.add(TransitionEvent(event_type="epoch_close",
                               payload={"epoch_id": "epoch_000"}))
    with pytest.raises(RuntimeError):
        tx.add(TransitionEvent(event_type="epoch_close", payload={}))
    with pytest.raises(RuntimeError):
        tx.commit()


def test_all_mid_epoch_events_are_refused(tmp_path):
    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    st = store.run_boundary(tmp_path, st, ARIConfig(), node_count=11,
                            registry_events=_registration_events())
    with pytest.raises(ValueError):
        store.append_mid_epoch_event(
            tmp_path,
            TransitionEvent(event_type="prompt_status_change",
                            payload={"prompt_id": "reviewer_prompt_v1",
                                     "to_status": "banned"}),
        )
    with pytest.raises(ValueError):
        store.append_mid_epoch_event(
            tmp_path,
            TransitionEvent(
                event_type="emergency_quarantine",
                payload={"component_id": "reviewer_v1",
                         "to_status": "quarantine",
                         "epoch_id": "epoch_001"},
            ),
        )


def test_transaction_commit_id_must_match_prepare():
    events = [
        TransitionEvent(
            event_type="epoch_transaction_prepare",
            transaction_id="transition_a",
            payload={"transition_id": "transition_a"},
        ),
        TransitionEvent(
            event_type="epoch_close",
            transaction_id="transition_a",
            payload={"epoch_id": "epoch_000"},
        ),
        TransitionEvent(
            event_type="epoch_transaction_commit",
            transaction_id="transition_b",
            payload={"transition_id": "transition_b"},
        ),
    ]
    assert committed_events(events) == []


def test_audit_log_envelope_and_run_pin_noop(tmp_path):
    audit = ImmutableAuditLog(tmp_path)
    assert audit.append("observation", {"target": "reviewer_v1", "n": 1})
    assert audit.append("observation", {"target": "reviewer_v1", "n": 2})
    lines = ImmutableAuditLog.read(tmp_path)
    assert len(lines) == 2
    # Independent per-file chain, same envelope discipline.
    assert lines[0]["prev_event_hash"] == ""
    assert lines[1]["prev_event_hash"] == lines[0]["event_hash"]
    for i, d in enumerate(lines):
        assert d["event_id"] == "evt_%06d" % i
        assert d["event_hash"] == expected_event_hash(d)
    # The transitions log is untouched by audit appends.
    assert not (tmp_path / RQGM_TRANSITIONS_FILENAME).exists()
    # No run pin resolvable → silent no-op, False.
    unpinned = ImmutableAuditLog()
    assert unpinned.append("observation", {"n": 3}) is False
    assert ImmutableAuditLog.read(tmp_path / "nowhere") == []


# ── filename hygiene (§9 test 6) ─────────────────────────────────────────────


def test_rqgm_filenames_are_meta_and_trace_registered():
    from ari.paths import PathManager, _TRACE_FILES

    for name in RQGM_FILES:
        assert name in PathManager.META_FILES, name
        assert PathManager.is_meta_file(name) is True, name
    assert RQGM_TRANSITIONS_FILENAME in _TRACE_FILES
    assert RQGM_AUDIT_FILENAME in _TRACE_FILES


def test_rqgm_filenames_blocklisted_in_node_reports():
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_NAMES,
        _INTERNAL_JSON_NAMES,
        classify_artifact_role,
    )

    for name in RQGM_FILES:
        assert name in _FILES_CHANGED_BLOCKLIST_NAMES, name
    for name in (EPOCH_STATE_FILENAME, RQGM_REGISTRY_FILENAME):
        assert name in _INTERNAL_JSON_NAMES, name
        assert classify_artifact_role(name) == "unknown"


# ── rqgm.enabled=false regression (§9 test 7) ────────────────────────────────


def _stub_runtime_deps(monkeypatch):
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


def test_disabled_mode_zero_files_zero_imports(monkeypatch, tmp_path):
    """simple_bfts / rqgm.enabled=false: no RQGM module import, no RQGM file,
    reserved provenance fields stay None (plan 02 §5.8)."""
    from ari.core import build_runtime

    _stub_runtime_deps(monkeypatch)
    for name in [n for n in list(sys.modules)
                 if n == "ari.rqgm" or n.startswith("ari.rqgm.")]:
        monkeypatch.delitem(sys.modules, name)

    _, _, _, bfts, _, _ = build_runtime(ARIConfig(), "goal",
                                        checkpoint_dir=tmp_path)
    assert getattr(bfts, "rqgm", None) is None
    assert not any(n == "ari.rqgm" or n.startswith("ari.rqgm.")
                   for n in sys.modules), "default run must not import ari.rqgm"
    for name in RQGM_FILES:
        assert not (tmp_path / name).exists(), name

    # PromptUseRecord reserved fields stay None on a default-path call.
    from ari.prompts import record_prompt_use

    record_prompt_use("agent/system", "0" * 12, checkpoint_dir=tmp_path)
    rec = _read_lines(tmp_path / "prompt_trace.jsonl")[0]
    assert rec["prompt_version"] is None
    assert rec["prompt_registry_version"] is None

    # CallRecord.epoch stays None (additive default).
    from ari.cost_tracker import CallRecord

    cr = CallRecord(timestamp="", node_id="", phase="", skill="", model="",
                    prompt_tokens=1, completion_tokens=1, total_tokens=2,
                    estimated_cost_usd=0.0)
    assert cr.epoch is None


def test_disabled_short_loop_writes_no_rqgm_files(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg = ARIConfig(bfts={"max_total_nodes": 2, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    for name in RQGM_FILES:
        assert not (tmp_path / name).exists(), name


# ── resume (§9 test 8) ───────────────────────────────────────────────────────


def test_resume_replay_only_equals_snapshot_fast_path(tmp_path):
    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1, run_id="r")
    st = store.run_boundary(tmp_path, st, ARIConfig(), node_count=11,
                            registry_events=_registration_events())
    fast = store.load_state(tmp_path)
    (tmp_path / EPOCH_STATE_FILENAME).unlink()
    (tmp_path / RQGM_REGISTRY_FILENAME).unlink()
    replay_only = store.load_state(tmp_path)
    assert replay_only.epoch.epoch_id == fast.epoch.epoch_id
    assert replay_only.epoch.epoch_fingerprint == fast.epoch.epoch_fingerprint
    assert replay_only.prompts.registry_version() == \
        fast.prompts.registry_version()
    assert replay_only.components.entries().keys() == \
        fast.components.entries().keys()


def test_runtime_ensure_epoch_resumes_and_opens_fresh(tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    ep0 = rt.ensure_epoch(1, run_id="run-a")
    assert ep0.epoch_id == "epoch_000"
    # A second runtime (resume) restores the same open epoch, no new one.
    rt2 = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    ep0b = rt2.ensure_epoch(3, run_id="run-a")
    assert ep0b.epoch_id == "epoch_000"
    assert ep0b.epoch_fingerprint == ep0.epoch_fingerprint
    # No checkpoint dir → total no-op, never raises.
    rt3 = RQGMRuntime(cfg)
    assert rt3.ensure_epoch(1) is None


# ── stamping (§9 test 9) ─────────────────────────────────────────────────────


def test_governed_prompt_use_fills_reserved_fields(tmp_path):
    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1)
    st = store.run_boundary(tmp_path, st, ARIConfig(), node_count=11,
                            registry_events=_registration_events())
    st.prompts.record_use("reviewer_prompt_v1", model="stub",
                          phase="review", checkpoint_dir=tmp_path)
    rec = _read_lines(tmp_path / "prompt_trace.jsonl")[-1]
    assert rec["prompt_name"] == "orchestrator/lineage_decision"
    assert rec["prompt_version"] == "reviewer_prompt_v1"
    assert rec["prompt_registry_version"] == st.prompts.registry_version()
    assert rec["template_hash"] == \
        st.prompts.get("reviewer_prompt_v1").prompt_hash
    # Unknown prompt id: best-effort no-op, never raises.
    st.prompts.record_use("ghost_prompt_v1", checkpoint_dir=tmp_path)


def test_cost_records_carry_epoch(tmp_path, monkeypatch):
    from ari import cost_tracker

    tracker = cost_tracker.CostTracker(tmp_path)
    tracker.record(model="stub", prompt_tokens=1, completion_tokens=1,
                   epoch="epoch_002")
    line = _read_lines(tmp_path / "cost_trace.jsonl")[-1]
    assert line["epoch"] == "epoch_002"

    # The litellm success handler reads epoch from call metadata (which
    # set_default_metadata(epoch=...) injects process-wide at epoch open).
    monkeypatch.setattr(cost_tracker, "_tracker", tracker)
    usage = SimpleNamespace(prompt_tokens=2, completion_tokens=3)
    resp = SimpleNamespace(usage=usage, model="stub")
    cost_tracker._litellm_success_handler(
        {"model": "stub",
         "litellm_params": {"metadata": {"epoch": "epoch_007"}}},
        resp, None, None,
    )
    line = _read_lines(tmp_path / "cost_trace.jsonl")[-1]
    assert line["epoch"] == "epoch_007"


# ── schemas (§9 test 10) ─────────────────────────────────────────────────────


def test_schemas_load_and_validate_real_artifacts(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    store = RqgmStateStore()
    st = store.open_epoch(tmp_path, ARIConfig(), node_count=1, run_id="r")
    store.run_boundary(tmp_path, st, ARIConfig(), node_count=11,
                       registry_events=_registration_events())

    epoch_schema = schemas.load("epoch_state.schema")
    registry_schema = schemas.load("rqgm_registry.schema")
    event_schema = schemas.load("rqgm_transition_event.schema")

    epoch_doc = json.loads((tmp_path / EPOCH_STATE_FILENAME).read_text())
    jsonschema.validate(epoch_doc, epoch_schema)
    registry_doc = json.loads((tmp_path / RQGM_REGISTRY_FILENAME).read_text())
    jsonschema.validate(registry_doc, registry_schema)
    for line in _read_lines(tmp_path / RQGM_TRANSITIONS_FILENAME):
        jsonschema.validate(line, event_schema)

    # Missing base/required fields are rejected.
    broken = dict(epoch_doc)
    del broken["epoch_fingerprint"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, epoch_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"schema_version": 1}, event_schema)
    # rqgm_record_base rejects a record missing its mandatory fields.
    defs = schemas.load("rqgm_defs.schema")
    base = dict(defs["$defs"]["rqgm_record_base"])
    base["$defs"] = defs["$defs"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"record_id": "x"}, base)
    jsonschema.validate(
        {"record_id": "proposal_000", "epoch_id": "epoch_004",
         "component_id": "generator_v2", "prompt_hash": "a" * 12,
         "role": "generator", "created_at": "2026-07-05T12:00:00Z",
         "source_refs": [], "status": "candidate"},
        base,
    )


def test_schema_defs_stay_in_sync_with_python_vocabulary():
    """The shared $defs file is canonical; embedded copies + the Python
    vocabulary in ari.rqgm.events must match it exactly."""
    from ari import schemas
    from ari.rqgm import events

    defs = schemas.load("rqgm_defs.schema")["$defs"]
    assert tuple(defs["rqgm_status"]["enum"]) == events.STATUS_VALUES
    assert tuple(defs["rqgm_role"]["enum"]) == events.ROLES
    assert tuple(defs["rqgm_tier"]["enum"]) == events.TIERS
    assert set(defs["rqgm_record_base"]["required"]) == {
        "record_id", "epoch_id", "component_id", "prompt_hash",
        "role", "created_at", "source_refs", "status",
    }

    epoch_defs = schemas.load("epoch_state.schema")["$defs"]
    registry_defs = schemas.load("rqgm_registry.schema")["$defs"]
    event_defs = schemas.load("rqgm_transition_event.schema")["$defs"]
    for name, local in [("hash12", epoch_defs), ("epoch_id", epoch_defs),
                        ("transition_id", epoch_defs),
                        ("hash12", registry_defs),
                        ("sha256_hex", registry_defs),
                        ("rqgm_status", registry_defs),
                        ("rqgm_role", registry_defs),
                        ("rqgm_tier", registry_defs),
                        ("hash12", event_defs), ("event_id", event_defs)]:
        assert local[name] == defs[name], f"{name} drifted from rqgm_defs"

    event_schema = schemas.load("rqgm_transition_event.schema")
    assert tuple(event_schema["properties"]["event_type"]["enum"]) == \
        events.EVENT_TYPES


def test_epoch_config_defaults_match_defaults_yaml():
    import yaml

    from ari.config import RQGMEpochConfig
    from ari.configs import FilesystemConfigLoader

    data = FilesystemConfigLoader().load("defaults")
    if not isinstance(data, dict):  # duck-typed guard for loader drift
        data = yaml.safe_load(Path("ari-core/ari/configs/defaults.yaml").read_text())
    typed = RQGMEpochConfig()
    yaml_epoch = (data.get("rqgm") or {}).get("epoch") or {}
    assert yaml_epoch.get("boundary") == typed.boundary == "node_count"
    assert yaml_epoch.get("nodes_per_epoch") == typed.nodes_per_epoch == 10


def test_store_satisfies_epoch_store_protocol():
    from ari.protocols import EpochStore

    assert isinstance(RqgmStateStore(), EpochStore)


# ── integration smoke: 2 epochs × 2 nodes (§9 smoke) ─────────────────────────


def _make_agent():
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    return agent


def _make_strategy():
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda frontier, goal, mem: frontier[0]
    bfts.select_next_node.side_effect = lambda pending, goal, mem: pending[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    # Plain strategies must expose NO `rqgm` attribute (duck-typed gate).
    del bfts.rqgm
    return bfts


def _run_short_loop(ckpt: Path, strategy, cfg):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    all_nodes = [root]
    total = _run_loop(
        cfg, strategy, _make_agent(), [root], all_nodes,
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=ckpt, run_id="rqgm-epoch-smoke",
    )
    return total, all_nodes


def test_mini_run_crosses_epoch_boundary_transactionally(monkeypatch, tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg = ARIConfig(
        bfts={"max_total_nodes": 5, "max_parallel_nodes": 1,
              "timeout_per_node": 60},
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True, "epoch": {"nodes_per_epoch": 2}},
    )
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    governed = runtime.wrap_search_strategy(_make_strategy())
    _run_short_loop(tmp_path, governed, cfg)

    lines = _read_lines(tmp_path / RQGM_TRANSITIONS_FILENAME)
    types = [d["event_type"] for d in lines]
    # GAP-1 fix: the run STARTS with the one-time founding registration
    # transaction (every founding prompt + component through the Task 02
    # seam), then epoch_000 opens over the populated registries.
    from ari.rqgm.prompt_spec import (
        FOUNDING_COMPONENT_TABLE,
        FOUNDING_PROMPT_TABLE,
    )

    # Task 14 (plan 14 §5.3): the runtime bootstrap passes the resolved cfg,
    # so the founding prompt rows are the frozen table PLUS the one
    # cfg-derived utility_policy row (appended after the table rows, before
    # the component rows). Reviewed expectation update — §8.3.
    n_prompts = len(FOUNDING_PROMPT_TABLE) + 1
    n_components = len(FOUNDING_COMPONENT_TABLE)
    assert types[0] == "epoch_transaction_prepare"
    assert types[1:1 + n_prompts] == ["prompt_registered"] * n_prompts
    assert types[1 + n_prompts:1 + n_prompts + n_components] == \
        ["component_registered"] * n_components
    assert types[1 + n_prompts + n_components] == "epoch_transaction_commit"
    assert types[2 + n_prompts + n_components] == "epoch_open"
    assert types.count("epoch_transaction_prepare") >= 2
    assert types.count("epoch_transaction_prepare") == \
        types.count("epoch_transaction_commit")
    assert types.count("epoch_close") == types.count("epoch_open") - 1
    # Every boundary is transactional: prepare .. [intake ..] [status
    # changes ..] close .. open .. commit. Task 07 candidate intake (plan 07
    # §5.3 / plan 09 T1) registers this boundary's minted candidates (FIX-A +
    # meta + Task 14 utility channels) at status=candidate, and the resolved
    # transition's T-edge status changes (Task 14 §5.5: the utility_policy
    # spine is now ALIVE, so a boundary carries real ``prompt_status_change``
    # / ``component_status_change`` events — pre-fix the dead spine produced
    # none in a short run) commit in the SAME boundary transaction. So between
    # the prepare and the close sit zero or more ``prompt_registered`` intake
    # events followed by zero or more status-change events.
    _boundary_body = {
        "prompt_registered", "prompt_status_change", "component_status_change",
    }
    for i, t in enumerate(types):
        if t == "epoch_close":
            j = i - 1
            while j >= 0 and types[j] in _boundary_body:
                j -= 1
            assert types[j] == "epoch_transaction_prepare"
            assert types[i + 1] == "epoch_open"
            assert types[i + 2] == "epoch_transaction_commit"
    # Verifiable chain end to end.
    prev = ""
    for d in lines:
        assert d["event_hash"] == expected_event_hash(d)
        assert d["prev_event_hash"] == prev
        prev = d["event_hash"]
    # Snapshot fast-path agrees with the log.
    snap = json.loads((tmp_path / EPOCH_STATE_FILENAME).read_text())
    assert snap["status"] == "open"
    assert snap["epoch_id"] >= "epoch_001"
    assert runtime.current_epoch.epoch_id == snap["epoch_id"]
    # Per-epoch cost attribution was stamped process-wide.
    from ari.cost_tracker import _DEFAULT_METADATA

    assert _DEFAULT_METADATA.get("epoch") == snap["epoch_id"]
    # End-of-run boundary flush regression: with max_total_nodes=5 and
    # nodes_per_epoch=2, the final iteration creates the 5th node AFTER the
    # last loop-head tick, so pre-fix the trailing epoch stayed open with 2
    # completed nodes. The end-of-run tick in _run_loop must now fire that
    # boundary too: founding registration + two full boundary transactions,
    # final epoch epoch_002.
    assert types.count("epoch_transaction_prepare") == 3
    assert snap["epoch_id"] == "epoch_002"


def test_final_iteration_epoch_boundary_flushed_at_end_of_run(
    monkeypatch, tmp_path,
):
    """v6-shape regression (end-of-run boundary flush in _run_loop).

    With ``nodes_per_epoch=1``, ``max_total_nodes=2``,
    ``max_parallel_nodes=1`` and a sequential stub agent, the 2nd node is
    appended by ``expand()`` AFTER the last outer-loop-head epoch tick, and
    the while guard exits on ``max_total_nodes`` before any tick can observe
    it. Pre-fix, every such run left its final epoch open with only the
    founding ``epoch_open`` in the transition log. The end-of-run flush in
    ``_run_loop`` must produce exactly ONE boundary quadruple — the exact
    event sequence is asserted (not ``>= 1``) so reverting the flush fails
    this test.
    """
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    cfg = ARIConfig(
        bfts={"max_total_nodes": 2, "max_parallel_nodes": 1,
              "timeout_per_node": 60},
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True,
              "epoch": {"nodes_per_epoch": 1},
              "governance": {"enabled": False},   # v6/v4 B4 ablation rung
              "adversarial": {"enabled": False}},  # keep the test offline
    )
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    governed = runtime.wrap_search_strategy(_make_strategy())
    _, all_nodes = _run_short_loop(tmp_path, governed, cfg)

    # Both nodes actually ran to completion (the shape's precondition).
    assert [(n.id, n.status.value) for n in all_nodes] == \
        [("node_root", "success"), ("child_1", "success")]

    lines = _read_lines(tmp_path / RQGM_TRANSITIONS_FILENAME)
    types = [d["event_type"] for d in lines]
    # EXACT sequence: the one-time founding registration transaction
    # (GAP-1 fix), the founding open, then precisely one transactional
    # boundary quadruple fired by the end-of-run flush — nothing else.
    from ari.rqgm.prompt_spec import (
        FOUNDING_COMPONENT_TABLE,
        FOUNDING_PROMPT_TABLE,
    )

    # Task 07 candidate intake (plan 07 §5.3 / plan 09 T1): with governance
    # off (FIX-A skipped) the meta channel still mints ONE boundary
    # candidate, now registered at status=candidate inside the SAME boundary
    # transaction — a ``prompt_registered`` between the boundary prepare and
    # close. Pre-fix this exact sequence encoded the bug where the minted
    # candidate was never registered (an empty boundary quadruple).
    #
    # Task 14 (plan 14 §5.4): the PolicyMutator runs in the SAME
    # candidate-minting window and its utility-policy candidate rides the
    # SAME intake, so the boundary now registers TWO candidates — the meta
    # channel's prompt candidate and the boundary's policy candidate. That
    # second line IS the cause half of P1 becoming reachable: before Task 14
    # nothing could ever propose a successor score.
    assert types == (
        ["epoch_transaction_prepare"]
        # +1: the Task 14 cfg-derived utility_policy row (plan 14 §5.3).
        + ["prompt_registered"] * (len(FOUNDING_PROMPT_TABLE) + 1)
        + ["component_registered"] * len(FOUNDING_COMPONENT_TABLE)
        + [
            "epoch_transaction_commit",
            "epoch_open",
            "epoch_transaction_prepare",
            "prompt_registered",          # meta-channel candidate intake
            "prompt_registered",          # Task 14 utility-policy candidate
            "epoch_close",
            "epoch_open",
            "epoch_transaction_commit",
        ]
    )
    # Hash chain stays verifiable across the flush-written events.
    prev = ""
    for d in lines:
        assert d["event_hash"] == expected_event_hash(d)
        assert d["prev_event_hash"] == prev
        prev = d["event_hash"]
    # The boundary opened a fresh (empty) successor epoch — matching
    # snapshot/resume expectations; it stays open at end-of-run.
    snap = json.loads((tmp_path / EPOCH_STATE_FILENAME).read_text())
    assert snap["epoch_id"] == "epoch_001"
    assert snap["status"] == "open"
    assert runtime.current_epoch.epoch_id == "epoch_001"


def test_a_failed_registry_write_aborts_instead_of_committing(tmp_path):
    """`append_events` RETURNS False on failure and never raises (its own
    docstring says so). `EpochTransaction.add`/`commit` discarded that bool, so
    a registry mutation whose write failed was still marked committed: the audit
    log listed sanctions/retirements that never entered rqgm_transitions.jsonl,
    and the snapshot-vs-replay integrity check AGREED because the replay was
    missing the same event. This is the P4 sanction path degrading invisibly.
    `open_epoch` in the same module already checked the bool — an omission, not
    house style."""
    from ari.rqgm.events import TransitionEvent
    from ari.rqgm.store import EpochTransaction, RqgmStateStore

    store = RqgmStateStore()
    real = store.append_events

    def _failing(ckpt, events):
        if any(e.event_type == "component_status_change" for e in events):
            return False                      # e.g. ENOSPC
        return real(ckpt, events)

    store.append_events = _failing
    tx = EpochTransaction(store, tmp_path, "transition_000_to_001")
    with pytest.raises(RuntimeError, match="could not persist"):
        with tx:
            tx.add(TransitionEvent(
                event_type="component_status_change",
                payload={"component_id": "reviewer_v1", "status": "retired"}))
            tx.commit()
    assert tx._committed is False, "a sanction that was not written must not read as applied"


def test_a_successful_transaction_still_commits(tmp_path):
    """The guard must not break the happy path."""
    from ari.rqgm.events import TransitionEvent
    from ari.rqgm.store import EpochTransaction, RqgmStateStore

    tx = EpochTransaction(RqgmStateStore(), tmp_path, "transition_000_to_001")
    with tx:
        tx.add(TransitionEvent(
            event_type="component_status_change",
            payload={"component_id": "reviewer_v1", "status": "retired"}))
        tx.commit()
    assert tx._committed is True
    body = (tmp_path / "rqgm_transitions.jsonl").read_text()
    assert "epoch_transaction_commit" in body and "component_status_change" in body
