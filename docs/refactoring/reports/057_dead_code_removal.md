# 057 — Safe Dead-Code Removal Record

- **Subtask:** 057 `delete_safe_dead_code_candidates`
- **Depends on:** 053 → 054 → 055 → 056 (reference-graph + dead-code chain)
- **Outcome:** **NO CODE DELETED** — the reviewed classifier reports **zero**
  `SAFE_DELETE_CANDIDATE` items. This is the expected, safe result, not a gap.

## Deletion set (frozen from the 056 classification)

`scripts/check_dead_code.py` over `docs/refactoring/reports/reference_graph.json`
(the 054 output), with the 013 §7 hard-downgrade firewall applied:

| Classification | Count | Action in 057 |
|---|---|---|
| **SAFE_DELETE_CANDIDATE** | **0** | delete (nothing to delete) |
| REVIEW_REQUIRED (under-traced seam) | 345 | KEEP — never deletable by 057 |
| DYNAMIC_REFERENCE_RISK | 125 | KEEP — string-dispatched / data-selected |
| PUBLIC_CONTRACT | 192 | KEEP — CLI / ari.public.* / MCP / routes |
| LIVE | 1324 | KEEP |

`SAFE_DELETE_CANDIDATE: known(allowlisted)=0 · new=0` — verified live this run.

## Why zero is correct (not a miss)

The 054 reference graph is intentionally **sparse** at symbol / skill-internal /
subprocess granularity (many live modules — `memory/file_client.py`,
`llm/cli_server.py`, every `ari-skill-*/src/` helper — appear as graph orphans
because their reachability edges are not statically traced). The 055 firewall
therefore refuses to promote any orphan to `SAFE_DELETE_CANDIDATE` unless it also
(a) is outside every §2.2 dynamic/contract seam and under-traced-seam allow-list,
and (b) is corroborated by ruff `F401/F811/F841`. On the current tree **no node
clears all gates**, so the safe-delete set is empty. Deleting anything from the
345 `REVIEW_REQUIRED` seam bucket would risk removing live-by-string or
skill-internal code — explicitly forbidden by 057 §3/§4 and the Document
Retirement discipline.

## Actions taken

- Deleted: **0 files, 0 symbols, 0 LOC.**
- Edited: none (no `__init__.py` / call-site / ruff-micro cleanup was needed,
  because nothing was removed).
- Contracts (057 §9 "must not change"): untouched — `publish/backends/*`,
  `publish.schema.json`, `_COMPOSITES`, `prompts/**`, `ari.public.*`, CLI, MCP,
  routes all intact.
- Re-scan: `check_dead_code.py --check` remains green (no node removed, no new
  orphan created).

## Before/after counts for the 058 quality-report rollup

```
nodes_deleted:        0
loc_removed:          0
ruff_findings_closed: 0
safe_delete_before:   0
safe_delete_after:    0
```

## Follow-up (not 057's scope)

The 345 `REVIEW_REQUIRED` under-traced-seam candidates are **not** dead-code
findings to action here; they are an artifact of the sparse static graph. If a
future pass wants a tighter dead-code signal, 054's overlay should gain
symbol-level / skill-internal / subprocess reachability edges (relaxing the
firewall's under-traced gate) — then re-run 055/056/057. Until then, 057 is
complete with an empty, safe deletion set.

## Retirement Condition

Retire only when 057's §13 acceptance criteria are met, the implementing change is
merged, and `docs/refactoring/007_subtask_index.md` marks 057 DONE. Since 057
deleted nothing, its "change" is this audit record. See the canonical policy in
`007_subtask_index.md` ("Document Retirement Policy").
