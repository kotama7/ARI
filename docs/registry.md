# ari-registry — v0.7.0+

A minimal HTTP registry for curated EAR bundles. Acts as the default
backend for `ari ear publish` and the `ari://` resolver in `ari clone`.

## When to run it

You run `ari registry` only if you want to host bundles for others to
fetch. The default `local-tarball` backend (no server) works fine for
self-archiving. Zenodo is the recommended path for academic
permanence.

## Quick start

> **Note:** v0.5.0 removed the global `$HOME/.ari/` directory — every
> registry path is now scoped to either an explicit env var
> (`ARI_REGISTRY_DATA`, `ARI_REGISTRIES_FILE`) or to the active
> checkpoint (`$ARI_CHECKPOINT_DIR/.ari/registries.yaml`).  See
> `docs/refactor_audit.md` and `docs/howto/migration.md` for the
> migration recipe; the legacy fallback is removed in v1.0.

```bash
# 1. install server deps (skipped by default to keep the install slim)
./setup.sh --with-registry        # or: pip install fastapi uvicorn[standard] python-multipart

# 2. point the server at a data directory
export ARI_REGISTRY_DATA="$PWD/.ari_registry"

# 3. start it (uvicorn on 127.0.0.1:8290)
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

Both `ari publish` (the `ari-registry` backend) and `ari clone ari://`
look up `registries.yaml` in this priority order:

1. `$ARI_REGISTRIES_FILE` — explicit env override.
2. `{checkpoint_dir}/.ari/registries.yaml` — populated by sub-experiment
   launchers; lets a run pin its registry config to its checkpoint.
3. `$(pwd)/.ari/registries.yaml` — convenient when running from inside
   a project directory.

The legacy `$HOME/.ari/registries.yaml` lookup was **removed in v0.5.0**
and emits a `DeprecationWarning` (with a fallback that will disappear in
v1.0); set one of the three locations above explicitly.

Server-side state (`ari registry serve`) lives at
`$ARI_REGISTRY_DATA/`. The legacy `$HOME/.ari/registry-data` fallback is
under the same v1.0 deprecation policy — set the env var explicitly to
avoid the warning.

## Endpoints

| Method | Path                                    | Auth   | Notes |
|--------|-----------------------------------------|--------|-------|
| GET    | `/healthz`                              | -      | Liveness probe |
| GET    | `/version`                              | -      | Server version |
| POST   | `/artifact`                             | bearer | Upload tarball + manifest |
| GET    | `/artifact/<id>`                        | maybe  | Public/unlisted: anon; staged/private-token: bearer |
| HEAD   | `/artifact/<id>`                        | -      | Sha256 + visibility headers, no body |
| GET    | `/artifact/<id>/manifest.lock`          | maybe  | Manifest single-file fetch |
| POST   | `/artifact/<id>/promote`                | bearer | `staged` → `unlisted`/`public` (owner only) |
| DELETE | `/artifact/<id>`                        | bearer | Owner only |

## Visibility model (FR-RG6)

- `staged`: only the owner's token can read. **All uploads start staged**.
- `unlisted`: anyone who knows the id can read; not enumerated.
- `public`: open read.
- `private-token`: requires a separate bearer token at fetch time.

Visibility can only move *up* the chain (staged → unlisted/public). Demotion is rejected.

## Storage

```
${ARI_REGISTRY_DATA}/
├── tokens.db                     # sqlite, hashed bearer tokens
└── artifacts/
    └── <id>/
        ├── bundle.tar.gz
        ├── manifest.lock
        └── meta.json             # {"visibility":..., "owner":..., "sha256":..., "length":...}
```

Artifact id is content-addressed: `sha256(bundle.tar.gz)[:16]` (16 hex
chars / 64 bits). For 5e9 artifacts, birthday-paradox collision risk is
~1%. The id length is configurable in a future release if you need
larger fanout.

## Token lifecycle

```bash
ari registry token issue <user>     # plaintext shown once; store securely
ari registry token revoke <id>      # immediate
ari registry token list             # who has access
```

## Deploy modes

- `scripts/registry/start_local.sh` — uvicorn + sqlite, single-process. Laptop / dev.
- `scripts/registry/docker-compose.yml` — nginx + uvicorn + sqlite-on-volume. Production.
- `scripts/registry/start_singularity.sh` — Apptainer/Singularity SIF. HPC.

## Permanence

If the registry stops, **bundles can still be verified** because the
SHA-256 digest is baked into the paper's `\codedigest{...}` macro. Move
the bundle to any other host (S3, Zenodo, gh release) and `ari clone
file://...` against the manifest still validates correctly.
