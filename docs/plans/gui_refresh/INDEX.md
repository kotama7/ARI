# ARI GUI 全面刷新計画 — Task Index

> Status: Planning  
> Owner: GUI refresh program  
> Updated: 2026-07-27（Wave 6b 文書移管完了 — task 10 を `planned` → `implemented`。ただし G6 は open（下記「現状」参照）。同日: G1／G2 通過 —「Wave 6a exit record」「G1 判定」「G2 判定」（g0_review_record.md）参照。G2-tail（AppContext reduction／`/state` freeze／RR-P0-8）解消により 03/04 を implemented、task 07 G4-tail の bullet 4（large tree/log の bounded query/render）閉鎖により 07 も implemented。前回: G4 通過（条件付き）— Wave 4e record）  
> Verified against implementation: 2026-07-23（branch RQGM worktree。`ari/viz/` backend・frontend・RQGM artifact・config 解決系と全計画を突き合わせ済み）

この `INDEX.md` は進捗、依存関係、削除状態だけを管理する。設計判断と実装詳細は各タスク計画に置き、完了後は恒久ドキュメントへ移管して計画書を削除する。

## Program goal

設定、起動、研究実行、成果確認、RQGM ガバナンス、運用診断を、同じ project/run 文脈で理解できる GUI へ刷新する。既存 GUI を一括置換せず、互換層を保った Strangler migration とする。

## Status values

- `planned`: 設計済み、未着手
- `in_progress`: 実装または検証中
- `implemented`: 実装済み、移行ゲート未通過
- `verified`: 受入条件と移行ゲートを通過
- `deleted`: 恒久文書へ移管し、この計画書を削除済み

## Task list

| ID | Plan | Status | Depends on | Primary gate |
|---|---|---|---|---|
| 00 | [Program charter and baseline](00_program_charter_and_baseline.md) | verified | — | G0 |
| 01 | [Information architecture and user journeys](01_information_architecture_and_user_journeys.md) | implemented | 00 | G1 |
| 02 | [Design system, accessibility, and i18n](02_design_system_accessibility_and_i18n.md) | implemented | 00 | G1 |
| 03 | [Application shell, routing, and frontend state](03_application_shell_routing_and_frontend_state.md) | implemented | 01, 02 | G2 |
| 04 | [Backend API, observability, and realtime](04_backend_api_observability_and_realtime.md) | implemented | 00 | G2 |
| 05 | [Configuration control plane](05_configuration_control_plane.md) | implemented | 00, 04 | G3 |
| 06 | [Configuration Studio and launch experience](06_configuration_studio_and_launch.md) | implemented | 01, 02, 03, 05 | G4 |
| 07 | [Research workspaces and Workflow Studio](07_research_workspaces_and_workflow_studio.md) | implemented | 01, 02, 03, 04 | G4 |
| 08 | [RQGM governance and score lineage](08_rqgm_governance_and_score_lineage.md) | implemented | 03, 04, 05 | G4 |
| 09 | [Security, performance, and operations](09_security_performance_and_operations.md) | implemented | 02, 03, 04, 05 | G5 |
| 10 | [Migration, testing, release, and docs](10_migration_testing_release_and_docs.md) | implemented | 01–09 | G6 |

**現状（2026-07-27）: G6 は未通過のまま open。** Wave 6b で恒久文書移管（新規 8 page × EN/ja/zh = 24 file + `rest_api` / `configuration` / `environment_variables` / `migration` / `quickstart` の 3 言語更新 + cutover runbook + CHANGELOG）が完了し task 10 を `implemented` にしたが、G6 exit condition の残り 4 要素 — (a) main への merge、(b) default-on rollout と観測期間、(c) 最低 1 minor の rollback 期間、(d) telemetry 確認後の legacy 削除 — はいずれも release process 側の事実であり、worktree からは判定できない。したがって `verified` 昇格と下記 **Delete-after checklist** の充足（特に「main に merge 済み」「rollback 期間終了・legacy usage telemetry ゼロ」）は現時点では不可能で、`docs/plans/gui_refresh/` の削除は G6 通過後にのみ実施する。詳細は `baseline/g0_review_record.md` の「Wave 6b exit record」§G6 readiness。

残余の追跡（詳細は `baseline/g0_review_record.md`）:

- **G2-tail（tasks 03/04）**: Wave 6a で解消 — AppContext scoping guard（03）、legacy `/state` FROZEN facade（04）、RR-P0-8 は **accepted (G2 tail)**（module-global 自体の物理削除は各 plan の *Deletion criteria*＝G6 legacy removal に紐付く）。03/04 は `implemented`。
- **task 07 G4-tail**: bullet 4（large tree/log/artifact の bounded query/render）は Wave 6a で閉鎖 — TreeV2 LOD + virtualized table + keyboard、`GET /api/v1/runs/{run_id}/logs` cursor explorer。07 は `implemented`。`verified` 昇格前に解消する polish 残余: (a) Projects portfolio polish（row click の sessionStorage handoff が legacy Results 向けに残存 — 機能 parity は維持、除去は plan 07 *Deletion criteria* の legacy handoff removal に紐付く）、(b) workflow 保存先 checkpoint copy の保存時ラベル表示（安全側は MN-3 revision guard + CoW guard で解消済み）、(c) PaperBench wizard polish。いずれも completion criteria の文言に掛からない。
- **task 06 governance step — delivered（残余ではない）**: **ADR-09 accepted 2026-07-27** により user-gated deferral は解消し、実装・検証まで完了した（実測は `baseline/g0_review_record.md` の「ADR-09 実装記録（2026-07-27）」— 実サーバー相手の end-to-end smoke 58 assertion と gate 表を含む）。GUI は NEW run に限り 2 つの orthogonal な mode intent を選択できる（`ari.mode`+`rqgm.enabled` / `paper.mode`+`rqgm.paper.enabled`。1 control が pair の両 key を書き、half-set は 400 `mode_interlock_mismatch`）。残る 96 の `rqgm.*` governance/tuning leaf は `mode_locked` のまま read-only 表示で、GUI v1 の RQGM read-only invariant は不変（mode 選択は governance mutation ではない）。default（`simple_bfts`+`linear`）は byte-identical、resume は persisted mode 優先で不変。MN-12。
- **task 06 residual**: resume/clone Studio slice と legacy Settings/Wizard 撤去（G6）。

## Dependency graph

```text
00 baseline
├── 01 information architecture ─┐
├── 02 design system ────────────┼── 03 application shell ─┬── 06 config/launch UX
└── 04 API and observability ────┴──────────────────────────┼── 07 research workspaces
                         └── 05 config control plane ───────┴── 08 RQGM governance
02 + 03 + 04 + 05 ──────────────────────────────────────────── 09 hardening
01–09 ───────────────────────────────────────────────────────── 10 cutover
```

## Program gates

| Gate | Exit condition |
|---|---|
| G0 — Contract freeze | 現行 route、API、Settings 契約（24-key POST / 27-key GET の非対称 shape）、checkpoint、主要画面を fixture として固定 |
| G1 — Experience contract | 情報設計、用語、design tokens、アクセシビリティ基準を承認 |
| G2 — Platform seam | 新 shell と `/api/v1` を旧画面・旧 endpoint と並行稼働 |
| G3 — Configuration truth | 全設定を schema、provenance、scope、secret policy 付きで解決可能 |
| G4 — Vertical slices | Config、Research、RQGM の各 workspace が run ID 明示で end-to-end 動作 |
| G5 — Production readiness | security、performance、a11y、i18n、recovery の budget を達成 |
| G6 — Cutover | 既定 UI 切替、最低 1 minor の rollback 期間、恒久文書移管を完了 |

## Global invariants

- 既存 hash URL、公開 REST API、Settings 24-key POST 契約（`SettingsContract.test.tsx` が固定。GET は 27-key で非対称）を移行期間中に破壊しない。
- `simple_bfts` と旧 checkpoint の挙動・成果物を GUI 都合で変更しない。
- 新 API と query は project/run ID を明示し、global active checkpoint に依存しない。
- secret の実値を API response、browser storage、manifest、log、telemetry に出さない。
- RQGM の「研究実行状態」と「制度・ガバナンス状態」を混同しない。
- score 書換えは immutable lineage として残し、異なる policy hash の score を同一尺度の連続値として描かない。
- execution mode（`ari.mode`）と paper mode（`paper.mode`）を独立軸として扱い、resume 中の mode 変更を許可しない（persisted mode が優先、downgrade-only）。
- 日本語・英語・中国語、keyboard 操作、screen reader、reduced motion を同じ acceptance gate に含める。
- GUI v1 の RQGM 操作は read-only とし、registry や transition を直接編集しない。

## Change control

- 各 plan の scope を超える変更は依存タスクと compatibility register を先に更新する。
- 新規 dependency、API、artifact、checkpoint field は ADR と migration note を伴う。
- feature flag は機能の二重実装を無期限に残す用途に使わない。
- hard gate を満たさない場合は legacy route へ戻せる状態を維持する。

## Delete-after checklist

- [ ] 各 task が `verified` になっている。（現状: 00 のみ `verified`、01–10 は `implemented`）
- [ ] 実装・テスト・migration が main に merge 済みである。（未達 — branch `RQGM` の未 commit 変更。merge 前に `scripts/readme_sync.py --check` の hard gate 解消が必要）
- [x] 公開仕様を `docs/reference/`、操作手順を `docs/guides/`、導入手順を `docs/getting-started/` へ移管した。（Wave 6b、2026-07-27）
- [x] 日本語・英語・中国語の対応文書と `last_verified` を同期した。（Wave 6b — 該当 33 page の heading 構造一致を機械検証、mismatch 0）
- [ ] rollback 期間が終了し、legacy usage telemetry がゼロである。（未開始 — default-on minor が未 release。ARI に telemetry pipeline は無く、観測は operator による `viz_access.jsonl` 読取り）
- [ ] `INDEX.md` の status を更新してから、完了した task plan を削除した。
- [ ] 全 task plan が `deleted` になった後、この `INDEX.md` と `docs/plans/gui_refresh/` ディレクトリ自体を削除した。

## 削除記録

release 由来の 4 条件 — main への merge、default-on rollout と観測期間、最低 1 minor の
rollback 期間、telemetry 確認後の legacy 削除 — は所有者の判断で免除された。G6 そのもの、
および未達部分がこの 4 つだけの条件も同様に扱う。**それ以外の条件は免除していない**:
設計判断が恒久文書に実在すること、削除で仕様が失われないこと、他ファイルが唯一の出典と
していないこと、コードについての事実を主張する完了条件が実際に成立していること。

| ファイル | 削除 | 理由 |
|---|---|---|
| `baseline/migration_notes.md` | 済 | MN-1〜MN-12 が `docs/guides/migration.md` に en/ja/zh で before/after/why/rollback 付きで再現済み。endpoint 影響表は `docs/reference/rest_api.md`。参照していた 4 箇所（`test_gui_confirmation_challenges.py`、`test_gui_csp_headers.py`、`test_gui_path_proxy_hardening.py`、`g0_review_record.md`）は同一変更で恒久文書へ張り替えた |

免除後も削除できなかったものと、その理由:

- **task plan 00–10** — 恒久文書に受け皿の無い内容が残る。00 は Compatibility register・成功指標・
  P0–P3 分類、03 は Target structure と query-key の `revision` 成分、04 と 08 は行番号で
  引用する兄弟が生存、09 は performance budget 10 行のうち 7 行が未移管
- **ADR 12 本** — `docs/adr/` には `manuscript_complete/` しか無く、GUI の ADR に恒久的な置場が
  存在しない。ADR は決定と**却下された代替案**の記録で、後者はコードに残らない。特に ADR-03 は
  実コードとテストから 19 箇所参照されている
- **`INDEX.md` 自身** — checklist 項目 7 が「全 task plan が deleted になった後」を要求

