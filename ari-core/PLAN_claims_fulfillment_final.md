# 最終実装計画 — metric-correctness 契約の完成（claims 充足）

先行計画 `PLAN_metric_correctness_contract.md`（Phase 1-4 実装済）の後継。
本計画は 2026-06-10〜11 の実機検証 run#1〜#10 で確定した事実のみを根拠とする。

---

## 0. 現在地（実装・実機検証済み）

| 機構 | commit | 実機検証 |
|---|---|---|
| 宣言契約 enforcement（invariants/correctness/provenance/recompute/claims/G-flags） | 8feeae3, 7004af5, 8e05332 | run#4: `correctness_uncovered`→should_block→finalize 阻止（真陽性） |
| 契約の gate 配線（persist→graft）＋ transform decorator 修復 | 7004af5, 0c70a8d | run#4: transform DONE・graft 確認 |
| claims 抽出（max_tokens 4096） | 7ff397b | run#6/#7/#10: organic に claims=12 |
| 義務の全 node 注入＋window pin＋force-finish hold＋nudge | 81e5bdd, a4f85ac | run#10: emit×4・nudge×3・correctness/ceiling 全充足 |
| emit 時の契約フィードバック（check_emission） | e626792 | run#10 + micro-replay×2（捏造 rename を誘発しないことを確認） |
| EXACT-name 指示＋部分カバー奨励 | c6efb8f, 1f73dd0 | micro-replay: 安全性のみ確認（採用率は未測定） |
| run-level coverage 注入（gate 整合フィルタ込み） | b12f063, ebc7867 | 単体/seam テストのみ。**誘導効果は未測定** |
| 周辺修正（bridge/S2 condense+緩和/memory rules/idea 継承/停滞 pivot/D6 refine/D7 plot） | c9b8a0c, b2b6914, 9e96df9, a216f4f, d18a2ef, f7a4069, a53483a, 6f69749 | 各 run で動作確認（D6 fuzzy 効果と memory rules 効果は未測定） |

**確定した残ギャップ＝「宣言 claims の実験カバレッジ」のみ。**
run#10 で 12 claims 中 0 充足（命名 0/65 一致）。micro-replay により「rename では埋まらない＝本物の実験不足」、
調査により「node 数を増やすだけでは埋まらない（探索が claims 非認知、元 CSR 10-node は headline の 10 変奏）」を確認済み。

---

## 1. 検証ラダー（安価→高価。各段に判定基準と分岐）

### V1. micro-replay：coverage 誘導の効果（コスト: LLM 1-2 呼出・数分）
- 手順: run#10 の checkpoint 状態（contract＋既存 results）から coverage block 付き義務を生成し、
  「この node の実験を設計せよ」を gpt-5.2 に 1 発で問う。
- **判定**: 提案実験が STILL UNCOVERED の claim（mode 比較/PMU 等）を狙う → V2 へ。
  headline 再演に終始 → 注入文言を強化して再試行（2 回まで）。それでも不発 → P3 を即時実施。

### V2. ミニ run（2-3 node・partA・〜40 分）
- 全レイヤー込みで観測:
  (a) 2 つ目以降の node が coverage block を受けて**異なる claim** を狙うか（分業の発生）
  (b) EXACT-name 採用率（>0 になるか）
  (c) 偽カバー（汎用名 `k` 等での誤 covered）の発生有無 → 発生したら P2-b を実施
  (d) 能動 memory 呼出・nudge→re-emit の再現
- **判定**: coverage が 0→n (n≥1) に動けば V3 へ。動かなければ P3（expansion-select）実施後に再 V2。

### V3. 本番規模 run（max_nodes=10・partB 空き時 or partA・数時間・実費大）
- 観測: coverage n/12 の推移（node 毎の単調増加）、PMU 系 claim の実現可能性（P2-c の判断材料）、
  終端 gate の通過（finalize された論文が出るか）、D6 fuzzy refine と memory rules の実効。
- **成功基準**: claim_evidence_missing が単調減少し、最終 block 理由が
  「platform 上測定不能な claim」のみに収斂すること（→ P2-c の根拠データになる）。

---

## 2. 実装項目（優先順）

### P1. root node を殺す litellm tool_calls エラーの修正【バグ・最優先】
- 事実: run#2/#7/#9 で root が
  `assistant message with 'tool_calls' must be followed by tool messages…` で死亡（**5 run 中 3 回**、node 予算の半分を損失）。
- 仮説: `_build_safe_window` の tail 展開（loop.py:656-664）が、複数 tool_calls を持つ assistant を
  先頭 tool の対だけで window に入れ、残りの応答が欠けたまま送信される経路。
  pin の lookahead（i+4）も複数応答＋注入 message で溢れる可能性。
- 作業: 再現テスト（複数 tool_calls＋注入 message の window 構築）→ `_validate_pairs` を送信直前の
  最終 window にも適用 or tail 展開で全 tc_ids の応答を強制同梱。
- 受け入れ: 合成ケースで欠落ペアが送信されないこと＋次の実 run で root 生存。

### P2. producer 側の claims 品質（contract 生成の改善）
- **(a) 汎用 evidence 名の禁止**: `_CLAIMS_EXTRACT_SYS` に「`k`/`matrix_id`/`mode_id` 等の汎用語を
  単独 evidence にしない（R1 偽カバーの温床）。各 claim に固有で識別的な名前を」を追加。
  受け入れ: run#10 контract 相当の入力で汎用単独名が消えること（micro 検証可）。
- **(b) steering 用 coverage の判定強化（V2 で偽カバーが出た場合のみ）**:
  `build_coverage_status` の covered 判定を「名前の過半数一致」に変更（gate の R1 は不変——
  over-block 回避の合意トレードオフを維持。steering だけ厳格化）。
- **(c) platform-feasibility（V3 の結果待ち）**: `branch_mpki` 等 PMU 前提の evidence が
  cpuX 非特権で測定不能と判明した場合、claims 抽出プロンプトに experiment.md の platform 記述を
  渡し「この環境で測定可能な evidence のみ宣言」を指示。
  ※ waiver チャネル（agent が infeasible を自己申告）は gaming 面になるため**作らない**。

### P3. expansion-select への coverage 提示【V1/V2 不発時の条件付き】
- 内容: `select_best_to_expand`（orchestrator/bfts.py:520）の候補提示文に
  「run-level で未充足の claims: […]」を 1 行追加（gate 整合 coverage を使用）。
- 設計確認済み: scheduler は元々 cross-branch（全候補の score/metrics/summary を一括提示）であり
  node 文脈の独立性を侵さない。
- 受け入れ: V2 再実行で分業が発生すること。

### P4. scoring への coverage 軸【最終手段・原則やらない】
- 「新規 claim カバー数」を node score に入れる案は **Goodhart リスク**
  （presence-only gate と組むと名前合わせ＝捏造圧力）。P3 まで不発の場合のみ、
  correctness/provenance 必須化とセットで再設計する。本計画では**実施しない**。

---

## 3. 確定済みの設計判断（変更しない）

1. **gate の R1（any-name で covered）は維持**——over-block 回避の合意トレードオフ。厳格化は steering 側のみ（P2-b）。
2. **既存の停滞 pivot は coverage 用途に使わない**——escape lever（idea 交代＝claims リセット）であり fulfillment lever ではない。
   実行系（cli/lineage.py の子 run 起動＋root promotion）まで配線済みであることは確認済み。
3. **D6（prose 粉飾）は advisory のまま**——「客観は block・主観は advisory」の合意設計。
   対処は paper_refine の適用強化（実装済 a53483a、fuzzy 効果は V3 で測定）。
4. **presence-not-truth 境界**——gate は証拠の存在を検証し真偽は検証しない（claim_gate 全体の明示境界）。
5. **coverage は測定名のみ運ぶ**——兄弟 branch の数値・結論は流さない（fault containment 維持）。
   かつ gate 整合（has_real_data node のみ、ebc7867）。

---

## 3.5 検証結果（2026-06-11 実施: P1/P2/P3）

| 項目 | 結果 |
|---|---|
| P1 実装＋単体 | ✅ c76624c — 注入遅延＋`repair_tool_message_order`（実 run の失敗形を再現する 4 テスト）。実 run での root 生存確認は次回 organic run |
| P2(a) 実 LLM 検証 | ✅ a6c7640 — run#10 実 plan で抽出: **汎用名 0/40**・全名識別的。PMU 系 6 件は plan が counters を明示するため例外条項が正当発動 |
| P2(b) | ✅ 過半数 steering（テスト済、gate R1 不変） |
| **P2(c) 前提の実証** | ⚠ **partA に perf 非搭載を実機確認**（`command not found`）→ PMU 系 claims は partA で恒久充足不能。idea/抽出への platform-capability 伝達が必要（実装は計画どおり保留だが、根拠は確定） |
| P3 / V1 micro-replay | ✅ 41c4666 — coverage block（0/12）提示で新 node 設計が **未充足 claim（M2 DTLB/LLC）を選択**・**canonical 名 EXACT 採用 4/4**・correctness/ceiling も自発同梱。headline 再演なし＝**分業が機構として機能** |

注: V1 で agent が選んだのは皮肉にも PMU 系（partA 不能）——steering は機能するが、platform 不能 claims が誘引になる。P2(c) の優先度を「V3 後」から「次の実装候補」へ引き上げる根拠。

## 4. 既知の別件（本計画外・記録のみ）

- `test_gui_env_propagation.py` の env 汚染による test_config 2 件の順序依存 fail（pre-existing）。
- idea テストの faiss 欠如 skip/fail（テスト実行環境差、pre-existing）。
- react 自動記録が type 無しで書かれる（観測タグの欠落、機能影響なし）。

## 5. 検証手法の規約（このセッションで確立）

- **修正部分のみの検証は micro-replay で行う**: 実 checkpoint の contract/emission＋新プロンプト＋実 LLM 1 呼出。
  フル run の前に必ず実施（安価・数分・捏造誘発等の安全性確認に有効）。
- ユニットテストは「関数直接呼出」が MCP tool 登録・subprocess 環境・window 生存などの
  経路破壊を検出できない——**seam テスト（実 writer→実 reader）と実 run の両方を完了条件とする**
  （feedback_validate_on_real_env_not_fakes に整合）。
