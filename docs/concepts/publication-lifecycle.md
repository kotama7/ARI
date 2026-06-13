---
sources:
  - path: ari-core/ari/pipeline
    role: implementation
  - path: ari-skill-paper
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-06-12
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
        │   (in parallel, the default-on Story2Proposal claim-evidence loop runs
        │    on the paper text once write_paper emits full_paper.tex:)
        │
        │   write_paper ──▶ full_paper.tex
        │        │
        │        ▼ link_paper_claims (draft)        ──▶ paper_claim_links.json
        │        ▼ claim_evidence_hard_gate (draft, non-blocking)
        │        │                                   ──▶ evaluation/claim_evidence_hard_gate_draft.json
        │        ▼ review_paper / evidence_grounded_semantic_review (non-blocking)
        │        ▼ merge_reviews
        │        ▼ paper_refine (anchor-preserving — keeps % CLAIM anchors)
        │        ▼ render_paper (recompile refined .tex ──▶ full_paper.pdf)
        │        ▼ link_paper_claims (final)          ──▶ paper_claim_links_final.json
        │        ▼ claim_evidence_hard_gate (FINAL)   ──▶ evaluation/claim_evidence_hard_gate_final.json
        │        │   (blocks finalize in strict mode)
        ▼        ▼
        └────────┴──▶ finalize_paper (paper-skill: inject_code_availability)
                       DEPENDS ON ear_publish AND the FINAL hard gate
        ▼
full_paper.tex with \codeavailability{} \codedigest{} \coderef{}
        │
        ▼ ari clone <ref> --expect-sha256 <baked digest>
        ▼
reader's machine: bundle bytes verified, no code execution
```

### Claim-evidence gate (Story2Proposal loop)

Every paper build now runs a deterministic claim-evidence **hard gate**,
a non-blocking **evidence-grounded semantic review**, and an
**anchor-preserving refine/render loop** on top of the existing paper
stages. The loop links the paper's `% CLAIM` anchors to recorded
results (`link_paper_claims`), checks them against the experiment data
(`claim_evidence_hard_gate`, run once on the draft and again on the
refined paper), threads both the hard gate and the semantic review into
the merged review, applies suggested revisions while preserving the
claim anchors (`paper_refine`), and recompiles the refined `.tex`
(`render_paper`). It is governed by the `claim_gate_policy` block in
`ari-core/config/workflow.yaml` and is **default-on in `warn`
(report-only) mode** — the gate records findings but never blocks the
build. Setting `claim_gate_policy.mode: strict` (or
`ARI_CLAIM_GATE_MODE=strict`) makes the **FINAL** gate block
`finalize_paper` on blocking errors (numeric mismatch, unresolved
operands, missing evidence).

Four robustness behaviours keep the loop honest end-to-end:

- **Blocking is reserved for objective falsehoods.** The gate's
  always-block tier contains only findings that are deterministically
  checkable (a number the run's own data contradicts, an invariant
  violation, a declared claim with no evidence anywhere in the run).
  Subjective findings — the LLM semantic review's overclaim and
  interpretation warnings — stay advisory by design: an LLM verdict is
  not reproducible across runs, so it must never be able to veto a
  paper. The remedy for subjective findings is the review→refine loop
  above, measured (not enforced) via the post-refine review's raw
  resolved-count delta.

- **Review feedback actually lands.** `merge_reviews` forwards every
  semantic-review warning to `paper_refine` as an advisory revision
  entry (a warning without a parallel suggested revision would never
  reach the refiner, so the warning count could never decrease). The
  reported `resolved_overclaim_count` is the raw previous−current
  delta — a negative value means the count *grew* after refine and is
  surfaced as a regression instead of being clamped to zero.
- **Numeric verification understands scientific notation.** The
  numeric-mention scanner (mirrored in
  `ari-skill-paper/src/claim_links.py` and ari-core's
  `claim_gate/latex.py`) parses mantissa × 10^exp forms
  (`4.44 \times 10^{-16}`, with `x`/`\times`/`\cdot`) and attached
  e-notation (including sentence-final), keeps digit-bearing tokens,
  and treats `\( \)` as math delimiters when locating a value's unit
  — eliminating false `numeric_mismatch` findings on such values.
  Huge exponents are skipped, never crash the gate.
- **Writer declarations are normalized at parse time.** Instructions
  alone proved unreliable, so the parser absorbs the common quirks:
  formula synonyms (`value`, `raw`, `abs`, …) normalize to the
  registry name; a stray `operands=` label prefix before bare `k=v`
  tokens is stripped; and when every anchor shares one id (e.g. each
  line stamped `% CLAIM:Cw:NCw`) the anchors are disambiguated per
  line so each declaration is verified independently.
- **The metric contract is minted once.** The first `make_metric_spec`
  call that produces a claims-bearing contract persists it as
  `{checkpoint}/metric_contract.json`; every later call returns that
  file verbatim (the response carries `contract_frozen: true`). LLM
  naming is not referentially stable — regenerating the contract
  mid-run changes the evidence vocabulary and hides sibling evidence
  emitted under earlier names from the exact-match gate (observed on
  a real run). Per-node spec fields (scoring guide etc.) are still
  computed per call; scaffold-only contracts (no claims) never
  freeze.

Artifacts: `paper_claim_links.json` (draft) /
`paper_claim_links_final.json`, and
`evaluation/claim_evidence_hard_gate_{draft,final}.json`.

Trust model: the **paper itself is the trust anchor**, not the
registry. `ari clone` hard-fails on any bundle whose recomputed
digest does not match `--expect-sha256` (or the `manifest.lock`
declaration). If a registry vanishes, the same bundle pinned anywhere
else (S3, Zenodo, gh release, local mirror) still verifies. This is
**bundle integrity** (digest match); the FINAL hard gate adds **claim
integrity** — it re-derives the numbers reported in the paper from the
recorded results and flags any that fall outside tolerance.

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
  the compute partition, hostname X, CPU model …" instead of guessing.
- **Git shim** (`ari/agent/shims/git.sh`) — wired into the
  reproducibility sandbox via `PATH=<sandbox>/.shims:<orig_path>`.
  Intercepts only `git clone` URLs that match the paper's
  `code_availability_ref`; everything else passes through. Logs every
  clone attempt to `<sandbox>/repro_clone_log.jsonl`. Configurable via
  `ARI_REPRO_CLONE_POLICY=passthrough|deny|warn`.

---

## See also

[Architecture](architecture.md) · [Registry](../reference/registry.md) · [Rubric schema](../reference/rubric_schema.md) · [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)
