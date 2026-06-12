# PLAN: Artifact-Summary Handoff — 分岐型LLMコード生成におけるコンテキスト制約付き状態受け渡し

Status: 研究計画（design 段階、未実装）。Origin: 2026-06-12 設計議論。
削除条件: 本計画の Phase 1〜5（pilot 実験まで）が完了し、結果が論文ドラフトまたは
後継 PLAN に転記された時点で本ファイルを削除する。

英語題目: *Artifact-Summary Handoff for Context-Bounded Branching LLM Code Agents*

---

## 0. 実装現状の検証結果（2026-06-12、コードベース監査済み）

本計画は ARI を reference implementation として用いる。計画の前提となる既存実装を
検証した結果を先に固定する。**以降の節はこの検証結果を前提に読む。**

### 0.1 計画の前提が実装と一致する点（検証済み）

| 前提 | 実装 | 根拠 |
|---|---|---|
| per-node work directory | `PathManager.node_work_dir()` → `experiments/{run_id}/{node_id}/` | `ari/paths.py:175-181`, `ari/cli/bfts_loop.py:374-381` |
| 親→子のコード成果物継承（結果ファイル除外） | `_run_loop()` 内の selective copy。`_OUTPUT_BLACKLIST`（results.csv, run.log, slurm-\*.out, stdout/stderr, \*.metrics.json, node_report.json 等）+ `PathManager.is_meta_file()` の2段除外 | `ari/cli/bfts_loop.py:382-445`（blacklist は :400-413） |
| node_report.json の構造化レポート | `build_node_report()`/`write_node_report()`。`files_changed` / `delta_vs_parent` / `metrics` / `self_assessment` / `next_steps_hints` / `build_command` / `run_command` を含む（計7+24フィールド、JSON Schema あり） | `ari/orchestrator/node_report/builder.py:481-590`, `ari/schemas/node_report.schema.json` |
| node_report の子への還流 | `_format_parent_report_block()` が親の delta_vs_parent / files_changed / concerns / next_steps_hints を抽出し **BFTS planner の expand プロンプト**に注入。`_PromptBudget` で各フィールドを文字数キャップ（delta 240 / concern 200 / hint 200 chars） | `ari/orchestrator/bfts.py:64-108, 629-633, 755` |
| tree.json / cost_trace.jsonl | tree.json は `Node.to_dict()`（id, parent_id, children, depth, status, metrics）。cost_trace.jsonl は CallRecord（timestamp, **node_id**, phase, skill, model, **prompt_tokens**, completion_tokens, estimated_cost_usd, latency_ms）を per-call 記録 → 本計画のトークン系指標は追加実装なしで算出可能 | `ari/cli/bfts_loop.py:882-888`, `ari/cost_tracker.py:59-75` |
| ReAct loop の予算 | `max_react_steps`（default 80, `ARI_MAX_REACT`）、`max_parallel_nodes`（default 4, `ARI_PARALLEL`）。会話は node ごとに完全分離（`messages` は `AgentLoop.run()` ローカル） | `ari/agent/loop.py:356-374, 617-620`, `ari/config/__init__.py:66-158, 429-471` |
| 機能の段階 toggle | VirSci/idea・survey・paper・review・ORS・rubric 各 stage は workflow.yaml の pipeline stage `enabled` で off 可能 | `ari-core/config/workflow.yaml`, `ari/config/__init__.py`（ARIConfig, pydantic） |
| deterministic evaluator の前例 | Evaluator Protocol（async `evaluate()` → `{score, reason, has_real_data, metrics}`）。node.metrics は evaluator 戻り値から populate され BFTS の選択に使われる | `ari/protocols/evaluator.py:19-40`, `ari/agent/loop.py`, `ari/orchestrator/node.py:98` |

### 0.2 計画が実装と食い違う点（本計画で修正済みの認識）

1. **linear refinement は存在しない。** 探索は BFTS のみ（`ari/orchestrator/bfts.py`、
   リポジトリ唯一の探索クラス）。`frontier_score` の 4 variant
   （scientific_only / scientific_plus_diversity / depth_penalized / ucb_like,
   `ari/config/__init__.py:106-120`）は **LLM selector が解答不能な場合の
   deterministic fallback のスコアリング**であり、探索方式の切替ではない
   （一次選択は LLM-driven: `bfts.py:418-575`）。→ §13.5 の SearchPolicy は**新規実装**。
2. **search_trace.jsonl は存在しない。** 既存は tree.json / cost_trace.jsonl /
   memory_access.jsonl / lineage_decisions.jsonl。→ §13.9 から削除し、必要なら
   handoff 実装時に新設する。
3. **「親 summary が子に渡る」経路は2面に分かれており、子 agent 自身のプロンプトには
   ほぼ何も入らない。** (a) node_report 由来 block は **planner の expand プロンプト**
   （子の方向性を決める側）にのみ入る。(b) 子 agent の実行コンテキストに入るのは
   ancestor memory 経由の `result_summary` エントリ（Tier-1b）と semantic 検索の
   detail supplement（Tier-2, `loop.py:164-345`）のみで、子の最初の user message は
   goal_text + node id/depth/label + 汎用 label 説明だけ（`loop.py:577-598`）。
   → 提案する「structured node summary を**子 agent のプロンプトへ**注入する」のは
   既存挙動の言い換えではなく**新規の handoff 面**である（§13.3）。
4. **memory off は env 変数系で、完全 off スイッチは未実装。** バックエンド選択は
   `ARI_MEMORY_BACKEND`（letta|in_memory）等。global memory は v0.6.0 で撤去済み。
   さらに loop は**全 tool 実行結果を node-scoped memory に自動保存**し
   （`loop.py:909-914`）、Tier-2 検索は type フィルタなしで ancestor の tool trace
   断片を拾い得る。→ **code_only 条件を成立させるには Tier-1b/Tier-2 注入の明示的
   off スイッチが必須**（§13.4 は新規実装、かつ無効化しないと条件が汚染される）。
5. **timeout_per_node は現状プロンプト文言のみで実行時強制されていない**
   （`bfts_loop.py:532-541` の TimeoutError 分岐は `as_completed` 後のため実質 dead
   code）。→ §12.1 の実験統制として使う場合は強制実装を直すか、統制変数から外す。
6. **experiments/ は gitignore 済み**（`.gitignore:31`）で、ランタイム出力
   （`experiments/{run_id}/{node_id}`）と同居する。→ §13.6 のベンチマークハーネスは
   tracked な場所に置く（`.gitignore` に例外を追加するか、ari-core 配下のテンプレート
   ディレクトリから run 時に配布する）。
7. **context overflow の明示的検出は存在しない。** 窓制御はヒューリスティック
   （直近 50 msg、tool 結果 500 chars 超を圧縮、`_MAX_TOOL_OUTPUT=4000` 等）。
   → §11.3 の context overflow rate は「cost_trace.jsonl の prompt_tokens がモデルの
   コンテキスト上限を超えた・窓圧縮が発動した回数」として計測器を定義して測る。

### 0.3 現状の de-facto handoff（= 本研究の出発点）

ARI の現行デフォルトは、おおよそ
**code（workdir copy） + planner 側 summary（node_report block） + memory 側 summary
（ancestor result_summary + semantic supplement）** であり、本計画の用語では
code_plus_summary の変種に相当する。本研究はこれを「実装上の工夫」から
**制御可能な handoff policy** に抽出・定式化し、ablation で各成分の寄与を測る。

---

## 1. 研究概要

LLM コード生成エージェントでは、実装→ビルド→実行→評価→修正の反復ループに加え、
複数の改善方針を並行して試す分岐型探索（BFTS, MCTS, evolutionary search）が
使われるようになっている。分岐型探索では**子ノードが親ノードの実験状態を何を介して
継承するか**が本質的な設計問題になる。全対話履歴・全 tool trace・全ログを渡せば
コンテキスト長が探索深度に比例して爆発し、何も渡さなければ失敗理由・改善方針・
評価結果が失われて同じ失敗と重複試行が再発する。

本研究は、親→子へ渡す状態を
**code artifact state（実行可能なファイル群、work directory 経由）** と
**operational summary state（実験状態の構造化要約、プロンプト経由）** に分解し、
この2つだけを渡す **Artifact-Summary Handoff** を提案・評価する。要約対象は会話履歴
ではなく**実験状態**（何を実装し、どのファイルが変わり、どのコマンドでビルド・実行し、
どの指標が得られ、どの失敗が残り、次に何を試すべきか）である点が特徴である。

主タスクは CSR SpMV 最適化とし、handoff 方式の違いが性能・正解性・トークン効率・
失敗再発率・重複試行率に与える影響を統制実験で評価する。本会議投稿時には stencil /
FFT / GEMM micro-kernel 等へ拡張する。

## 2. 中心的主張

分岐型 LLM コード生成では、親ノードの全対話履歴や全ログを子へ渡す必要はない。
実行可能なコード成果物と構造化されたノード要約を渡せば、性能改善に必要な情報を
十分に継承でき、かつ入力トークン数と最大コンテキスト長を探索深度から切り離せる。

## 3. 比較する handoff 方式

| mode | code (workdir) | summary (prompt) | log (prompt) | 備考 |
|---|---|---|---|---|
| code_only | ✓ | — | — | 実行可能状態のみ。memory 注入も off（§0.2-4） |
| summary_only | — | ✓ | — | 要約のみで状態継承できるか |
| **code_plus_summary（提案）** | ✓ | ✓（structured） | — | |
| code_plus_full_log | ✓ | — | ✓（tool trace / stdout / stderr / 評価理由を可能な限り） | 情報量上限 baseline。親の結果**ファイル**は workdir へコピーしない（ログは prompt のみ） |
| code_plus_truncated_log | ✓ | — | ✓（固定 token / tail truncation） | full_log の現実版 |
| rolling_summary | ✓ | ✓（自然言語逐次要約） | — | 一般的 conversation summary との差を測る |
| failure_only_summary | ✓ | ✓（known_failures のみ） | — | 失敗情報だけの寄与を測る |

## 4. Summary schema ablation

structured node summary のどの要素が効くかを分離する:
full / −metrics / −known_failures / −next_steps / −delta_vs_parent / −changed_files /
−build·run_command / 自然言語版 vs structured JSON 版 / LLM 生成 vs 決定論的抽出。

## 5. 実験対象タスク

主タスク: **CSR SpMV 最適化**（y = Ax）。最適化方針の探索余地が広く
（OpenMP scheduling, row-length bucketing, SELL-C-σ, blocked CSR, unrolling,
prefetch, locality, load balance）、行列ファミリ
（uniform random / banded / power-law / block / diagonal-dominant / skewed、
必要に応じ SuiteSparse）で条件を変えられる。リポジトリには CSR SpMM の既存
checkpoint・metric_contract の運用実績があり（§0.1）、評価系の土地勘がある。

拡張タスク候補: stencil, FFT kernel, GEMM micro-kernel, graph BFS/PageRank,
JSON parser, compression kernel。本会議版では最低3タスク。

## 6. 評価指標

- **主性能**: best valid geomean speedup @ N nodes。valid = compile + run +
  correctness（相対誤差閾値、**OpenMP reduction の FP 順序差を許容する ε を明記**）+
  no timeout + 全行列 benchmark 完了 + protocol violation なし。invalid は score 0。
- **探索効率**: AUC of best-so-far, first valid node index, valid node rate,
  compile/correctness rate, token-normalized score。
- **コンテキスト効率（中心指標）**: mean/max input tokens per node, cumulative input
  tokens, context growth rate vs depth, context overflow rate（§0.2-7 の定義）,
  summary compression ratio, selector token cost, LLM call 数, wall-clock。
  いずれも cost_trace.jsonl（prompt_tokens, node_id per call）から算出可能（§0.1）。
- **handoff 品質**: useful inheritance rate, parent code modification rate,
  from-scratch rewrite rate, repeated failure/strategy rate, stale-result reuse rate,
  parent result misuse rate, duplicate attempt rate。
- **failure recurrence**: 同一コンパイルエラー / 正解性エラー / protocol violation /
  性能劣化要因 / 無効方針 / 親結果ファイル誤用の再発分析。

## 7. 実験条件

### 7.1 主実験
探索を BFTS に固定し handoff のみ変更。固定: 初期 experiment.md・初期コード・
harness・LLM model・temperature・executed node 数・max ReAct steps・parallelism・
deterministic evaluator。token 数は固定しない（input token 削減自体が評価対象）。
timeout per node は §0.2-5 の通り現状非強制のため、強制実装を入れるか統制から外すかを
Phase 1 で決める。

**選択分散の統制**: BFTS の一次ノード選択は LLM-driven（§0.2-1）であり handoff 比較の
ノイズ源になるため、主実験では deterministic fallback selector
（`frontier_score: scientific_only` 相当）を**一次選択として使う option を新設**し、
LLM selector は副実験で扱う。

### 7.2 補助実験
1. **token budget 固定比較**: 同一トークン予算内で各方式が実行できた有効ノード数。
2. **探索方式比較**: handoff を code_plus_summary に固定し、BFTS vs
   linear refinement（**新規実装**、§13.5）。
3. **複数モデル**: GPT 系 / Claude 系 / Gemini 系 / open-weight code model で再現性確認。

### 7.3 無効化する ARI 機能（主実験）
VirSci/idea, arXiv survey, Letta/ancestor memory 注入（§0.2-4 の新規 off スイッチ）,
paper, review, ORS, rubric-derived axes, LLM-judge 最終評価。
理由: handoff 効果を外部記憶・文献・仮説生成・論文生成の効果から分離するため。

## 8. ARI への実装計画

### 8.1 HandoffConfig（新規）
`ari/config/__init__.py` の ARIConfig（pydantic）に追加し、`apply_bfts_env_overrides`
と同型の env override を付ける。

```yaml
handoff:
  mode: code_plus_summary   # code_only | summary_only | code_plus_summary |
                            # code_plus_full_log | code_plus_truncated_log |
                            # rolling_summary | failure_only_summary
  summary_max_tokens: 800
  summary_schema: structured_json   # | natural_language
  summary_source: deterministic     # | llm
  include_parent_outputs: false
  inject_into: [agent]              # agent | planner | both（§0.2-3 の2面を明示制御）
  memory_injection: off             # Tier-1b/Tier-2 注入の明示スイッチ（新規）
```

### 8.2 node_summary_view（新規）
node_report.json（§0.1 で全フィールド存在確認済み）から子へ渡す短い view を生成:

```json
{
  "node_id": "...", "parent_id": "...", "label": "...",
  "valid": true, "objective_score": 2.31,
  "changed_files": ["spmv.c", "run.sh"],
  "delta_vs_parent": "...",
  "build_command": "make", "run_command": "./bench",
  "key_metrics": {"valid_geomean_speedup": 2.31, "max_relative_error": 1e-7},
  "known_failures": ["dynamic scheduling degraded banded matrices"],
  "next_steps": ["try row-length bucketing for skewed matrices"]
}
```

既存の `_PromptBudget`（§0.1）が planner 側 block の文字数キャップとして同思想の
先行実装になっており、これを handoff 全面に一般化する。

### 8.3 注入面の配線（§0.2-3 が根拠）
- **agent 面（新規）**: `AgentLoop.run()` の最初の user message
  （`loop.py:577-598`）に mode に応じて node_summary_view / log block を注入。
- **planner 面（既存改修）**: `_format_parent_report_block()`（`bfts.py:64-108`）を
  HandoffConfig 配下に置き、mode で on/off。
- **workdir 面（既存）**: `bfts_loop.py:382-445` の copy + `_OUTPUT_BLACKLIST` を
  mode（code を含むか）で on/off。
- full_log / truncated_log は cost をかけず node の transcript / tool trace 保存から
  構成する（結果ファイルは workdir へコピーしない）。

### 8.4 memory 注入の明示 off（新規）
`build_working_context_messages()`（`loop.py:164-345`）の Tier-1b / Tier-2 を
`handoff.memory_injection` で制御。off にしないと tool trace が memory 経由で
子に漏れ、code_only 条件が成立しない（§0.2-4）。

### 8.5 SearchPolicy（新規）
`bfts`（現状）に加え `linear_latest` / `linear_best` を新規実装。
`bfts_score_only` は「LLM selector を使わず `_fallback_score` を一次選択にする」
mode として実装（§7.1 の統制にも使う）。

### 8.6 SpMV harness（tracked な置き場所に、§0.2-6）
`experiments/handoff_spmv/` 相当を tracked 化（`.gitignore` 例外 or ari-core 配下の
テンプレート + run 時配布）。内容: experiment.md, baseline_spmv.c, candidate_spmv.c,
Makefile, run_candidate.sh, matrix_generators.py, benchmark.py, evaluate_node.py,
README.md。**LLM が編集してよいファイルと benchmark/evaluator（編集禁止）を分離**し、
編集禁止側は checksum で protocol violation を検出する。

### 8.7 deterministic evaluator（新規、Protocol 準拠）
`ari/protocols/evaluator.py` の Evaluator Protocol に準拠（§0.1）。出力例:

```json
{"valid": true, "score": 2.41, "metric_name": "valid_geomean_speedup",
 "compile_success": true, "correctness_pass": true, "max_relative_error": 3.2e-7,
 "timeout": false,
 "speedups": {"uniform": 1.9, "banded": 2.7, "powerlaw": 2.2, "block": 2.9}}
```

### 8.8 実行・集計スクリプト
- `scripts/run_handoff_ablation.py`: mode 切替 / 複数 seed / node・step budget 固定 /
  不要機能 off / checkpoint path 整理（`workspace/checkpoints/<ts>_<slug>/` 規約）。
- `scripts/analyze_handoff_ablation.py`: tree.json, cost_trace.jsonl,
  node_report.json, results.json, evaluator 出力を読み、§6 の全指標 + bootstrap CI を
  集計（search_trace.jsonl は存在しないため対象外、必要なら handoff_trace.jsonl を新設）。

## 9. Research Questions

- **RQ1**: Artifact-Summary Handoff は full log handoff と同等の性能
  （best valid geomean speedup, AUC, valid node rate）を維持できるか。
- **RQ2**: 入力トークン数と最大コンテキスト長（cumulative/mean/max input tokens,
  context growth rate, overflow rate）を削減できるか。
- **RQ3**: code only では失敗再発・重複試行（failure recurrence, duplicate attempt,
  repeated strategy, invalid node rate）が増えるか。
- **RQ4**: structured summary のどの要素が寄与するか（field ablation による
  performance drop / token reduction / failure recurrence increase）。
- **RQ5**: 効果は探索方式・タスク・モデル・seed を超えて再現するか。

## 10. 投稿戦略

HPC SpMV 論文ではなく LLM code agent / automated software engineering の論文として
投稿する。初期: ASE/ICSE workshop, MLSys workshop, LLM for HPC workshop。
本会議: ASE Research Track（最有力）, ICSE, MLSys, OOPSLA。
ジャーナル: ASE Journal, TOSEM, TSE, TMLR。

**Related work の必須差別化**（reviewer リスク対策）: AIDE（tree search +
journal/summary 継承）、SWE-agent / OpenHands の context condensation、
MLE-bench 系 agent、agent workflow memory。差別化軸は「handoff 方式そのものを
独立変数として統制 ablation し、operational state の要素別寄与を測る初の
empirical study」であり、特定手法の提案勝負にしない。

## 11. スケジュール

- **Phase 1 設計**: §0 の食い違い7点の解消方針確定（timeout 強制、harness 置き場所、
  memory off スイッチ、handoff_trace 要否）、HandoffConfig schema 確定。
- **Phase 2 最小実装**: HandoffConfig / node_summary_view / agent 面注入 /
  memory off / code_only・code_plus_summary・code_plus_full_log。
- **Phase 3 SpMV harness**: baseline 実装、matrix generator、correctness checker
  （ε 設計込み）、timing harness、results.json schema、編集禁止ファイルの checksum。
- **Phase 4 evaluator**: Protocol 準拠 deterministic evaluator、node.metrics 保存。
- **Phase 5 pilot**: code_only / code_plus_summary / code_plus_full_log /
  code_plus_truncated_log の小規模比較（deterministic selector、複数 seed 最小構成）。
- **Phase 6 本実験**: 全 mode、summary ablation、token budget 固定、複数 seed。
- **Phase 7 拡張**: linear refinement 実装比較、追加タスク、複数モデル。
- **Phase 8 論文化**: related work、RQ 別結果、qualitative failure analysis、
  threats to validity、replication package。

## 12. リスクと対策

1. **ARI 固有の engineering に見える** → state transfer model として抽象化し、ARI は
   reference implementation と位置づける。
2. **SpMV 単一タスクに見える** → 行列ファミリ多様化 + 追加タスク（Phase 7）。
3. **full log baseline が弱い** → truncated / rolling / failure-only / retrieval
   baseline を併設。
4. **structured summary の設計が恣意的** → field ablation（§4）で要素別寄与を示す。
5. **LLM の偶然性** → 複数 seed、bootstrap CI、paired comparison、per-task breakdown、
   deterministic selector（§7.1）で選択分散を遮断。
6. **LLM Judge 依存に見える** → 主評価は deterministic evaluator のみ。LLM Judge は
   主評価から除外。
7. **先行研究（AIDE 等）との近接** → §10 の差別化軸で統制 empirical study として
   位置づける。
