# ari-skill-evaluator requirements

## Scientific ownership

- The idea stage owns `MetricContractV1`; evaluator and transform consume the
  same immutable contract through `ari.public`.
- Deterministic parsing may report candidate vocabulary, but cannot admit it as
  scientific truth.
- LLM metric extraction is an explicit `MetricContractProposalV1` operation.
  It always requires a named human reviewer and an
  `MetricAdmissionDecisionV1` before persistence.
- A persisted canonical contract is mint-once. A conflicting second mint is an
  error. The pre-v1 reader is conservative, read-only, and never guesses a
  missing unit.

## Hard gate

`claim_evidence_hard_gate` delegates to `ari.public.claim_gate.run_hard_gate`
and emits `GateReportV1`. It must:

- bind the report to policy, evidence, formula implementation, metric contract,
  and permitted unit-conversion provenance;
- resolve canonical evidence only from the exact run and known executed node;
- verify typed measurement and artifact digests before using values;
- reject unknown units, formulas, nodes, cross-run references, missing
  evidence, and changed artifacts without inference;
- separate typed `blocking_findings` from `advisory_findings`;
- block only at the final phase according to policy, with `off` never blocking.

The wrapper returns an error-only payload when `should_block` is true so the
pipeline cannot finalize. Old published reports are readable through
`migrate_legacy_gate_report`; missing old provenance is marked unrecorded rather
than reconstructed.

## Semantic review

`evidence_grounded_semantic_review` uses a separate model policy and prompt. It
records model/revision, full prompt digest, evidence digest, and hard-gate
report digest in `SemanticReviewV1`. A timeout, model failure, or parse failure
returns `status: unavailable`, never success. It is non-blocking and cannot
modify or override the hard-gate bytes.

## Acceptance suite

- Evaluator unit tests cover deterministic mint, explicit proposal/admission,
  frozen-contract conflicts, model-policy separation, and hard-gate
  immutability.
- Core calibration covers numeric mismatch, formula failure, unit conversion,
  unknown units, missing/cross-run evidence, artifact tampering, policy modes,
  semantic overclaim labels, and negative controls.
- Workflow/manifest conformance rejects every non-empty workflow tool that is
  absent from its skill manifest.
