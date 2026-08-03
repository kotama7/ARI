# Evaluator calibration corpus

`evaluator_v1.json` is the permanent, versioned calibration input for ARI's
scientific evaluator boundary.  The hard-gate cases execute in CI and cover
numeric agreement, formula resolution, unit conversion, evidence identity,
artifact integrity, and policy behavior.  The semantic cases are human labels
for advisory reviewer calibration; they are not converted into deterministic
scientific truth and are not used to change a hard-gate result.

Changes require a schema-version decision, a human review of every expected
label, and the evaluator calibration test.  Removing a case requires recording
which replacement preserves its positive or negative boundary.
