---
sources:
  - path: ari-core/ari/rqgm/proposals/virsci_adapter.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/router.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/configs/defaults.yaml
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-core/tests/test_rqgm_virsci_adapter.py
    role: test
last_verified: 2026-08-08
---

# VirSci Integration

VirSci (a multi-agent scientific-collaboration idea generator) reaches ARI
through two independent surfaces. Neither is enabled by default, and neither
requires the other:

1. **The `ari-skill-idea` MCP skill** (both execution modes) — the
   `generate_idea` stage of `workflow.yaml` calls the skill's
   `generate_ideas` tool once before BFTS starts. The skill has two engines
   behind one output contract: the default lightweight **reimpl** discussion
   loop, and the opt-in **real_wrap** engine (`ARI_IDEA_VIRSCI_REAL=1`) that
   runs the vendored VirSci mechanism. See
   [MCP Skills Reference → ari-skill-idea](../reference/skills.md).
2. **The RQGM `VirSciAdapter`** (`ari_rqgm` mode only) — an optional
   high-cost deliberative generator behind the `ProposalRouter`
   (`ari/rqgm/proposals/router.py`). This guide covers that surface.

The adapter (`ari/rqgm/proposals/virsci_adapter.py`) is an **MCP-only
normalizer**: it calls the idea skill's `survey` and `generate_ideas` tools
over MCP and imports nothing from `ari-skill-idea`. Heavy dependencies
(torch/faiss/agentscope) stay inside the skill process, which keeps the
skill's degradation tiers intact and makes "tests pass without VirSci
installed" structural.

## Configuration

The generator is one entry in the `proposal_router.generators` block
(`ari.config.VirSciGeneratorConfig`; defaults mirrored in
`ari-core/ari/configs/defaults.yaml`, parity pinned by
`ari-core/tests/test_rqgm_proposals.py`):

```yaml
proposal_router:
  summary_budget_chars: 6000
  generators:
    virsci:
      enabled: false            # opt-in; never enabled by default
      mode: event_triggered     # v1 supports only `event_triggered`
      max_calls_per_epoch: 2    # hard per-epoch cap on adapter invocations
      trigger_on: [initial_exploration, frontier_stagnation,
                   major_pivot, paper_candidate]
```

- **`enabled`** (default `false`) — the master switch for the adapter. See
  [Guarantees when `enabled: false`](#guarantees-when-enabled-false).
- **`mode`** — invocation mode; the only accepted value in v1 is
  `event_triggered` (there is no polling or per-node mode).
- **`max_calls_per_epoch`** — the per-epoch call budget. Budget accounting
  counts **dispatch heads**, not records: one VirSci call yields several
  `ProposalRecord`s but consumes one budget unit
  (`ProposalStore.count_for_epoch`). The count is derived from the stored
  records, so it is deterministic across resume, and a fully deduplicated
  retry (the MCP 3-retry policy) appends nothing and consumes no budget.
- **`trigger_on`** — the router trigger events that may route to the
  adapter. Removing an event from this list makes VirSci unavailable for
  that event.

`proposal_router.*` is consumed only when the effective mode is `ari_rqgm`
(the single exception, `record_only`, is unrelated to VirSci — see
[RQGM migration](rqgm_migration.md)). Under `simple_bfts` the existing
skill-side levers — the `workflow.yaml` `generate_idea` stage and
`ARI_IDEA_VIRSCI_REAL` — remain the only VirSci controls.

## Event-triggered routing and budgets

Routing is the pure policy function `ari.rqgm.proposals.router.route`
(deterministic, no I/O, no randomness — P2): for a trigger event, the first
*enabled* generator with remaining budget in a fixed priority order wins.
The v1 priority table:

| Trigger event | Priority order |
|---|---|
| `initial_exploration` | `virsci` → `prior_art` → `cheap` |
| `frontier_stagnation` | `virsci` → `mutation` → `cheap` |
| `major_pivot` | `virsci` → `prior_art` → `cheap` |
| `paper_candidate` | `prior_art` → `mutation` → `cheap` |

So with VirSci enabled and budget remaining, the adapter is the first
preference for `initial_exploration`, `frontier_stagnation`, and
`major_pivot`; the fixed `paper_candidate` order never selects it, whatever
`trigger_on` says. An exhausted budget falls through to the next generator,
and a generator that returns zero drafts degrades one tier to the uncapped
`cheap` fallback — the BFTS loop never dies on a router failure.

v1 run-loop wiring: the loop dispatches `initial_exploration` at root
ideation (`generate_root_proposals`, which supersedes the agent-initiated
root `generate_ideas` call) and records expansion directions as
observations. `ProposalRouter.on_event` is the re-ideation surface for the
other trigger events; a mid-run event appends candidate records under the
same budgets but never shifts the `ideas[0]` directive in v1 — promoting a
re-ideation result is a governance decision.

The adapter itself calls `survey` (topic → paper list; degrades to an empty
list on failure) and then `generate_ideas` over MCP, and normalizes the
`generate_ideas` payload into one `ProposalDraft` per idea — it reads only
the nine legacy top-level keys (`virsci_adapter.GENERATE_IDEAS_KEYS`), which
are now a subset of what the skill returns. A `generate_ideas`
failure degrades to zero drafts; content-key dedup at the store makes the
whole path idempotent under retries.

## Archive vs. summary

VirSci output is split on write ("store everything, show a summary"):

- **Archived under the checkpoint** — the full `generate_ideas` payload (raw
  idea list, `gap_analysis`, generator config) goes to
  `{checkpoint}/proposals/archive/<record_id>/` (`raw_output.json`,
  `generator_config.json`). The skill's on-disk transcript artifacts —
  `{checkpoint}/virsci_logs/virsci_stdout.log` and
  `{checkpoint}/virsci_snapshot/` — are *referenced* in the record's
  `archive_refs`, never copied.
- **What BFTS sees** — only the bounded `ProposalSummaryView` (hard
  per-field character budgets; the rendered expand context is capped by
  `proposal_router.summary_budget_chars`, default 6000 — parity with the
  pre-RQGM `_build_idea_ctx_for_expand` channel). No transcript or
  discussion content ever enters a summary field or the rendered context;
  pinned by
  `test_rqgm_virsci_adapter.py::test_transcript_content_never_reaches_expand_context`.

The shared extras additionally ride into the `idea.json` projection's
top-level keys, preserving the pre-RQGM `idea.json` contract:
`ProposalRouter._projection_meta` re-reads the archived payload and copies
whichever of the five legacy keys (`gap_analysis`, `papers_analyzed`,
`n_agents`, `discussion_rounds`, `virsci_integration_status`) and the ten
typed-contract keys the skill now also returns (`typed_schema_version`,
`contract_status`, `survey_snapshot`, `survey_snapshot_digest`,
`survey_snapshot_ref`, `idea_set`, `idea_set_digest`, `research_contract`,
`research_contract_digest`, `rejected_candidates`) are present.

## Guarantees when `enabled: false`

With the default `enabled: false` **and** the default typed-contract
postures (`knowledge.mode: off`, `capability_binding.mode: legacy`,
`assurance.mode: off`), all pinned by
`ari-core/tests/test_rqgm_virsci_adapter.py`:

- **The adapter is never constructed.** `ProposalRouter._build_generators`
  only instantiates `VirSciAdapter` when the flag is true and an MCP client
  exists (`test_mode_virsci_matrix_config_and_boot`).
- **The adapter module is never imported.** The import is inside that
  conditional branch and the module has no import side effects
  (`test_virsci_disabled_adapter_module_never_imported`).
- **No VirSci runtime is required, ever.** The adapter imports nothing from
  `ari-skill-idea` and no VirSci dependency
  (`test_adapter_imports_nothing_from_the_idea_skill`); the test module uses
  a fake MCP client throughout — no VirSci install, no vendored submodule,
  no real LLM call.
- **The evaluation harness enforces absence.** In the B3 (VirSci-off)
  ablation condition, `virsci_absence_violations` fails a run that shows
  VirSci prompts or transcript files — see
  [RQGM Evaluation](rqgm_evaluation.md).

These guarantees cover the default postures only. Moving any of
`knowledge.mode`, `capability_binding.mode`, or `assurance.mode` off its
default makes `ProposalRouter._typed_contract_required()` true, and the
router then constructs the adapter (whenever an MCP client exists) and
reports `virsci` as enabled whatever `generators.virsci.enabled` says.

## The four mode × VirSci combinations

`proposal_router.generators.virsci.enabled` is orthogonal to `ari.mode`:
mode resolution never reads `proposal_router.*`, and the VirSci gate never
reads `ari.mode`. All four combinations are valid config and boot cleanly
(`test_mode_virsci_matrix_config_and_boot`):

| `ari.mode` | `virsci.enabled` | Behaviour |
|---|---|---|
| `simple_bfts` | `false` | Default. `proposal_router.*` is inert; the skill-side levers (`generate_idea` stage, `ARI_IDEA_VIRSCI_REAL`) are the only VirSci controls. |
| `simple_bfts` | `true` | Valid but inert: nothing constructs the router in `simple_bfts`, so the flag has no effect. Skill-side levers stay authoritative. |
| `ari_rqgm` | `false` | With the typed-contract postures at their defaults, the router runs with `cheap`/`mutation`/`prior_art` only: no VirSci runtime, vendored path, prompt, or snapshot corpus is touched. |
| `ari_rqgm` | `true` | `VirSciAdapter` joins the routing table; MCP calls to `survey` + `generate_ideas` under the per-epoch cap. |

## The vendored submodule and the skill

`ari-skill-idea/vendor/virsci` is a git submodule holding the **unedited**
upstream VirSci sources. Only the skill's opt-in `real_wrap` engine
(`ARI_IDEA_VIRSCI_REAL=1`) runs the vendored VirSci mechanism — the
`select_coauthors` / `generate_idea` path over a Semantic Scholar snapshot.
The default reimpl engine borrows only the vendored discussion prompt
templates (`sci_platform/utils/prompt.py`, read at skill import) and falls
back to inline prompts when the submodule is not checked out, so it runs
either way; `ari-core` never imports it. Which engine actually ran
is reported in the `virsci_integration_status` key of the `generate_ideas`
payload (`"real_wrap"` vs `"reimpl: …"` with the reason) — the RQGM adapter
normalizes both statuses identically.

Because the RQGM integration is MCP-only, `ari-core` never touches the
submodule. This is pinned twice: the adapter module imports neither the
skill nor any VirSci runtime
(`test_rqgm_virsci_adapter.py::test_adapter_imports_nothing_from_the_idea_skill`),
and no adversarial module imports VirSci
(`test_rqgm_adversarial.py::test_adversarial_package_never_imports_virsci`).
The RQGM test modules run entirely against fake MCP clients — they pass on
a machine where the submodule was never checked out and the `virsci` pip
extra was never installed.

See also: [Execution Modes](execution_modes.md) ·
[RQGM migration](rqgm_migration.md) ·
[RQGM Evaluation](rqgm_evaluation.md) ·
[MCP Tools Reference](../reference/mcp_tools.md) ·
[Environment Variables](../reference/environment_variables.md)
