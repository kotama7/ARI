---
sources:
  - path: ari-core/ari/claim_gate_contract.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate/gate.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-core/ari/calibration/evaluator_v1.json
    role: test
last_verified: 2026-08-07
---

# Scientific evaluation contract

ARI separates scientific admission, objective evidence checking, and semantic
advice. These layers are intentionally not interchangeable.

## Metric admission

`MetricContractV1` freezes metric name, unit, direction, comparison scope,
formula, named operands, tolerance, required measured evidence, correctness
requirements, invariants, and formula provenance. Its canonical digest changes
if any scientific field changes. The evaluator projects an admitted idea-owned
contract to `MetricGateContractV1` and persists it once.

For legacy input, `propose_metric_contract` may produce a
`MetricContractProposalV1`. This is an untrusted LLM suggestion with model,
revision, prompt, evidence, and idea digests. It cannot be used until a named
human reviewer creates `MetricAdmissionDecisionV1`. Deterministic parser output
is evidence for that decision, not an admission shortcut.

## Deterministic hard gate

`GateReportV1` binds one gate result to the exact run, policy digest, evidence
digest, metric-contract digest, named-formula implementation digest,
restricted-expression evaluator digest, and every permitted unit conversion.
It has separate typed `blocking_findings` and `advisory_findings`.

Canonical runs consume typed `MeasurementSetV1` documents from the exact run
and node. Artifact references include run id, node id, relative path, and
SHA-256 digest. Missing, changed, unbound, cross-run, or untyped evidence is not
guessed. Unit conversion uses a closed dimension-preserving registry; unknown
units fail. `off` records findings but never blocks; only a final-phase result
can block finalization.

This gate verifies evidence identity and paper-to-result derivation. It does not
prove that an instrument, simulator, benchmark design, or scientific hypothesis
is externally valid.

## Semantic advisory

`SemanticReviewV1` records its dedicated model and revision, full prompt digest,
evidence digest, and the immutable hard-gate report digest. It may flag
overclaim, overgeneralization, unsupported claims, interpretation, and visual
semantics. It cannot change the numeric gate, and failure is represented as
`status: unavailable` rather than a fabricated success.

## Compatibility and calibration

Readers verify every v1 digest. Pre-v1 metric contracts and gate reports have
explicit conservative migration readers; they do not overwrite old files or
reconstruct provenance that was never recorded. The bundled
`ari.calibration/evaluator_v1.json` corpus runs hard-gate positive and negative
controls in CI and carries human semantic labels for model calibration.

The stable Python surface is `ari.public.evaluation` (also re-exported through
`ari.public.claim_gate`). JSON Schemas live in `ari-core/ari/schemas/`.
