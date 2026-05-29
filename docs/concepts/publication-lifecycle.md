---
sources:
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-skill-paper
    role: implementation
last_verified: 2026-05-26
---

# Publication Lifecycle (v0.7.0)

ARI v0.7.0 turns the EAR from "drop the whole checkpoint into ear/"
into a curated, digest-anchored publication chain. The author writes a
small `ear/publish.yaml` allowlist; ari-core enforces a built-in deny
list and computes a deterministic bundle digest. The digest is baked
into the paper (`\codedigest{...}`), so any reader can verify the
bundle at any future time, even if the registry hosting it disappears.

```
generate_ear ──▶ {checkpoint}/ear/                 (full author-curated repo)
                  + ear/publish.yaml               (small allowlist + license/visibility)
        │
        ▼ ear_curate (transform-skill)
        ▼
{checkpoint}/ear_published/  +  manifest.lock      (sha256 of canonical {path,sha256,size} JSON)
        │
        ▼ ear_publish (transform-skill, optional)
        ▼
backend.publish ──▶ ari-registry / gh / zenodo / local-tarball
        │
        ▼ writes publish_record.json
        │
        ▼ finalize_paper (paper-skill: inject_code_availability)
        ▼
full_paper.tex with \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
reader's machine: bundle bytes verified, no code execution
```

Trust model: the **paper itself is the trust anchor**, not the
registry. `ari clone` hard-fails on any bundle whose recomputed
digest does not match `--expect-sha256` (or the `manifest.lock`
declaration). If a registry vanishes, the same bundle pinned anywhere
else (S3, Zenodo, gh release, local mirror) still verifies.

### `ari clone` resolvers

| Scheme | Resolver | Notes |
|--------|----------|-------|
| `file://<path>` | local file or directory | offline / mirror |
| `https://<url>` / `http://<url>` | tarball download | any HTTPS host |
| `ari://<id>` | ari-registry client | reads `registries.yaml` for endpoint/token. Resolution: `$ARI_REGISTRIES_FILE` → `{checkpoint}/.ari/registries.yaml` → `./.ari/registries.yaml`. The legacy `$HOME/.ari/` location was removed in v0.5.0 and emits a `DeprecationWarning` (fallback dropped in v1.0). |
| `gh:<user>/<repo>` | GitHub repo or release | API + tarball |
| `doi:<doi>` | Zenodo deposition | DOI → file list → bundle |

### `ari registry` (optional self-hosted)

Minimal FastAPI server in `ari/registry/`. Sqlite-backed token store,
content-addressed artefact storage at
`${ARI_REGISTRY_DATA}/artifacts/<id>/{bundle.tar.gz, manifest.lock,
meta.json}`. Visibility is monotone: `staged` → `unlisted` / `public`
(demotion rejected). Deploy via uvicorn (laptop), docker-compose
(production), or Apptainer (HPC). See [docs/reference/registry.md](../reference/registry.md).

### Reproducibility sandbox extras

- **`_run_env.json`** — `ari/agent/run_env.py` writes per-`work_dir`
  hardware metadata (hostname, SLURM job/partition/nodelist, CPU
  model/threads/MHz/arch, mem_total, compiler versions) from inside
  the executing process so SLURM jobs (which run on a different node
  than the agent) report accurate facts. The `node_report` builder
  enriches reports with this data; downstream stages recover "ran on
  sx40 partition, hostname X, Intel Xeon …" instead of guessing.
- **Git shim** (`ari/agent/shims/git.sh`) — wired into the
  reproducibility sandbox via `PATH=<sandbox>/.shims:<orig_path>`.
  Intercepts only `git clone` URLs that match the paper's
  `code_availability_ref`; everything else passes through. Logs every
  clone attempt to `<sandbox>/repro_clone_log.jsonl`. Configurable via
  `ARI_REPRO_CLONE_POLICY=passthrough|deny|warn`.

---

## See also

[Architecture](architecture.md) · [Registry](../reference/registry.md) · [Rubric schema](../reference/rubric_schema.md) · [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)
