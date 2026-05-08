# ari-registry — v0.7.0+

A minimal HTTP registry for curated EAR bundles. Acts as the default
backend for `ari ear publish` and the `ari://` resolver in `ari clone`.

## When to run it

You run `ari registry` only if you want to host bundles for others to
fetch. The default `local-tarball` backend (no server) works fine for
self-archiving. Zenodo is the recommended path for academic
permanence.

## Quick start

> **Note:** `~/.ari/` paths are **DEPRECATED since v0.5.0** and will be
> removed in v1.0.  Set `ARI_REGISTRY_DATA` and `ARI_REGISTRIES_FILE`
> (or place `registries.yaml` under your checkpoint) to opt in to the
> new layout — see `docs/refactor_audit.md` and
> `DEPRECATION_REMOVAL.md`.

```bash
# 1. install server deps (skipped by default to keep the install slim)
./setup.sh --with-registry        # or: pip install fastapi uvicorn[standard] python-multipart

# 2. start it
./scripts/registry/start_local.sh # uvicorn on 127.0.0.1:8290, sqlite under ~/.ari/registry-data
                                  # (DEPRECATED — set $ARI_REGISTRY_DATA)

# 3. mint a token (plaintext is shown ONCE)
ari registry token issue alice

# 4. configure the client
cat > ~/.ari/registries.yaml <<EOF   # DEPRECATED — prefer $ARI_REGISTRIES_FILE
registries:
  - name: default
    url: http://127.0.0.1:8290
    token: \$ARI_REGISTRY_TOKEN
EOF
export ARI_REGISTRY_TOKEN=ari_<paste-from-step-3>
```

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
