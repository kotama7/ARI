# ADR-04 — config schema metadata の格納方式と versioning

> Status: accepted (2026-07-23)  
> Decision-by gate: G3  
> Refs: plan 00:173、plan 05 §Canonical field metadata、ADR-12

## Context

`ARIConfig`（pydantic v2）は type/default/enum を持つが、UI category、scope、mutability、sensitivity、applies_when、env_override は runtime 型に存在しない。この metadata をどこに・どの形式で持ち、どう version するかの決定が G3 の前提だった。実体は Wave 3a で実装済みであり、本 ADR はその決定を正式化する（clerical backfill）。

## Decision

1. **格納方式は in-code registry**: `ari-core/ari/config/field_registry.py` の `FIELD_META` overlay（prefix 規則 + exact-path override）+ `walk_config_leaves()` の自動列挙を merge した `build_field_registry()`。外部 YAML/JSON ファイルは採用しない。
   - 理由: 型検査・review・決定論（P2）が code として担保される。pydantic model と同一 repo/同一 commit で動くため、モデル変更と metadata 変更が atomic に diff に現れる。外部ファイル案は「第 4 の config file」を生み、defaults.yaml と同種のパリティ drift を再発させるため棄却。
2. **カバレッジ 100% は runtime 不変条件**: `get_uncovered() == []` を registry 構築時に強制（`LookupError`）し、テストでも固定。leaf 追加時に metadata 記述が漏れると build が失敗する。
3. **versioning は二軸分離**（plan 05 の要求どおり）: 表示 schema は `schema_version: 1`（`GET /api/v1/config/schema` の payload）、解決規則は `resolver_version: "legacy-compatible-1"`（`ari/config/resolver.py` の `RESOLVER_VERSION`）。schema の additive 変更は version 据え置き、破壊的変更は increment。resolver の規則変更は resolver_version bump + migration preview を要求する。
4. GUI 文書（project config / template / draft）の格納は ADR-12（`gui_store/`）が別途規定する。

## Consequences

- metadata 変更は Python diff として review される。非エンジニアが編集する用途には向かないが、本 program の運用者は開発者であり許容。
- 将来 metadata を data file 化する場合は `schema_version` bump + 本 ADR の supersede を要する。
