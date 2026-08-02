# Collection support records

Files in this directory are reviewed supply-chain inputs, not runtime discovery
results. A collection release is supported only when its complete record is
present here and its adapter accepts the exact record.

## ToolUniverse

`tooluniverse-support-v1.json` currently admits ToolUniverse `1.3.1`. The record
was derived from the official GitHub tag/commit, PyPI artifacts, Apache-2.0
license, `uv.lock`, `pyproject.toml`, and compact-mode definition. It contains:

- the full upstream commit and tag;
- SHA-256 for wheel, sdist, license, dependency lock, and compact contract;
- the direct dependency declarations and Python constraint;
- a canonical path/size/SHA-256 tree digest for every non-cache file below the
  installed `tooluniverse` package (3,542 files for `1.3.1`).

The package license does not grant or validate the terms, availability, quality,
or scientific correctness of every external API/data/model reached by a leaf.
Those identities and limitations remain leaf provenance and admission concerns.

### Adding or updating a release

1. Review the official GitHub release/tag and resolve it to a full commit.
2. Download wheel and sdist from PyPI and verify their published SHA-256 values.
3. Review the license, direct dependencies, `uv.lock`, compact tool definitions,
   stdio entry point, and relevant loader/execution changes.
4. Build an isolated environment from the frozen dependency lock, install the
   exact wheel without source substitution, and run
   `scripts/verify_tooluniverse.py --smoke` for each proposed category.
5. Add a new immutable support-matrix record. Never edit a historical release
   record to describe different bytes.
6. Sync `sources.yaml` without approval and review the pending lock/index/diff,
   quarantine changes, category profile changes, permissions, schema
   normalization, lineage, and admission decisions.
7. Approve ordinary changes with `--approve`. If any input/output/default schema
   changed, separately review them and add `--approve-schema-changes`.
8. Run package tests, generic/direct-provider conformance, record/replay without
   the provider environment, docs build, and manifest/schema checks.

Rollback uses the previous support record, provider environment, active
`CATALOG.lock`, and cassettes. Runtime never changes a release or catalog on
startup.
