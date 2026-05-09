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

Examples currently in flight (see `DEPRECATION_REMOVAL.md`):

| Item | Announced | Warned since | Removal target |
|---|---|---|---|
| `$HOME/.ari/registries.yaml` fallback | v0.5.0 | v0.5.0 | v1.0 |
| `$HOME/.ari/registry-data` fallback | v0.5.0 | v0.5.0 | v1.0 |
| Legacy v0.5 JSONL memory store | v0.5.0 | v0.5.0 | v1.0 |
| `ari/migrations/v05_to_v07/` shims | v0.7.0 | v0.7.0 | v1.0 |

## Release checklist

When cutting a release:

1. Update `CHANGELOG.md` with the new section.  Group entries under
   **Added** / **Changed** / **Fixed** / **Deprecated** /
   **Removed** / **Security**.
2. Bump the version in `ari-core/pyproject.toml` and each
   `ari-skill-*/pyproject.toml`.
3. Run the full test suite + the refactor-guards CI workflow.
4. Run the docs gate:
   - `grep -rn '~/\.ari/' docs/` excluding `DOCUMENTATION_PLAN.md`
     and `refactor_audit.md` returns zero.
   - Every documented env var maps to a real source reference.
   - Every documented MCP tool exists in the skill's `mcp.json`.
5. Tag: `git tag v0.X.Y && git push origin v0.X.Y`.
6. Open a release on GitHub with the changelog excerpt.
7. Publish bundles: `ari ear publish` for any artefacts that need to
   ship alongside.

## Compatibility windows

- A **MINOR** release is forward-compatible: a checkpoint produced
  on the previous minor must keep working on the new minor.
- A **MAJOR** release may require a one-shot migration step.  The
  migration is documented in `docs/howto/migration.md` and run via
  `ari migrate ...`.
- Skills are versioned independently.  A skill at `0.7.x` should
  work with `ari-core` at any `0.7.y` (compatibility within a
  minor).  Across minors, expect a coordinated release.

## See also

- `CHANGELOG.md` — per-release notes.
- `DEPRECATION_REMOVAL.md` — full deprecation programme.
- `docs/howto/migration.md` — per-version migration recipes.
- `docs/reference/public_api.md` — the surface this policy
  protects.
