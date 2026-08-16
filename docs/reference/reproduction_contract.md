---
sources:
  - path: ari-skill-paper-re/src/contracts.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
last_verified: 2026-08-16
---

# Reproduction and grading contract

`ari-skill-paper-re` v1.0 separates an immutable scientific input from every
execution attempt. A score is publishable only when it is bound to a verified,
successful reproduction run and all requested judge runs complete.

The checked-in JSON Schemas are under `ari-skill-paper-re/schemas/`. Run
`python ari-skill-paper-re/scripts/sync_contracts.py` to reject schema drift.

## Records and identity

| Record | Identity and purpose |
|---|---|
| `ReproductionPlanV1` | Canonical digest of rubric, input tree, `reproduce.sh`, command, sandbox/image, timeout, resource request, expected artifacts, and policy. |
| `ReproductionAttemptV1` | One terminal execution, linked to its parent attempt and plan, with environment identity, exact log/output-manifest digests, output-tree digest, missing artifacts, and typed failure evidence. |
| `ReproductionRunV1` | Ordered contiguous attempt lineage. Only a successful run selects one successful attempt. |
| `GradeReportV1` | Rubric/paper/run digests, judge identity and independence, all leaf evidence/raw responses, run count, variance, negative controls, call traces, and final validity. |

Every record rejects unknown fields and a digest that does not match its
canonical finite-JSON payload. Artifact paths are relative, cannot traverse,
and are verified by digest and byte count before use.

## Workspace layout and retry

For plan digest `<P>`, metadata lives under the caller's source tree:

```text
.ari-reproduction/
  <P>/
    plan.json
    input-manifest.json
    input/                         # content-addressed, read-only snapshot
    run.json
    attempts/
      0001-<attempt-id>/
        work/                      # private writable execution tree
        output-manifest.json
  latest.json                     # verified active run pointer
```

Execution never writes results into the caller's source files. Symlinks,
non-regular outputs, files above 1 GiB, and trees above 8 GiB are removed from
the private output and make the attempt fail with `filesystem-policy`.
`reproduce.log` is written atomically. The output manifest records every added,
modified, or deleted path and any policy incident.

A repeated successful plan is an idempotent replay after re-verifying its run,
artifacts, and output tree. A repeated failed/timed-out/cancelled plan creates a
new attempt whose `parent_attempt_id` points to the preceding attempt. Changing
the source, rubric, image, policy, resources, or timeout creates a different
plan rather than silently extending old lineage.

## Sandbox admission

| Substrate | Immutable identity | Default network denial |
|---|---|---|
| Docker | Full local `sha256:<image-id>` or `name@sha256:<digest>` | `--network=none`; read-only root, bounded tmpfs, no capabilities, no-new-privileges, PID limit |
| Apptainer/Singularity | Local regular non-symlink SIF (hashed) or remote `@sha256:<digest>` URI | isolated network namespace with clean environment, contained filesystem, and no home mount |
| Local | Host/toolchain identity recorded | Requires explicit administrator isolation attestation; otherwise choose `network_policy=inherit` explicitly |
| SLURM | Digest-bound common HPC handoff plus scheduler/module/resource/runtime evidence | Requires administrator isolation attestation for `deny`; the job uses `--export=NIL` and explicit literals/modules |

The execution environment is constructed from a minimal allowlist and never
copies the parent environment. `network_policy=inherit` is recorded as
unverified; it is not represented as isolation. Timeout and cancellation kill
the full local/container process group, forcibly remove a named Docker
container, or cancel the scheduler handle before terminalization.

`auto` chooses an available substrate but does not invent an image or weaken a
policy. If the selected substrate cannot satisfy immutable-image, network,
GPU, scheduler, or resource constraints, planning/execution fails explicitly.

## Grade validity

`grade_with_simplejudge` requires all of the following:

- a schema-valid rubric whose paper digest matches non-empty supplied paper
  text;
- a digest-verified `ReproductionRunV1` with status `succeeded`;
- every requested judge run to complete;
- persisted raw per-call and per-leaf responses;
- completed negative controls below the configured threshold.

Judge/provider failure, schema mismatch, missing/tampered/failed reproduction,
or unavailable negative controls produces `status=failed` with no scientific
score. A completed grade whose negative control exceeds the threshold retains
the observed score for diagnosis but is marked `invalid-negative-control`, not
`valid`. Skipping controls has the same invalid status. Reusing the rubric
generator model as judge is reported as `not-independent` rather than being
presented as an independent audit.

## PaperBench provenance and patch removal

`paperbench_patches.json` pins the exact reviewed upstream Git commit and maps
each remaining runtime adaptation to upstream symbols, rationale, and a
deletion gate. An override is accepted only when both `ARI_PAPERBENCH_PATH` and
the matching `ARI_PAPERBENCH_COMMIT` are supplied and Git confirms that exact
identity. Package roots are temporarily visible only during bootstrap and are
then removed from `sys.path`; pip-installed PaperBench is not a fallback.

The compatibility inventory is intentionally shrinking. v1.0 removed:

- the host-local sandbox fallback and `ARI_PHASE1_ALLOW_FALLBACK`;
- mutable default images and `pb-env` / `pb-reproducer` `:latest` aliases;
- the `apptainer_image` tool argument and `ARI_PHASE1_SINGULARITY_IMAGE`;
- source-mutating salvage wrappers and implicit `code_only` grading;
- duplicated local/Docker/Apptainer/SLURM runner entry points.

A remaining PaperBench adaptation is deleted when its inventory gate passes
against the pinned upstream suite. A compatibility name or fallback may not be
reintroduced without a named owner, removal release, migration test, and
fail-closed security review.
