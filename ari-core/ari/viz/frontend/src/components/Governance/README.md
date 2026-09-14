# components/Governance

Read-only RQGM Governance workspace (user-facing guide:
`docs/guides/rqgm_gui.md`; the read-model contract this page renders:
`docs/reference/rqgm_gui_read_models.md`).

Route `#/governance?run=<run_id>` (gui_v2-gated). All data comes from the
Wave-4a `/api/v1/runs/{run_id}/rqgm/*` read models via the typed react-query
hooks in `src/hooks/useV1.ts`; the page performs **no mutation** (v1 has no
RQGM mutation endpoint) and re-executes no kernel/score-policy decision.

| File | Contents |
|---|---|
| `GovernancePage.tsx` | Shell: `?run=` param, capability gating (a `simple_bfts` run gets a capability state screen, not an error), tablist a11y composite, realtime (`topic 'run'` → rqgm cache invalidation) + `StaleDataBanner`, shared node selector. |
| `OverviewTab.tsx` | Bounded committed-replay summary + tri-state integrity badges; broken chain → `DegradedState` (degraded ≠ research failure). |
| `RegistryTab.tsx` | Components/prompts tables, 10-status lifecycle badges, active-set marker, rollup-vs-replay `verified` tri-state. |
| `AccountabilityTab.tsx` | Adversarial chain of one node with explicit raw-vs-validated separation; structurally-inert impeachment-chain capability note. |
| `ScoreLineageTab.tsx` | Two-channel score lineage: penalty waterfall (channel 1) and policy-hash-faceted history (channel 2 — never one series across hashes); epoch utility policies + committed score rewrites. |
| `AuditTab.tsx` | Byte-offset cursor-paged audit table with record_type/epoch filters, "load more", raw-source offset per row. |
| `shared.tsx` | The two disjoint badge vocabularies (registry lifecycle vs node score state), policy-hash label, score cell (missing ≠ 0), error text helper. |

Truth rules enforced here (`docs/reference/rqgm_gui_read_models.md`
§"Ground rules" and §"Presentation truth rules the API enforces"): raw
attack ≠ validated penalty; registry lifecycle and node score states are
separate state machines with separate token families; committed records
only; cross-policy scores are faceted, never joined; missing sources render
as `unknown`, never as clean/zero; zero attacks is a capability state, not
health.
