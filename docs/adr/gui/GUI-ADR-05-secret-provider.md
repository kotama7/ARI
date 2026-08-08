---
sources:
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/v1/catalogs.py
    role: implementation
  - path: ari-core/ari/viz/state.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/SecretField.tsx
    role: implementation
  - path: ari-core/tests/test_gui_v1_secret_put_and_catalogs.py
    role: test
  - path: ari-core/tests/test_gui_secret_readiness.py
    role: test
  - path: docs/guides/configuration_studio.md
    role: doc
last_verified: 2026-08-09
---

# GUI-ADR-05: secret provider

Status: accepted for the provider decision. The program charter listed "secret
provider and authentication mode" as a single decision to record, so this record
covers both axes; the authentication half was deliberately left open here and is
decided by GUI-ADR-13.

Decision: the GUI's secret provider is the `.env` chain plus the process
environment — read priority active-checkpoint `.env` > repo `ARI/.env` >
`ari-core/.env` > `~/.env` > `os.environ` (`ari.viz.api_settings._env_chain`).
The only read exposed over HTTP is readiness, `GET /api/v1/secrets/status`
(GUI-ADR-11); the plaintext `GET /api/env-keys` is redacted. Assignment is the
write-only `PUT /api/v1/secrets/{secret_id}` (`ari.viz.v1.secrets.put_secret`),
whose resource space is the `SECRET_NAMES` allowlist — any other id is 404, a
non-string/empty/control-character value is 400, and the response is the
post-write readiness row with no value field. Provider/model suggestions come
from `GET /api/v1/config/catalogs/models`, which re-serves the legacy
`GET /api/models` payload plus each provider's env-key name so the Studio's
`SecretField` targets the right secret without a frontend constant. The legacy
`POST /api/env-keys` stays live in hardened form; both writers delegate to the
single `api_settings._upsert_env_key` (same-directory temp file, `fsync`,
`os.replace`, `0o600`, live `os.environ` export).

Alternatives: an OS keychain or platform secret store, rejected because the GUI
must stay portable to headless remote hosts where no such store exists (no
keyring dependency is present). Leaving `POST /api/env-keys` as the only write
path was rejected because its name rule is `^[A-Z][A-Z0-9_]{0,63}$`, i.e. any
UPPER_SNAKE name, which is not the secret allowlist and so cannot be the
canonical surface. Returning the stored value for confirmation was rejected in
GUI-ADR-11 and is structurally excluded here by the response DTO.

Consequences accepted: readiness reads a chain but the write targets one fixed
file (`ari.viz.state._env_write_path`, the repo-root `.env`), so a
checkpoint-local definition keeps winning the `source_class` badge after a
successful PUT — this asymmetry is documented under "How secrets work" in
`docs/guides/configuration_studio.md`. Two write paths therefore coexist; the
full facade (closing the legacy any-UPPER_SNAKE contract onto the allowlisted
PUT) was deferred to the slice where the Studio replaces legacy Settings, and
has not happened — `#/settings` still mounts. The legacy settings-save path also
keeps its frozen heuristic — `api_settings.py:272` writes the key only when
`_raw_key and "test" not in _raw_key and len(_raw_key) >= 20`, which the canonical PUT does not reproduce. Adding a secret
name is an additive allowlist change; adding any field that carries a value
requires superseding GUI-ADR-11.

Divergences from what was originally specified: a per-secret
`GET /api/v1/secrets/{secret_id}/status` was called for; the implementation is a
single collection endpoint `/api/v1/secrets/status`. A write lock and a
transaction boundary preventing an installation
secret from mutating before a project save fails; the writer provides atomic
replace and owner-only mode but no lock and no cross-resource transaction.

Supersedes: nothing. Discharged by: GUI-ADR-13 for authentication mode —
`ari/viz/auth.py` records the handoff and implements loopback-default local mode
with a bearer-token gate on non-loopback binds. Closes risk-register rows for
the plaintext `GET /api/env-keys` response (every value whose name contained
`API_KEY`/`SECRET`/`TOKEN`, returned with its source path) and for arbitrary
key/value `.env` upsert via `POST /api/env-keys`. Owning tests:
`ari-core/tests/test_gui_v1_secret_put_and_catalogs.py` (route registration,
allowlist 404, body 400s, readiness flip, value never echoed, catalog env keys a
subset of `SECRET_NAMES`) and `ari-core/tests/test_gui_secret_readiness.py`
(including `TestUpsertEnvKeyHardening`).
