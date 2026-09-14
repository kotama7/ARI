---
sources:
  - path: ari-core/ari/analysis.py
    role: implementation
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-benchmark/tests/test_server.py
    role: test
last_verified: 2026-08-02
---

# Deterministic analysis contract

ARI separates scientific measurement, statistical analysis, figure rendering,
and acceptance decisions. `ari-skill-benchmark` owns summaries, inference, and
run comparison. `ari-skill-plot` owns rendering. `ari-skill-evaluator` owns
scientific acceptance gates.

## Versioned boundary

`ari.public.analysis` exports four immutable contracts:

- `AnalysisRequestV1` for unit-bearing inline or digest-bound samples;
- `StatisticalTestRequestV1` for an explicit family of comparisons;
- `RunComparisonRequestV1` for scalar outcomes with substrate identity; and
- `AnalysisResultV1` for summaries, statistical results, or run rankings.

The generated schemas are `analysis_request_v1.schema.json`,
`statistical_test_request_v1.schema.json`, `run_comparison_request_v1.schema.json`,
and `analysis_result_v1.schema.json`.

## Scientific invariants

Units are never inferred. A comparison fails when metric identities or units
differ. Empty and all-missing samples fail. `missing_policy=error` rejects any
missing or non-finite observation; `drop` records the removed count. Ordered
paired samples require equal lengths, while `pair_id` pairing requires unique,
matching identities.

Every statistical result includes both sample counts, test statistic, raw and
adjusted p-values, an effect size, a confidence interval, normality and variance
diagnostics where defined, pairing evidence, independence status, library
versions, and a resolved input digest. A request with more than one comparison
must declare Bonferroni, Holm, or Benjamini-Hochberg correction. An immutable
`analysis_plan_digest` binds a pre-registered plan without treating it as proof
that the plan was followed.

Replicate independence is never inferred from repeated values or a shared
backend. `compare_runs` groups identical backend/environment substrates,
labels shared substrate explicitly, and reports independence only as declared
when unique replicate identities are present. Cross-environment rankings fail
by default and require an explicit caveated opt-in.

## Sources and artifacts

CSV, JSON, and non-object NumPy sources use `WorkspaceRefV1`, a safe relative
path, a byte limit, and an expected SHA-256 digest. The complete source bytes,
including CSV metadata comments, remain digest-bound. Optional result artifacts
are written atomically as deterministic JSON and CSV under a path keyed by the
resolved input digest.

Figure requests now go to `plot-skill:render_figure`. The renderer consumes
finite values and explicit units, executes no caller code, and returns an
`ari.figure-manifest/v1` projection with source/data/spec digests, record IDs,
render environment, and PNG/PDF byte digests.

## Removal and recovery

The public benchmark `plot` tool, matplotlib, pandas, schema-less file parsing,
and the unimplemented `compare_runs` declaration were removed in v0.2. The
former p-value-only result is not accepted as an `AnalysisResultV1`; migration
readers must remain outside the public MCP inventory and are removed after P6
telemetry reaches zero. Roll back to the commit before v0.2 only to read an old
checkpoint, never to produce new scientific results.
