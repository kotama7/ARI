---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-core/ari/schemas/execution_request_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/execution_result_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/measurement_set_v1.schema.json
    role: schema
last_verified: 2026-08-02
---

# Execution and measurement contracts

ARI uses one public contract for workspace access, local or container process
execution, complete logs, and scientific measurements. Skills import it from
`ari.public.execution`; scheduler lifecycle remains owned by `ari-skill-hpc`.

## Closed workspace

`WorkspaceRefV1` fixes one canonical absolute root. Caller paths cannot contain
`..`, escape through an absolute path, or traverse a symlink. Reads and writes
walk path components through directory file descriptors with `O_NOFOLLOW`.
Writes use a private file, `fsync`, and an atomic rename. A caller-selected
`work_dir` is created only after it has passed the same containment policy.

The policy deliberately has no “helpful” basename fallback: a rejected path is
an error and is never rewritten into a different target.

This is the file-access boundary for ARI tools and their declared
inputs/artifacts; it is not a host filesystem sandbox for arbitrary child code.
Code that is not trusted to run as the ARI service account requires a reviewed
container, scheduler isolation, or another operating-system sandbox. The
execution record must not claim stronger isolation than the selected substrate.

## Execution request

`ExecutionRequestV1` contains exactly one of structured `argv` or an explicitly
enabled `shell_command`, plus:

- canonical workspace and wall-time limit;
- a minimal explicit environment (the parent environment is not copied);
- CPU, address-space, process-count, and output-size limits;
- `inherit` or `deny` network policy;
- relative input paths bound to SHA-256 digests;
- optional immutable or explicitly unresolved container identity.

Declared script operands are digest-checked and replaced with private immutable
snapshots before launch. Other declared inputs are marked
`verified-at-launch`; the result never claims they were snapshotted.

Host execution cannot prove network denial and therefore rejects `network:
deny`. A reviewed container adapter may request denial only when its exact argv
contains the runtime isolation boundary (`--network none` for Docker or the
corresponding Apptainer/Singularity network namespace). Container execution
uses a clean environment and refuses an unsupported-runtime host fallback.

## Execution result

`ExecutionResultV1` separates two identifiers:

- `execution_identity` is the canonical digest of the request and remains the
  same across retries;
- `attempt_id` is unique for each actual launch.

Timeout and cancellation terminate and reap the complete process group. The
result reports the requested limits separately from `limit_report`, which says
what the POSIX kernel/executor actually enforced. Unsupported requested kernel
controls fail closed.

The requested `network` value is also separate from `network_report`:
`inherited`, `isolated`, or `external-unverified`. Normalizing output from an
external launcher therefore cannot silently turn a requested denial into a
verified isolation claim.

Inline stdout and stderr are bounded previews. The complete byte streams are
always written inside `.ari-execution/` as content-addressed artifacts with
digest and size. Consumers can recover and verify the full output without
rerunning the command.

## Measurements

`MeasurementSetV1` keeps parameters, measurements, predictions, and scores in
disjoint namespaces. Each `MeasurementRecordV1` records:

- metric identity and a finite numeric value;
- a declared unit, or the explicit state `unit_status: missing`;
- method/source provenance;
- the parameters under which it was measured;
- execution identity, attempt identity, terminal status, and exit code;
- the SHA-256 artifacts supporting the value.

`coding-skill.emit_results` writes the canonical object under
`measurement_set`, while retaining the v1 flat projection during the P6
compatibility window. The common parser cross-checks both views and rejects a
split-brain document. Legacy v1 and unversioned files are read-only migration
inputs; absent units and execution evidence remain explicitly missing rather
than being inferred.

For coding-skill output, `scientifically_admissible` is true only when at least
one measurement exists and every measurement has a declared unit, a successful
zero-exit execution identity, and at least one evidence artifact. This flag is
an integrity prerequisite, not a domain-validity judgment; evaluator claim and
domain gates still apply.

The execution context includes an unguessable, server-issued receipt. At
emission time coding-skill matches the receipt to the exact workspace,
execution attempt, status, exit code, and artifact list, then re-hashes every
artifact. Fabricated contexts, expired server-session receipts, and modified
logs fail closed before a results file is written. The receipt itself is not
persisted in the scientific record.

## Schemas and migration

The generated normative schemas are:

- `workspace_ref_v1.schema.json`
- `execution_request_v1.schema.json`
- `execution_result_v1.schema.json`
- `measurement_set_v1.schema.json`

Run `python scripts/sync_skill_metadata.py` to check schema drift. During P6,
producers must emit the canonical measurement set, consumers must use
`parse_measurement_document`, and compatibility-reader telemetry must reach
zero before the flat writer/coercion and unversioned reader are deleted.
