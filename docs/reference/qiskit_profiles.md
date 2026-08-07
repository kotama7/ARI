---
sources:
  - path: ari-skill-tool-registry/src/qiskit_contracts.py
    role: schema
  - path: ari-skill-tool-registry/src/qiskit_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_local.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_remote.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_results.py
    role: implementation
  - path: ari-skill-tool-registry/src/qiskit_verification.py
    role: implementation
  - path: ari-skill-tool-registry/providers/qiskit-support-v1.json
    role: config
  - path: ari-skill-tool-registry/providers/qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json
    role: config
last_verified: 2026-08-05
---

# Qiskit and IBM Quantum experiment profiles

ARI integrates Qiskit through immutable experiments in the federated tool
registry. It does not treat an upstream MCP collection as scientific authority,
and it does not register one ARI wrapper per upstream tool. One reviewed source
can provide many profiles while the model-facing surface remains the registry's
five operations.

## Trust boundary

The current support record fixes the official Qiskit MCP repository commit,
provider wheels/source archives, license, dependency locks, complete installed
package trees, and exact MCP tool contracts. It separately fixes Qiskit 2.5.1,
Qiskit Aer 0.17.2, and Qiskit IBM Runtime 0.48.0. Runtime verifies the selected
interpreter, package tree, distributions, entry point, architecture, and policy
environment before use. A version range, edited installation, alternate module,
runtime download, or unexpected tool contract is not admitted.

These checks establish software identity and protocol conformance, not physical
correctness. Scientific admission additionally requires a closed experiment,
declared limitations, statistical bounds, exact validation/replay evidence, and
domain review. Relevant upstream primary sources are the
[Qiskit MCP repository](https://github.com/Qiskit/mcp-servers),
[IBM's MCP server guide](https://quantum.cloud.ibm.com/docs/en/guides/qiskit-mcp-servers),
[Qiskit QPY API](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qpy), and the
official PyPI release pages linked from the support record.

The only formally promoted identity is
`qiskit/core-0.3.1+aer-0.17.2-local-ideal`, with verified lock digest
`sha256:0407982946540409fc37193bd86130d72f86fc1c1447d581ee39dca1da19f220`.
Its scope is exactly credential-free seeded Bell-state Aer execution under
`ari.quantum.sample.local-ideal/v1`, with QPY, target, software, seed, count
bounds, live MCP schema, golden/replay evidence, all fifteen Provider gates,
and human approval fixed by digest. IBM Runtime, remote simulator, and IBM
hardware remain candidates because no admitted credential, exact live
backend/configuration/calibration identity, or backend-bound golden/replay
evidence is available. The local promotion cannot confer remote authority.
Promotion does not activate the Provider: the committed default `CATALOG.lock`
remains empty, and each run must freeze an explicitly reviewed Provider and
Capability Binding Lock.

The official core MCP contract performs circuit analysis/conversion and
transpilation, but not simulation. The official Runtime MCP contract includes
account-management operations. ARI exposes neither contract directly. It uses
only the minimum reviewed leaves internally and implements local Aer execution
in a separate fixed worker.

## Capability separation

| Backend kind | Capability | Required identity | Reproducibility meaning |
|---|---|---|---|
| `local-ideal` | `ari.quantum.sample.local-ideal/v1` | Aer method, precision, threads, target, seeds | Seeded software simulation without a noise model |
| `local-noisy` | `ari.quantum.sample.local-noisy/v1` | All ideal fields plus exact noise model | Seeded simulation of the declared model, not hardware prediction |
| `remote-simulator` | `ari.quantum.sample.remote-simulator/v1` | Runtime backend/target/access tier and live snapshot | Stochastic remote service result |
| `ibm-hardware` | `ari.quantum.sample.ibm-hardware/v1` | Hardware target and calibration snapshot plus mitigation | Stochastic measurement of one live calibrated backend |

The broker never substitutes one row for another during invocation or replay.
Profiles with the same backend kind/name, target, and software stack share an
independence group. Multiple wrappers or repeated jobs in that group are not
independent-method agreement.

## Closed experiment contract

Every `QiskitExperimentV1` fixes:

- canonical QPY bytes, SHA-256, QPY format byte, producing Qiskit version,
  qubit/classical-bit counts, and every parameter binding with `rad` or `1` unit;
- preset pass manager, optimization level, transpiler seed, and optional initial
  layout;
- target qubit count, sorted unique basis gates, directed coupling map, and a
  digest derived from exactly those fields;
- shots and expected bitstring probability intervals, including the maximum
  allowed unlisted probability mass;
- for local profiles, Aer version, method, precision, CPU/thread bound,
  simulator seed, and either no noise or the complete declared noise model;
- for remote profiles, Runtime client version, backend/version, opaque instance
  digest, access-tier ID, calibration requirement, and mitigation options;
- exact golden and replay evidence files, limitations, timeout, and polling
  interval.

QPY header verification prevents a file produced by a different Qiskit version
from silently retaining an old profile identity. The reviewed Runtime provider
cannot pass parameter bindings through its sampler contract, so remote profiles
with bindings fail validation rather than being silently rebound.

The only invocation input is a bounded, safe `request_id`. It is the idempotency
key and is not scientific input. Circuit bytes, backend, shots, paths, provider
operations, and environment cannot be overridden by the caller.

## Execution and provenance

Local execution follows this closed sequence:

1. Recheck QPY, profile evidence, provider bytes, and exact distributions.
2. Ask the official core MCP to transpile for the declared basis/coupling and
   optimization level.
3. Validate and store the returned transpiled QPY.
4. Start the fixed local worker with a minimal environment and exact
   distribution-version assertions.
5. Execute Aer with declared method, precision, threads, shots, seed, and noise;
   validate counts and statistical limits; publish normalized and raw artifacts.

Remote execution opens one isolated Runtime MCP session for the job:

1. Inject the scoped token and select the reviewed channel without publishing
   account-discovery or account-deletion leaves.
2. Confirm the opaque instance identity; capture backend properties, coupling,
   and calibration; reject backend, target, or simulator/hardware-kind mismatch.
3. Transpile the closed circuit, submit the declared sampler request, and return
   a common asynchronous handle.
4. Map provider status into submitted/running/completed/failed/cancelled states.
   A timeout requests cancellation. A cancellation racing with submission is
   completed once the provider job ID becomes known.
5. Validate backend, shots, result type, bitstrings, counts, and declared bounds
   before publishing the final envelope.

Every raw provider response has a role-distinct, digest-prefixed artifact name.
This prevents identical bytes used for different roles from confusing artifact
identity. The stable backend snapshot digest excludes volatile capture time,
queue count, and operational status, while the original timestamped response is
still preserved. The result records circuit/transpiled-circuit/target/software/
method/backend snapshot/calibration/job/result identities and normalized counts.

## Credential handling

`QISKIT_IBM_TOKEN` is the only credential accepted by this adapter. Declare it
through the Skill's `quantum.ibm-runtime` credential scope. Do not place it in
`sources.yaml`, a profile, launcher `literal_env`, CLI argument, lock, notebook,
fixture, or checkpoint.

The core provider and local worker never receive it. The Runtime subprocess gets
it through a minimal environment bridge. Exact secret values are redacted from
MCP text, structured content, diagnostics, exceptions, and stderr before they
cross the provider boundary. Source and lock identities record no token value;
the IBM instance is represented by an operator-reviewed digest, not its raw CRN.
Record/replay files must pass the same absence checks.

## Evidence, replay, and interpretation

`ari.qiskit-golden/v1` binds profile ID, experiment digest, and validated counts.
`ari.qiskit-replay-fixture/v1` also binds invocation arguments, method digest,
shots, and completed normalized result. Both files must exist and match their
declared SHA-256; metadata containing only a digest is insufficient.

Record mode additionally captures real raw artifacts and the exact catalog and
policy selection. Replay requires the same immutable tool identity and returns
the recorded result without provider packages, network, IBM credentials, or
backend access. Replay demonstrates provenance-preserving analysis, not that a
live quantum backend would reproduce the same stochastic counts.

Bell/GHZ fixtures exercise seeded ideal and noisy local execution. Statistical
bounds are part of the profile and must be justified for the intended claim.
Passing them does not validate arbitrary circuits, a new noise model, another
backend, a later calibration, or a larger research conclusion.

## Operator procedure

Start with `ari-skill-tool-registry/providers/qiskit-source.example.yaml` and use
an isolated exact environment. Optional dependency groups are convenience pins;
a production provider environment should be built and retained as immutable
review evidence.

```bash
cd ari-skill-tool-registry
python scripts/verify_qiskit.py \
  --core-python /absolute/qiskit-env/bin/python \
  --core-package-root /absolute/qiskit-env/lib/python3.13/site-packages/qiskit_mcp_server \
  --experiment /absolute/local-profile.yaml \
  --smoke --run-profile bell-local-ideal \
  --artifact-root /absolute/verification-artifacts
python src/sync_catalog.py
python src/sync_catalog.py --approve --approve-schema-changes
```

For Runtime profiles, add both `--runtime-python` and
`--runtime-package-root`. A remote smoke check may consume quota or submit work
only when `--run-profile` names a remote profile; package/profile verification
alone does not submit a job.

Review the pending catalog diff for capabilities, backend lineage, independence
groups, permissions, schema, evidence, and limitations. Approval is operator
action outside an active run. Run the registry tests, generated-contract check,
manifest check, credential redaction test, and offline replay before promotion.

## Update, rollback, and deletion gates

A provider, Qiskit, Aer, Runtime, backend target, mitigation, or circuit update
creates new immutable support/profile identity. Never mutate an historical
support record to mean different bytes. Rebuild isolated environments, review
the upstream diff and licenses, regenerate tool/package-tree/contract digests,
re-run scientific fixtures, and approve the resulting catalog/schema diff.

Rollback selects the prior support record, environment, profile, QPY/evidence,
catalog lock, and cassette. First reconcile every submitted remote handle; a
rollback cannot erase responsibility for a live provider job.

Retiring a Qiskit support line requires zero active catalog references, terminal
or reconciled remote jobs, replacement/migration notes, successful replay of its
published cassettes without the provider, and retention of readers needed by the
support window. Only then may provider environments and unreachable adapter
branches be removed. QPY, result, cassette, and migration readers remain while
published evidence still depends on them.
