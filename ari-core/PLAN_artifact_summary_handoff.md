# PLAN: What Should Branching LLM Code Agents Inherit? — Artifact / History Handoff の統制研究

Status: 研究計画（design 段階・未実装）。Origin: 2026-06 設計議論＋コードベース監査＋関連研究調査。
削除条件: Phase A〜C（MVP pilot まで）完了し、結果が論文ドラフトまたは後継 PLAN に転記された時点で本ファイルを削除する。
実装マスター: [`MASTER_PLAN_handoff_impl.md`](MASTER_PLAN_handoff_impl.md)（how/order と subtask Plan.md 索引）。
英語題目: **What Should Branching LLM Code Agents Inherit? A Controlled Study of Artifact and History Handoff**

---

## 0. 実装現状（監査済, paths=`ari-core/ari/`）

以降は本検証を前提に読む。**0.2 は論文の前に必ず塞ぐ穴**で、塞がない限り統制比較は成立しない。各項目の実装計画は [`MASTER_PLAN_handoff_impl.md`](MASTER_PLAN_handoff_impl.md) と各 dir の `Plan.md` を参照。

### 0.1 流用可能な土台（検証済）
| 前提 | 実装 |
|---|---|
| per-node work_dir = `experiments/{run_id}/{node_id}/` | `paths.py:175-181`, `cli/bfts_loop.py:373-381` |
| 親→子 code 継承＋結果除外（2段） | `_OUTPUT_BLACKLIST`＋`is_meta_file()`, `cli/bfts_loop.py:398-445` |
| node_report.json（31 prop） | `orchestrator/node_report/builder.py:551-586` |
| cost_trace.jsonl（per-call node_id+prompt_tokens） | `cost_tracker.py` |
| 評価信号 `node.metrics["_scientific_score"]` | `orchestrator/bfts.py:336` 他、生成 `evaluator/llm_evaluator.py:662,713` |
| ancestor-scoped memory（Tier-1b/2） | `agent/loop.py:295-353`, scope 強制 `in_memory.py:101-106` |
| ローカル backend 既定（ollama, qwen3:8b/32b） | `config/__init__.py:581-582` |

### 0.2 先に塞ぐ食い違い（＝統制比較の前提条件）
1. **B1 第3 handoff 経路**: Tier-1a（`loop.py:193-216`）＋Tier-1c（metric-contract obligation＋`build_coverage_status`, `loop.py:218-290`）が ancestor ガード（`loop.py:292`）より前で無条件発火、`_PINNED_USER_MARKERS`（`loop.py:766-775`）で window を生存。塞がないと全アームが operational state を共有。→ [`ari/agent/Plan.md`](ari/agent/Plan.md)。
2. **B2 evaluator が選択を回せない**: `node.metrics = eval_result["metrics"]`（`loop.py:1461`）で `metrics._scientific_score` 不在なら全ノード 0.0。evaluator は `core.py:195` ハードコード、loop は Protocol 外 `evaluate_sync`。→ [`ari/evaluator/Plan.md`](ari/evaluator/Plan.md)。
3. **B3 契約が LLM 自己決定・run/model 依存**: `make_metric_spec`（core/pinned ツール, `workflow.py:172`/`loop.py:719`）が evaluator の metric_spec を実行時に上書き（`loop.py:1162-1196`）し、per-run 契約を `metric_contract.json` に書き Tier-1c で全子孫に注入。契約が条件ごとに変わると capability×handoff が capability×自己生成契約品質と交絡。→ 固定契約の外生化が必須。[`ari/agent/Plan.md`](ari/agent/Plan.md)。
4. **sterile-gate の意味反転**: `compute_files_changed(parent,child)` 無条件 clamp（`cli/bfts_loop.py:631-656`）。copy-OFF では子 dir 空→全 deleted→sterile にならない。→ [`ari/cli/Plan.md`](ari/cli/Plan.md)。
5. **timeout dead code**（`cli/bfts_loop.py:532-541`）／**full_log overflow 検出なし**で窓圧縮が黙って truncated 化（`loop.py:725,803-804`）。→ [`ari/cli/Plan.md`](ari/cli/Plan.md)。
6. **バックエンド非決定性**: seed 不渡し（`client.py:180`）、gpt-5* は temp drop（`client.py:130`）。ローカルは seed plumb で再現性が立つ。→ [`ari/llm/Plan.md`](ari/llm/Plan.md)。
7. 既存 fixture は全 SpMM（Y=AX）。タスクは Stage 0 で確定。
8. harness が gitignore 全体無視（`.gitignore:31-37`）→ force-negate 必須。→ [`../scripts/Plan.md`](../scripts/Plan.md)。
9. `search_trace.jsonl` 不在／`memory_access.jsonl` は取得テキスト非記録。

### 0.3 de-facto handoff（出発点）
ARI 既定は code（workdir copy）＋ planner 側 summary（`bfts.py:64-108`）＋ memory 側（Tier-1a/1b/1c/2）の混合。本研究はこれを制御可能な handoff policy に分解・統制比較する。

---

## 1. 中心的問い
分岐型 LLM コード生成で**子ノードが親から何を継承すべきか**。「code/summary/両方」の3択は自明（both 最良）かつ単一 trajectory で実質既出のため貢献ではない。貢献は1段深い粒度——summary の**どのフィールド**を**どの形式**で継承すれば必要十分か、その結論が**分岐継承で・モデル能力を超えて転移するか**——に置く。最も強い結末は「**最適な継承法は条件（capability/task/depth）で食い違う**」という contingency の発見であり、本研究はそれを confirmatory に検出する設計にする。

## 2. 新規性の位置づけ（RQ-A は scaffold、RQ-B/C/D が貢献）
| 先行研究 | 何をしたか | 本研究が埋める白地 |
|---|---|---|
| AIDE(2502.13138)/AI-Scientist-v2(2504.08066) | 分岐探索＋親→子に code＋単一サマリ Σ(T) | summary を固定し中身を割らない、retrieval/非親 reach 無し |
| Lindenbauer "Complexity Trap"(2508.21433) | raw/masking/summary 統制比較・masking≈summary（**単一 trajectory**） | 分岐/cross-node・モデル能力への転移は未検証 |
| MEMOIR(2605.17539, 並行) | tree-search の階層 memory ablation | 別ドメイン(組合せ最適化)・tier 有無を ablate（field 別でない）・surface 非対象 |
| AWM(2409.07429)/MemGPT/Context-Eng survey(2507.13334) | agent-memory の枠を所有 | content 固定で surface/topology/capability を振る統制は無し |

差別化（1文）: 先行研究は handoff サマリを固定し単一 run・単一モデルで文脈圧縮を比較したに留まる。本研究は **artifact と history チャネルを分離**し、**history の content を field 別に ablate** し、**masking≈summary が分岐継承で・モデル能力を超えて転移するか**を、LLM-judge を排した決定論評価で測る初の統制研究。⚠「分岐型 agent memory を統制した初」は MEMOIR が先取り済みのため主張しない。

## 3. handoff の分解
- **artifact チャネル**（唯一直交）: 親 code を work_dir で継承するか否か。
- **history チャネル**: **FORM**（none→masked→truncated→extractive-summary→rolling、上限 full-trace）× **CONTENT**（field 別: delta_vs_parent/changed_files/concerns/next_steps/**known_failures**(導出)/key_metrics）× **SURFACE**（in-prompt push / memory-retrieval pull）。
- **memory の扱い（確定）**: 第5チャネルにも headline にもしない。(i) RQ-A/B では off に統制すべき confound（B1）。(ii) RQ-C 配下に従属ノブ＝inheritance TOPOLOGY（parent-only vs full-ancestor、content 固定。`loop.py:301`＋`in_memory.py:103`、ARI 固有・未所有）。

## 4. 比較アーム
code_only / summary_only / code+summary / code+masked / code+full_trace / code+truncated / code+rolling / **aide_journal**(Σ 相当 baseline) ／ **+CONTENT ablation**（summary −1 field ずつ＝RQ-B）／ **+TOPOLOGY ノブ**（RQ-C 従属）。上記を **model_size∈{small,large（同一ファミリ; 勾配なら 8/14/32 等）}** で交差（RQ-D）。

## 5. Research Questions
- **RQ-A（scaffold・貢献ではない）**: artifact と history のどちらが必要か。clean 比較の土台。
- **RQ-B（primary・本命）**: history summary の**どの field** が効くか。**H-B: failure/concern 系が支配的で next_steps は寄与しない。**
- **RQ-C（differentiator）**: masking≈summary は分岐継承で転移するか。**H-C: 単一 trajectory では masking で足りるが、分岐では失敗情報が直近窓外に落ち extractive-failure-summary が masking 単独より有意に優る。**
- **RQ-D（capability × handoff・新規）**: handoff の価値はモデル能力に依存するか。**H-D（FORM×capability 交差）: large は masking で足り small は failure-summary が必須**（RQ-C と接続）。勾配≥3点で「形（閾値/順位反転）」を検出。
- sanity（格下げ・非 headline）: S1 code+summary は code+full_trace と parity（TOST）。S2 注入トークン分離計測の上で削減確認。

## 6. タスク・測定器・モデル
- **6.1 タスク**: SpMV(y=Ax) か SpMM(Y=AX) を Stage 0 で確定（既存 fixture は全 SpMM）。
- **6.2 deterministic evaluator が測定器を独占所有**: oracle（fp64 参照解）＋ε（行ごと `C·γ_{nnz}·Σ|A||x|`）＋timing（warmup/reps median＋分散, pin, freq, OMP, NUMA）＋checksum 固定 baseline＋anti-gaming（matrix/timing/baseline/correctness 独占, correctness 用 x は call 時供給）＋geomean 集計＋hardware fingerprint。→ [`ari/evaluator/Plan.md`](ari/evaluator/Plan.md)。
- **6.3 モデル**: 主バックボーン＝ローカル qwen3（small/large、seed・temp 固定・digest pin）で確認的 run を高 n・無コスト・再現可能に。frontier API は robustness 1本。Stage 0 で qwen3:8b の validity floor を pilot。→ [`ari/llm/Plan.md`](ari/llm/Plan.md)。

## 7. 実験計画と統計
事前登録（Stage 0 で凍結）: ε・C／`_scientific_score` 正規化／invalid floor／N／failure codebook／単一 primary 対比／H-B・H-C・H-D の向き／model 水準。単位＝run（1木＝1スカラ）。run 単位 cluster bootstrap、speedup は log 領域、parity は TOST＋事前マージン、多重性 Holm/BH。selector は deterministic 固定（G9a）。注入トークンを per-node prompt_tokens と分離計測。RQ-D は**交互作用基準の検出力**で順位反転を検定。summary 忠実性（導出 known_failures vs evaluator failure_signature）で「表現の差」と「生成品質の差」を分離。

## 8. 実装計画
クリティカルパス（Stage 0-5）・依存 DAG・subtask 索引・MVP カットは [`MASTER_PLAN_handoff_impl.md`](MASTER_PLAN_handoff_impl.md) に集約。背骨は **B2 → B3 → B1**。各 subtask は該当 dir の `Plan.md` 参照。

## 9. スコープとフェーズ
- Phase A（MVP/workshop）: 3 アーム×1 タスク×ローカル large×deterministic selector、事前登録、run 単位 n≥~8–10、cluster bootstrap、scrub＋gitignore negation。
- Phase B: RQ-B（field 別）＋ masked/aide_journal（RQ-C）＋ dosage sweep。
- Phase C: RQ-D（small/large 勾配）＋ topology ノブ＋ frontier robustness＋追加タスク（SE タスク or MLSys 判断）。
- 各 Phase 入口で cost go/no-go（ローカル主体で大幅緩和）。

## 10. Threats to Validity
internal: B1 第3経路／sterile 非対称／dead timeout／selector 確率性／full_log overflow 自壊／side-channel／GPU 残留非決定性。construct: 主指標は handoff 質か selection 運か（selection-invariant 指標併報）／summary 忠実性交絡／starting kernel 交絡（全アーム同一・事前登録）／capability 操作が規模のみか（同一ファミリで担保）。external: 単一カーネル・単一言語(C/OpenMP)・主にローカル qwen3（→ frontier アームで補強）。

## 11. 再現性・アーティファクト・データ管理
固定 commit／per-call の model digest/temp/seed 記録／frozen-trace から図表再生成／harness tracked（force-negate）／SuiteSparse は name＋group＋SHA256＋snapshot 日付 pin／生成 native code の sandbox/timeout／**収集時の機械情報スクラブ**（tracked artifact・図・commit に機械情報を一切入れない）／GB 級 trace の保管。→ [`../scripts/Plan.md`](../scripts/Plan.md)。

## 12. リスクと対策
最大リスク（cost×検出力）→ ローカル主バックボーンで緩和。新リスク＝small の capability floor → Stage 0 pilot。新規性が弱い/3択縮退 → §2 差別化＋RQ-B/C/D を主役＋contingency（条件で食い違う）を背骨に＋aide_journal baseline。null → H-B/H-C/H-D を向き付き事前登録で informative に。venue → SE タスク追加 or MLSys 明確化。

## 13. 投稿戦略
初期: DL4C / MLSys・ASE workshop（Phase A）。本会議: MLSys（context 効率＋capability 軸）または ASE/ICSE（要 SE タスク追加）。冒頭で AIDE・AI-Scientist-v2・Lindenbauer・MEMOIR(並行) を引き、「summary を発明したのでなく、何を・どの形式で継承すべきかを field 粒度で初めて統制分離し、分岐継承とモデル能力をまたぐ転移（および条件依存性）を検証した」と位置づける。
