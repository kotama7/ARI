# provider-artifacts

Materialized Capability Provider runtimes and the environment-specific catalogs
built from them. Nothing here is portable: every path is absolute and every
environment belongs to this machine.

The reviewed evidence for these Providers is **not** here — it stays tracked
under `ari-skill-tool-registry/providers/<name>/<version>/`. This directory
holds only what that evidence points at, mirroring `containers/`: the README is
tracked, the payload is ignored.

The one exception is the retained ORFS SIF, which the OpenROAD wrapper execs
from `${runtime_dir}` and so must live at the bundle's
`providers/openroad/0.6.1+orfs-26q3-gcd-nangate45/runtime/openroad-orfs-26q3.sif`
path instead.

## Contents

- `README.md` — this file.

## Selecting a catalog at runtime

The checked-in `ari-skill-tool-registry/CATALOG.lock` is empty by design: it is
the portable default, and a populated catalog is machine-specific evidence.
Point the broker at one of these instead. `catalogs/all/` carries every source
and is the one to use unless you deliberately want a narrower surface.

```sh
export ARI_TOOL_REGISTRY_LOCK=$PWD/provider-artifacts/catalogs/all/CATALOG.lock
export ARI_TOOL_REGISTRY_INDEX=$PWD/provider-artifacts/catalogs/all/catalog.index.json
```

Enabling the Skill does not enable any leaf. Only sources present in the
selected lock can execute, so the Skill flag and the catalog remain two
independent gates.

## Re-promoting the OpenROAD SLURM profile

Four things move together. Changing any one of them invalidates the rest, so do
them in this order or the promotion fails closed partway through.

1. **Pick a node that is idle now.** The profile pins `--nodelist`, so a busy
   node is waited on, not routed around, and the job is cancelled when
   `command_timeout_seconds` (900) expires with `Elapsed 00:00:00`. It must be
   `x86_64` (the retained SIF is) and report `Gres=(null)` (the profile grants
   no GPU capability); both are checked as invariants regardless of what the
   snapshot declares.

   ```sh
   sinfo -h -N -o "%N|%P|%t|%G" | awk -F'|' '$3=="idle" && $4=="(null)"'
   ```

2. **Rewrite `site-config.json`** with that cluster/partition/node and a fresh
   256-bit nonce. It is ignored by Git; `git config --local
   ari.sitePrivacy.config` points the pre-commit hook at it.

3. **Regenerate `scheduler-snapshot-v1.json`** in the bundle. It declares this
   site's Slurm version, GRES types, partition limits and node shape, and binds
   `site_identity_digest = sha256_digest(site-config)`. A new nonce alone
   changes that digest, so a stale snapshot fails with `scheduler site identity
   digest differs`.

4. **Clear the idempotency ledger** at `slurm-work/.ari-openroad/` before
   re-running. The request digest is deterministic, so a completed record from
   an earlier promotion is replayed against a workspace that has since been
   cleaned up, surfacing as `FileNotFoundError` on `result-v1.json`.

`slurm-work/` is the promoted `work_root` and is recorded in the profile as an
absolute path. It must keep existing: catalog sync rejects the source with
`work_root must be an existing non-symlink directory` if it does not.

## Rebuilding

Deleting this directory loses no reviewed evidence, only the ability to run.
Rebuild the environments from the pinned locks, then re-run
`ari-skill-tool-registry/src/sync_catalog.py --approve` with the new absolute
paths in `sources.yaml`. For every provider except the OpenROAD SLURM profile
no re-promotion is required, because leaf identity no longer depends on install
location; that one needs the four steps above because its `work_root` and site
identity are part of the promoted profile.
