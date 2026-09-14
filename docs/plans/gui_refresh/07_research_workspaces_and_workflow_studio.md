# 07 — Research Workspaces and Workflow Studio

> Status: planned  
> Dependencies: 01, 02, 03, 04  
> Gate: G4 — Vertical slices

## Purpose

Home、Monitor、Tree、Ideas、Results、PaperBench、Workflow、Artifacts を、同じ run identity と progressive disclosure model で再構成する。各画面が重複して status/config/artifact を解釈せず、研究の「現在」「因果」「証拠」「成果」「手順」を役割分担して示す。

## Scope

- project portfolio と run list/comparison。
- run Overview/Live Monitor、Tree、Ideas/Claims、Evidence/Results。
- PaperBench integration と result-to-evidence lineage。
- EAR（Experiment Artifact Record）の curate/publish/promote lineage と publish.yaml 編集。
- sub-experiment（recursive run）lineage の可視化。
- Workflow Studio の version/revision/validation/conflict handling。
- artifact/log explorer と raw/debug access。
- shared selection、filter、deep link、export。

## Non-goals

- RQGM governance workspace は task 08。
- config form と launch flow は task 06。
- workflow execution semantics や research algorithm を GUI 都合で変更しない。

## Workspace responsibility matrix

| Workspace | Primary question | Must not become |
|---|---|---|
| Projects | 次にどの project/run を扱うか | 全 run の詳細 dashboard |
| Overview | 今何が起き、何をすべきか | raw log dump |
| Tree | どの探索経路が score/evidence へ至ったか | workflow editor |
| Ideas and Claims | 仮説、claim、evidence の関係は何か | paper archive browser |
| Evidence and Results | 何が成果で、どう再現・検証するか | governance state の代用 |
| Workflow Studio | どの pipeline revision を実行するか | active run の live mutation tool |
| Operations | process/resource/log の異常は何か | research conclusion page |

## Projects and run portfolio

- recent、running、attention required、completed を filter/sort する。
- run card は lifecycle、phase、mode、cost、freshness、owner/template を要約する。
- sub-experiment lineage（`parent_run_id`、`recursion_depth`（上限 3）、`inherit_ideas[n]`、`parent_terminated`）を run 間 relation として一覧と detail の両方に表示し、親子 run を deep-link で辿れるようにする。BFTS の node tree（run 内）と run lineage tree（run 間）を混同しない。
- RQGM accepted/rejected を overall research success badge に変換しない。
- compare は同じ metric definition/policy/version の run だけを既定で重ねる。
- empty state は create/import/resume の次 action を出す。

## Run Overview and Live Monitor

- P1: lifecycle、current research phase、blocker、next action、last update。
- P2: phase stepper、tree/idea/result count、resource/cost、artifact freshness。
- P3: recent events、queue/process、evaluation summary、governance summary。
- P4: filtered logs、trace、config diff、source artifact links。
- P5: raw event/API payload、projector diagnostics。

research phase と governance stage を二つの timeline または明示分離した row で表示する。現行の phase 語彙（`/state` の `current_phase`: idle/starting/bfts/paper/review と PhaseStepper の starting→idea→bfts→paper→review）を新 phase model が包含することを parity test で確認する。SSE 切断時は last known data と stale age を表示し、停止と推定しない。

## Tree workspace

- 既存 D3 zoom/pan/select interaction を再利用し、shared visualization frame に接続する。
- node selection を URL に反映し、details inspector と Ideas/Results/RQGM deep link を共有する。inspector は現行 DetailPanel の tab（Overview、MCP Trace、Code、Memory、Access log、Report、dev-mode Raw JSON）と capability parity を保つ。
- node status（pending/running/success/failed/abandoned）と label（draft/improve/debug/ablation/validation/other）は orchestrator の enum をそのまま用いる。
- score label は metric、epoch、policy hash、computed/recomputed state を伴う。score の実体は `metrics._scientific_score`/`_axis_scores` と RQGM sentinel（`_pre_penalty_score`、`_validated_attack_penalty`、`_utility_policy_hash`、`_stale` 系）であり、frontend 側での ad-hoc 抽出（現行 TreeVisualization の直読み）を typed DTO に置換する。
- large tree は level-of-detail、viewport culling、virtualized side table を使う。
- keyboard navigation と equivalent tabular hierarchy を提供する。
- frontier、selected path、stale/invalidated/removed を別 visual semantics で表現する。

## Ideas, claims, and evidence

- idea → claim → evidence → node/artifact/result の relation を表示する。
- confidence、evaluation、source freshness、contradiction を区別する。
- raw generated text と validated evidence を同じ status にしない。
- search/filter を URL 化し、result/paper/RQGM accountability から deep-link できる。
- source file と parsed representation の差異を diagnostics で確認できる。

## Evidence, Results, and PaperBench

- final output、evaluation metric、rubric、artifact、reproduction metadata を同じ result record に結ぶ。
- result から workflow revision、resolved config digest、tree node、evidence へ遡る。
- ORS reproducibility chain（rubric → replicator → phase1 reproduce → judge grade、現行 `OrsChainSection`）は provenance SHA 付きの lineage 表示として維持・強化する。
- **EAR / publication lineage を第一級で扱う**: curate（bundle sha256、included files）→ preview → publish（`consent=true` 必須）→ promote（staged→public）の各段階、`publish.yaml` の編集、`manifest.lock` の bundle digest、clone-verify を result からの追跡経路として表示する。publish 済み bundle と checkpoint 内容の対応が traceability の終端になる。
- PaperBench は独立した benchmark 状態を保持し、run completed と benchmark passed を混同しない。現行の in-memory job state（再起動で消失）を durable job record に置換し、既知の F6a report-endpoint drift を adapter で解消する。
- import/export は schema/version/error を明示し、partial success を表示する。
- chart comparison は unit/normalization/version compatibility を検証する。
- publish/export artifact に run ID、timestamp、filter、config digest を含める。

## Workflow Studio

- React Flow canvas を維持し、node/edge validation と accessible list editor を併設する。
- workflow は stable ID、schema version、revision、base revision を持つ。
- autosave は revision/ETag を用い、2 秒 timer の blind overwrite を廃止する。
- dirty、saving、saved、conflict、invalid、offline を明示する。
- validation は unknown phase、cycle、missing dependency、disabled required phase、config reference を検査する。
- active run の workflow は immutable snapshot として表示し、編集は clone/new revision を作る。
- 現行の二重 file 意味論を fixture 化して解消する: 編集は active checkpoint の copy に書かれ同一 checkpoint の再実行にのみ効く一方、**新規 launch は常に同梱 workflow.yaml をコピーするため編集が新 run に伝播しない**。さらに active checkpoint が無いと同梱ファイル自体を書き換える（task 09 の P0）。新設計では「この編集はどの run に効くか」を保存時に明示する。
- YAML round-trip で comment preservation を保証しない場合は、保存前に明示 warning/diff を出す。

## Artifacts, logs, and diagnostics

- artifact explorer は canonical artifact ID と safe path boundary を使う。
- structured artifact は domain view、raw source、schema/version、download を分離する。
- JSONL/log は cursor、tail、time range、level/topic filter を使う。
- 5 MB 一括 read のような generic fallback を主要 UX にしない。
- parse error は offset/line、raw excerpt、rebuild/retry action を返す。
- secret redaction と permission を server-side で適用する。

## Cross-workspace coordination

- run、node、claim、artifact、result、workflow revision は stable deep link を持つ。
- selection は URL/entity ID で渡し、session storage の暗黙 handoff を廃止する。
- breadcrumbs と back link は origin context を保持する。
- global filter は無制限共有せず、time range/run identity など意味が同じものだけ共有する。
- export は current filters と source revisions を manifest 化する。

## Migration sequence

1. old screen の screenshot、API、empty/error/loading behavior を固定する。
2. Projects と Overview を新 shell/API の最初の vertical slice とする。
3. Tree を shared visualization + run-explicit query へ移す。
4. Ideas/Evidence/Results の entity/deep-link contract を統合する。
5. PaperBench を canonical result/evidence model に adapter 接続する。
6. Workflow を revision-aware API と accessible editor へ移す。
7. artifact/log explorer を cursor/read-model API へ移す。
8. usage telemetry 後に legacy page-local fetching と handoff を削除する。

## Testing

- project/run list と two-run isolation E2E。
- Overview の lifecycle/stale/degraded/terminal state matrix。
- 10k-node tree の selection、LOD、keyboard、performance test。
- idea/claim/evidence/result deep-link integrity test。
- PaperBench import/error/partial/reproduction lineage test。
- Workflow valid/invalid/conflict/offline/reload/round-trip test。
- cursor logs/artifacts の no-gap/no-duplicate、redaction、corrupt record test。
- visual regression と three-locale responsive test。

## Completion criteria

- 全 workspace が canonical run ID と typed API を使う。
- Overview、Tree、Ideas、Results、Workflow の責務が重複せず deep-link で接続される。
- research status、benchmark status、governance status を混同しない。
- large tree/log/artifact が bounded query/render で操作できる。
- workflow edit が revision conflict を検出し、active run snapshot を変更しない。
- 旧画面との capability parity または意図的変更が migration note に記録される。

## Deletion criteria

- 各 workspace guide/API reference を恒久文書へ移し、legacy fetching/handoff/page route が removal criteria を満たしている。

## Delete-after checklist

- [ ] workspace user guides を三言語で更新した。
- [ ] workflow/artifact contracts を reference docs へ移した。
- [ ] legacy session-storage handoff と page fetch を削除した。
- [ ] main merge と CI green を確認した。
- [ ] `INDEX.md` を更新した。
