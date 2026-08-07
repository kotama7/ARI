# ari-skill-evaluator

MCP boundary for immutable metric contracts and evidence-grounded evaluation.
It separates deterministic scientific admission and checking from advisory LLM
judgment; it does not manufacture a scalar scientific-quality truth.

## Flow

1. `make_metric_spec` deterministically consumes an admitted
   `ResearchContractV1`. The resulting `MetricGateContractV1` is digest-bound,
   persisted once, and cannot change vocabulary on a rerun.
2. A legacy idea without that contract may call `propose_metric_contract`.
   This is an explicit LLM proposal only; it records model, revision, prompt,
   idea, and evidence digests and always requires human review.
3. `make_metric_spec(..., proposal_json=..., reviewer=...)` admits the exact
   proposal and records `MetricAdmissionDecisionV1`. Without a reviewer it does
   not persist a scientific contract.
4. `claim_evidence_hard_gate` recomputes claims from exact-run typed
   measurements and digest-verified artifacts. Its `GateReportV1` is the only
   blocking evaluation output.
5. `evidence_grounded_semantic_review` emits a provenance-bound
   `SemanticReviewV1`. It is advisory and verifies that the hard-gate report was
   not modified.

## Tools

| Tool | Role | LLM |
|---|---|:---:|
| `make_metric_spec` | Deterministic mint/read/admission boundary | No |
| `propose_metric_contract` | Explicit untrusted metric-contract proposal | Yes |
| `claim_evidence_hard_gate` | Deterministic evidence and arithmetic gate | No |
| `evidence_grounded_semantic_review` | Independent semantic advisory | Yes |

## Model policy

- Metric proposal: explicit `model` argument, then
  `ARI_MODEL_METRIC_PROPOSAL`, then `ARI_LLM_MODEL`, then `gpt-4o-mini`.
- Semantic review: explicit `model` argument, then
  `ARI_MODEL_SEMANTIC_REVIEW`, then `ARI_LLM_MODEL`, then `gpt-4o-mini`.
- `ARI_SEMANTIC_REVIEW_MODEL_REVISION` records the semantic model revision when
  the caller does not provide one.

The evaluator does not read the former `ARI_MODEL_EVAL` or `ARI_MODEL`
aliases. Other core evaluators may retain those variables during their own
compatibility windows.

## Verification

```bash
PYTHONPATH=../ari-core pytest tests/ -q
PYTHONPATH=../ari-core pytest ../ari-core/tests/test_claim_gate_v1.py -q
```

See `docs/reference/evaluation_contract.md` for the versioned contracts and
legacy-reader boundary.
