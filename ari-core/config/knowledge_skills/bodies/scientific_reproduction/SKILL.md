# Scientific Reproduction

## When to use

Use when reproducing a paper, repository, experiment package, or reported result.

## Preconditions

The target publication, source revision, artifacts, expected claims, environment,
and Verification Contract are identified and content-addressed.

## Procedure

Inspect the package without executing attachments, acquire required execution
capabilities through binding, reconstruct the declared environment, execute the
locked reproduction workflow, retain raw outputs, compare against expected
claims, and request independent reproduction Harness verification.

## Decision points

Classify deviations as target defects, documentation gaps, environment limits,
scientific failures, or infrastructure errors using fixed evidence—not preference.

## Failure conditions

Stop certification on mutable source, unbound execution, missing dependency or
license, target substitution, verifier bypass, or unresolved result discrepancy.

## Expected artifacts

Produce source/environment locks, execution requests/results, raw and normalized
measurements, discrepancy log, reproduction Attestation, and limitations.

## Scientific cautions

Reproduction differs from artifact correctness and claim transcription. A Harness
pass applies only to its declared property and scope.

## Evaluation obligations

Require source/environment integrity, execution replay, result comparison,
reproduction verification, claim-evidence consistency, and publication
certification for any final verified claim.
