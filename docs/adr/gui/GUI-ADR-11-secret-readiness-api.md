---
sources:
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/catalogs.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx
    role: implementation
  - path: ari-core/tests/test_gui_secret_readiness.py
    role: test
  - path: ari-core/tests/test_gui_v1_secret_put_and_catalogs.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/devModeAndDangerousOps.test.tsx
    role: test
last_verified: 2026-08-16
---

# GUI-ADR-11: secret readiness replaces plaintext env-key reads

Context: the security review of the GUI surface recorded that
`GET /api/env-keys` returned, in plaintext, the value of every environment
variable whose name contains `API_KEY`, `SECRET`, or `TOKEN`, together with the
source file each came from; the configuration-control-plane review recorded the
matching intent that this endpoint be closed and replaced once a readiness API
existed. The security plan's secret policy required that an API return
`configured`, provider, source class, and last-updated only, that secret key
names be limited to a schema allowlist, and that newline/control characters be
rejected. This was tracked as risk RR-P0-2.

Decision: `GET /api/v1/secrets/status` returns
`{schema_version: 1, secrets: [{name, configured, source_class, last_updated}]}`;
the value is structurally absent — `ari.viz.v1.dto.SecretV1` has no value field.
Rows are the fixed-order allowlist `ari.viz.v1.secrets.SECRET_NAMES`
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`,
`SEMANTIC_SCHOLAR_API_KEY`, `LETTA_API_KEY`, `ZENODO_TOKEN`,
`ARI_REGISTRY_TOKEN`), each enumerated from existing code rather than invented.
The row carries no provider field, although the policy above allowed one: the
provider-to-env-name mapping is served instead by the model catalog
(`ari.viz.v1.catalogs.PROVIDER_ENV_KEYS`), whose values are pinned against
`SECRET_NAMES` by `ari-core/tests/test_gui_v1_secret_put_and_catalogs.py`.
`source_class` is `project_env` / `repo_env` / `user_env` / `process_env` /
`null`, resolved by `ari.viz.api_settings._env_chain()` — shared with the legacy
harvest, first-occurrence-wins, so the two endpoints cannot disagree about which
file won. `last_updated` is the winning `.env` file's mtime in UTC; `null` for
`process_env` and for unset names. The plaintext read is closed immediately with
no deprecation period; the legacy endpoint survives as a shape-compatible
adapter: non-empty values become `ENV_KEY_REDACTED` (`***configured***`), empty
values stay `""`, the `source` map is unchanged, and a top-level
`redacted: true` marker lets clients detect the new contract. Removal of the
unversioned endpoint itself follows the legacy-facade policy (ADR-02), not this
record. `POST /api/env-keys` keeps its write semantics but rejects, with 400 and
no file write, any name that does not fullmatch `^[A-Z][A-Z0-9_]{0,63}$` or that
carries newline/control characters.

The source record enumerated no rejected alternatives; it stated the decision,
its consequences and its supersedes line only. Nothing is reconstructed here,
because what the deciders weighed and set aside is not recoverable from the
decision or from the code.

Consequences: reading a secret value back into the GUI is no longer possible, so
the developer-mode "Auto-read" prefill in
`ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` became a
readiness display, and the guidance became "✓ `<NAME>` configured
(`<source_class>`) — leave blank to use it" when the key is set and
"`<NAME>` not configured — enter manually" when it is not. Adding a secret name is an
additive allowlist change; adding any field that carries a value requires
superseding this record. The behaviour change is announced as migration note
MN-2.

Supersedes / superseded-by: first decision on this subject; not superseded. The
write side was later extended rather than reversed by the canonical
`PUT /api/v1/secrets/{secret_id}` (ADR-05, `ari.viz.v1.secrets.put_secret`),
whose acknowledgment is readiness-shaped (`SecretUpdatedV1`), so the
no-value-in-any-response rule still holds.

Divergence from the code: this record left the remainder of RR-P0-4 —
atomicity, file permission, oversized value — to a later gate and called the
POST write path unchanged. Atomicity and permission subsequently landed in
`_upsert_env_key` (same-directory temp file, `fsync`, `os.replace`, owner-only
`0o600`), so the on-disk write is no longer literally unchanged, and RR-P0-4 was
closed rather than deferred. No value-length limit exists on either write path;
the oversized-value clause of the secret policy remains unimplemented.

Permanent references: `docs/guides/migration.md`, section "Secrets are never
returned; readiness replaces auto-fill (MN-2)"; `docs/reference/rest_api.md`,
sections "Secrets" and "Behaviour changes on the legacy surface (MN notes)".

Owning tests: `ari-core/tests/test_gui_secret_readiness.py` —
`TestSecretsStatusReadiness` (including `test_no_value_ever_in_serialized_payload`
and `test_readiness_get_is_read_only`), `TestEnvKeysRedaction`,
`TestSaveEnvKeyNameAllowlist`, `TestUpsertEnvKeyHardening`; frontend
`ari-core/ari/viz/frontend/src/__tests__/devModeAndDangerousOps.test.tsx`.
