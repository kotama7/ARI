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

## OpenROAD

`openroad-support-v1.json` admits the official
[OpenROAD-MCP v0.6.1](https://github.com/The-OpenROAD-Project/OpenROAD-MCP/releases/tag/v0.6.1)
Python release at one full commit and the official
[ORFS 26Q3](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/releases/tag/26Q3)
support line with its exact OpenROAD submodule commit. The record binds the
source archive, BSD-3-Clause license, Python dependency lock, direct
dependencies, installed package tree, and ten-tool MCP schema contract.

The official project now recommends its maintained npm distribution and labels
the Python distribution deprecated/final. ARI pins Python 0.6.1 only because the
current reviewed generic process launcher is Python-only. Moving to npm is a new
supply-chain and launcher admission, not an in-place edit of this record.

ARI does not publish the upstream interactive session tools. Their generic exec
surface accepts commands broader than a scientific flow profile should. Each
catalog leaf is instead one immutable `OpenRoadExperimentV1`: inputs, executable,
image, ORFS/OpenROAD commits, PDK/library, seed, thread count, closed Tcl verbs,
declared outputs, metric pointers/units/context, and evidence fixtures are fixed
before sync. Runtime passes `-no_init`, as recommended by the official
[OpenROAD test guidance](https://openroad.readthedocs.io/en/latest/contrib/DeveloperGuide.html),
and writes JSON design metrics through the documented
[`-metrics` interface](https://openroad.readthedocs.io/en/latest/contrib/Logger.html).

### Adding a provider release or toolchain line

1. Resolve the official tag to a full commit and record immutable archive,
   license, lock, direct-dependency, package-tree, and MCP-contract digests.
2. Resolve the ORFS tag and its OpenROAD submodule to full commits. Keep each
   historical support record immutable.
3. Build the provider and OpenROAD/ORFS toolchain in isolated environments;
   never use a mutable image tag or an implicit host `openroad`.
4. Start from `openroad-source.example.yaml`. Close the source workspace so it
   contains exactly its declared regular files, and calculate every digest.
5. Produce exact `ari.openroad-golden/v1` and
   `ari.openroad-replay-fixture/v1` files. The verifier checks their bytes and
   metric identity/ranges; a digest string without the file is rejected.
6. Run `scripts/verify_openroad.py --smoke` and, for a validation run,
   `--run-profile ... --artifact-root ...`. Review the result metrics,
   transcript, output manifest, and cleanup.
7. Sync the catalog and separately approve schema changes. Same-design,
   same-PDK/library profiles remain in one independence group even when their
   version or flow results disagree.

Rollback selects the prior provider/toolchain record, experiment profile,
catalog lock, and cassette. PDK and library license terms are profile-specific;
the OpenROAD/ORFS license does not grant rights to third-party technology data.
