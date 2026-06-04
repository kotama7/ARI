---
sources:
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/config
    role: config
last_verified: 2026-06-04
---

# ARI Verifiable Research Memory

How ARI's memory is structured so that experiment results, failures, and
procedures are **typed, artifact-grounded, and verifiable** — not just
free-form natural-language logs. This is the durable design record (the
working plan that produced it has been retired); see also
[memory.md](memory.md) for the ancestor-scoped retrieval baseline.

## Why

The ancestor-scoped Letta memory (memory.md) gives branch isolation but stores
mostly free-form text. A research-automation system additionally needs to:

- trace which log / code / output file a result rests on;
- reuse failure cases, fixes, and performance evidence;
- never use an ungrounded claim as a paper assertion;
- separate reproduced results from unverified ones.

Verifiable Research Memory adds a typed, evidence-grounded layer **on top of**
Letta (kept as a low-level archival/search backend) without making Letta the
knowledge owner.

## Principles

1. **Memory is an index, not evidence** — a memory points at evidence
   (artifacts/metrics/commands/logs), it is not the claim itself.
2. **Single source of truth = `node_report.json`** — provenance (metrics,
   artifacts with sha256, build/run commands, files_changed, hardware,
   concerns/hints) lives there. Typed memory carries a `node_report_ref`
   pointer plus a searchable `text`; it does **not** copy node_report fields.
3. **Branch isolation** — a node reads only its ancestors' memory (never
   siblings / other checkpoints).
4. **Copy-on-Write, append-only** — a node writes only its own `node_id`; past
   entries stay byte-stable. State changes (e.g. reproducibility) are appended
   as new events, never in-place edits.
5. **Typed** — every entry has a `kind` (observation, experiment_result,
   failure_case, procedure, reflection, artifact_summary, paper_claim,
   reproducibility_event).
6. **Artifact-grounded generation** — paper/figure claims rest only on
   artifact-backed (ideally reproduced) memory; ungrounded reflection may aid
   exploration but never the paper body.
7. **Reproducibility-aware** — reproducibility status is an append-only event,
   folded to the latest per target at read time.
8. **Loop-orchestrated** — memory reads/writes are done by deterministic
   loop/pipeline hooks. The LLM does not actively pull memory (measured: agents
   never call the recall tools; recall is a one-shot startup pre-seed). The
   agent's own `add_memory` is optional and never relied upon.
9. **Letta is a low-level backend** — archival insert / semantic search /
   per-checkpoint collections only; ARI owns what/how/where/grounded/verified.

## Architecture

```
node end ─▶ consolidate_node_memory  (node_report → typed experiment_result /
            (bfts_loop hook)           failure_case / reflection, with provenance)
                  ▼
          typed research-memory store (Letta archival, ancestor-scoped, CoW)
                  ▼
paper pipeline ─▶ write_verified_context (best node's root→best lineage)
                  → {checkpoint}/verified_context.json
                  ▼
write_paper ─▶ reads the path directly, render_grounded_block → system prompt
              → quantitative claims grounded only on verified, artifact-backed
                (rerun_passed first) results.
```

- **Working context (Phase 0)**: at node start the loop injects the experiment
  core (goal/metric/hardware) + ancestor `result_summary` conclusions
  deterministically (replacing the old aggregate-truncated semantic dump). This
  is the *inheritance* path and is independent of the verifiable layer below.
- **Typed index / verified context**: the verifiable layer above, gated by
  `consolidation_enabled()` (default ON).

## Components

- `ari-skill-memory`: `schemas.py` (typed records), `provenance.py` (sha256
  refs from node_report), `audit.py` (claim↔artifact integrity),
  `writer.py` / `retriever.py` (typed write + kind/scope/artifact-filtered
  read + reproducibility fold), `consolidation.py` (node_report → specs),
  `context_builder.py` (verified context). Exposed as MCP tools
  (`add_experiment_result`, `search_research_memory`, `get_verified_context`,
  `consolidate_node_memory`, `audit_memory`, …) — all called by hooks.
- `ari-core`: `pipeline/verified_context.py` (best-node lineage scoping +
  grounded-block render), the `bfts_loop` node-end consolidation hook, and the
  write_paper consumption.

## Gating & cost

`ARI_MEMORY_CONSOLIDATE` (default **ON**; `0`/`false`/`no`/`off` to disable,
single source of truth `ari.config.consolidation_enabled`) controls both the
node-end consolidation and the paper verified-context build. Cost: ~1–2 typed
writes per node (each embeds) on top of the existing `result_summary`;
measured linear and acceptable.

## Validation (real env)

- Phase 0 working-context injection: validated on a live BFTS run (experiment
  core + full ancestor `result_summary`, sibling isolation).
- Consolidation: validated live — the node-end hook wrote a provenanced
  `experiment_result` (6 sha256 artifact refs + node_report_ref) and
  `failure_case` for failed nodes, without breaking the loop.
- Verified context → paper grounding: validated end-to-end on real data and
  via the paper-pipeline wiring (`verified_context_json` passed as a path, not
  via `load_inputs`, so the write_paper stage / claim-stage topology is
  unperturbed).

## Deliberate non-goals

- **BFTS planner typed-injection** (feeding ancestor failure_case/procedure
  into `expand()` to avoid repeating failures) was evaluated against an
  evidence gate and **intentionally not built** — a real run measured 0%
  failure-recurrence (see `ari-core/REQUIREMENTS.md`). Re-evaluate only if a
  future run shows high recurrence.
- Letta self-editing, cross-experiment global memory, learned memory policies —
  out of scope.
