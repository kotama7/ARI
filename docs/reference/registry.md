---
sources:
  - path: ari-core/ari/registry
    role: implementation
  - path: ari-core/ari/clone/resolvers/ari.py
    role: implementation
  - path: ari-core/ari/publish/backends/ari_registry.py
    role: implementation
  - path: scripts/registry
    role: doc
  - path: scripts/setup/install_deps.sh
    role: implementation
last_verified: 2026-08-16
---

# ari-registry — v0.7.0+

A minimal HTTP registry for curated EAR bundles. Acts as the default
backend for `ari ear publish` and the `ari://` resolver in `ari clone`.

## When to run it

You run `ari registry` only if you want to host bundles for others to
fetch. The default `local-tarball` backend (no server) works fine for
self-archiving. Zenodo is the recommended path for academic
permanence.

## Quick start

> **Note:** v0.5.0 demoted the global `$HOME/.ari/` directory — every registry
> path should now come from an explicit env var (`ARI_REGISTRY_DATA`,
> `ARI_REGISTRIES_FILE`).  See [migration](../guides/migration.md) for the
> recipe; the legacy fallback emits a `DeprecationWarning` and is removed in
> v1.0.  Setting `ARI_REGISTRY_DATA` in step 2 is not optional hygiene:
> `start_local.sh` and `start_singularity.sh` both still default it to
> `$HOME/.ari/registry-data`.

```bash
# 1. server deps ship in requirements.txt / the lockfile, so a plain
#    ./setup.sh already installs fastapi + uvicorn + python-multipart.
#    --with-registry is accepted but informational only.
./setup.sh --with-registry        # or: pip install fastapi uvicorn[standard] python-multipart

# 2. point the server at a data directory
export ARI_REGISTRY_DATA="$PWD/.ari_registry"

# 3. start it (uvicorn on 127.0.0.1:8290 — `ari registry serve` on its own
#    defaults to --host 0.0.0.0; the script overrides it)
./scripts/registry/start_local.sh

# 4. mint a token (plaintext is shown ONCE)
ari registry token issue alice

# 5. configure the client
export ARI_REGISTRIES_FILE="$ARI_CHECKPOINT_DIR/.ari/registries.yaml"
mkdir -p "$(dirname "$ARI_REGISTRIES_FILE")"
cat > "$ARI_REGISTRIES_FILE" <<EOF
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: \$ARI_REGISTRY_TOKEN
EOF
export ARI_REGISTRY_TOKEN=ari_<paste-from-step-4>
```

## Settings file resolution (v0.7+)

Both `ari ear publish --backend ari-registry` and `ari clone ari://` look up
`registries.yaml` through the same four-step chain:

1. `$ARI_REGISTRIES_FILE` — explicit env override.
2. `{checkpoint_dir}/.ari/registries.yaml` — intended to let a run pin its
   registry config to its checkpoint.
3. `$(pwd)/.ari/registries.yaml` — convenient when running from inside
   a project directory.
4. `$HOME/.ari/registries.yaml` — **deprecated**; honoured only if the file
   exists, and then only after emitting a `DeprecationWarning`. Removed in v1.0.

> **Step 2 never fires today.** Both lookups take `checkpoint_dir` as an
> optional argument, and neither call site passes one — `_select_registry()` in
> the publish backend and `resolve()` in the `ari://` resolver both call it
> bare. A `.ari/registries.yaml` sitting inside a checkpoint is therefore
> invisible unless you point `$ARI_REGISTRIES_FILE` at it or run from that
> directory.

If no file yields any registries, both paths fall back to a single synthetic
registry built from `$ARI_REGISTRY_URL` (plus `$ARI_REGISTRY_TOKEN`); with
neither, the command fails with `no ari-registry configured`. The publish
backend additionally accepts `$ARI_REGISTRY_NAME` to pick an entry by name.

Write tokens in the file as a literal or as `$VAR`. The `${VAR}` form shown in
the resolver docstring does **not** work: the `$`-prefix branch is tested first
in both `_expand_token` implementations, so `${ARI_REGISTRY_TOKEN}` is looked up
as an environment variable literally named `{ARI_REGISTRY_TOKEN}` and silently
expands to the empty string.

Server-side state (`ari registry serve`) lives at
`$ARI_REGISTRY_DATA/`. The legacy `$HOME/.ari/registry-data` fallback is
under the same v1.0 deprecation policy — set the env var explicitly to
avoid the warning.

## Endpoints

| Method | Path                                    | Auth   | Notes |
|--------|-----------------------------------------|--------|-------|
| GET    | `/healthz`                              | -      | Liveness probe; returns `{"ok": true}` |
| GET    | `/version`                              | -      | `{"version": "0.7.0", "service": "ari-registry"}` |
| POST   | `/artifact`                             | bearer | Multipart upload: `bundle` file + `manifest` / `metadata` / `visibility` form fields. Re-uploading identical bytes is idempotent and answers `duplicate: true`; a different owner is refused |
| GET    | `/artifact/<id>`                        | maybe  | Public/unlisted: anon; staged: owner's bearer token; private-token: any valid bearer token |
| HEAD   | `/artifact/<id>`                        | -      | Sha256 + visibility + length headers, no body — **no auth check, at any visibility** |
| GET    | `/artifact/<id>/manifest.lock`          | -      | Manifest single-file fetch — **no auth check either**, so a staged bundle's full file list and per-file digests are public to anyone holding the id |
| POST   | `/artifact/<id>/promote?target=...`     | bearer | `target` is a query parameter (default `public`); owner only |
| DELETE | `/artifact/<id>`                        | bearer | Owner only |

Unknown ids answer 404; a missing/garbage bearer token is 401; a valid token
that is not the owner is 403; an invalid visibility target is 400.

## Visibility model (FR-RG6)

- `staged`: only the owner's token can read. **`ari ear publish` always uploads
  as staged**, though the HTTP endpoint itself accepts any of the four values.
- `unlisted`: anyone who knows the id can read; not enumerated. (Nothing is
  enumerated — the server exposes no listing endpoint at all.)
- `public`: open read.
- `private-token`: requires a bearer token at fetch time — any valid token, not
  specifically the owner's.

Visibility can only move *up* the chain. The rank order is
`staged(0) < unlisted(1) = private-token(1) < public(2)`, so `unlisted` and
`private-token` are interchangeable in both directions, and only a strictly
lower target (e.g. `public → unlisted`, anything `→ staged`) is rejected.

## Storage

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite, hashed bearer tokens
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"id":..., "visibility":..., "owner":...,
                                  #  "created_at":..., "sha256":..., "length":...}
```

Artifact id is content-addressed: `sha256(bundle.tar.gz)[:16]` (16 hex
chars / 64 bits). This page used to put the ~1% birthday-collision point at
5e9 artifacts; that is the **50%** point. On a 64-bit space,
`p ≈ 1 − exp(−n²/2N)` gives ~1% at about **6e8** artifacts and 49% at 5e9.
The id length is configurable in a future release if you need larger fanout —
today the `[:16]` truncation is hard-coded in `FilesystemStorage.derive_id`.

## Token lifecycle

```bash
ari registry token issue <user>     # plaintext shown once; store securely
ari registry token revoke <id>      # immediate
ari registry token list             # who has access
```

## Deploy modes

- `scripts/registry/start_local.sh` — uvicorn + sqlite, single-process. Laptop / dev.
  Honours `ARI_REGISTRY_HOST` (default `127.0.0.1`), `ARI_REGISTRY_PORT`
  (`8290`) and `ARI_REGISTRY_DATA` (default `$HOME/.ari/registry-data`, the
  deprecated location); writes a pidfile and log beside the data dir and is a
  no-op if the recorded pid is still alive.
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume. Production.
  Note that the `proxy` service bind-mounts `./nginx.conf`, and that file is
  **not** in the repository — supply your own before `docker compose up`.
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF. HPC.
  Builds `$ARI_REGISTRY_SIF` (default `$HOME/.ari/ari-registry.sif`) on first
  run and serves on `0.0.0.0:$ARI_REGISTRY_PORT` with the data dir bound at
  `/data`.

## Permanence

If the registry stops, **bundles can still be verified** because the
SHA-256 digest is baked into the paper's `\codedigest{...}` macro. Move
the bundle to any other host (S3, Zenodo, gh release) and `ari clone
file://...` against the manifest still validates correctly.

## See also

[Publication lifecycle](../concepts/publication-lifecycle.md) · [Configuration](configuration.md) · [PaperBench API](api_paperbench.md)
