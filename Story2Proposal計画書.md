# Story2Proposal の原理を ARI に写像する統合計画書

### Story2Proposal-Inspired Architectural Integration Plan for ARI（統合版 / 第9版・検証境界 caveat + late-bind/生成方針の確定）

ステータス: 実装着手済み — Phase A/A2/B/C/D/E のコード＋単体テスト完了、`config/workflow.yaml` のトポロジは**検証済み依存順に back-port 済み**（…→review/semantic→merge→refine→render→final gate→finalize、`finalize_paper`→final gate 依存、`merge_reviews` へ hard_gate/semantic パス、file順依存違反ゼロ＝有効化は `enabled` 反転＋`ARI_CLAIM_GATE_MODE` のみ）、恒久仕様は各ディレクトリの `REQUIREMENTS.md` に反映済み。**Step 13（実機 e2e 通し）2026-06-05 完了**（checkpoint `20260528180541_…CSR-form`、`numeric_coverage_rate=1.0`/`mismatch=0`/`reproducible=1.0`、login node・`warn` mode、`ari-core/REQUIREMENTS.md` の Status に記録）。**Step 14（hard gate↔semantic review↔ORS 関係）確認済み**（同 REQUIREMENTS「Evaluation-mechanism relationship」）。**strict(blocking) path 検証済み**（2026-06-05、同 checkpoint・`write=False`：clean→非ブロック／数値改ざん→`numeric_mismatch`→`should_block=True`→wrapper `{"error"}`→finalize skip、`REQUIREMENTS.md` Status＋回帰テスト `test_s2p_tools.py`）。**§10 評価実験（Condition A–D / Ablation 1–6 ＋ overclaim 人手スポットチェック）は意図的スキップ**（2026-06-05 決定）— 統合の効果を定量化する比較“研究評価”であり正しさの要件ではない（機構は Phase A–E 実装・Step 13 通し・strict 検証で確立済み）。削除要件の規定に従い `ari-core/REQUIREMENTS.md` の Status に skip 理由を記録済み。経験的 ORS×gate 比較も同種の研究評価で、明示要望が無い限り対象外。**有効化判断（2026-06-05 決定）: S2P 9ステージを既定 ON（warn mode）に有効化**（`config/workflow.yaml`、gate は報告のみで finalize を止めない。strict は `claim_gate_policy.mode: strict`／`ARI_CLAIM_GATE_MODE=strict` で随時。e2e は全24ツール列を検証）。**残るは最終クリーンアップのみ**（子計画＋本マスターの削除、`experiments/` の gitignore 成果物の扱い）。本書は**マスター統合計画**。実装はタスク別子計画に細分化済み（下記）。

> **削除要件（必読）**: 本マスター計画は、配下のタスク別子計画が**全て削除条件を満たして削除され、恒久仕様が各ディレクトリの `REQUIREMENTS.md` と関連 docs に反映された時点で、完了を記録する同じ PR で削除**する。証拠ゲートで不要と判断した範囲は「未実装・意図的スキップ」として該当 `REQUIREMENTS.md` に1行残してから削除する。**部分完了では削除しない。**（リポジトリ慣習:「完了記録と同 PR で要件/計画ファイル削除」に準拠。`PLAN_memory_inheritance.md` と同方式。）
>
> タスク別子計画（対応ディレクトリ）:
> - `ari-skill-transform/PLAN_s2p_science_data_claims.md` — Phase A / A2(生成): science_data.json の claims / numeric_assertions
> - `ari-skill-paper/PLAN_s2p_claim_annotation.md` — Phase A2(writer/後処理): % CLAIM 注釈 / paper_claim_links / figure late-bind
> - `ari-core/PLAN_s2p_hard_gate.md` — Phase B / B2 / B3: claim_evidence_hard_gate（数値再計算 / coverage / policy）
> - `ari-skill-evaluator/PLAN_s2p_semantic_review.md` — Phase D: evidence_grounded_semantic_review
> - `ari-core/PLAN_s2p_merge_refine.md` — Phase E: merge_reviews 分離 + paper_refine 配線 + finalize 依存
> - `ari-core/PLAN_s2p_hypothesis_ledger.md` — Phase C: hypothesis 台帳の要否判定（調査）
> - `experiments/PLAN_s2p_evaluation.md` — §10: 評価設計（Condition A–D / 指標 / Ablation）

---

## 0. この計画書の位置づけ（統合の定義）

本書は、Story2Proposal（arXiv:2603.27065, *A Scaffold for Structured Scientific Paper Writing*）を **ARI に統合する**ための計画書である。ただし本書でいう「統合」とは、Story2Proposal のシステム（visual contract の内部実装や architect/writer/refiner/renderer の4 agent 構成）を**逐語移植すること**ではない。

**統合の定義（architectural integration）**：本書でいう統合は code-level integration ではなく **architectural integration** である。すなわち Story2Proposal の codebase や visual-contract schema を移植するのではなく、その contract-governed generation principle・evaluation axes・generate–evaluate–adapt loop を ARI の既存 execution-grounded substrate に**写像（map）**する。

> Here, integration means **architectural integration** rather than code-level integration: we do not port Story2Proposal's implementation or visual-contract schema, but map its contract-governed generation principle, evaluation axes, and generate–evaluate–adapt loop onto ARI's execution-grounded substrate.

本書が統合する対象は、Story2Proposal の **2つの転用可能な貢献**である。

```text
統合する対象:
  ① contract-governed generation の原理
  ② generate–evaluate–adapt loop と3評価軸
     （reasoning verification / data fidelity / visual coherence）
```

### 0.0 Research Contract substrate の選定（第7版での確定 / 重要）

第6版までは「Research Contract = EAR を再フレーミング」としていたが、実コード確認の結果これは誤りであった。実 EAR は次の性質を持つ。

```text
- EAR は構造化 JSON オブジェクトではなく、ディレクトリツリー（ファイル束）:
  ear/{code/, data/, figures/, README.md, reproduce.sh, environment.json}。型付きスキーマ無し。
- figures は「ディレクトリ」、results は README.md の散文で、claim が参照できる安定 id を持たない。
- そして決定的に、write_paper は EAR を読まない（後述 §3）。EAR は論文執筆後に publish される archive。
```

したがって claim を EAR に置いても **writer の目に入らず、contract-governed generation が成立しない**。本第7版では Research Contract の substrate を次のように確定する。

```text
Research Contract substrate = science_data.json（writer が実際に消費する構造化 evidence object）
                              + node_report.json / results.json（実行 provenance：安定 id と数値）
EAR                          = 従来どおり「published artifact bundle」として据え置く（contract ではない）。
```

`claims[]` / `numeric_assertions[]` は **science_data.json に追加**し、`supported_by` / `operands` は安定 id を持つ既存物（`tree.json`/`node_report.json` の node.id、`figures_manifest.json` の figure id、`results.json` の measurement）を参照する。

ただし science_data.json の configuration は node_id / per-result id を**意図的に剥がす**（paper-facing）ため、claim は configuration に依拠せず**実 node_id を claim 自身へ直書き**する（生成器は transform_data 時点で node_id を保持している）。result は `(node_id, metric_path)` と定義する。figure 参照は generate_figures 後に生成されるため **late-bind** する。claim / numeric_assertion は science_data の**決定論部分**（`configurations.metrics` / `results.json`）にのみ接地し、LLM 生成の `experiment_context` / `implementation_overview` には依拠しない（再現性のため）。

### 0.1 統合スコープ（採用・適応・非移植の明確化）

| Story2Proposal の要素 | ARI への統合形態 | 区分 |
|---|---|---|
| contract-governed generation の原理 | **science_data.json を Research Contract substrate** として再フレーミング（EAR ではない） | **採用(原理)** |
| 共有 contract が claim/evidence を統治 | science_data.json に `claims[]` / `numeric_assertions[]` を追加 | **適応** |
| 評価軸 data fidelity → **execution data fidelity** に再定義 | 決定論的 hard gate（数値再計算・artifact 実在・未登録数値検出） | **適応(実行接地)** |
| 評価軸 reasoning verification | evidence-grounded semantic review（非ブロッキング） | **適応(実行接地)** |
| 評価軸 visual coherence | hard gate（figure 参照・source_data 実在）+ semantic review（caption 意味整合） | **適応** |
| generate–evaluate–adapt loop | write_paper → gate/review → paper_refine → 最終 gate → finalize | **採用(ループ)** |
| shared visual contract の内部実装（visual registry/obligations の固有構造） | 移植しない（ARI の science_data.json + figures_manifest.json が visual registry / source_data / figure reference の **execution-grounded counterpart** として対応。section obligation 機構の完全再現ではない） | **非移植** |
| architect/writer/refiner/renderer の4 agent 構成 | 移植しない（ARI は BFTS 木探索 + multi-stage pipeline で代替） | **非移植** |

「非移植」とした2要素は、ARI 側に**対応する execution-grounded の受け皿**（science_data.json + figures_manifest.json、BFTS + pipeline）が既存であるため、原理の統合先として ARI 側の実体を使う。これは「同等機能」の主張でも Story2Proposal の拒否でもなく、**原理を ARI の execution-grounded アーキテクチャに写像する**という統合方針の帰結である。

### 0.2 統合によって ARI が得る新規性

```text
Story2Proposal は evidence を与件として contract 統治するが、ARI は evidence を実行して生成する。
統合の結果、ARI は contract-governed generation を「実行に接地した provenance」へ拡張する:
  claim を、実行された commands / logs / measured results / artifacts / hardware metadata に接地し、
  数値を results.json から決定論的に再計算して検証する（既存 ARI にゼロの能力）。
```

---

## 1. 目的

Story2Proposal の contract-governed generation と評価ループを ARI に統合し、ARI の研究遂行を **execution-grounded provenance** で統治する。

```text
Story2Proposal:
research story（narrative + 与件の experimental evidence）
→ shared visual contract（section 構造・図表 registry・validation rules）
→ structured manuscript

ARI（統合後）:
research idea
→ code generation / experiment planning
→ 実機（HPC）実行で evidence を生成
→ node_report / results provenance（実行コマンド・ログ・artifact・SHA・hardware・executor）
→ science_data.json = Research Contract substrate（+ claims / numeric_assertions）
→ contract-governed paper generation
→ hard gate + evidence-grounded review（generate–evaluate–adapt）
→ paper / EAR publish / reproducibility grade
```

中心命題：

```text
Story2Proposal の contract-governed generation を、与件 evidence ではなく
ARI が実行して生成する evidence の上に統合する。
```

---

## 2. 統合元（Story2Proposal）の確定事実（PDF 読解済み）

| 項目 | 原論文の記述 |
|---|---|
| 名称 | shared visual contract |
| agent 構成 | architect / writer / refiner / renderer + evaluation agents |
| contract の中心 | section structure, global visual registry, section obligations, validation rules |
| 生成過程 | architect → writer → refiner → renderer、および generate–evaluate–adapt loop |
| 評価軸 | reasoning verification / data fidelity / visual coherence |
| 入力 | research story = narrative + context + experimental evidence。evidence は与件であり、実験は実行しない |
| 比較対象 | DirectChat / Fars |
| 主要結果 | vs DirectChat 6.145 / 3.963（+2.182）、vs Fars 5.705 / 5.197（+0.508） |
| 限界 | ablation study がないこと、入力 research story の質に依存すること |
| ベンチ論文 | Escrowed Batch Reveal / Symbolic Execution / Hazard-Signature Tombstones / Poisoning LLM-Induced Rules（非 HPC） |

### 2.1 統合時の誤記防止

Story2Proposal は intro / related work で、以下に近い問題意識をすでに主張している。

```text
- claim-experiment misalignment
- shared claim-evidence maps
- provenance tracking
- manuscript-level consistency
```

したがって、統合の新規性を次のように書いてはならない。

```text
× ARI newly introduces claim-evidence alignment.
× ARI newly introduces provenance tracking.
× ARI simply implements or extends Story2Proposal.
```

統合の差分は、以下に限定する。

```text
○ ARI integrates Story2Proposal's contract-governed generation and evaluation axes into an
   execution-grounded pipeline.
○ ARI grounds claim-evidence alignment in executed computational artifacts.
○ ARI extends manuscript-level provenance to execution-grounded provenance.
```

---

## 3. 統合先（ARI 既存機構）— 統合の substrate と、EAR の実態

### 3.1 provenance / artifact 系（安定 id と数値の供給源）

| 要素 | ARI の既存実装 | 想定場所 |
|---|---|---|
| artifact 登録 / provenance / SHA | `node_report.json`（`files_changed` + SHA256、`artifacts[role]`、hardware、executor、`node_id`） | `ari-core/ari/schemas/node_report.schema.json`, `ari-core/ari/orchestrator/node_report/builder.py` |
| result / metrics | `node.metrics`, `results.json`（`params`/`measurements`/`predictions`/`scores`） | `ari-core/ari/orchestrator/node.py`, `ari-core/ari/checkpoint.py`, `ari-skill-coding/src/server.py`（`emit_results`） |
| node tree（安定 node id） | `tree.json`（`node.id` / metrics / lineage） | `ari-core/ari/checkpoint.py`, `ari-core/ari/orchestrator/node.py` |
| **science data（Research Contract substrate）** | nodes → `science_data.json`（per-configuration の params + measurements）。**writer が消費する** | `ari-skill-transform/src/server.py`（`nodes_to_science_data`） |
| figures（安定 figure id） | `figures_manifest.json`（`{figures: [{id, path, latex_snippet}]}`）。**writer が消費する** | figure 生成ステージ |
| evidence bundle（公開用） | EAR：`ear/{code/, data/, figures/, README.md, reproduce.sh, environment.json}` の**ディレクトリ束** | `generate_ear` / `ear_curate` / `ear_publish`（`ari-skill-transform`） |
| artifact-grounded 再現検証 | `ors_*`: rubric 生成 → sandbox seed → replicator → run → SimpleJudge grade | `ari-core/config/workflow.yaml`, `ari-core/ari/viz/api_paperbench.py` |

### 3.2 評価系の実態（評価軸の統合先）

| 既存ステージ／機構 | 実際の挙動 | 統合での役割 |
|---|---|---|
| `review_paper` | 静的 YAML rubric、text-only。VLM findings、experiment_summary、figures manifest を注入しない。非ブロッキング | 独立査読として維持（evidence を混ぜない）。S2P 評価軸は別系統で統合 |
| `vlm_review_figures` | 図画像のみを VLM 評価。図↔本文整合・caption 妥当性・source_data 実在は見ない。ブロッキング | image 品質は既存。visual coherence の構造部分は hard gate で補う |
| dynamic-axes LLM evaluator | operand は実験ノード metrics であり paper draft ではない | paper 評価をここに直接足さない |
| 数値照合 | paper の値 vs results.json / CSV の照合は既存にない | S2P の data fidelity を実行接地で統合する地点 |

### 3.3 EAR の実態（contract に使えない理由 / 確認済み）

| 確認項目 | 実態 | 影響 |
|---|---|---|
| EAR の形 | 構造化 JSON ではなく**ディレクトリ束**。型付きスキーマ無し | claims[] を自然に足せる対象ではない |
| EAR の figures/results | `figures/` は dir、results は README.md 散文。**安定 id 無し** | claim の参照先にできない |
| **write_paper の入力** | `tree.json` / `science_data.json` / `related_refs.json` / `figures_manifest.json`。**EAR は読まない** | **claim は EAR でなく science_data.json に置く必要がある** |
| EAR の生成時点 | 論文執筆後に curate/publish される archive | contract（生成統治）ではなく成果物バンドル |
| `results.json` の粒度 | 集計済みスカラーのみ。per-trial 生値は保持されない | 数値照合 MVP は formula-level に限定（§Phase B2） |
| `write_paper_iterative` | ARI ネイティブ。テンプレ穴埋めの単一 LLM 呼び出し | claim-id 注釈は実現可能だが付け漏れ前提 → 後処理検証（§Phase A2） |
| science_data.json の configuration | node_id / per-result id を**意図的に剥がす**（paper-facing）。rank/label しか持たない | claim は configuration に依拠せず、実 node_id を claim へ直書き（§Phase A） |
| science_data.json の生成種別 | configurations/summary は決定論、experiment_context/implementation_overview は **LLM 生成** | claim は決定論部分にのみ接地（再現性） |
| pipeline 順序 | `transform_data → generate_figures → write_paper`。figure id は transform_data 後に生成 | claim の figure 参照は generate_figures 後に **late-bind**（§Phase A2） |

### 3.4 パイプライン topology（統合後）

```text
transform_data（science_data.json 生成 + candidate claims/numeric_assertions を draft 登録）
  ▼
write_paper（science_data.json の claims を参照、% CLAIM:Cx:NCx anchor 付きで生成）
  ├── finalize_paper      (depends_on: write_paper, ..., claim_evidence_hard_gate[最終])
  └── review_paper        (depends_on: write_paper)

vlm_review_figures        (depends_on: generate_figures, loop_back→generate_figures)
merge_reviews             (depends_on: review_paper, vlm_review_figures, evidence_grounded_semantic_review)
ear_curate / ear_publish  (論文確定後：公開バンドル化)
ors_*                     (後段：再現 grade)
```

blocking 変更は `claim_evidence_hard_gate` の追加1点に限定する。refine が走る場合、finalize が依存するのは refine 後 paper に対する hard gate とする。

---

## 4. 統合の差分（実装対象）

```text
Story2Proposal の contract:
  与えられた research story の内部で story field ↔ manuscript section を結ぶ。実験は実行しない。

ARI への統合:
  evidence が実際に実行されて生成される。
  idea → code → 実機（HPC）実行 → 計測ログ / artifact / node_report / results → science_data → claim
  まで provenance を閉じ、contract-governed generation を execution-grounded に拡張する。
```

統合のために ARI へ追加する実装対象：

1. **science_data.json を Research Contract substrate 化** — `claims[]` と `numeric_assertions[]` を追加（EAR ではない）。
2. **claim↔evidence の決定論的 hard gate** — 登録済み照合 + numeric coverage（未登録数値検出）。S2P の data fidelity / structural validation の統合（execution data fidelity に再定義）。
3. **数値照合（formula-level, MVP）** — `node_id` + `metric_path` で operand 解決（results.json）。
4. **evidence-grounded semantic review** — S2P の reasoning / visual coherence(意味) の統合。非ブロッキング。
5. **hypothesis 台帳の要否判定** — `active_idea` 履歴で代替できるか先に確認。

artifacts / results / figures / environment / reproducibility は既存機構を使用し、新規実装しない。EAR の役割（公開バンドル）も変えない。

---

## 5. 統合アーキテクチャ

```text
transform_data
  │   （science_data.json を生成。candidate claims/numeric_assertions を draft 登録。claim に実 node_id 直書き、figure は generate_figures 後に late-bind、決定論部分にのみ接地）
  ▼
write_paper
  │   （Research Contract = science_data.json の claim を参照し、% CLAIM:Cx:NCx anchor 付きで本文生成）
  ▼
claim-id 後処理検証（paper_claim_links 確定・numeric mention 分類・未登録数値検出）
  ▼
claim_evidence_hard_gate  ← (1) 初回：draft に対する検証（S2P data fidelity の実行接地統合）
  │
  ├── review_paper                       （既存・独立・非ブロッキング、変更しない）
  └── evidence_grounded_semantic_review   （S2P reasoning / visual coherence の統合・非ブロッキング）
  ▼
merge_reviews（independent_reviews / evidence_grounded_reviews を分離、suggested_revisions を渡す）
  ▼
paper_refine（S2P refiner=グローバル整合役割／出力は差分編集／% CLAIM anchor を保持）
  ▼
render_paper（S2P renderer A_rend, eq.6：refine 後 .tex を PDF へ再コンパイル。非ブロッキング）
  ▼
claim-id 後処理検証（再）＋ claim_evidence_hard_gate  ← (2) 最終：refine 後 paper を再検証
  │   （errors があれば finalize をブロック）
  ▼
finalize_paper
  ▼
ear_curate / ear_publish（公開バンドル）→ ors_*（external reproducibility）
```

要点：

```text
- science_data.json を Research Contract substrate とし、Story2Proposal の contract 原理を統合する。
- EAR は公開バンドルとして据え置き、contract には使わない。
- shared visual contract の内部実装と4 agent 構成は移植しない（ARI 側の実体に統合する）。ただし refiner / renderer の**役割**は ARI に対応物を置く: refiner=`paper_refine`、renderer (A_rend, eq.6)=`render_paper`（refine 後 .tex を PDF へ再コンパイル。これが無いと配布 PDF が refine 前のまま stale になる—S2P は render を refine の後段に置く）。
- blocking gate は決定論的 hard gate のみ。S2P の semantic 評価は非ブロッキングで統合する。
- hard gate は refine の前後で実行し、finalize は refine 後の最終 gate に依存させる。
- **render_paper（S2P renderer A_rend）を refine の後段に置く**: refine が書く .tex を PDF へ再コンパイルし、配布 PDF が refine を反映するようにする（従来は write_paper の draft PDF が残り stale だった）。`paper_refine` のみに依存し hard gate でゲートしない（refine 成功時は常に最新 PDF を出す）。非ブロッキング（latexmk 失敗は前の PDF を残し finalize チェインを壊さない＝.tex を真実源とする方針を維持）。
- review_paper の独立性契約は維持する。
- paper_refine は S2P の refiner（eq.5 `(M',C)=A_ref({D_i},C)`）と同じ**グローバル整合役割**（cross-section の整合・冗長圧縮・用語統一）を担うが、**出力は全文再生成ではなくターゲット差分（find/replace 編集の JSON）**とする。S2P の refiner は「整える」限定タスクであり全文書き直しではない。全文再生成は CLI シム経由で生成量過多→タイムアウトを招くため、グローバル文脈（全文を入力で参照）は保ちつつ出力を変更スパンに限定する。差分は (i) find が一意、(ii) 編集スパン内の `% CLAIM` anchor を replace が逐語保持、の両条件を満たすもののみ決定論的に適用し、anchor 喪失や no-op 時は draft へ revert する。
```

---

## 6. hard gate / semantic review / ORS の関係

| 機構 | 役割 | 統合元（S2P）対応 | 性質 | 失敗時 |
|---|---|---|---|---|
| claim_evidence_hard_gate | 登録済み claim・数値・figure 参照が executed evidence と一致 + 未登録数値検出 | **execution data fidelity**（S2P data fidelity を実行接地に再定義）/ validation rules | deterministic | finalize をブロック（strict 時） |
| evidence_grounded_semantic_review | claim の言い過ぎ・解釈妥当性・caption 意味整合 | reasoning verification / visual coherence(意味) | LLM / non-blocking | paper_refine に修正提案 |
| review_paper | venue rubric による text-only 独立査読 | （S2P 外。ARI 既存） | independent review | 非ブロッキング |
| vlm_review_figures | 図画像の品質 | （visual coherence の画像部分に近い） | image review | ブロッキング |
| ORS | artifact から第三者的に再現 | （S2P 外。ARI 独自） | external reproducibility | 後段 grade |

```text
hard gate = internal consistency（生成済み evidence と paper の内部整合）
ORS       = external reproducibility（第三者 replicator が artifact から再現できるか）

注: hard gate の数値照合は「paper の数値 ↔ results.json の値」の転記・導出の整合性を検証するもので、
    results.json の値そのものの真偽（results ↔ 現実）は検証しない。後者は ORS（再実行）が担う。
    したがって "deterministic numeric verification" を「数値が真と検証済み」と過剰に読まないこと。
```

---

## 7. 実装計画

---

## Phase A: science_data.json を Research Contract substrate 化（claim 層追加）

### 追加構造（science_data.json に追加する）

```yaml
# science_data.json（既存 configurations[] 等に加えて）
claims:
  - id: C1
    text: "The proposed workflow reduces unsupported performance claims."
    section: "results"
    status: draft        # draft | supported | unsupported | rejected
    supported_by:
      nodes: [n12]          # 実 node_id を claim へ直書き（tree.json/node_report.json の安定 id）。rank/label に依拠しない
      results: [{ node_id: n12, metric_path: "measurements.runtime" }]   # result = (node_id, metric_path)
      figures: []           # figures_manifest.json の figure id。generate_figures 後に late-bind（draft 時は空）
      artifacts: ["ear/code/kernel.cu"]   # publish 後の bundle path（任意）
    numeric_assertions:
      - id: NC1
        text_span: "reduces unsupported claims by 23.5%"
        metric: "unsupported_claim_reduction"
        value: 23.5
        unit: "%"
        formula: "relative_reduction_percent"
        operands:
          baseline: { node_id: n_base, metric_path: "measurements.unsupported_claims" }
          proposed: { node_id: n_prop, metric_path: "measurements.unsupported_claims" }
        aggregation: { statistic: "mean", trials: 10 }   # MVP では記録のみ
        tolerance: { absolute: 0.2, relative: 0.01 }
    risk: "The evidence is based on a single benchmark."
```

### 方針

```text
- claims[] は EAR ではなく science_data.json に置く（writer が消費する唯一の構造化 evidence object）。
- 新スキーマ層（Pydantic 等）を導入しない。ARI 標準の dataclass + JSON Schema に合わせる。
- science_data.json の configuration は node_id を意図的に剥がす（paper-facing）。したがって configuration の
  rank/label には依拠せず、claim 自身に実 node_id を直書きする（生成器は transform_data 時点で node_id を保持）。
- supported_by.nodes / operands.node_id は tree.json / node_report.json の安定 node.id を直接持つ。
- result は opaque な R1 ではなく (node_id, metric_path) として定義する。
- supported_by.figures は figures_manifest.json の figure id を参照するが、figure は generate_figures 後にしか
  存在しないため late-bind する（transform_data の draft 時点では空）。
- claim / numeric_assertion は science_data の決定論部分（configurations.metrics / results.json）にのみ接地し、
  LLM 生成の experiment_context / implementation_overview には依拠しない（再現性のため）。
- numeric_assertions[] は hard gate による再計算の対象とする。
```

### 完了条件

```text
- science_data.json に claims[] / numeric_assertions[] を保存・読込できる。
- claim が安定 node_id を直接保持し、result = (node_id, metric_path) を解決でき、figure id は late-bind で付与できる。
- claim status を draft / supported / unsupported / rejected で管理できる。
- numeric_assertions[] に value / unit / formula / operands(node_id + metric_path) / tolerance を保存できる。
- write_paper が science_data.json 経由で claims を受け取れる（既に消費しているため追加配線は最小）。
```

---

## Phase A2: candidate claims の生成タイミングと claim-id 注釈

### 推奨 flow

```text
transform_data（nodes_to_science_data）
  → evidence から candidate claims を生成 → science_data.json の claims[] / numeric_assertions[] に draft 登録
  → claim に実 node_id を直書き（configuration には依拠しない）。result = (node_id, metric_path)
  → figure 参照はまだ存在しないため空（generate_figures 後に late-bind）
  → 接地先は決定論部分（configurations.metrics / results.json）のみ

write_paper（science_data.json を既に消費）
  → claims[] の id を参照しながら本文を書く
  → 数値 claim の行頭に anchor「% CLAIM:Cx:NCx」を注釈させる
  （必要なら claims_registry を experiment_summary 同様に展開して prompt に明示注入する）

claim-id 後処理検証（write_paper 直後・hard gate の前段。refine 後にも再実行）
  → anchor と claims[] の整合（実在 id か）
  → 数値トークン抽出 → 分類（numeric_mentions）→ numeric_assertions[] との対応付け
  → paper_claim_links（anchor / span_hash / line_range）を確定

claim_evidence_hard_gate → evidence_grounded_semantic_review
```

### 生成と束縛の方針（第9版で追加）

```text
- candidate claim / numeric_assertion の生成は LLM の draft 工程である（claim 文も提案数値も LLM 提案）。
  「決定論部分にのみ接地」とは claim が指す evidence の話であり、生成自体は LLM。
  → LLM が draft 提案 → hard gate が results.json に対し決定論的に検証、という役割分担。
- figure 束縛は claim-id 後処理検証（write_paper 後・figures_manifest 存在時）で paper_claim_links に記録する。
  transform 段の science_data.json は事後改変しない（出力の冪等性 / 再現性を壊さない）。
  science_data.json の claims[].figures は draft の空のまま据え置き、図リンクは paper_claim_links を正とする。
```

### numeric mention の分類

```yaml
numeric_mentions:
  - { value: 18.2, unit: "%", type: result_claim, requires_assertion: true }
  - { value: 10, unit: "trials", type: experimental_setting, requires_assertion: false, must_match_environment_or_method: true }
  - { value: 2024, type: citation_year, requires_assertion: false }
  - { value: 2, type: figure_table_ref, requires_assertion: false }
```

```text
- citation_year / figure_table_ref / equation 番号は decode 時のパターンで決定論的に除外する。
- experimental_setting は requires_assertion=false（method/environment 記述との整合は別途確認可能）。
- result_claim（speedup / improvement / reduction / 絶対値主張）は requires_assertion=true。
- 曖昧な数値は所属 section の policy（§Phase B3）に従ってデフォルトを決める。
```

### paper_claim_links（anchor 主キー）

```json
{
  "paper_claim_links": [
    {"claim_id": "C1", "numeric_id": "NC1", "section": "results",
     "anchor": "CLAIM:C1:NC1", "span_hash": "sha256-of-normalized-sentence", "line_range": [120, 122]}
  ]
}
```

```text
- 安定キーは anchor（inline の % CLAIM:Cx:NCx）。refine/renderer を越えて生き残らせる。
- span_hash は「正規化した文」のハッシュで、refine で文が変わったかの検出に使う（不変キーではない）。
- line_range は補助。行番号は整形で動くため主キーにしない。
- paper_refine には「% CLAIM anchor を保持せよ」を明示する。
- % CLAIM anchor は claim_evidence_hard_gate(最終) 完了まで保持する。camera-ready source から除去するかは
  venue policy に従う。除去する場合も paper_claim_links.json を provenance artifact として保存する。
```

---

## Phase B: claim↔evidence 決定論的 hard gate（execution data fidelity の統合）

### 接続

```text
- write_paper 直後に初回実行（draft 検証）。
- paper_refine 後に再実行（最終 paper 検証）。
- finalize_paper.depends_on += claim_evidence_hard_gate(最終)
- strict 時、errors があれば finalize_paper をブロックする。
```

### 入力

```text
- science_data.json（claims[] / numeric_assertions[]。supported_by/operands は実 node_id + metric_path を保持）
- paper_claim_links / numeric_mentions
- tree.json / node_report.json / results.json / CSV / metrics files
- figures_manifest.json / figures / source_data
- checkpoint files（artifact 実在確認。publish 後は ear_published/manifest.lock も参照可）
- paper draft（初回）または refined paper（最終）
- claim_gate_policy（§Phase B3）
```

### 決定論的検証項目

```text
[claim 実在性]
1. status: supported の claim に supported_by があるか。
2. supported_by の node.id / figure id が tree.json / node_report.json / figures_manifest.json に実在するか。
3. 参照 artifact path が checkpoint（または publish bundle）に存在するか。
4. supported claim が executed node に接続されているか。

[numeric claim 照合（formula-level, MVP）]
5. numeric_assertions[] の operands(node_id, metric_path) が node_report / results.json で解決でき、値が存在するか。
6. formula に基づき value を results.json / node_report の保存済みスカラーから再導出できるか。
7. 再導出値が tolerance 内で paper 記載値と一致するか。
8. baseline と proposed が同一 environment（node_report 一致）で比較されているか。

[numeric coverage ← 未登録数値のすり抜け防止]
9. section 帰属は LaTeX の \section{} / \begin{abstract} / \appendix を決定論的に parse して判定する。
   policy.target_sections の section から数値トークンを抽出し分類（numeric_mentions）。
   requires_assertion=true の数値で numeric_assertions[] / paper_claim_links に紐づかないものを検出。
   - strict section: error / warn section: warning / excluded: 対象外

[figure/table 実在（visual coherence の構造部分）]
10. paper で参照される Figure / Table が figures_manifest.json に登録されているか。
11. figure の source_data / 生成 script が存在するか。
12. 未参照 figure がないか。
```

### hard gate では扱わないもの（semantic review へ）

```text
- claim の意味的な言い過ぎ / 因果表現の妥当性 / caption と本文の意味的一貫性 / contribution の過剰一般化
（未登録「数値」は hard gate で検出。未登録「主張(非数値)」の意味判定は semantic review。）
```

### output

```json
{
  "gate": "claim_evidence_hard_gate", "phase": "final", "policy": "strict", "status": "failed",
  "errors": [
    {"claim_id": "C2", "type": "numeric_mismatch",
     "message": "Reported speedup is not reproducible from results.json.",
     "reported": 18.2, "recomputed": 14.7, "tolerance": 0.2},
    {"type": "uncovered_numeric", "section": "abstract", "value": 31.0, "classified_as": "result_claim",
     "message": "Numeric '31%' in abstract maps to no numeric_assertion."}
  ],
  "warnings": []
}
```

保存先：`workspace/checkpoints/<ts>_<slug>/evaluation/claim_evidence_hard_gate_{draft|final}.json`

---

## Phase B2: numeric claim schema と再計算 utility

### MVP（formula-level 照合）

```text
- operands(node_id, metric_path) を node_report / results.json で解決し、その値から式を再導出する。
  例: relative_speedup = baseline_mean / proposed_mean
- tolerance（absolute / relative）で paper 記載値と照合する。
- 既存 ARI にゼロの新規チェックであり、S2P data fidelity を実行接地で統合する中核。
```

### operand 解決仕様

```yaml
operands:
  baseline: { node_id: n_base, metric_path: "measurements.runtime" }   # results.json 内 dot-path
  proposed: { node_id: n_prop, metric_path: "measurements.runtime" }
```

```text
- node_id → node_report.json / その node の results.json を特定（claim が直接保持する安定 id）。
- metric_path → results.json の dot-path（measurements.* / scores.* など）で scalar を取得。
- 解決不可 / 値なしは error（type: operand_unresolved）。
```

### 将来拡張（trial 集計）— 別スコープ

```text
- aggregation: {statistic: mean, trials: N} の真の再計算は per-trial 生値の保持が前提。
- 前提改修: ari-skill-coding(emit_results) で per-trial 配列を emit、ari-skill-transform で保持。
- MVP では aggregation は「記録のみ・再計算は formula-level」とする。
```

### formula examples

```text
relative_speedup:             baseline_mean / proposed_mean
relative_improvement_percent: (baseline_mean - proposed_mean) / baseline_mean * 100
relative_reduction_percent:   (baseline_mean - proposed_mean) / baseline_mean * 100
absolute_difference:          proposed_mean - baseline_mean
```

---

## Phase B3: hard gate policy config

```yaml
claim_gate_policy:
  numeric_coverage:
    mode: warn          # strict | warn | off
    target_sections:
      strict:  ["abstract", "results", "conclusion"]
      warn:    ["introduction", "discussion", "limitations"]
      excluded: ["related_work", "references", "appendix", "equations"]
  numeric_match:
    default_tolerance: { absolute: 0.0, relative: 0.02 }   # numeric_assertion 側 tolerance が優先
  blocking:
    block_on: ["numeric_mismatch", "operand_unresolved", "missing_evidence"]
    # uncovered_numeric は mode=strict のときのみ block
```

```text
- MVP: mode=warn から開始（false positive を観察しながら分類精度を上げる）。
- 評価実験: mode=strict。
- excluded section は coverage 対象外。section 別厳格度はこの policy で一元管理する。
```

---

## Phase C: hypothesis 台帳の要否判定

```text
1. lineage_decisions.jsonl に active_idea の履歴が十分残るか確認する。
2. science_data.json の claims[] と active_idea を接続できるか確認する。
3. hypothesis → experiment → result → claim の chain が復元可能か確認する。
4. 不足があれば最小の hypotheses[] 層を science_data.json に追加する。
```

方針：最初から台帳を新設せず、既存 lineage mechanism で代替可否を先に評価する。

---

## Phase D: evidence_grounded_semantic_review（S2P reasoning / visual coherence の統合）

### 命名

```text
コード名: evidence_grounded_semantic_review
論文中: "integrating Story2Proposal's reasoning verification and visual coherence evaluation,
         grounded in executed artifacts"
```

### 設計制約

```text
- review_paper を改造しない（text-only reviewer independence contract を維持）。
- dynamic-axes LLM evaluator には直接足さない（operand が実験ノードで paper ではない）。
- 非ブロッキング。suggested_revisions を paper_refine に渡す。
- paper_refine 後に再評価し、改善を測定できるようにする（generate–evaluate–adapt の統合）。
```

### 評価対象（決定論で測れない意味のみ）

```text
[reasoning semantics]   Abstract/Intro の主張が evidence の範囲を超えないか、Conclusion の過剰一般化、
                        limitation の Discussion 反映、contribution の広すぎ。
[data interpretation]   数値一致は Phase B 判定済み。解釈・因果・比較表現の妥当性のみ。
[visual semantics]      figure 実在は Phase B 判定済み。caption と本文・図の傾向の意味整合、言い過ぎのみ。
[unregistered claim]    science_data.json claims[] に対応しない strong claim(非数値) を検出し、blocking せず refine へ。
```

### 出力

```json
{
  "stage": "evidence_grounded_semantic_review", "status": "revise",
  "scores": {"reasoning": 0.72, "data_interpretation": 0.81, "visual_semantics": 0.76},
  "warnings": [{"type": "overclaim", "section": "conclusion",
                "message": "The conclusion generalizes beyond the evaluated benchmark."}],
  "suggested_revisions": [{"section": "conclusion", "instruction": "Limit the claim to the evaluated HPC benchmark."}]
}
```

保存先：`workspace/checkpoints/<ts>_<slug>/evaluation/evidence_grounded_semantic_review.json`

### paper_refine への接続（generate–evaluate–adapt の統合）

```text
write_paper
→ claim-id 後処理検証 → claim_evidence_hard_gate（初回・draft）
→ evidence_grounded_semantic_review（+ review_paper 独立）
→ merge_reviews（suggested_revisions 集約）
→ paper_refine（提案を反映、% CLAIM anchor を保持）
→ evidence_grounded_semantic_review rerun（score_delta 測定）
→ claim-id 後処理検証（再）→ claim_evidence_hard_gate（最終・refined paper、ブロッキング）
→ finalize_paper
```

---

## Phase E: merge_reviews の整理

```json
{
  "independent_reviews": {
    "venue_review": "review_paper output",
    "vlm_figure_review": "vlm_review_figures output"
  },
  "evidence_grounded_reviews": {
    "claim_evidence_hard_gate": "claim_evidence_hard_gate_final.json",
    "evidence_grounded_semantic_review": "evidence_grounded_semantic_review.json"
  }
}
```

方針：review_paper の独立性を維持。evidence-grounded review は別カテゴリ。paper_refine には両方渡してよいが、レポート上は分ける。

---

## 8. 実装順序

```text
Step 1: 本計画書を確定する。
Step 2: docs に Story2Proposal 統合の位置づけメモを追加する。
Step 3: science_data.json スキーマに claims[] / numeric_assertions[]（operands = node_id + metric_path）を追加する。
        claim には configuration に依らず実 node_id を直書きする（transform_data が node_id を保持）。
Step 4: transform_data（nodes_to_science_data）で candidate claims を draft 生成する。
Step 5: write_paper に「science_data.json の claim を参照し % CLAIM:Cx:NCx anchor を付ける」指示を追加する
        （必要なら claims_registry を prompt に明示注入。EAR には足さない）。
Step 6: claim-id 後処理検証を実装する（6a 分類 / 6b links 確定 / 6c 未登録数値検出）。
Step 7: claim_evidence_hard_gate を実装する（7a 実在 / 7b 数値再計算 / 7c coverage / 7d figure / 7e draft+final 両実行）。
Step 8: claim_gate_policy config を定義し、MVP=warn / 評価=strict を切替可能にする。
Step 9: evidence_grounded_semantic_review を別 evaluator として追加する。
Step 10: suggested_revisions を paper_refine に渡し、refine 後に semantic review と hard gate を再実行する（anchor 保持）。
Step 11: merge_reviews で independent_reviews と evidence_grounded_reviews を分ける。
Step 12: finalize_paper を「最終 hard gate」に依存させる。
Step 13: 実機 compute node で transform_data → write_paper → 後処理検証 → hard gate → semantic review → refine → 最終 hard gate → finalize を通す。
Step 14: ORS 再現 grade と hard gate / semantic review の関係を確認する。
Step 15: hypothesis 台帳の要否を判定する。
```

注：

```text
- 検証は fake/login node ではなく、可能なら実機 compute node で行う。
- 出力は workspace/checkpoints/<ts>_<slug>/ に揃える。
- テスト緑だけでなく、実機 run による provenance 生成を完了条件に含める。
- 数値再計算は MVP では formula-level に限定し、trial 集計は将来課題（skill 改修前提）とする。
- EAR は公開バンドルとして据え置き、claims を載せない。
```

---

## 9. 関連研究としての記述方針（統合の説明）

### 9.1 推奨表現（英）

```text
Story2Proposal introduced a contract-governed multi-agent framework for structured scientific
manuscript generation, in which a persistent shared visual contract records section structure,
a global registry of visual artifacts, and document-wide validation rules, and architect,
writer, refiner, and renderer agents coordinate through the contract under a generate–evaluate–
adapt loop with reasoning-verification, data-fidelity, and visual-coherence evaluation.
Story2Proposal takes the experimental evidence as given input and governs how it is written up;
it does not execute experiments.

ARI integrates Story2Proposal's contract-governed generation principle and its evaluation axes
into an execution-grounded research pipeline. Rather than re-implementing the visual contract or
the four-agent manuscript pipeline, ARI realizes the contract by extending its structured
experiment record (science_data) with explicit claims and numeric assertions that reference
stable node, result, and figure identifiers, and realizes the evaluation axes as (i) a
deterministic claim-evidence hard gate that re-computes reported numbers from executed results
and detects unregistered numeric statements, and (ii) a non-blocking evidence-grounded semantic
reviewer that detects over-claiming without compromising independent manuscript review. Because
ARI executes the experiments, claims are grounded in commands, logs, measured results, artifacts,
and hardware metadata.
```

### 9.2 推奨表現（日）

```text
Story2Proposal は、persistent shared visual contract（section 構造・図表 registry・validation rules）と
architect / writer / refiner / renderer agent、reasoning verification / data fidelity / visual coherence
の評価により、構造化された論文原稿を生成する contract-governed framework である。
Story2Proposal は実験エビデンスを与件として受け取り、その書き上げ方を統治するもので、実験自体は実行しない。

本研究の ARI は、Story2Proposal の contract-governed generation の原理と評価軸を、execution-grounded な
研究パイプラインへ統合する。visual contract や4 agent 構成を再実装するのではなく、
contract は ARI の構造化実験記録（science_data）を、安定な node / result / figure 識別子を参照する
claim・numeric assertion で拡張して実現し、
評価軸は (i) 実行結果から数値を再計算し未登録数値を検出する決定論的 claim-evidence hard gate と、
(ii) 独立査読を壊さず言い過ぎを検出する非ブロッキングの evidence-grounded semantic review として実現する。
ARI は実験を実行するため、claim はコマンド・ログ・計測結果・artifact・ハードウェアメタデータに接地される。
```

### 9.3 避けるべき表現

```text
× Story2Proposal manages code, experiments, logs, and HPC execution.
× ARI newly introduces claim-evidence alignment / provenance tracking.
× ARI simply implements or extends Story2Proposal.
× Story2Proposal-style evaluation and ARI ORS are the same.
```

---

## 10. 評価設計

```text
- Story2Proposal には ablation がない → ARI は hard gate / semantic review / refine feedback の ablation を入れられる。
- baseline は DirectChat / Fars（manuscript 比較）→ ARI は実行 provenance + ORS 再現 grade を評価できる。
- evidence は与件 → ARI は実行済み artifact に基づく evidence generation を評価できる。
- benchmark は非 HPC → ARI は HPC 実機タスクで execution-grounding を示せる。
```

### 10.1 評価条件

```text
Condition A: Baseline ARI（claims[] なし / hard gate なし / semantic review なし）
Condition B: ARI + claim hard gate
Condition C: ARI + hard gate + semantic review（report only）
Condition D: ARI + hard gate + semantic review + paper_refine feedback
```

### 10.2 指標

```text
unsupported_claim_count
claim_evidence_mismatch_count
execution_grounded_claim_rate
numeric_claim_reproducible_rate
numeric_coverage_rate
uncovered_numeric_count
numeric_claim_mismatch_count
unverified_strong_claim_count
finalization_block_rate
semantic_review_score_delta
semantic_review_detected_overclaim_count
semantic_review_resolved_overclaim_count
human_verified_overclaim_precision
ors_reproduction_grade
paper_review_score
```

### 10.3 主要指標の定義

```text
execution_grounded_claim_rate =
  実在 executed node/result/artifact/figure に接続された claim 数 / 論文中の検証対象 claim 数

numeric_claim_reproducible_rate =
  tolerance 内で再導出できた numeric_assertion 数 / 検証対象 numeric_assertion 数

numeric_coverage_rate =
  numeric_assertion に紐づく result_claim 数値トークン数 / 検証対象 section の result_claim 数値トークン数

semantic_review_score_delta =
  refine 後 score - refine 前 score
```

注：
```text
- numeric_claim_reproducible_rate は単独だと assertion を減らすほど高く見えるため、必ず numeric_coverage_rate と併記する。
- semantic_review_score_delta は同一 reviewer の自己評価でバイアスを持つため、独立指標（hard gate error 減 / review_paper score / 人手）と併記する。
- human_verified_overclaim_precision は、semantic review が検出した overclaim を人手スポットチェックで検証した精度。LLM が過剰に「言い過ぎ」と判定する偽陽性を抑えるため、統合の効果根拠として detected / resolved count と合わせて報告する。
```

### 10.4 Ablation

```text
Ablation 1: claim hard gate なし vs あり
Ablation 2: 数値照合（formula-level）なし vs あり
Ablation 3: numeric coverage 検出 なし vs あり（mode=warn vs strict）
Ablation 4: semantic review なし vs あり
Ablation 5: semantic review report only vs + paper_refine feedback
Ablation 6: paper-only review vs execution-grounded review
```

---

## 11. 研究上の主張（統合の貢献）

### 11.1 英語

```text
ARI integrates Story2Proposal's contract-governed generation and its reasoning, data-fidelity,
and visual-coherence evaluation into an execution-grounded pipeline. The contract is realized by
extending ARI's structured experiment record (science_data) with claims and numeric assertions
that reference stable node, result, and figure identifiers; data-fidelity is realized as a
deterministic claim-evidence hard gate that re-computes reported numbers from executed results
and flags unregistered numeric statements (verifying transcription/derivation consistency between the
paper and recorded results, not the truthfulness of the recorded results themselves, which external
reproducibility via ORS addresses); and reasoning and visual coherence are realized as a
non-blocking evidence-grounded semantic reviewer that preserves independent manuscript review.
Because evidence is produced by execution rather than supplied as input, ARI extends
manuscript-level contract governance to execution-grounded research provenance.
```

### 11.2 日本語

```text
ARI は、Story2Proposal の contract-governed generation と reasoning / data fidelity / visual
coherence 評価を、execution-grounded パイプラインへ統合する。contract は構造化実験記録（science_data）を
安定な node / result / figure 識別子を参照する claim・numeric assertion で拡張して実現し、
data fidelity は実行結果から数値を再計算し未登録数値を検出する決定論的 hard gate として（paper↔results の転記・導出の整合性を検証するもので、results の真偽は ORS が担う）、
reasoning / visual coherence は独立査読を壊さない非ブロッキングの evidence-grounded semantic review として
実現する。evidence を与件ではなく実行で生成するため、ARI は manuscript-level の contract 統治を
execution-grounded provenance へ拡張する。
```

---

## 12. 結論

本書は、Story2Proposal の **contract-governed generation の原理**と**評価軸**を ARI に統合する計画である。統合は次のように行う。

```text
- Story2Proposal の contract        → ARI の science_data.json を Research Contract substrate 化
                                       （claims[] / numeric_assertions[]。claim に実 node_id を直書き、
                                       figure は late-bind、決定論部分にのみ接地）。EAR ではない。
- Story2Proposal の data fidelity    → execution data fidelity に再定義 → 決定論的 hard gate（数値再計算 + 未登録数値検出）。
- Story2Proposal の reasoning/visual → 非ブロッキングの evidence-grounded semantic review。
- Story2Proposal の eval-adapt loop  → write_paper → gate/review → paper_refine → 最終 gate → finalize。
- visual contract 内部実装 / 4 agent → 移植せず、ARI 既存機構（BFTS + pipeline + science_data + figures_manifest）に統合。
- EAR                                → 公開バンドルとして据え置き、contract には使わない。
```

統合の新規性は、与件 evidence ではなく**実行で生成した evidence に contract 統治を接地する** execution-grounded provenance にある。

実装は既存 science_data / node_report / results / EAR / ORS / review 系 / LLM evaluator を作り直さず、§7・§8 の最小追加に限定する。

最終的な位置づけ：

```text
Story2Proposal:
  shared visual contract（section structure, visual registry, validation rules）。evidence は与件。

ARI（統合後）:
  Research Contract substrate = science_data.json（writer が消費する構造化実験記録）を、
  実行された node / result / figure provenance（安定 id）に接地した claim で拡張したもの。
  S2P の評価軸を、決定論的 hard gate（internal consistency）と evidence-grounded semantic review（意味）に
  統合し、ORS（external reproducibility）と併せて生成–評価–更新ループを回す。EAR は公開バンドル。
```
