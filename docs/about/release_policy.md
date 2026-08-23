---
sources:
  - path: CHANGELOG.md
    role: doc
  - path: CONTRIBUTING.md
    role: doc
  - path: DEPRECATION_REMOVAL.md
    role: doc
  - path: ari-core/pyproject.toml
    role: config
  - path: .github/workflows/refactor-guards.yml
    role: config
  - path: .github/workflows/docs-sync.yml
    role: config
  - path: scripts/docs
    role: implementation
last_verified: 2026-08-17
---

# Release & Versioning Policy

## SemVer interpretation

ARI follows [Semantic Versioning 2.0](https://semver.org/spec/v2.0.0.html).

| Bump | What changed | Examples |
|---|---|---|
| **MAJOR** (1.0 → 2.0) | Backwards-incompatible changes to the **public** surface | `ari.public.*` symbol removed, MCP tool semantics change, checkpoint format breaking |
| **MINOR** (0.6 → 0.7) | Backwards-compatible feature additions | new `ari.public.*` symbol, new MCP tool, new `ari` subcommand, new env var with safe default |
| **PATCH** (0.7.0 → 0.7.1) | Bug fixes, doc updates, internal refactors with no API surface change | LLM prompt tweak that does not alter tool I/O, dashboard CSS, dependency bump |

**Public surface** for SemVer purposes:

- The CLI (`ari ...`) — every documented subcommand and flag.
- `ari.public.*` Python imports.
- Each skill's `mcp.json` tool list, names, and request/response
  shape.
- The viz REST API (everything under `/api/`).
- Documented checkpoint files (`tree.json`, `nodes_tree.json`,
  `node_report.json`, `settings.json`, `workflow.yaml`,
  `experiment.md`, `manifest.lock`, `publish_record.json`,
  `lineage_decisions.jsonl`).
- Documented environment variables (those listed in
  `docs/reference/environment_variables.md`).

**Not** part of the public surface:

- Modules outside `ari.public.*`.
- Internal-only helpers (`_`-prefixed names).
- Test fixtures and `vendor/` snapshots (PaperBench, VirSci, ...).
- Prompt strings under `ari/prompts/` (governed by Phase PC, but not
  SemVer-protected — they may change in any minor release as long as
  the tool I/O contract holds).

## Support policy

| Branch | Status | What gets backported |
|---|---|---|
| `main` (latest minor) | Active | Features + bug fixes |
| Previous minor | Maintenance for **6 months** after the next minor's release | Security + critical bug fixes only |
| Older minors | Out of support | None |

The current state lives in `CHANGELOG.md` and on the
[GitHub releases](https://github.com/) page.

## Deprecation & removal

A *deprecation* is a notice that a public symbol or behaviour will
be removed.  We follow this lifecycle:

1. **Announce** — release notes + `CHANGELOG.md` flag the change.
2. **Warn** — runtime emits a `DeprecationWarning` for at least one
   minor release.
3. **Remove** — the next MAJOR drops the warning and removes the
   code.

The authoritative ledger is the root `DEPRECATION_REMOVAL.md` (tiers,
phases DR1–DR5, and each of the **five** sanctioned Tier-B `~/.ari/`
fallback sites — the two below plus `~/.ari/publish.yaml`,
`~/.ari/letta-venv/`, and the second `registries.yaml` reader);
`CONTRIBUTING.md::Deprecation process` is the short how-to for authors.
Examples currently in flight:

| Item | Announced | Warned since | Removal target |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` fallback | v0.5.0 | v0.7.1 | v1.0 |
| `$HOME/.ari/registry-data` fallback | v0.5.0 | v0.7.1 | v1.0 |
| Legacy v0.5 JSONL memory store | v0.5.0 | v0.5.0 | v1.0 |
| `~/.ari/memory.json` default arg | v0.7.0 | v0.7.1 (removed) | v1.0 |
| `ari/migrations/v05_to_v07/` shims | v0.7.0 | v0.7.0 | v1.0 |

All five Tier-B fallbacks, the `ari.migrations.v05_to_v07` package, and
the `legacy_reconstruct` shim are dropped together at DR5 / v1.0, at
which point `ARI_LETTA_VENV` becomes mandatory.

## Release checklist

When cutting a release:

1. Update `CHANGELOG.md` with the new section.  Group entries under
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security**.
2. Bump the version in `ari-core/pyproject.toml`.  That is the **package
   version**, and everything derived from it follows automatically
   (`_read_ari_core_version()` in `scripts/snapshot_contracts.py` stamps it
   into the four contract goldens' `_meta.ari_core_version`).

   **Do not bump the `ari-skill-*` packages in lockstep.**  They are versioned
   independently and today range from `0.1.0` to `2.0.0` — see
   [Compatibility → Skills vs core](compatibility.md#skills-vs-core).  A skill's
   version is not decoration: `LockedSkillV1` records it in the per-run skills
   lock alongside the manifest and provider digests, and
   `write_or_verify_skills_lock` requires exact equality once that lock exists.
   Moving a skill's number therefore *asserts that skill changed*, and setting
   all seventeen to one number would replace seventeen meaningful values with
   seventeen copies of the same one — a replay could no longer tell from the
   lock which skill actually moved.  `scripts/check_skill_manifests.py` would
   propagate the claim into `skill.yaml` too, since it fails on any
   manifest↔pyproject `version-drift`.

   Bump a skill when *its own* surface changes, and raise its `ari-core>=` floor
   only when it genuinely needs the newer core.  Those floors already carry the
   coupling and are deliberately uneven (`>=0.8.0` for `harness` and
   `knowledge`, `>=0.9.1` for seven others, absent for the rest); a lockstep
   bump would force a skill that really does work against `0.8.0` to claim
   otherwise.  What pairs a set of versions is the **coordinated release** — the
   git tag — not matching numbers.

   Then decide, explicitly, whether the release also moves the
   **published version pin** — the number the project advertises to
   readers.  It is a *second* register, with its own single source
   (`docs/version.json`, which `docs/i18n/version.js` fetches at page
   load) restated in six other files that must move in the same commit:

   - `README.md`, `README.ja.md`, `README.zh.md` — the shields.io
     `version-vX.Y.Z` badge.
   - `report/en/main.tex`, `report/ja/main.tex`, `report/zh/main.tex` —
     the `\date{vX.Y.Z, ...}` line.

   Moving the pin also means rebuilding the three
   `report/<lang>/main.pdf` and re-running
   `scripts/docs/sync_report_pdf.sh` (it writes into **both**
   `docs/assets/report/` and `docs/public/report/`).  The PDFs are
   generated: editing `\date` without a LaTeX rebuild leaves every
   published copy showing the old number.

   Moving the pin also means giving the three READMEs a release-notes
   section for the new number (`## What's new in vX.Y.Z`, localised in
   `README.ja.md` / `README.zh.md`) — that is how v0.8.1 and v0.9.0
   shipped.  `check_readme_parity.py` forces the section into all three
   at once (it compares heading shape), but **nothing** checks that it
   exists at all, so this checklist is the only place the requirement
   lives.  A badge advertising a version the README does not document is
   its own defect.

   A **package-only bump is permitted** and leaves the pin untouched: a
   contract-preserving release with nothing user-visible has nothing to
   advertise.  v0.9.1 (2026-07-05) was exactly that — see its
   `CHANGELOG.md` entry — which is why the pin reads `v0.9.0` while
   `ari-core` is at `0.9.1`.  The pin may therefore **lag** the package
   version; it must never **lead** it, because that would advertise a
   version that was never packaged.
   `python scripts/docs/check_site_i18n.py` enforces both halves: the
   seven files above agree with each other, and the pin does not lead
   `ari-core/pyproject.toml`.
3. Run the full test suite + the `refactor-guards`, `docs-sync`, and
   `docs-change-coupling` CI workflows.
4. Run the docs gate. What CI (`docs-sync.yml`, `refactor-guards.yml`)
   actually blocks on:
   - `refactor-guards.yml` fails on a **newly added** `~/.ari/` line in
     `ari-core/ari/**.py` outside its allow-list (the deprecation helper,
     `migrations/`, and the shim sites that warn before falling through),
     and on any `$HOME/.ari/` directory created by a pytest run. There is
     no repo-wide `grep` over `docs/`: many `~/.ari/` mentions there are
     legitimate (the vendored PaperBench `agent.env` lookup, `start.sh`
     PID files, the Tier-B fallbacks themselves).
   - Every documented env var maps to a real source reference.
   - Every documented MCP tool exists in the skill's `mcp.json`.
   - `python scripts/docs/check_doc_sources.py` exits 0 (every declared
     `sources:` path exists). The stricter `--require-all` — which also
     demands that *every* live doc declare `sources:` — is a staged
     rollout and does **not** pass today: the per-directory `README.md`
     files carry no front matter.
   - `python scripts/docs/check_doc_links.py --html-only` exits 0. The
     full Markdown link pass (`check_doc_links.py` with no flag) runs
     advisory-only in CI.
   - `python scripts/docs/check_i18n_js.py` exits 0 (the landing surface's
     `docs/i18n/landing.{en,ja,zh}.js` declare one identical key set; the
     legacy `docs.{en,ja,zh}.js` viewer dictionaries were removed when the
     docs moved to VitePress).
   - `python scripts/docs/check_readme_parity.py` exits 0 (the root
     `README.{md,ja,zh}` share one Markdown heading shape).
   - `python scripts/docs/check_site_i18n.py` and the report tri-language
     parity / report-PDF-sync steps exit 0.
   - Advisory: `python scripts/docs/check_translation_freshness.py`
     (no `ja`/`zh` translation has a `last_verified` older than its
     English source — see [Source traceability](../README.md#source-traceability)).
     `--strict` turns it blocking; expect it to fail immediately after an
     English-only doc pass.
5. Tag: `git tag v0.X.Y && git push origin v0.X.Y`.
6. Open a release on GitHub with the changelog excerpt.
7. Publish bundles: `ari ear publish` for any artefacts that need to
   ship alongside.

## Compatibility windows

- A **MINOR** release is forward-compatible: a checkpoint produced
  on the previous minor must keep working on the new minor.
- A **MAJOR** release may require a one-shot migration step.  The
  migration is documented in `docs/guides/migration.md` and run via
  `ari migrate ...`.
- Skills are versioned independently, and their numbers do **not**
  track `ari-core`'s: against `ari-core` 0.9.1 the shipped skills range
  from `0.1.0` (`ari-skill-harness`, `ari-skill-knowledge`) to `2.0.0`
  (`ari-skill-orchestrator`).  Nothing in the code enforces a
  skill↔core version pair, so a skill's version is a statement about
  that skill's own API, not about which core it needs.  Pair them by
  the coordinated release, not by matching numbers.

## See also

- `CHANGELOG.md` — per-release notes.
- `CONTRIBUTING.md::Deprecation process` — full deprecation programme.
- `docs/guides/migration.md` — per-version migration recipes.
- `docs/reference/public_api.md` — the surface this policy
  protects.
