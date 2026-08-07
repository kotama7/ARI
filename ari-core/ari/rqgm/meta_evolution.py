"""Meta-agent evolution: coordinator, containment, sandbox/shadow (RQGM Task 11).

Layer 2 (the meta tier: PromptMutator, CleanRoomPromptGenerator, the replay
selector and failure-summary compressor seams) becomes an evolution target
under strictly narrower authority than the institutional layer
(``docs/concepts/rqgm_architecture.md``, "Key invariants" — meta-tier
authority limits). The governing invariant (SPEC invariant 18):
governance agents may evolve, but their authority cannot expand.

This module implements:

* :class:`MetaAgentOutputRecord` — the ONLY artifact a meta-agent produces
  (§6.2); every meta output is a *candidate*, never an activation (§5.3).
  Storage: append-only ``{ckpt}/rqgm_meta_outputs.jsonl`` (fail-open writer,
  the ``prompt_evolution.jsonl`` posture; ``record_id`` is derived from the
  content hashes so MCP-style retries dedup at read time, §10).
* :class:`PromptRegistryView` / :class:`ComponentRegistryView` — frozen
  read-only views (§5.5 layer 1, "no handle"): retired prompts appear as
  ``{prompt_id, role, status}`` stubs with **no text, no path, no hash**.
* :func:`assemble_filtered_inputs` — the M7 input filter: committed role
  catalogs + abstract failure summaries + ids only; never prompt text.
* :class:`MetaSandboxMCPProxy` — the §5.5 layer-3 tool filter (same
  duck-type as ``MCPClient``; structural contract:
  :class:`ari.protocols.MCPToolCaller`), plus :func:`run_meta_sandboxed`,
  a thin wrapper over ``ari.agent.react_driver.run_react``.
* :class:`MetaEvolutionCoordinator` — the non-evolving epoch-boundary driver
  (§5.4), invoked between ``GovernanceOrchestrator.audit_epoch`` and
  ``RegistryTransitionEngine.resolve_transition`` (SPEC steps 12→13).
  Lineage-hook discipline: config-gated, budget-capped, best-effort — a
  meta-evolution failure degrades to "no candidates this epoch".
* :class:`MetaCandidateSandbox` / :func:`downstream_fate` /
  :class:`MetaCandidateEvaluation` — deterministic sandbox evaluation over
  frozen input bundles (cached), shadow bookkeeping, and the §6.3 record
  consumed by Task 09 through the existing ``candidate_evaluations`` seam.
* :class:`MetricSpecWeightCap` — the §5.8 constitutional cap on the one
  ungoverned meta channel (``make_metric_spec`` rewriting evaluator weights
  mid-run): attached to the node executor only under ``ari_rqgm``, so
  ``simple_bfts`` behavior is byte-for-byte unchanged.

Under ``simple_bfts`` this module is never imported (``build_runtime``
conditional) and no meta file is ever created. VirSci-independent. Every
*judgment* here is deterministic (P2): meta-agent invokers are injectable
(tests use deterministic fakes; NEVER a real LLM in tests).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from ari.rqgm import meta_rules
from ari.rqgm.events import (
    ACTIVE_STATUSES,
    canonical_json,
    hash12,
    payload_hash,
)
from ari.rqgm.prompt_loader import _resolve_checkpoint_dir
from ari.rqgm.prompt_records import (
    PromptCandidate,
    candidate_from_dict,
    record_prompt_evolution_event,
)

log = logging.getLogger(__name__)

META_OUTPUTS_FILENAME = "rqgm_meta_outputs.jsonl"

#: Statuses whose prompt entries are reduced to no-text stubs in the views.
_RETIRED_STATUSES: tuple[str, ...] = ("retired", "banned")

# Serialises appends (boundary thread + best-effort callers) — the
# ``record_prompt_use`` lock discipline.
_LOCK = threading.Lock()


def _now_iso() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── MetaAgentOutputRecord (plan 11 §6.2) ────────────────────────────────────


def format_meta_output_record_id(
    component_id: str,
    epoch_id: str,
    output_kind: str,
    input_bundle_hash: str,
    output_payload_hash: str,
) -> str:
    """Content-derived id (``meta_out_<hash12>``): an MCP-style retry of the
    same invocation reproduces the same id, so duplicate appends dedup at
    read time (plan 11 §10). No wall clock enters the id (P2)."""
    return "meta_out_" + hash12(
        canonical_json(
            [component_id, epoch_id, output_kind, input_bundle_hash,
             output_payload_hash]
        )
    )


@dataclass(frozen=True)
class MetaAgentOutputRecord:
    """One meta-agent output (§6.2) — always inert provenance: routing into
    the Task 07 intake is the coordinator's separate, kernel-gated step."""

    record_id: str
    epoch_id: str
    component_id: str
    role: str
    output_kind: str
    target_role: str
    prompt_hash: str | None = None
    candidate_ref: str = ""
    expected_improvement: str = ""
    shadow: bool = False
    sandboxed: bool = True
    input_bundle_hash: str = ""
    output_payload_hash: str = ""
    status: str = "recorded"
    created_at: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "record_type": "meta_agent_output",
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
            "status": self.status,
            "output_kind": self.output_kind,
            "target_role": self.target_role,
            "candidate_ref": self.candidate_ref,
            "expected_improvement": self.expected_improvement,
            "shadow": self.shadow,
            "sandboxed": self.sandboxed,
            "input_bundle_hash": self.input_bundle_hash,
            "output_payload_hash": self.output_payload_hash,
        }


def meta_output_from_dict(d: dict) -> MetaAgentOutputRecord:
    return MetaAgentOutputRecord(
        record_id=str(d.get("record_id", "")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(d.get("component_id", "")),
        role=str(d.get("role", "")),
        output_kind=str(d.get("output_kind", "")),
        target_role=str(d.get("target_role", "")),
        prompt_hash=d.get("prompt_hash"),
        candidate_ref=str(d.get("candidate_ref", "")),
        expected_improvement=str(d.get("expected_improvement", "")),
        shadow=bool(d.get("shadow", False)),
        sandboxed=bool(d.get("sandboxed", True)),
        input_bundle_hash=str(d.get("input_bundle_hash", "")),
        output_payload_hash=str(d.get("output_payload_hash", "")),
        status=str(d.get("status", "recorded")),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(d.get("source_refs") or ()),
    )


def append_meta_output(checkpoint_dir, record) -> bool:
    """Append one line to ``{ckpt}/rqgm_meta_outputs.jsonl``.

    Fail-open like every ARI provenance writer: no resolvable checkpoint →
    no-op ``False``; I/O failure is logged, never raised into the run loop.
    """
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return False
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    if not payload.get("created_at"):
        payload["created_at"] = _now_iso()
    try:
        with _LOCK:
            Path(ckpt).mkdir(parents=True, exist_ok=True)
            with open(
                Path(ckpt) / META_OUTPUTS_FILENAME, "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception:
        log.warning("meta-output append failed", exc_info=True)
        return False


def load_meta_outputs_log(checkpoint_dir) -> list[dict]:
    """Absence-tolerant reader with read-time dedup by ``record_id`` (first
    line wins — the §10 retry-idempotency rule; content-derived ids make
    duplicates byte-equal anyway)."""
    out: list[dict] = []
    seen: set[str] = set()
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return out
    path = Path(ckpt) / META_OUTPUTS_FILENAME
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                rid = str(d.get("record_id", ""))
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                out.append(d)
    except OSError:
        pass
    return out


# ── read-only registry views (plan 11 §5.5 layer 1: no handle) ──────────────


@dataclass(frozen=True)
class PromptEntryView:
    """Status/role metadata of one governed prompt — never text, never a
    path. Retired/banned entries are stubs with an empty ``prompt_hash``."""

    prompt_id: str
    role: str
    status: str
    prompt_hash: str = ""


@dataclass(frozen=True)
class ComponentEntryView:
    """Status/role/tier metadata of one component plus its (read-only)
    capability declaration — flags are authority metadata, not secrets."""

    component_id: str
    role: str
    tier: str
    status: str
    prompt_id: str = ""
    capabilities: tuple = ()  # sorted (key, value) pairs — hashable/frozen

    def capability_dict(self) -> dict:
        return {k: v for k, v in self.capabilities}


@dataclass(frozen=True)
class PromptRegistryView:
    entries: tuple[PromptEntryView, ...] = ()


@dataclass(frozen=True)
class ComponentRegistryView:
    entries: tuple[ComponentEntryView, ...] = ()


def _freeze_capabilities(caps) -> tuple:
    if not isinstance(caps, dict):
        return ()
    out = []
    for key in sorted(caps):
        value = caps[key]
        if isinstance(value, (list, tuple)):
            value = tuple(str(v) for v in value)
        out.append((str(key), value))
    return tuple(out)


def build_prompt_registry_view(prompts) -> PromptRegistryView:
    """Frozen view over a ``GovernedPromptRegistry`` (or entry map). Retired
    entries lose text, path, AND hash — a meta-agent cannot even fingerprint
    retired bytes through the view (M7 defense in depth)."""
    entries = getattr(prompts, "entries", None)
    entry_map = entries() if callable(entries) else dict(prompts or {})
    views: list[PromptEntryView] = []
    for prompt_id in sorted(entry_map):
        entry = entry_map[prompt_id]
        status = str(getattr(entry, "status", "") or "")
        if status in _RETIRED_STATUSES:
            views.append(
                PromptEntryView(
                    prompt_id=str(prompt_id),
                    role=str(getattr(entry, "role", "") or ""),
                    status=status,
                )
            )
        else:
            views.append(
                PromptEntryView(
                    prompt_id=str(prompt_id),
                    role=str(getattr(entry, "role", "") or ""),
                    status=status,
                    prompt_hash=str(getattr(entry, "prompt_hash", "") or ""),
                )
            )
    return PromptRegistryView(entries=tuple(views))


def build_component_registry_view(components) -> ComponentRegistryView:
    entries = getattr(components, "entries", None)
    entry_map = entries() if callable(entries) else dict(components or {})
    views: list[ComponentEntryView] = []
    for component_id in sorted(entry_map):
        entry = entry_map[component_id]
        views.append(
            ComponentEntryView(
                component_id=str(component_id),
                role=str(getattr(entry, "role", "") or ""),
                tier=str(getattr(entry, "tier", "") or "institutional"),
                status=str(getattr(entry, "status", "") or ""),
                prompt_id=str(getattr(entry, "prompt_id", "") or ""),
                capabilities=_freeze_capabilities(
                    getattr(entry, "capabilities", None)
                ),
            )
        )
    return ComponentRegistryView(entries=tuple(views))


def _view_entry_dict(view: ComponentEntryView) -> dict:
    """The §6.1-shaped dict the kernel's capability checks consume."""
    out = {
        "component_id": view.component_id,
        "role": view.role,
        "tier": view.tier,
        "status": view.status,
        "capabilities": view.capability_dict(),
    }
    return out


# ── filtered input bundles (M7; plan 11 §5.5 layer 1) ───────────────────────


def _abstract_failure_summaries(replay_pool) -> list[dict]:
    """Abstract views only (Task 06 contamination-free ``abstract_view``);
    raw attack/defense text never enters a meta input bundle."""
    if replay_pool is None:
        return []
    try:
        cases = replay_pool.cases() if callable(
            getattr(replay_pool, "cases", None)
        ) else list(replay_pool or ())
    except Exception:
        return []
    out = []
    for case in cases:
        view = (
            case.get("abstract_view")
            if isinstance(case, dict)
            else getattr(case, "abstract_view", None)
        )
        if isinstance(view, dict) and view:
            out.append(dict(view))
    return out


def _governance_summary(governance_report) -> dict:
    """Categorical rollup of the epoch's GovernanceReport: action counts
    only — no free text, no evidence, no prompt bytes."""
    if governance_report is None:
        return {}
    report = (
        governance_report
        if isinstance(governance_report, dict)
        else getattr(governance_report, "to_dict", lambda: {})()
    )
    counts: dict[str, int] = {}
    for rec in report.get("recommendations") or ():
        rec = rec if isinstance(rec, dict) else {}
        action = str(rec.get("action", "") or "")
        if action:
            counts[action] = counts.get(action, 0) + 1
    out: dict = {"epoch_id": str(report.get("epoch_id", "") or "")}
    if counts:
        out["recommendation_counts"] = {a: counts[a] for a in sorted(counts)}
    return out


def assemble_filtered_inputs(
    meta_entry,
    *,
    governance_report=None,
    replay_pool=None,
    replay_case_ids=(),
) -> dict:
    """The pre-filtered input bundle for one meta-agent invocation (§5.5).

    Contents are the Task 08 allowed-inputs family only: the committed
    role-spec catalog, the founding output-schema contract, mandatory
    constitutional constraints, abstract failure summaries, replay-case
    *ids*, and a categorical governance rollup. Retired prompt text is
    structurally absent (M7): nothing here dereferences a registry.
    """
    from ari.rqgm.clean_room import ROLE_SPECS, role_output_schema
    from ari.rqgm.prompt_spec import REQUIRED_CONSTRAINTS_BY_ROLE

    role = str(
        getattr(meta_entry, "role", None)
        or (meta_entry.get("role") if isinstance(meta_entry, dict) else "")
    )
    bundle = {
        "meta_role": role,
        "role_spec": str(ROLE_SPECS.get(role, "")),
        "output_schema": role_output_schema(role),
        "constitutional_constraints": list(
            REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
        ),
        "failure_summaries": _abstract_failure_summaries(replay_pool),
        "replay_case_ids": sorted(str(c) for c in replay_case_ids or ()),
        "governance_summary": _governance_summary(governance_report),
    }
    return bundle


def input_bundle_hash(bundle: dict) -> str:
    """``hash12(canonical_json(bundle))`` — the single RQGM hash scheme."""
    return payload_hash(bundle)


# ── MetaSandboxMCPProxy (plan 11 §5.5 layer 3) ──────────────────────────────


class MetaSandboxMCPProxy:
    """Phase-filtered tool surface for sandboxed meta rollouts.

    Same duck-type as ``ari.mcp.client.MCPClient`` (structural contract:
    :class:`ari.protocols.MCPToolCaller`): ``list_tools`` / ``call_tool`` /
    ``close_all`` / ``to_claude_mcp_config`` / ``_COW_TOOLS``. Only the
    allowlisted read-only helper tools and the synthesized *final_tool*
    (``submit_meta_output``) are exposed; anything else returns the exact
    ``{"error": ...}`` envelope without dispatching (M2/M4/M7: no
    memory-write, registry, or audit tools exist inside the sandbox).
    """

    DEFAULT_FINAL_TOOL = "submit_meta_output"

    def __init__(
        self,
        inner=None,
        *,
        allowed_tools=(),
        final_tool: str = DEFAULT_FINAL_TOOL,
    ) -> None:
        self.inner = inner
        self.final_tool = str(final_tool)
        self._allowed: frozenset = frozenset(
            str(t) for t in allowed_tools or ()
        ) | {self.final_tool}

    @property
    def _COW_TOOLS(self):  # noqa: N802 - mirrors the MCPClient attribute
        # Copy-on-write node tools are a work-dir mutation surface; the meta
        # sandbox never exposes them.
        return frozenset()

    def list_tools(self, phase: str | None = None) -> list[dict]:
        tools: list[dict] = []
        if self.inner is not None:
            try:
                for tool in self.inner.list_tools(phase) or ():
                    if str(tool.get("name", "")) in self._allowed:
                        tools.append(tool)
            except Exception:
                log.warning("sandbox inner list_tools failed", exc_info=True)
        if not any(t.get("name") == self.final_tool for t in tools):
            tools.append({
                "name": self.final_tool,
                "description": (
                    "Submit the meta-agent output (single JSON object). "
                    "Terminates the sandboxed rollout."
                ),
                "inputSchema": {"type": "object"},
            })
        return tools

    def call_tool(self, tool_name, args, *, cow_node_id=None) -> dict:
        name = str(tool_name)
        if name not in self._allowed:
            return {
                "error": (
                    f"tool {name!r} is not available inside the meta "
                    "sandbox (read-only allowlist + final tool only)"
                )
            }
        if name == self.final_tool or self.inner is None:
            # The final tool is synthesized: run_react captures its args as
            # the rollout result; there is nothing to dispatch.
            return {"result": "ok"}
        try:
            return self.inner.call_tool(name, args, cow_node_id=cow_node_id)
        except TypeError:
            return self.inner.call_tool(name, args)

    def to_claude_mcp_config(self, *args, **kwargs) -> dict:
        # No external server ever reaches a sandboxed meta rollout.
        return {}

    def close_all(self) -> None:
        # The proxy never owns the inner client's lifecycle.
        return None


def run_meta_sandboxed(
    llm,
    proxy: MetaSandboxMCPProxy,
    *,
    system_prompt: str,
    user_prompt: str,
    sandbox,
    allow_paths=None,
    max_steps: int = 8,
) -> dict:
    """Thin wrapper over ``ari.agent.react_driver.run_react`` (§5.5 layer 3):
    scratch-dir sandbox, path validation, proxy tool surface, terminated by
    the synthesized final tool. One-shot ``LLMClient.complete`` calls are
    preferred when the role needs no iteration — this harness exists for the
    agentic minority."""
    from ari.agent.react_driver import run_react

    return run_react(
        llm,
        proxy,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        agent_phase="rqgm_meta",
        final_tool=proxy.final_tool,
        max_steps=max_steps,
        sandbox=Path(sandbox),
        allow_paths=[Path(p) for p in (allow_paths or [Path(sandbox)])],
    )


# ── MetaEvolutionCoordinator (plan 11 §5.4) ─────────────────────────────────


@dataclass(frozen=True)
class MetaEvolutionResult:
    """One boundary step's outcome: records are provenance; candidates were
    routed to the Task 07 intake; recommendations/summaries are non-binding
    inputs the GovernanceOrchestrator may ignore (§5.3)."""

    records: tuple = ()
    candidates: tuple = ()
    replay_recommendations: tuple = ()
    failure_summaries: tuple = ()
    skipped: tuple = ()


class MetaEvolutionCoordinator:
    """Non-evolving driver of the meta tier (fixed-tier trust, no judgment).

    Invoked once per epoch boundary, after ``audit_epoch`` and before
    ``resolve_transition``. It invokes meta-agents through injectable
    *invokers* (``role -> callable(inputs dict) -> output dict | None``;
    tests use deterministic fakes), records every output, and forwards
    admissible candidates to the Task 07 intake at ``status: candidate``.
    The coordinator appends to the audit log — never the agents (M4).
    """

    def __init__(
        self,
        rqgm_cfg=None,
        kernel=None,
        *,
        audit_log=None,
        checkpoint_dir=None,
        invokers: dict | None = None,
    ) -> None:
        self._cfg = rqgm_cfg
        self._kernel = kernel
        self._audit_log = audit_log
        self._ckpt = checkpoint_dir
        self._invokers = dict(invokers or {})

    # ── config views (duck-typed; defaults mirror defaults.yaml) ──────

    def _me_cfg(self):
        cfg = self._cfg
        if isinstance(cfg, dict):
            return cfg.get("meta_evolution")
        return getattr(cfg, "meta_evolution", None)

    def enabled(self) -> bool:
        me = self._me_cfg()
        if isinstance(me, dict):
            return bool(me.get("enabled", True))
        return bool(getattr(me, "enabled", True))

    def evolving_roles(self) -> tuple:
        me = self._me_cfg()
        if isinstance(me, dict):
            raw = me.get("evolving_roles")
        else:
            raw = getattr(me, "evolving_roles", None)
        if raw is None:
            return meta_rules.META_EVOLVING_ROLES
        return tuple(str(r) for r in raw)

    def max_meta_candidates_per_epoch(self) -> int:
        me = self._me_cfg()
        if isinstance(me, dict):
            raw = me.get("max_meta_candidates_per_epoch", 1)
        else:
            raw = getattr(me, "max_meta_candidates_per_epoch", 1)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1

    # ── audit plumbing (coordinator-only writes; M4) ──────────────────

    def _audit(self, event_type: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        try:
            self._audit_log.append(event_type, payload)
        except Exception:
            log.warning("meta audit append failed", exc_info=True)

    # ── the boundary step ─────────────────────────────────────────────

    def run_epoch_boundary_step(
        self,
        *,
        epoch_state=None,
        governance_report=None,
        components=None,
        prompts=None,
        replay_pool=None,
    ) -> MetaEvolutionResult:
        """Plan 11 §5.4 (with the lineage-hook fail-open discipline).

        Never raises; every skip and denial leaves an audit line. Nothing in
        this method mutates any registry, score, frontier entry, or
        governance verdict (§5.3 — the byte-identity test pins it).
        """
        epoch_id = str(getattr(epoch_state, "epoch_id", "") or "")
        if not self.enabled():
            self._audit("meta_evolution_skipped", {
                "epoch_id": epoch_id, "reason": "meta_evolution.enabled=false",
            })
            return MetaEvolutionResult(
                skipped=("meta_evolution.enabled=false",)
            )
        component_view = build_component_registry_view(components)
        # The prompt view is built for handoff parity (meta invokers receive
        # views only); unused entries cost nothing.
        prompt_view = build_prompt_registry_view(prompts)
        evolving = set(self.evolving_roles())
        records: list[MetaAgentOutputRecord] = []
        candidates: list[PromptCandidate] = []
        recommendations: list[dict] = []
        summaries: list[dict] = []
        skipped: list[str] = []
        budget = self.max_meta_candidates_per_epoch()
        emitted = self._candidates_already_emitted(epoch_id)
        for view in self._active_meta_agents(component_view, evolving):
            invoker = self._invokers.get(view.role)
            if invoker is None:
                # Root cause of the silent-boundary gap: the live runtime
                # registers no invokers, so every agent used to fall
                # through here without a trace. The reason now rides the
                # boundary's ``meta_evolution`` summary line below.
                skipped.append(
                    f"no invoker registered for role {view.role!r} "
                    f"({view.component_id})"
                )
                continue
            inputs = assemble_filtered_inputs(
                view,
                governance_report=governance_report,
                replay_pool=replay_pool,
            )
            bundle_hash = input_bundle_hash(inputs)
            try:
                output = invoker(dict(inputs), prompt_view)
            except TypeError:
                try:
                    output = invoker(dict(inputs))
                except Exception:
                    log.warning("meta invoker failed", exc_info=True)
                    skipped.append(f"invoker failed for {view.component_id}")
                    continue
            except Exception:
                log.warning("meta invoker failed", exc_info=True)
                skipped.append(f"invoker failed for {view.component_id}")
                continue
            if not isinstance(output, dict) or not output:
                skipped.append(f"empty output from {view.component_id}")
                continue
            kind = str(output.get("output_kind", ""))
            if kind not in meta_rules.OUTPUT_KINDS:
                reason = f"unknown output_kind {kind!r} from {view.component_id}"
                skipped.append(reason)
                self._audit("meta_output_denied", {
                    "epoch_id": epoch_id, "component_id": view.component_id,
                    "reason": reason,
                })
                continue
            if kind in ("prompt_candidate", "clean_room_candidate"):
                if emitted >= budget:
                    reason = (
                        f"max_meta_candidates_per_epoch={budget} reached "
                        f"in {epoch_id}"
                    )
                    skipped.append(reason)
                    self._audit("meta_output_budget_skipped", {
                        "epoch_id": epoch_id,
                        "component_id": view.component_id,
                        "reason": reason,
                    })
                    continue
            record = self._to_output_record(
                view, output, epoch_id=epoch_id, bundle_hash=bundle_hash
            )
            denial = self._kernel_gate(view, record)
            if denial is not None:
                record = replace(record, status="denied")
                append_meta_output(self._ckpt, record)
                skipped.append(denial)
                self._audit("meta_output_denied", {
                    "epoch_id": epoch_id, "component_id": view.component_id,
                    "record_id": record.record_id, "reason": denial,
                })
                continue
            append_meta_output(self._ckpt, record)
            self._audit("meta_agent_output", record.to_dict())
            records.append(record)
            routed = self._route_output(view, output, record)
            if isinstance(routed, PromptCandidate):
                candidates.append(routed)
                emitted += 1
            elif kind == "replay_case_recommendation" and isinstance(
                routed, dict
            ):
                recommendations.append(routed)
            elif kind == "failure_summary" and isinstance(routed, dict):
                summaries.append(routed)
        # Boundary summary line (silent-enabled-path gap fix): the enabled
        # path is now always audit-visible, no-op boundaries included —
        # the disabled path keeps its pinned ``meta_evolution_skipped``.
        self._audit("meta_evolution", {
            "epoch_id": epoch_id,
            "outcome": "proposed" if candidates else "no_op",
            "candidate_count": len(candidates),
            "output_count": len(records),
            "skipped": list(skipped),
        })
        return MetaEvolutionResult(
            records=tuple(records),
            candidates=tuple(candidates),
            replay_recommendations=tuple(recommendations),
            failure_summaries=tuple(summaries),
            skipped=tuple(skipped),
        )

    # ── internals ─────────────────────────────────────────────────────

    def _active_meta_agents(
        self, component_view: ComponentRegistryView, evolving: set
    ) -> list[ComponentEntryView]:
        return [
            v
            for v in component_view.entries
            if v.tier == "meta"
            and v.status in ACTIVE_STATUSES
            and v.role in evolving
        ]

    def _candidates_already_emitted(self, epoch_id: str) -> int:
        """Resume-safe budget floor from the checkpoint log (in-memory BFTS
        state is never relied on). Shadow-stamped records are excluded: only
        the shadow-evaluation driver writes them, they are never routed
        (``_route_output`` refuses them), and they count against the Task 12
        shadow budget instead — every routed candidate has shadow=False."""
        count = 0
        for rec in load_meta_outputs_log(self._ckpt):
            if (
                str(rec.get("epoch_id", "")) == epoch_id
                and str(rec.get("status", "")) == "recorded"
                and str(rec.get("output_kind", "")) in (
                    "prompt_candidate", "clean_room_candidate"
                )
                and not rec.get("shadow", False)
            ):
                count += 1
        return count

    def _to_output_record(
        self, view: ComponentEntryView, output: dict, *, epoch_id: str,
        bundle_hash: str,
    ) -> MetaAgentOutputRecord:
        kind = str(output.get("output_kind", ""))
        payload_keys = ("candidate", "replay_case_ids", "failure_summary")
        payload = {k: output.get(k) for k in payload_keys if k in output}
        out_hash = payload_hash(payload)
        candidate = output.get("candidate")
        candidate_ref = str(
            (candidate or {}).get("candidate_id", "")
            if isinstance(candidate, dict) else ""
        )
        record_id = format_meta_output_record_id(
            view.component_id, epoch_id, kind, bundle_hash, out_hash
        )
        return MetaAgentOutputRecord(
            record_id=record_id,
            epoch_id=epoch_id,
            component_id=view.component_id,
            role=view.role,
            output_kind=kind,
            target_role=str(output.get("target_role", "") or ""),
            prompt_hash=None,
            candidate_ref=candidate_ref,
            expected_improvement=str(
                output.get("expected_improvement", "") or ""
            ),
            # ``shadow`` is coordinator truth, never invoker (LLM) output: a
            # coordinator-invoked incumbent is always live (shadow=False and
            # routed). Shadow stamping belongs solely to the shadow-evaluation
            # driver, which appends records directly and bypasses routing
            # (§5.7 "routed nowhere") — trusting the invoker field would let
            # a meta-agent route a candidate while its truth record disclaims
            # it, and dodge the resume-safe budget floor.
            shadow=False,
            sandboxed=True,
            input_bundle_hash=bundle_hash,
            output_payload_hash=out_hash,
            source_refs=tuple(
                str(r) for r in output.get("source_refs") or ()
            ),
        )

    def _kernel_gate(
        self, view: ComponentEntryView, record: MetaAgentOutputRecord
    ) -> str | None:
        """Deterministic admission: schema + capability (+M1 activation
        block). Returns a denial reason or ``None``. Without a kernel the
        gate fails closed — no unvalidated meta output is ever routed."""
        if self._kernel is None:
            return "no ConstitutionalKernel available (fail closed)"
        entry = _view_entry_dict(view)
        action = meta_rules.ACTION_BY_OUTPUT_KIND.get(record.output_kind, "")
        try:
            cap = self._kernel.validate_capability(
                entry, action, "candidates"
            )
            if cap.blocking:
                return "capability denied: " + ", ".join(
                    v.code for v in cap.violations
                )
            schema = self._kernel.validate_record_schema(record.to_dict())
            if schema.blocking:
                return "record schema rejected: " + ", ".join(
                    v.code for v in schema.violations
                )
        except Exception:
            log.warning("kernel gate failed (fail closed)", exc_info=True)
            return "kernel gate error (fail closed)"
        return None

    def _route_output(
        self, view: ComponentEntryView, output: dict,
        record: MetaAgentOutputRecord,
    ):
        """§5.3 routing: candidates → the Task 07 intake at the very
        beginning of the lifecycle; everything else is non-binding data
        returned to the caller. The meta origin is provenance, not
        privilege — no shortcuts."""
        if record.shadow:
            # §5.7: shadow outputs are routed nowhere. Unreachable from
            # ``run_epoch_boundary_step`` (which stamps shadow=False), kept
            # as the routing seam's own enforcement of the invariant.
            return None
        kind = record.output_kind
        if kind in ("prompt_candidate", "clean_room_candidate"):
            raw = output.get("candidate")
            if not isinstance(raw, dict) or not raw:
                return None
            if str(raw.get("status", "candidate")) != "candidate":
                # M1: an activation attempt is a kernel matter, not a patch.
                reason = None
                if self._kernel is not None:
                    report = self._kernel.validate_capability(
                        _view_entry_dict(view), "activate", "candidates"
                    )
                    reason = ", ".join(v.code for v in report.violations)
                self._audit("meta_output_denied", {
                    "epoch_id": record.epoch_id,
                    "component_id": view.component_id,
                    "record_id": record.record_id,
                    "reason": (
                        "candidate declared non-candidate status "
                        f"({raw.get('status')!r}): {reason or 'M1'}"
                    ),
                })
                return None
            candidate = candidate_from_dict({
                **raw,
                "generated_by": {
                    **dict(raw.get("generated_by") or {}),
                    "component_id": view.component_id,
                    "meta_output_record_id": record.record_id,
                },
                "component_id": view.component_id,
                "epoch_id": record.epoch_id,
                "status": "candidate",
            })
            record_prompt_evolution_event(self._ckpt, candidate)
            return candidate
        if kind == "replay_case_recommendation":
            # Non-binding: the ReplayBoard unions the constitutionally
            # mandated minimum set regardless (§5.3) — a cherry-picking
            # selector cannot suppress mandatory cases.
            return {
                "component_id": view.component_id,
                "record_id": record.record_id,
                "replay_case_ids": sorted(
                    str(c) for c in output.get("replay_case_ids") or ()
                ),
            }
        if kind == "failure_summary":
            summary = output.get("failure_summary")
            return dict(summary) if isinstance(summary, dict) else None
        return None


# ── sandbox / shadow evaluation of meta candidates (plan 11 §5.7, §6.3) ─────


def sandbox_cache_key(
    candidate_prompt_hash: str,
    role: str,
    epoch_id: str,
    bundle_hashes,
    output_schema: dict,
) -> str:
    """The Task 12 cache-key discipline: content only, no wall clock."""
    return hash12(
        canonical_json([
            str(candidate_prompt_hash), str(role), str(epoch_id),
            sorted(str(b) for b in bundle_hashes or ()),
            output_schema or {},
        ])
    )


class MetaCandidateSandbox:
    """Offline replay of frozen historical meta-task bundles through a
    candidate (§5.7). Deterministic pass criteria only: schema-valid
    outputs, declared constraints preserved, no forbidden-input references
    (shingle scan against the Task 08 contamination list), budget respected.
    ``evaluate`` is a pure function of its inputs given a deterministic
    *invoker*; results are cached by content key.
    """

    def __init__(self, *, cfg=None) -> None:
        self._cfg = cfg
        self._cache: dict[str, dict] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def _sandbox_cfg(self):
        me = self._cfg
        if isinstance(me, dict):
            me = me.get("meta_evolution")
        else:
            me = getattr(me, "meta_evolution", None)
        if isinstance(me, dict):
            return me.get("sandbox")
        return getattr(me, "sandbox", None)

    def max_cases(self) -> int:
        sb = self._sandbox_cfg()
        raw = sb.get("max_cases", 6) if isinstance(sb, dict) else getattr(
            sb, "max_cases", 6
        )
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 6

    def use_cached_results(self) -> bool:
        sb = self._sandbox_cfg()
        raw = (
            sb.get("use_cached_results", True)
            if isinstance(sb, dict)
            else getattr(sb, "use_cached_results", True)
        )
        return bool(raw)

    def evaluate(
        self,
        *,
        candidate_prompt_hash: str,
        role: str,
        epoch_id: str,
        input_bundles,
        invoker,
        output_schema: dict | None = None,
        required_constraints=(),
        forbidden_texts=(),
        max_output_chars: int = 16000,
    ) -> dict:
        """Return the §6.3 ``sandbox`` block (byte-stable for identical
        inputs — P2). *invoker* is ``bundle -> str`` (deterministic fake in
        tests); *forbidden_texts* is the Task 08 contamination corpus."""
        from ari.rqgm import clean_room_rules
        from ari.rqgm.prompt_evolution import check_output_against_schema

        bundles = list(input_bundles or ())[: self.max_cases()]
        key = sandbox_cache_key(
            candidate_prompt_hash, role, epoch_id,
            [input_bundle_hash(b) for b in bundles],
            output_schema or {},
        )
        if self.use_cached_results() and key in self._cache:
            self.cache_hits += 1
            return dict(self._cache[key])
        self.cache_misses += 1
        cases_run = 0
        schema_valid = 0
        constraints_kept = 0
        contamination_hits = 0
        budget_violations = 0
        forbidden_docs = {
            "forbidden_%03d" % i: str(t)
            for i, t in enumerate(forbidden_texts or ())
        }
        for bundle in bundles:
            cases_run += 1
            try:
                reply = str(invoker(dict(bundle)) or "")
            except Exception:
                reply = ""
            if not check_output_against_schema(
                reply, dict(output_schema or {"__reply__": "freeform"})
            ):
                schema_valid += 1
            if all(str(c) in reply for c in required_constraints or ()):
                constraints_kept += 1
            if forbidden_docs:
                hits = clean_room_rules.contamination_hits(
                    reply, forbidden_docs, ()
                )
                contamination_hits += sum(len(v) for v in hits.values())
            if len(reply) > int(max_output_chars):
                budget_violations += 1
        block = {
            "cases_run": cases_run,
            "schema_valid_rate": (
                round(schema_valid / cases_run, 6) if cases_run else 0.0
            ),
            "constraint_preservation_rate": (
                round(constraints_kept / cases_run, 6) if cases_run else 0.0
            ),
            "contamination_hits": contamination_hits,
            "budget_violations": budget_violations,
        }
        block["passed"] = bool(
            cases_run > 0
            and block["schema_valid_rate"] == 1.0
            and block["constraint_preservation_rate"] == 1.0
            and contamination_hits == 0
            and budget_violations == 0
        )
        self._cache[key] = dict(block)
        return block


def downstream_fate(
    evolution_records, status_history, component_id: str
) -> dict:
    """§5.6.4 deterministic fitness: the recorded fate of the artifacts one
    producer emitted, aggregated from the Task 07 log and the Task 09 status
    history — no LLM in the loop."""
    produced: list[dict] = []
    for rec in evolution_records or ():
        if rec.get("record_type") != "prompt_candidate":
            continue
        producer = str(
            (rec.get("generated_by") or {}).get("component_id")
            or rec.get("component_id") or ""
        )
        if producer == str(component_id):
            produced.append(rec)
    validated: set[str] = set()
    for rec in evolution_records or ():
        if (
            rec.get("record_type") == "prompt_candidate_validation"
            and rec.get("passed")
            and str(rec.get("stage", "")) in (
                "static_validation", "constitutional_validation"
            )
        ):
            validated.add(str(rec.get("candidate_id", "")))
    hist = status_history if isinstance(status_history, dict) else {}
    promoted: list[str] = []
    sanctioned = 0
    for rec in produced:
        cid = str(rec.get("candidate_id", ""))
        entry = hist.get(cid) or {}
        status = str(entry.get("status", ""))
        if status in (
            "probationary_active", "active", "warning", "probation",
            "quarantine", "retired", "banned",
        ):
            promoted.append(cid)
            if status in (
                "warning", "probation", "quarantine", "retired", "banned"
            ):
                sanctioned += 1
    n = len(produced)
    validated_n = sum(
        1 for rec in produced
        if str(rec.get("candidate_id", "")) in validated
    )
    return {
        "candidates_produced": n,
        "validation_pass_rate": round(validated_n / n, 6) if n else 0.0,
        "promotion_rate": round(len(promoted) / n, 6) if n else 0.0,
        "post_promotion_sanction_rate": (
            round(sanctioned / len(promoted), 6) if promoted else 0.0
        ),
    }


@dataclass(frozen=True)
class MetaCandidateEvaluation:
    """The §6.3 record: deterministic aggregations only. Rides Task 09's
    existing ``candidate_evaluations`` parameter — no interface change."""

    record_id: str
    epoch_id: str
    candidate_component_id: str
    incumbent_component_id: str = ""
    sandbox: dict = field(default_factory=dict)
    shadow: dict = field(default_factory=dict)
    downstream_fate: dict = field(default_factory=dict)
    authority_non_expansion_check: str = "fail"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "record_type": "meta_candidate_evaluation",
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "candidate_component_id": self.candidate_component_id,
            "incumbent_component_id": self.incumbent_component_id,
            "sandbox": dict(self.sandbox),
            "shadow": dict(self.shadow),
            "downstream_fate": dict(self.downstream_fate),
            "authority_non_expansion_check":
                self.authority_non_expansion_check,
            "created_at": self.created_at,
        }


def shadow_summary(meta_output_records, candidate_component_id: str) -> dict:
    """Fold the shadow-stamped meta outputs of one candidate into the §6.3
    ``shadow`` block. Shadow outputs are routed nowhere (§5.7) — this
    summary is their ONLY consumer."""
    epochs: set[str] = set()
    refs: list[str] = []
    for rec in meta_output_records or ():
        if (
            rec.get("shadow", False)
            and str(rec.get("component_id", "")) == str(candidate_component_id)
        ):
            epochs.add(str(rec.get("epoch_id", "")))
            refs.append(str(rec.get("record_id", "")))
    return {
        "epochs_observed": len(epochs),
        "outputs_recorded": len(refs),
        "comparison_observation_refs": sorted(refs),
    }


def build_meta_candidate_evaluation(
    *,
    epoch_id: str,
    candidate_entry: dict,
    incumbent_entry: dict | None,
    sandbox_block: dict,
    shadow_block: dict,
    fate_block: dict,
    kernel=None,
) -> MetaCandidateEvaluation:
    """Assemble the §6.3 record; the authority check is the kernel's pure
    set arithmetic (invariant 18) when a kernel is supplied, else ``fail``
    (deny-by-default)."""
    check = "fail"
    if kernel is not None:
        try:
            report = kernel.validate_authority_non_expansion(
                candidate_entry, incumbent_entry
            )
            check = "pass" if not report.blocking else "fail"
        except Exception:
            check = "fail"
    cand_id = str(
        (candidate_entry or {}).get("component_id", "")
        if isinstance(candidate_entry, dict)
        else getattr(candidate_entry, "component_id", "")
    )
    record_id = "meta_eval_" + hash12(
        canonical_json([epoch_id, cand_id, sandbox_block, fate_block])
    )
    return MetaCandidateEvaluation(
        record_id=record_id,
        epoch_id=str(epoch_id),
        candidate_component_id=cand_id,
        incumbent_component_id=str(
            (incumbent_entry or {}).get("component_id", "")
            if isinstance(incumbent_entry, dict)
            else getattr(incumbent_entry, "component_id", "") or ""
        ),
        sandbox=dict(sandbox_block or {}),
        shadow=dict(shadow_block or {}),
        downstream_fate=dict(fate_block or {}),
        authority_non_expansion_check=check,
    )


# ── the §5.8 constitutional cap on make_metric_spec ─────────────────────────


class MetricSpecWeightCap:
    """Suppress node-initiated axis-weight overrides under ``ari_rqgm``.

    Attached to the node executor by ``RQGMRuntime.wrap_node_executor`` ONLY
    (the attribute is absent under ``simple_bfts``, whose weight precedence
    stays MetricSpec > ctor > AxisDef > defaults, byte-for-byte). Called at
    the single ``make_metric_spec`` handler site in ``ari/agent/loop.py``:
    the epoch-frozen weight regime (Task 02 ``utility_policy``) outranks any
    weights a node smuggles through ``make_metric_spec``; the attempt is
    appended to the audit log as an observation, never an error.

    **Governed rewrite vs ungoverned smuggling** (RQGM Task 14 §5.9 — read
    this before concluding that "weights are capped" and "weights are
    rewritten at every epoch boundary" contradict each other; they do not).
    This cap forbids an **ungoverned** weight change: mid-epoch, by a node,
    with no candidate, no validation, no adoption and no audit — laundering a
    score change through a work product. Task 14's boundary rewrite is its
    exact opposite: proposed by a registered component (``policy_mutator``),
    validated against the frozen legality rules
    (``kernel_rules.UTILITY_POLICY_RULES``, CK-UTL-001..008), adopted through
    the T-table at a boundary, audited as a transition, and PAID FOR by
    invalidating every node scored under the old policy. The distinction is
    *who* and *when*, not *whether*.

    Task 14 makes the clamp below MORE true, not less: the ctor/AxisDef
    regime it falls through to is now the GOVERNED one — the policy the
    registry adopted, rather than a static config constant.
    """

    def __init__(self, *, audit_log=None, epoch_state=None) -> None:
        self._audit_log = audit_log
        self._epoch_state = epoch_state  # value or zero-arg callable

    def _epoch_id(self) -> str:
        ep = self._epoch_state
        try:
            ep = ep() if callable(ep) else ep
        except Exception:
            ep = None
        return str(getattr(ep, "epoch_id", "") or "")

    def __call__(self, spec_data, evaluator) -> dict | None:
        requested = (
            spec_data.get("axis_weights")
            if isinstance(spec_data, dict) else None
        )
        metric_spec = getattr(evaluator, "metric_spec", None)
        current = getattr(metric_spec, "axis_weights", None)
        if not requested and not current:
            return None
        if metric_spec is not None and current:
            # Clamp: dropping MetricSpec weights lets ``_resolve_axis_weights``
            # fall through to the ctor/AxisDef weights — exactly the regime
            # ``capture_utility_policy`` froze at the epoch boundary.
            metric_spec.axis_weights = None
        observation = {
            "event": "metric_spec_weight_override_suppressed",
            "epoch_id": self._epoch_id(),
            "requested_axis_weights": dict(requested or {}),
            "suppressed_spec_weights": dict(current or {}),
            "policy": "epoch_frozen_weights",
        }
        if self._audit_log is not None:
            try:
                self._audit_log.append(
                    "metric_spec_weight_override_suppressed", observation
                )
            except Exception:
                log.warning("weight-cap audit append failed", exc_info=True)
        return observation
