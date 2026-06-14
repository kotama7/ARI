# Plan — B2b SpMM kernel fixtures + compile/run/timing runner

Status: 実装計画（一部 land 済、compile/run/timing は実機検証待ち）。Origin: 2026-06 handoff study。
親計画: [`../../../MASTER_PLAN_handoff_impl.md`](../../../MASTER_PLAN_handoff_impl.md)、研究計画 [`../../../PLAN_artifact_summary_handoff.md`](../../../PLAN_artifact_summary_handoff.md) §6.2、[`../Plan.md`](../Plan.md)（evaluator B2）。

## 依存関係（他 Plan.md）
- 上流依存: [`../Plan.md`](../Plan.md)（B2: deterministic evaluator が `measure_node` を呼ぶ）。
- 関連: oracle/ε/matrix/aggregation の純 Python は `../spmm_harness.py`（land 済・login テスト済）。

## 削除要件
`_default_run_kernel`（compile/run/timing）が **実機 compute node で検証**され、`measure_node` が実速度を返すことを確認し、MASTER 完了ログに記録された時点で本 Plan.md を削除する。

## 構成
- `spmm_kernel.h` — `spmm()` の契約（agent が保つ署名）。
- `spmm_main.c`（FROZEN）— I/O＋warmup/timed-reps＋median timer。agent 編集禁止（checksum）。
- `baseline_spmm.c`（FROZEN）— 1x baseline（naive・単一スレッド）。
- `candidate_spmm.c`（TEMPLATE）— agent が最適化する `spmm()`。初期は baseline 同等（valid start）。node ごとに work_dir へ複製。
- `Makefile` — 手動ビルド（runner は gcc 直叩きで同一フラグ）。

## 状態
- **login 検証可・済**: baseline の compile+run+正解性（`reference_spmm` 一致）を `tests/test_spmm_harness.py` のコンパイル smoke（コンパイラ無ければ skip）で確認。
- **実機 compute node 必須**: timing の代表性（W3/R10 median）、OpenMP スケーリング、candidate の実速度。リポジトリ規約によりログインの timing は非代表。

## 検証ゲート（実機）
compute node で baseline/candidate を compile→run し、(i) Y が fp64 reference と ε 内で一致、(ii) timing が安定（分散小）、(iii) candidate 最適化で speedup>1 が観測されることを確認。
