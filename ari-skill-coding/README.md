# ari-skill-coding

Workspace-scoped code authoring, bounded process execution, complete log
capture, and typed scientific result emission for ARI agents.

## MCP tools

| Tool | Contract |
|---|---|
| `write_code` | Atomic text write below the configured workspace root; rejects traversal and symlinks |
| `edit_code` | Exact-snippet replacement in an existing file; `old_string` must match exactly once unless `replace_all` is set, so an ambiguous edit fails instead of changing the wrong place |
| `run_code` | Structured interpreter argv, source SHA-256 verification, immutable source snapshot, timeout/process limits, and complete log artifacts |
| `run_bash` | Explicit shell permission for builds or compound commands; local or configured clean container execution |
| `emit_results` | Canonical `ari.measurement-set/v1`; rejects non-finite or non-JSON values instead of coercing them |
| `read_file` | Symlink-safe, bounded and paginated workspace read |
| `describe_environment` | Node-aware environment catalog (arch, CPU, GPUs, compilers on PATH, raw `module avail`, and the names — never the values — of set toolchain env vars); no arguments |

`run_code` and `run_bash` return a stable `execution_identity`, a per-attempt
`attempt_id`, the exact enforcement report, input bindings, container identity,
and content-addressed stdout/stderr artifacts. Copy the returned
`measurement_execution` object into `emit_results.execution` to bind measured
values to the successful execution and its evidence. The object includes a
server-session receipt; emission verifies the exact attempt and re-hashes its
artifacts before writing.

## Security and provenance

- `ARI_WORK_DIR` is the core-owned root. Caller `work_dir` values may only name
  subdirectories below it and are validated before creation.
- Reads and writes walk path components without following symlinks. Writes are
  atomic.
- Workspace scoping protects tool-mediated file access; host child code is not
  an operating-system filesystem sandbox. Run code that is not trusted as the
  ARI service account only in a reviewed isolated substrate.
- The parent process environment is not copied to user code. Only a fixed
  platform environment and explicitly reviewed values reach the launcher.
- Local execution uses a new process group; timeout/cancellation reaps the
  group. Requested POSIX resource controls fail closed if unavailable.
- Host execution declares network inheritance. The manifest therefore grants
  `network` only to the two execution tools; network denial requires a reviewed
  isolated substrate. Results report the requested policy separately from the
  actual `inherited`, `isolated`, or `external-unverified` enforcement state.
- Container execution uses exact structured runtime argv, a clean environment,
  no unknown-runtime host fallback, and either a SHA-256 image/SIF identity or
  an explicit `unresolved` status for a mutable tag.
- Inline logs are bounded previews. Complete logs are retained under
  `.ari-execution/` and can be checked against their SHA-256 digests.

## Scientific measurements

Measurements must be finite numbers and cannot overlap parameter, prediction,
or score names. Units are never inferred. A measurement without a unit is
written with `unit_status: missing`. `scientifically_admissible` requires at
least one measurement and, for every record, a unit, a successful zero-exit
execution identity, and an evidence artifact. Domain-specific validity remains
the evaluator's responsibility.

New files contain only the canonical `measurement_set` object. The shared
parser retains a read-only migration path for old flat `results.json` files and
cross-checks mixed historical documents, but the writer never recreates those
fields or coerces unsupported values.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ARI_WORK_DIR` | Core-owned workspace root | `/tmp/ari_work` |
| `ARI_MAX_CHILD_PROCS` | Optional POSIX process-count limit | unset |
| `ARI_CONTAINER_IMAGE` | SIF path or OCI image reference | unset (host) |
| `ARI_CONTAINER_MODE` | `auto`, `docker`, `singularity`, or `apptainer` | `auto` |
| `APPTAINER_CACHEDIR` / `SINGULARITY_CACHEDIR` | Explicit runtime cache directory | runtime default |

## Development

```bash
PYTHONPATH=../ari-core pytest -q tests
```

The permanent contract is documented in
`docs/reference/execution_contract.md`; generated JSON Schemas live under
`ari-core/ari/schemas/`.
