# PREREG — Stage 0 凍結（What Should Branching LLM Code Agents Inherit?）

Status: 事前登録（凍結値。実験開始後は変更しない）。Origin: 2026-06、ユーザ委任により推奨デフォルトを採択。
親: [`MASTER_PLAN_handoff_impl.md`](MASTER_PLAN_handoff_impl.md)、研究計画 [`PLAN_artifact_summary_handoff.md`](PLAN_artifact_summary_handoff.md) §7。
削除条件: 本研究の confirmatory run が完了し、凍結値と結果が論文ドラフトまたは後継 PLAN に転記された時点で削除。

## 採択した実行方針
- **主タスク**: **SpMM（Y=AX, A=CSR）**。既存 fixture・評価運用実績があり MVP を最短で実物まで詰められるため。SpMV は Phase C。
- **実装ブランチ**: **`bfts_compare`**（実装コード専用）。計画/PREREG は PR #31（`plan-artifact-summary-handoff`）に温存。

## 凍結値
| # | 項目 | 凍結値 |
|---|---|---|
| 1 | valid 述語 | compile ∧ run ∧ correctness(ε) ∧ no-timeout ∧ 全必須行列完了 ∧ no protocol-violation。invalid=score 0 |
| 2 | ε 誤差モデル | 出力要素ごと `|y_cand−y_ref| ≤ C·γ_k·Σ|A||x|`、`γ_k=k·u/(1−k·u)`、`u`=fp64 unit roundoff、**C=8** |
| 3 | `_scientific_score` 正規化 | `s = min(geomean_speedup / TARGET, 1.0)`、**TARGET=4.0×** |
| 4 | invalid-family 規則 | 必須 family を1つでも落とせば node-invalid（geomean に 0 を混ぜない） |
| 5 | N（best valid @ N nodes） | **10** |
| 6 | failure codebook | COMPILE{syntax,linker,header} / CORRECTNESS{eps_exceeded,nan} / PROTOCOL{frozen_checksum} / TIMEOUT / NOOP_STERILE / PARENT_OUTPUT_MISUSE |
| 7 | primary 対比（単一） | **code_plus_summary vs code_plus_full_log**（SpMM・large モデル・deterministic selector） |
| 8 | 仮説の向き | H-B: failure/concern 系が支配・next_steps 寄与せず／H-C: 分岐で extractive-failure-summary > masking 単独／H-D（FORM×capability 交差）: large=masking 十分・small=failure-summary 必須 |
| 9 | モデル水準 | 主＝ローカル qwen3 dense **8B / 14B / 32B**（同一ファミリ）、large=32B が MVP。frontier API は robustness 1本 |
| 10 | 統計 | 単位=run（1木=1スカラ）、**n≥10/cell**、run クラスタ bootstrap、parity は TOST（**margin=log(1.05)**）、多重性 Holm |
| 11 | 固定定数 | seed kernel＋最適化フラグ（全アーム同一・checksum）、timing **W=3 warmup / R=10 reps（median）**、`OMP_NUM_THREADS` 固定、turbo off、単一アーキ |

## pilot ゲート（confirmatory 前に確認）
- (a) qwen3:8b が SpMM で validity を非ゼロで超えるか（床打ちなら small を 14B に上げる）。
- (b) 最大サイズ（32B）が GPU 経路に載るか。
- (c) deterministic selector が非ゼロ `_scientific_score` を消費するか（B2 land 後）。
