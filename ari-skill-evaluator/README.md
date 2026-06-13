# ari-skill-evaluator

MCP skill for metric-spec generation and claim/evidence verification.

**Role: spec + verifier, not a judge.**  It mints the per-run metric
spec and verifies that the paper's claims are grounded in executed
evidence — it does not produce a scalar quality score itself (P3 multi-
objective evaluation principle).

## Flow

1. The agent calls `make_metric_spec(experiment_text)` to derive the
   `MetricSpec` (expected_metrics, metric_keyword, scoring_guide,
   min_expected_metric). It prefers the idea-stage canonical
   `primary_metric` and falls back to deterministic parsing of the
   experiment file. On first mint it also attaches a metric-correctness
   contract (concept invariants + the idea's falsifiable claims) and
   persists it to `metric_contract.json`; the contract is **mint-once**
   (frozen on first persist) so the evidence vocabulary stays stable
   across the run.
2. Around the paper build, `claim_evidence_hard_gate` (deterministic,
   no LLM) verifies claim/number consistency against executed evidence.
3. `evidence_grounded_semantic_review` (LLM, non-blocking) flags
   over-claiming / mis-interpretation beyond the evidence.

## Tools

| Tool | Description | LLM |
|---|---|:---:|
| `make_metric_spec` | Mint the `MetricSpec` + mint-once metric-correctness contract from the experiment/idea | ✓ |
| `claim_evidence_hard_gate` | Deterministic claim-evidence HARD GATE (thin wrapper over ari-core's gate); in strict mode the final phase BLOCKS `finalize_paper` | ✗ |
| `evidence_grounded_semantic_review` | Non-blocking advisory review of over-claiming / interpretation | ✓ |

## Environment variables

| Variable | Purpose | Fallback order |
|---|---|---|
| `ARI_MODEL_EVAL` | Evaluator-specific LLM model | (none) |
| `ARI_MODEL` | ARI common model | used when `ARI_MODEL_EVAL` is unset |
| `ARI_LLM_MODEL` | Cross-skill fallback | used when both above are unset |

## P2 exception

`make_metric_spec` and `evidence_grounded_semantic_review` call an LLM,
so they are **not** byte-deterministic; reruns may produce slightly
different specs/reviews. `claim_evidence_hard_gate` uses no LLM and is
deterministic. See `docs/concepts/PHILOSOPHY.md#p2-exceptions` for the
project's stance on allowed P2 deviations.

## Tests

```bash
pytest tests/ -q
```

## See also

- `docs/reference/skills.md#ari-skill-evaluator` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
- `docs/reference/environment_variables.md` — env-var table.
