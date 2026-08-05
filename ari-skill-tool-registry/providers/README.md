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
6. Run the Provider-specific promotion command with the authenticated human
   maintainer identity. Retain its digest-bound promotion approval; registration
   evidence alone is only `eligible-for-verified`.
7. Sync `sources.yaml` without approval and review the pending lock/index/diff,
   quarantine changes, category profile changes, permissions, schema
   normalization, lineage, and admission decisions.
8. Approve ordinary changes with `--approve`. If any input/output/default schema
   changed, separately review them and add `--approve-schema-changes`.
9. Run package tests, generic/direct-provider conformance, record/replay without
   the provider environment, docs build, and manifest/schema checks.

Rollback uses the previous support record, provider environment, active
`CATALOG.lock`, and cassettes. Runtime never changes a release or catalog on
startup.

The formally promoted ToolUniverse, Qiskit local-Aer, and OpenROAD local-CPU
identities live in separate immutable subdirectories. Each `verified-lock-v1.json`
binds the exact Provider-specific capability scope and a human-maintainer
approval. A support record or example YAML alone is still candidate, and a
promotion lock never edits or activates the default `CATALOG.lock`.

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

`openroad/0.6.1+orfs-26q3-gcd-nangate45/verified-lock-v1.json` is the promoted
local scope. It is local-MCP, x86_64 CPU, one thread, fixed GCD
post-placement CTS/routing, Nangate45, and the retained ORFS SIF. The SIF itself
is not committed because it is 1.54 GB; its full SHA-256, source OCI manifest,
inner OpenROAD digest, and required materialization path are fixed.

`openroad/0.6.1+orfs-26q3-gcd-nangate45-slurm-cpu/verified-lock-v1.json` is a
second, independent promoted scope with lock
`sha256:d640dd226c101f9027e11f11c2201afd694b4914c11d7d45b458d142bc2971fd`.
It fixes an anonymous exclusive-node SLURM CPU allocation, zero requested GPUs,
the same GCD/Nangate45 scientific inputs, exact scheduler-client snapshot,
PRoot/SIF/unsquashfs/worker-Python identities, nonce-bound fixed-wrapper
terminal evidence, live result, and human approval. GPU execution, another
design/PDK/corner, and the npm MCP distribution remain separate identities and
require their own promotion evidence.
The only promotion entry points are the human-admin commands
`scripts/promote_openroad_gcd_cpu.py` and
`scripts/promote_openroad_gcd_slurm_cpu.py`; Agent MCP surfaces cannot call
them.

An OpenROAD SLURM identity is site-private. Its clear cluster, partition, and
node selectors exist only in an ignored runtime configuration with a 256-bit
nonce. Checked-in scheduler snapshots, manifests, evidence, fixtures, and locks
bind the salted full SHA-256 `site_identity_digest` and disclose no physical
selector. Promotion fails if the site file is tracked, is not ignored, has a
predictable nonce, or if any Git candidate file contains a clear site identity.
The same fail-closed check covers staged blob bytes, filenames, and symlink
targets and is installed for this checkout as `.githooks/pre-commit`.

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

## Qiskit and IBM Quantum

`qiskit-support-v1.json` admits the official
[Qiskit MCP server 0.3.1](https://pypi.org/project/qiskit-mcp-server/0.3.1/)
and
[IBM Runtime MCP server 0.6.1](https://pypi.org/project/qiskit-ibm-runtime-mcp-server/0.6.1/)
from the shared [Qiskit MCP repository](https://github.com/Qiskit/mcp-servers),
at one full commit. It also fixes Qiskit 2.5.1, Qiskit Aer 0.17.2, and Qiskit
IBM Runtime 0.48.0. The record binds each provider source archive, wheel,
Apache-2.0 license, dependency lock, direct dependencies, complete installed
package tree, and exact MCP tool contract. Scientific distribution source
archives and Python constraints are recorded separately from provider bytes.

The core provider's reviewed contract has seven circuit-analysis/conversion/
transpilation tools and does not execute a circuit. The Runtime provider has
twenty tools, including account-management operations that ARI must not publish.
ARI therefore exposes neither upstream set directly: each catalog leaf is one
immutable `QiskitExperimentV1`, and the adapter internally calls only the
transpilation or setup/snapshot/sampler/status/result/cancel subset needed by
that profile. Local Aer execution happens in a separate distribution-verified
worker. The four backend kinds have distinct capabilities and admission meaning.

`qiskit/core-0.3.1+aer-0.17.2-local-ideal/verified-lock-v1.json` promotes only
the credential-free local-Aer profile and capability
`ari.quantum.sample.local-ideal/v1`. IBM Runtime MCP and IBM hardware are not
covered by this approval. Their candidate support pins remain useful inputs,
but formal promotion additionally requires an admitted credential scope, exact
backend/configuration/calibration identity, and live backend-bound golden/replay
evidence without storing the token or raw instance CRN.
The only promotion entry point is the human-admin command
`scripts/promote_qiskit_local_aer.py`; Agent MCP surfaces cannot call it.

QPY is the canonical circuit artifact. The verifier checks its bytes, `QISKIT`
header, QPY format byte, producing Qiskit major/minor/patch, circuit dimensions,
profile digest, and exact golden/replay files. Remote profiles additionally bind
backend version, target basis/coupling digest, an opaque instance digest, access
tier, mitigation policy, and captured calibration identity. Raw live snapshots
remain artifacts even though volatile queue/operational fields are excluded
from the stable scientific snapshot digest.

### Adding or updating a provider/software release

1. Review the official repository tags and resolve both provider releases to
   full commits. Download the PyPI wheel/sdist and verify published hashes.
2. Review the license, dependency lock, direct dependencies, entry points, and
   exact tool definitions. Record a complete canonical package tree and contract
   digest; do not edit an existing historical release to describe new bytes.
3. Review Qiskit, Aer, and Runtime source releases separately. Aer's reduced
   maintenance status is a risk requiring explicit acceptance for each support
   line.
4. Build isolated exact environments. Runtime environments must include the
   reviewed core MCP distribution because the official Runtime package depends
   on it. Do not resolve ranges at registry startup.
5. Start from `qiskit-source.example.yaml`. Create QPY with the pinned Qiskit,
   calculate target/software identities, and produce exact
   `ari.qiskit-golden/v1` and `ari.qiskit-replay-fixture/v1` files.
6. Run `scripts/verify_qiskit.py --smoke`; for local scientific validation also
   use `--run-profile ... --artifact-root ...`. Review provider tool names,
   transpiled QPY, counts, statistical bounds, and artifact manifests.
7. For remote profiles, review backend/configuration/calibration identities and
   access tier without recording the raw instance CRN. Supply
   `QISKIT_IBM_TOKEN` only through the `quantum.ibm-runtime` credential scope.
8. Sync without approval, review catalog/schema/lineage/permission changes, then
   explicitly approve. Run token redaction, backend mismatch, async cancellation,
   record/replay, manifest/schema, and package tests.

Rollback restores the prior support record, exact provider environments,
experiment profile, QPY/evidence files, active catalog lock, and cassettes.
Remote jobs already submitted under the newer record must first reach a terminal
state or be reconciled by their recorded provider handle; rollback must not hide
or abandon them. IBM service terms, account entitlements, and backend access are
external to the Apache-2.0 software licenses and remain operator responsibilities.
