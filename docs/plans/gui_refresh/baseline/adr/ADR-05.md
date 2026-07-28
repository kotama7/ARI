# ADR-05 — secret provider（G3 scope）と authentication mode（G5 へ残置）

> Status: accepted — provider 部分は完了（Wave 4d で canonical PUT/catalog 実装済み、2026-07-24 追記参照）。authentication mode は本 ADR の範囲外（decision 5）として open のまま decision-by G5  
> Decision-by gate: G3（provider）/ G5（auth）  
> Refs: plan 00:174、plan 05 §Configuration API、plan 09 §Secret policy、ADR-11、RR-P0-2、RR-P0-4

## Context

plan 05 は secret reference/readiness 管理を G3 の構成要素とし、canonical API として `PUT /api/v1/secrets/{secret_id}`（write-only）を提案していた。Wave 3a/3b で readiness 側と既存 write 経路の hardening が完了した一方、canonical PUT は未実装であり、その扱いの明示が G3 exit に必要。

## Decision

1. **GUI v1 の secret provider は「.env chain + process env」**とする: 読み取り優先順は `{ckpt}/.env` > `/ARI/.env` > `ari-core/.env` > `~/.env` > `os.environ`（既存挙動の追認）。keychain/OS secret store は採用しない（HPC/リモート環境での可搬性を優先）。
2. **読み取りは readiness のみ**: `GET /api/v1/secrets/status`（ADR-11。configured / source_class / last_updated のみ、値は構造的に返せない DTO）。平文 `GET /api/env-keys` は redact 済み（RR-P0-2 closed）。
3. **書込みは当面 legacy `POST /api/env-keys` を hardened 形で継続**: 名前 allowlist（`^[A-Z][A-Z0-9_]{0,63}$`、制御文字拒否、Wave 3a）+ atomic write + owner-only 0o600（Wave 3b）。
4. **canonical `PUT /api/v1/secrets/{secret_id}` は Wave 4（Configuration Studio の secret flow）へ明示的に割当てる**。Studio の SecretField が接続する先として実装し、その時点で legacy POST を facade 化する。G3 はこの割当の記録をもって充足とする。
5. authentication mode（local same-origin policy / remote session）は本 ADR の範囲外として **open のまま G5 で決定**する（plan 09 §Deployment trust modes）。

## Consequences

- Wave 4 で PUT 実装時に本 ADR へ追記し、backlog row を完全 accepted 化する。
- `GET /api/v1/config/catalogs/models`（plan 05 の provisional API）も同じく Wave 4（Studio の catalog 供給）へ割当てる。

## 追記 — Wave 4d 実装完了（2026-07-24, gui_refresh task 06）

decision 4 の割当ては実装済み:

1. **`PUT /api/v1/secrets/{secret_id}` を実装**（`ari/viz/v1/secrets.py::put_secret`、routes.py `do_PUT` → v1 router）。write-only: body は `{value}` のみ、`secret_id` は `SECRET_NAMES` allowlist 限定（他は 404）、value は strip 後非空・改行/制御文字拒否（400）。書込みは hardened `api_settings._upsert_env_key`（atomic tmp+fsync+replace、0o600、live env export）へ委譲し、応答は書込み後の readiness 行（`SecretUpdatedV1`）のみ — 値は構造的に返せない。Studio（`#/studio`）の SecretField が本 endpoint に接続済み。
2. **`GET /api/v1/config/catalogs/models` を実装**（`ari/viz/v1/catalogs.py`）。legacy `GET /api/models` の static suggestion を single-source で再提供し、provider ごとの env-key 名（`PROVIDER_ENV_KEYS ⊆ SECRET_NAMES`）を付加。
3. legacy `POST /api/env-keys` は引き続き hardened 形で稼働する。両 write 経路は同一の `_upsert_env_key` writer を共有しており分岐しない。完全な facade 化（任意 UPPER_SNAKE 名を受ける legacy 契約を allowlist 限定の canonical PUT に閉じる契約変更）は、Studio が legacy Settings を置換する後続 slice（task 06 launch/cutover）で行う。
4. テスト: `ari-core/tests/test_gui_v1_secret_put_and_catalogs.py`（値の非 echo、readiness flip、allowlist 404/400、catalog と SECRET_NAMES の整合）。

これをもって backlog row の provider 部分は完全 accepted。authentication mode は decision 5 のとおり本 ADR の範囲外（G5、plan 09 §Deployment trust modes）。
