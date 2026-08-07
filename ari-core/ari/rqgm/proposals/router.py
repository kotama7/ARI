"""ProposalRouter — budget-aware deterministic dispatcher (RQGM Task 03 §5.2).

Active only in ``ari_rqgm`` mode. Routing is a **pure policy function**
(:func:`route`, P2 — deterministic-rule-first precedent from
``deterministic_stagnation_pivot``): the router itself is not an LLM in v1;
what evolves later (Task 07) are the generator *prompts*, not the routing
rule.

Trigger events map onto existing hooks (plan 03 §5.2):

===================== =====================================================
``initial_exploration`` run start / first proposal need in ``_run_loop``
``frontier_stagnation`` ``detect_stagnation()`` true in the lineage hook
``major_pivot``         lineage decision ``switch_to_idea`` / ``fanout``
``paper_candidate``     paper-pipeline pre-flight (``WorkflowDriver.run``)
===================== =====================================================

Failure discipline: every public method catches, logs, and falls back to
the status-quo path (existing fallback child, existing ``idea.json``). The
BFTS loop never dies on a router failure.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ari.rqgm.proposals.generators import (
    AttackDrivenGenerator,
    CheapGenerator,
    MutationGenerator,
    PriorArtDifferentiationGenerator,
    ProposalDraft,
    draft_with_record_id,
)
from ari.rqgm.proposals.records import ProposalRecord
from ari.rqgm.proposals.store import ProposalStore, import_idea_json_records

log = logging.getLogger(__name__)

ROUTER_COMPONENT_ID = "proposal_router_v1"

#: Closed v1 trigger-event vocabulary (plan 03 §5.2).
TRIGGER_EVENTS: tuple[str, ...] = (
    "initial_exploration",
    "frontier_stagnation",
    "major_pivot",
    "paper_candidate",
)

#: Deterministic per-event generator priority (first enabled generator with
#: remaining budget wins; ``cheap`` is the uncapped terminal fallback).
#: ``attack_driven`` is deliberately absent until Task 06 lands.
#: ``prior_art`` sits ahead of ``cheap`` on ``initial_exploration`` too. It was
#: absent, so the FIRST idea — the one every later node descends from — had no
#: literature-grounded path at all unless the default-OFF ``virsci`` was
#: enabled, and the run silently fell through to ``cheap``: papers_analyzed=0,
#: an empty gap analysis, and a novelty claim that was pure LLM self-assessment.
#: The addition is safe by construction: ``PriorArtDifferentiationGenerator``
#: returns [] when ``ctx["survey_refs"]`` is empty, so with no refs the router
#: falls through to ``cheap`` exactly as before.
_EVENT_PRIORITY: dict[str, tuple[str, ...]] = {
    "initial_exploration": ("virsci", "prior_art", "cheap"),
    "frontier_stagnation": ("virsci", "mutation", "cheap"),
    "major_pivot": ("virsci", "prior_art", "cheap"),
    "paper_candidate": ("prior_art", "mutation", "cheap"),
}


def route(
    event: str,
    budgets: dict[str, int | None],
    available_generators: set[str] | frozenset[str],
) -> str | None:
    """Pure routing policy: ``(event, budgets, available) -> generator``.

    *budgets* maps generator name → remaining per-epoch calls (``None`` ==
    unlimited). Deterministic tie-breaking is the fixed priority order of
    :data:`_EVENT_PRIORITY`; disabled generators (absent from
    *available_generators*) are never selected. No I/O, no randomness (P2).
    """
    for name in _EVENT_PRIORITY.get(event, ("cheap",)):
        if name not in available_generators:
            continue
        remaining = budgets.get(name)
        if remaining is not None and remaining <= 0:
            continue
        return name
    return None


class ProposalRouter:
    """Dispatches proposal generation over the five-generator registry.

    *cfg* is the resolved :class:`ari.config.ARIConfig` (only
    ``proposal_router.*`` is read — never during mode resolution, plan 01
    §5.6). *generators* is the injectable registry override used by tests
    (deterministic fakes; never a real LLM). *epoch_state* is either an
    ``EpochState``-like object or a zero-arg callable returning one, so the
    router always stamps the CURRENT epoch after boundary transactions.
    """

    def __init__(
        self,
        cfg,
        llm=None,
        mcp=None,
        store: ProposalStore | None = None,
        epoch_state=None,
        *,
        generators: dict | None = None,
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm
        self.mcp = mcp
        if store is None:
            if checkpoint_dir is None:
                raise ValueError("ProposalRouter needs a store or checkpoint_dir")
            store = ProposalStore(checkpoint_dir)
        self.store = store
        self._epoch_state = epoch_state
        self._generators = (
            dict(generators) if generators is not None else self._build_generators()
        )

    # ── construction ──────────────────────────────────────────────────

    def _router_cfg(self):
        return getattr(self.cfg, "proposal_router", None)

    def _generator_cfg(self, name: str):
        gens = getattr(self._router_cfg(), "generators", None)
        return getattr(gens, name, None)

    def _typed_contract_required(self) -> bool:
        return not (
            str(getattr(getattr(self.cfg, "knowledge", None), "mode", "off")) == "off"
            and str(
                getattr(
                    getattr(self.cfg, "capability_binding", None),
                    "mode",
                    "legacy",
                )
            ) == "legacy"
            and str(getattr(getattr(self.cfg, "assurance", None), "mode", "off"))
            == "off"
        )

    def _build_generators(self) -> dict:
        ckpt = self.store.checkpoint_dir
        registry: dict = {
            "cheap": CheapGenerator(self.llm, checkpoint_dir=ckpt),
            "mutation": MutationGenerator(self.llm, checkpoint_dir=ckpt),
            "attack_driven": AttackDrivenGenerator(self.llm),
            "prior_art": PriorArtDifferentiationGenerator(
                self.llm, checkpoint_dir=ckpt
            ),
        }
        vcfg = self._generator_cfg("virsci")
        if (
            bool(getattr(vcfg, "enabled", False)) or self._typed_contract_required()
        ) and self.mcp is not None:
            # Conditional construction is the virsci.enabled=false guarantee:
            # with the default config this import/constructor never runs.
            from ari.rqgm.proposals.virsci_adapter import VirSciAdapter

            registry["virsci"] = VirSciAdapter(self.mcp, checkpoint_dir=ckpt)
        return registry

    # ── policy inputs ─────────────────────────────────────────────────

    def _epoch_id(self) -> str | None:
        es = self._epoch_state() if callable(self._epoch_state) else self._epoch_state
        return getattr(es, "epoch_id", None)

    def _enabled(self, name: str) -> bool:
        gcfg = self._generator_cfg(name)
        if name == "virsci" and self._typed_contract_required():
            return True
        default = name in ("cheap", "mutation", "prior_art")
        return bool(getattr(gcfg, "enabled", default))

    def _available_for_event(self, event: str) -> set[str]:
        out: set[str] = set()
        for name, gen in self._generators.items():
            if not self._enabled(name):
                continue
            if name == "virsci":
                trigger_on = list(
                    getattr(self._generator_cfg("virsci"), "trigger_on", [])
                    or []
                )
                if event not in trigger_on:
                    continue
            out.add(name)
        return out

    def _remaining_budget(self, name: str) -> int | None:
        gcfg = self._generator_cfg(name)
        try:
            cap = int(getattr(gcfg, "max_calls_per_epoch", 0) or 0)
        except (TypeError, ValueError):
            cap = 0
        if cap <= 0:
            return None  # unlimited
        used = self.store.count_for_epoch(name, self._epoch_id())
        return cap - used

    def budgets_for(self, names) -> dict[str, int | None]:
        return {name: self._remaining_budget(name) for name in names}

    # ── invocation surfaces (plan 03 §5.2) ────────────────────────────

    def generate_root_proposals(self, ctx: dict | None = None) -> list[ProposalRecord]:
        """Root ideation on the ``_run_loop`` main thread (marker-guarded).

        Idempotent: an already-populated store (resume, or a completed
        earlier call) is a no-op. An inherited pinned ``idea.json`` is first
        imported as ``legacy_idea_json`` records (cross-run inheritance keeps
        riding ``inherit_idea_index``); then the router generates fresh
        proposals and emits the projection. On any failure the run proceeds
        on the status-quo path (existing ``idea.json`` if present).
        """
        ctx = dict(ctx or {})
        try:
            if self.store.load_all():
                return []  # marker-guarded: root ideation already happened
            imported = 0
            existing = self.store.checkpoint_dir / "idea.json"
            if existing.exists():
                imported = import_idea_json_records(
                    self.store.checkpoint_dir, epoch_id=self._epoch_id()
                )
            records = self._dispatch(
                "initial_exploration", ctx, select_directive=(imported == 0)
            )
            self.store.write_idea_projection(
                meta=self._projection_meta(records)
            )
            self._log_decision("initial_exploration", records, imported=imported)
            return records
        except Exception:
            log.warning(
                "generate_root_proposals failed; falling back to the "
                "status-quo idea.json path", exc_info=True,
            )
            return []

    def record_expansion_proposal(self, node, direction) -> ProposalRecord | None:
        """Record one ``BFTS.expand`` child direction (observation only).

        v1 wraps expansion as a CheapGenerator-labelled record with zero
        behavior change to expansion itself; ``prompt_hash`` is ``None``
        (the direction came from the existing bfts_expand channel, not a
        router prompt). Never raises.
        """
        try:
            from ari.rqgm.proposals.records import (
                ProposalSummaryView,
                clamp_summary,
            )

            title = (
                getattr(direction, "name", "")
                or getattr(direction, "raw_label", "")
                or str(getattr(direction, "id", ""))
            )
            desc = str(getattr(direction, "original_direction", "") or "")
            summary = clamp_summary(
                ProposalSummaryView(
                    title=str(title),
                    short_description=desc,
                )
            )
            draft = ProposalDraft(
                generator="cheap",
                summary=summary,
                source_refs={
                    "node_id": str(getattr(direction, "id", "") or ""),
                    "parent_node_id": str(getattr(node, "id", "") or ""),
                },
                raw_output={"direction": desc, "observed": True},
            )
            committed = self._commit_drafts(
                [draft],
                status="expanded",
                projected=False,  # observations never enter idea.json
            )
            return committed[0] if committed else None
        except Exception:
            log.warning("record_expansion_proposal failed", exc_info=True)
            return None

    def on_event(self, event: str, ctx: dict | None = None) -> list[ProposalRecord]:
        """Deterministic event dispatch (re-ideation surface).

        Appends candidate records and re-emits the projection under the same
        content-visible rewrite discipline as ``apply_root_choice``. The
        directive (``ideas[0]``) is NOT shifted by mid-run events in v1 —
        promoting a re-ideation result is a governance decision (Task 05).
        """
        ctx = dict(ctx or {})
        try:
            records = self._dispatch(event, ctx, select_directive=False)
            if records:
                self.store.write_idea_projection(
                    meta=self._projection_meta(records)
                )
            self._log_decision(event, records)
            return records
        except Exception:
            log.warning("proposal router on_event(%s) failed", event,
                        exc_info=True)
            return []

    # ── internals ─────────────────────────────────────────────────────

    def _dispatch(
        self, event: str, ctx: dict, *, select_directive: bool
    ) -> list[ProposalRecord]:
        available = self._available_for_event(event)
        name = route(event, self.budgets_for(available), available)
        if name is None:
            log.warning("no generator available for event %s", event)
            return []
        generator = self._generators[name]
        ctx = dict(ctx)
        ctx.setdefault("parent_record", self.store.selected())
        drafts = list(generator.generate(ctx) or [])
        if not drafts:
            # Degrade one tier: the uncapped cheap generator always answers.
            if name != "cheap" and "cheap" in self._generators:
                drafts = list(self._generators["cheap"].generate(ctx) or [])
            if not drafts:
                return []
        drafts.sort(
            key=lambda d: -float(d.summary.scores.get("overall", 0.0) or 0.0)
        )
        return self._commit_drafts(
            drafts, status="candidate", first_status=(
                "selected" if select_directive else None
            ),
        )

    def _commit_drafts(
        self,
        drafts: list[ProposalDraft],
        *,
        status: str,
        first_status: str | None = None,
        projected: bool = True,
    ) -> list[ProposalRecord]:
        committed: list[ProposalRecord] = []
        for i, draft in enumerate(drafts):
            record_id = self.store.next_record_id()
            draft = draft_with_record_id(draft, record_id)
            source_refs = dict(draft.source_refs)
            if i == 0:
                # Budget unit marker: one dispatch == one call, regardless of
                # how many records it produced (see ProposalStore.count_for_epoch).
                source_refs["dispatch_head"] = True
            archive_refs: dict = dict(draft.raw_output.get("archive_refs") or {})
            raw_ref = self.store.write_archive(
                record_id, "raw_output.json", draft.raw_output
            )
            if raw_ref:
                archive_refs["raw_output"] = raw_ref
            cfg_ref = self.store.write_archive(
                record_id,
                "generator_config.json",
                self._generator_config_snapshot(draft.generator),
            )
            if cfg_ref:
                archive_refs["generator_config"] = cfg_ref
            if draft.prompt_hash:
                archive_refs["prompt_hashes"] = {"generator": draft.prompt_hash}
            record = ProposalRecord(
                record_id=record_id,
                generator=draft.generator,
                status=(first_status if (i == 0 and first_status) else status),
                epoch_id=self._epoch_id(),
                component_id=ROUTER_COMPONENT_ID,
                role="generator",
                prompt_hash=draft.prompt_hash,
                created_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                source_refs=source_refs,
                summary=draft.summary,
                archive_refs=archive_refs,
                idea_projection={"projected": bool(projected)},
            )
            if self.store.append(record):
                committed.append(record)
        return committed

    def _generator_config_snapshot(self, name: str) -> dict:
        gcfg = self._generator_cfg(name)
        snap: dict = {"generator": name}
        for key in ("enabled", "max_calls_per_epoch", "mode", "trigger_on"):
            val = getattr(gcfg, key, None)
            if val is not None:
                snap[key] = val
        model = getattr(getattr(self.cfg, "llm", None), "model", None)
        if model:
            snap["model"] = model
        return snap

    def _projection_meta(self, records: list[ProposalRecord]) -> dict | None:
        """Bubble the generator's 9-key extras (VirSci gap analysis etc.)
        from the freshly archived raw output into the projection."""
        for rec in records:
            if rec.generator != "virsci":
                continue
            ref = rec.archive_refs.get("raw_output")
            if not ref:
                continue
            try:
                raw = json.loads(
                    (self.store.checkpoint_dir / ref).read_text(
                        encoding="utf-8"
                    )
                )
                payload = raw.get("generate_ideas")
                if isinstance(payload, dict):
                    return {
                        k: payload[k]
                        for k in (
                            "gap_analysis",
                            "papers_analyzed",
                            "n_agents",
                            "discussion_rounds",
                            "virsci_integration_status",
                            "typed_schema_version",
                            "contract_status",
                            "survey_snapshot",
                            "survey_snapshot_digest",
                            "survey_snapshot_ref",
                            "idea_set",
                            "idea_set_digest",
                            "research_contract",
                            "research_contract_digest",
                            "rejected_candidates",
                        )
                        if k in payload
                    }
            except Exception:
                continue
        return None

    def _log_decision(
        self, event: str, records: list[ProposalRecord], *, imported: int = 0
    ) -> None:
        """Append to the shared ``lineage_decisions.jsonl`` audit log with
        ``trigger: "proposal_router"`` (plan 03 §8 — decisions share the
        existing log; the record store itself is data, not decisions)."""
        try:
            record = {
                "ts": time.time(),
                "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "trigger": "proposal_router",
                "executed": bool(records),
                "decision": {
                    "event": event,
                    "generator": records[0].generator if records else None,
                    "record_ids": [r.record_id for r in records],
                },
                "extra": {"imported_legacy": int(imported)},
            }
            path = self.store.checkpoint_dir / "lineage_decisions.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            log.debug("proposal_router decision log append failed",
                      exc_info=True)
