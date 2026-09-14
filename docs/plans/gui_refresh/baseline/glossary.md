# Target Domain Glossary

> Status: active working doc  
> Created: 2026-07-23  
> Owner: GUI refresh program  
> 移管先: docs/reference|concepts at G6

plan 00 の target domain model と plan 01 の terminology contract を統合した用語正本。GUI label、config key/artifact、三言語表記を一箇所で管理し、docs（特に `docs/guides/execution_modes.md`）と同一 glossary を共有する。曖昧語（Mode、Success、Attack score、Deleted、Current score、Settings 単独）は GUI label として使用禁止（plan 01 参照）。

| Term (EN) | GUI label policy | Config key / artifact | ja | zh | Notes |
|---|---|---|---|---|---|
| Project | 「Project」。portfolio の管理境界として表示 | greenfield（現行は project ≡ run ≡ checkpoint。`YYYYMMDDHHMMSS_<slug>` dir 名が ID、7 search base を scan） | プロジェクト | 项目 | 初期実装は「暗黙の default project」への mapping（ADR-08） |
| Run | 「Run」。URL/API で必ず `run_id` を明示 | checkpoint dir 名 = run_id（現行）。`meta.json` | ラン（実行） | 运行 | global active checkpoint への依存禁止（global invariant） |
| Checkpoint | 「Checkpoint」。run の保存点として表示し、別 run と混同させない | `{ARI_CHECKPOINT_DIR}` 配下の directory | チェックポイント | 检查点 | UI 利用のための必須 migration を要求しない（compatibility register） |
| ResolvedConfigSnapshot | 「Effective config」/ launch summary。不変記録として read-only 表示 | 新: `resolved_config.json`（additive）。legacy: `launch_config.json` | 実効設定スナップショット | 生效配置快照 | secret 実値を含めない。digest は redacted canonical 表現から計算 |
| ResearchState | 「Research status」。governance と別 status model | `/state` の `current_phase`（idle/starting/bfts/paper/review） | 研究状態 | 研究状态 | phase 語彙は新 model が現行を包含することを parity test で確認 |
| GovernanceState | 「Governance status」。research success/failure と独立表示 | `rqgm_state.json`、`rqgm_transitions.jsonl`（replay が正本） | ガバナンス状態 | 治理状态 | 「Governance accepted」≠「Research completed」（plan 01 terminology contract） |
| Epoch | 「Epoch」。ID/digest 付きで表示 | `epoch_state.json`。truth は `rqgm_transitions.jsonl` replay | エポック | 纪元 | epoch 比較は schema/policy compatibility 確認後のみ |
| PolicyVersion | 「Policy `<hash12>`」。score は必ず「Score under policy `<hash>`」 | `utility_policy_hash` = `hash12(canonical_json(...))`。policy body は `{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}` | ポリシー版 | 策略版本 | penalty 側 frozen policy と epoch policy が同名 hash を使う実装の subtlety に注意（DTO で別名化、plan 08） |
| RegistryNode / ComponentEntry | 「Registry component」。lifecycle は実装語彙のまま表示 | `rqgm_registry.json`（`registry_version`、`as_of_event_hash`）。STATUS_VALUES: candidate/validated/shadow/probationary_active/active/warning/probation/quarantine/retired/banned | レジストリ構成要素 | 注册表组件 | component lifecycle 語彙と node score 状態語彙は別 state machine。混在禁止 |
| Transition (T1–T21) | 「Transition」。status（pending/committed/aborted/rejected/failed）と `rule_id` を表示 | `rqgm_transitions.jsonl`。`rule_id` ∈ T1–T21 + `EMERGENCY_EDGE` | 遷移 | 转换 | committed の replay 結果のみを current state とする |
| ScoreObservation (UtilityRecord) | 「Score observation」。base → validated penalty → final の waterfall | `UtilityRecord`（`utl_*`）in `rqgm_adversarial_cases.jsonl`。node sentinel: `_pre_penalty_score`、`_validated_attack_penalty`、`_utility_policy_hash` | スコア観測 | 得分观测 | 履歴は上書きしない。異 policy hash を同一連続 series で描かない |
| Execution mode | 「Execution mode」。単独の「Mode」表記禁止 | `ari.mode` ∈ `simple_bfts` \| `ari_rqgm`。provenance は `rqgm_state.json` の `mode_source`/`switch_journal` | 実行モード | 执行模式 | resume 中の変更禁止（persisted mode 優先、downgrade-only） |
| Paper mode | 「Paper mode」。execution mode と独立軸として常時区別 | `paper.mode` ∈ `linear` \| `rqgm_archive`。`paper_archive_state.json` 不在 = `linear` | 論文モード | 论文模式 | 2×2 の全組合せが有効（plan 01 global shell context） |
| Execution environment | 「Execution environment」。execution mode と別概念 | `config/profiles/*.yaml`（laptop/HPC/cloud。merge は 4 key のみ） | 実行環境 | 执行环境 | `docs/guides/execution_modes.md` は `ari.mode` を「execution mode」と呼ぶため、両者の区別を docs と同一 glossary で明文化（plan 01:183） |
| Raw attack / Validated penalty | 「Raw attack」と「Validated penalty」を別 label で表示。「Attack score」禁止 | raw_attack（`atk_*`）→ validated_attack（`vat_*`）。score へ触れるのは adjudicated ValidatedAttack のみ | 生攻撃／検証済みペナルティ | 原始攻击／已验证惩罚 | 「attack 0 件 = 健全」と表示しない（inert chain は capability state として表示、plan 08） |
| Stale / Invalidated / Removed | 三状態を別 label で表示。「Deleted」禁止 | node sentinel `_stale`/`_stale_reason`/`_valid_for_frontier`。`SelectiveErasureEvent`（`erase_*`）、`FrontierRebuildEvent`（`rebuild_*`） | 陳腐化／無効化／除去 | 陈旧／已失效／已移除 | logical state と物理削除を分離。physically deleted はさらに別状態 |
| EAR (Experiment Artifact Record) | 「EAR」/ publication lineage として result から追跡可能に表示 | curate（bundle sha256）→ preview → publish（`consent=true` 必須）→ promote。`publish.yaml`、`manifest.lock` | 実験成果物レコード | 实验工件记录 | publish 済み bundle と checkpoint 内容の対応が traceability の終端（plan 07） |
| Sub-experiment lineage | 「Run lineage」。run 内の BFTS node tree と混同させない | `meta.json` の `parent_run_id`、`recursion_depth`（上限 3）、`inherit_ideas[n]`、`parent_terminated` | サブ実験系譜 | 子实验谱系 | run 間 relation として run list と run Overview の両方から辿れるようにする |

## 付記

- registry component の lifecycle 状態と tree node の score 状態（computed/recomputed/stale/invalidated/removed）は別語彙・別 state machine（plan 01:183、plan 08:94）。
- 「Settings」単独 label は禁止し、Preferences / Template / Effective config / Secret と scope を明示する（plan 01 terminology contract）。
- G6 で i18n glossary（三言語 key parity 資産）と docs へ移管する。
