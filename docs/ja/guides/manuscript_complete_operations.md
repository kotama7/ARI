---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/segments.py
    role: implementation
  - path: ari-core/ari/manuscript/evaluation.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: scripts/evaluate_manuscript_complete.py
    role: implementation
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
  - path: scripts/manuscript_complete_release_gates.json
    role: config
  - path: .github/workflows/manuscript-complete.yml
    role: config
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/fixtures/manuscript_complete/factory.py
    role: test
last_verified: 2026-08-09
---

# Manuscript Complete オペレータランブック

## 有効化

デフォルトはレガシーと完全に同一の挙動です:

```yaml
manuscript:
  mode: off
  profile: generic_empirical_v1
  repair:
    policy: disabled
```

writer の入力を変えずにギャップを計測するには `audit` を使います。authoring の
前で停止させるには `enforce` を使います。自動 repair は enforce の下でのみ
有効です:

```yaml
manuscript:
  mode: enforce
  profile: generic_empirical_v1
  brief_character_budget: 24000
  repair:
    policy: auto
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

環境変数によるオーバーライドは `ARI_MANUSCRIPT_MODE` と
`ARI_MANUSCRIPT_REPAIR_POLICY` です。attempt の途中での profile、mode、
workflow、KCA lock、authority の変更は黙って調停されません。新しい attempt を
compile してください。

## 点検と明示的な repair

```bash
ari manuscript compile CHECKPOINT --mode audit
ari manuscript status CHECKPOINT --fail-if-blocked
ari manuscript inspect CHECKPOINT --requirement MC-RP-002
ari manuscript inspect CHECKPOINT --lane contextual_negative
ari manuscript plan-repair CHECKPOINT --config CHECKPOINT/workflow.yaml
ari manuscript repair CHECKPOINT --request REPAIR_ID
```

`plan-repair` は外部への操作を一切行いません。`repair` はまず admit された
正確なスコープを記録し、その上で resume 可能な research runtime を使います。
experiment のリクエストは、request ID、requirement ID、source context、固定
変数、許可された変更を運ぶ 1 個の bounded な node になります。RQGM と KCA の
hook は設定されていれば通常どおり走ります。完了は新しい context/readiness の
compile だけで決まり、executor の exit code で決まることはありません。

projection や artifact の再構築は experiment の予算をまったく消費しないことが
あります。retrieval は `related_refs.json` に記録されます。disclosure は
`manuscript_disclosures.json` を作成しますが、それはあくまで disclosure で
あって事実としての証拠ではありません。人間を必要とする method と policy の
決定は `human_required` のままです。

`ari paper` は意図的に research executor を持ちません。既存のチェックポイントに
experiment の repair が必要な場合は、`ari resume` か上記の明示的なコマンドを
使ってください。

## Resume とリカバリ

segment レコードと request の transaction は immutable です。再起動時には、
fresh な completed segment が再利用されます。すでに commit
済みの repair request が再び呼ばれることはありません; コーディネータはまず
証拠を再構築し、それを再評価します。node/run/call の累積使用量は transaction
レコードから復元されます。

自動ループは必ず停止し、その理由はちょうど 1 つです。その理由はループの
戻り値の `termination_reason` であり、永続化されません。transition チェーンに
記録が残るのは一部の停止だけです: 終端 transition `automatic_repair_<reason>`
が append されるのは、その遷移先 state がストアの現在保持する state の合法な
後続である場合に限られます。append される場合は attempt の `readiness.json` を
digest で参照し、そこで未解決の requirement を読み続けられます。
node/run/call/resource の累積使用量は、`auto-rounds/` 配下に commit された
すべての round レコードが運びます。

| Termination reason | 条件 | 遷移先 state | チェーンへの append |
|---|---|---|---|
| `authoring_ready` | readiness が `ready` または `ready_with_disclosures` に到達した | なし | なし; authoring へ進む |
| `no_admitted_repair_request` | compile が readiness レポートを出さなかった、repair plan を出さなかった、または request を持たない plan を出した | `blocked_unavailable` | あり。ただし compile が既に `blocked_unavailable` を書いていた場合を除く |
| `human_decision_required` | 実行も充足もされた request が無く、少なくとも 1 件が `human_required` を返した | `blocked_unavailable` | あり |
| `required_resolver_unavailable` | 実行も充足もされた request が無く、`human_required` も `exhausted` も 1 件も無かった | `blocked_unavailable` | あり |
| `cumulative_budget_exhausted`、round の後 | 実行も充足もされた request が無く、1 件が `exhausted` を報告した | `repair_pending` | あり |
| `cumulative_budget_exhausted`、round の前 | 復元された使用量が `max_new_nodes`、`max_experiment_runs`、`max_llm_calls`、`max_resource_units` のいずれかを超えている | `repair_pending` | なし |
| `round_budget_exhausted` | commit 済みの round レコードが `repair.max_rounds` に到達した | `repair_pending` | なし |
| `no_progress_cycle` | 同じ source context digest と同じ requirement-status ベクタが再出現した | `repair_pending` | なし |

最後の 3 行が ready に至らない停止としてよくあるもので、いずれも記録され
ません。これらが break する時点では直前の compile が既に `repair_pending` を
書いており、`repair_pending` は自分自身の合法な後続ではないため、何も append
されません。チェーンを `automatic_repair_no_progress_cycle` や
`automatic_repair_round_budget_exhausted` で grep しないでください; それらが
書かれることはありません。これらの停止はループの戻り値から読むか、
`auto-rounds/` 配下の commit 済み round レコードと attempt の `readiness.json`
から再構成してください。これらについて理由を永続化することは設計されて
いますが実装されていません: `ManuscriptAutoRepairRoundV1` は round、その plan
と source context の digest、request ID と transaction digest、request ごとの
結果、使用済みの予算を運びますが、termination reason のフィールドは持たず、
他のどの artifact もそれを記録しません。

進捗が無いことは、source context digest と `(requirement_id, status)` の
ベクタだけで判定されます。言い回しを変えた散文、新しいドラフト、表現を変えた
要約は進捗ではありません; 進捗なのは変化した証拠だけです。終端 transition は
現在の state から合法な場合にのみ append されるため、停止したループが
compiler の既に所有する state を書き換えてしまうことはありません。

クラッシュは、commit 済みの round とその証拠再構築の間に落ちることが
あります。次回の起動時、ループは現在の plan digest に既に commit 済みの round
レコードがあることを認識し、その round をちょうど 1 回だけ閉じます: 証拠の
再構築をやり直して再 compile し、resolver は一切呼びません。再 compile した
context digest と requirement-status ベクタが変わっていなければ、この調停は
同一の round を 2 度目に始めるのではなく `no_progress_cycle` として終了します。

同じ規則が 1 段下でも成り立ちます。transaction が既に commit されている
request は、executor を呼ばずにそのレコードからリプレイされ、新たな予算は
課金されず、当初課金された量を運ぶ冪等な再利用としてマークされます。
`related_refs.json` に既に記録された文献 retrieval は request digest で照合
されて再利用されます。これが、provider 呼び出しの後・transaction レコードの
前でクラッシュした場合の冪等性の境界です: resume に provider 呼び出しは不要
で、重複クエリも発行されません。

ランが `repair_pending` で停止した場合は、未解決の requirement と予算を確認して
ください。`blocked_unavailable` は admit された capability、Harness、または
人間の決定を必要とします; state ファイルを削除しないでください。
`no_progress_cycle` の後は、明示的に承認された操作を通じて source の証拠を
変えてください。そうしなければ block されたままです。

transition チェーンや immutable な artifact が壊れた場合は、audit のために
`.ari-manuscript/` を保全したうえで、新しいチェックポイント/attempt を開始して
ください。digest フィールドを編集したり、attempt のファイルをその場で置き換えたり
しないでください。

`paper.mode: rqgm_archive` では、
`paper_archive_state.json.manuscript_authoring` と
`paper_draft_archive.jsonl` の Manuscript フィールドを確認します。
`manuscript_bound_winner` は、archive の winner が現在の固定 bundle を使った
ことを意味します。`bound_linear_fallback` は、archive の生成に失敗したが
linear backend が同じ bundle を消費したことを意味します。
`audit_legacy_archive_winner` と `audit_legacy_linear_fallback` は、明示的に
Manuscript Complete の authoring ではありません。`stale_detected` や
`authoring_backend_failed` を state の編集で解消してはなりません; 新しい
attempt を compile するか、元の immutable な bundle で resume してください。
stale かどうかは archive の最初の writer 呼び出しの前に判定され、その対象は
fingerprint の変化だけにとどまりません: `stale_reasons` は
`input_fingerprint_changed` を記録し、同じ durable archive が以前は別の
`manuscript.mode` で駆動されていた場合には `manuscript_mode_changed` を、
ドラフトは既に存在するのにそれらに対する `manuscript_authoring` ブロックが
一度も書かれていない場合には `preexisting_archive_has_no_binding_state` を、
そして異なる fingerprint を運ぶ最初の archive 済みドラフトに対しては
`draft_binding_mismatch:<epoch_id>:<node_id>` を記録します。enforce では
どの理由であってもランは次の writer 呼び出しの前に停止します。audit では
理由が記録され、その起動における archive の継続はスキップされ、ランは
linear pipeline に degrade します。したがって audit の観測面は保持された
`stale_reasons` であって status ではありません — status はこのとき
`audit_legacy_linear_fallback` になります。よって、archive が既に走った
チェックポイントで `manuscript.mode` を `audit` から `enforce` に切り替える
ことは、黙ったアップグレードではなく block される resume です; 新しい attempt
を compile してください。`verification_or_fallback_failed` は、bundle は
消費されたものの共有の verification tail（または linear fallback 自身）が
例外を送出したことを意味します; `failure_reason` を読み、best-belief な
winner が既に記録されていた場合は `winner_id` と `winner_tex_sha256` も読んで
ください。`bound` と `audit_legacy_authoring_observed` はそもそも outcome では
ありません: archive が何かを生成する前に、enforce では `bound`、audit では
`audit_legacy_authoring_observed` として書かれるものなので、どちらかを保持した
ままのチェックポイントは outcome が記録される前に停止したのです — 結果では
なく中断されたランとして読んでください。archive 生成の失敗がどの outcome に
なるかは manuscript の mode と呼び出し側が渡した fallback によって固定され、
失敗を引き起こした例外によって決まることは決してありません。
`manuscript.mode: off` の下では、archive はレガシーの fail-open な姿勢を
保ちます: エラーはログされ、ランは通常の linear paper pipeline に degrade し、
`manuscript_authoring` ブロックは一切書かれません。`audit` の下では degrade
して `audit_legacy_linear_fallback` を記録します。`enforce` の下では、既に
検証済みの同じ binding を消費すると明示的にマークされた fallback にのみ
degrade できます; `ari run`、`ari resume`、`ari paper` はいずれも manuscript の
軸が有効なときは必ずマーク済みの fallback を渡すため、enforce での archive
失敗は `bound_linear_fallback` に落ちます。一方 `authoring_backend_failed` は、
archive runtime をマークの無い fallback で直接駆動した場合の fail-closed な
outcome です — 何も執筆されず、ランは停止します。enforce の内部では、degrade
するか停止するかを選ぶ設定は存在しません — それはマーカーだけで決まり、
manuscript の設定面は `manuscript.mode`、`manuscript.profile`、
`manuscript.brief_character_budget`、`manuscript.repair.*` がすべてです。
admissible な候補を 1 つも生まなかった archive round は、それ自体が archive の
失敗であり、同じ経路をたどります。hard-disqualify されたドラフトは audit の
ために保持されますが、reviewer スコアを上げて選ばせることは決してできません。

## Publication

```bash
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

lock コマンドは、すべての source、bound された manuscript の入力、PaperBuild の
artifact、reproduction の証拠、そして最終 PDF を再 hash します。決定の後に何か
変わっていれば非ゼロの結果を返し、lock は書きません。

### 決定を読む

`explain-publication` は attempt ID、決定とその digest、PaperBuild の digest、
そしてすべての sub-verdict — その gate、`pass`/`fail`/`not_required` の status、
reason code、記録した artifact digest — を出力します。reason code は失敗した
gate に対してのみ書かれ、`freshness` gate は artifact digest をまったく持ち
ません。決定が `publishable` でないときコマンドは常に `2` で終了するので、
スクリプト中ではゲートとして読めます。

`publication_decision.json` を持たない attempt は、`decision: not_evaluated`、
`reason: publication_decision_missing`、および attempt ID として報告され、
やはり `2` で終了します。これは block された決定ではありません — 何も評価
されていないのです。決定は paper pipeline 自身が、manuscript の軸が有効で
ステージ一覧に `lock_paper_build` または `ors_run_reproduce` を含むランの
末尾で書きます; また finalizer は、`paper_build.json` が無い場合や、context、
readiness、binding のパス変数が未設定の場合にも、何も書かずに戻ります。
したがって決定が無いということは、その末尾が一度も走らなかったという
ことです。`audit` か `enforce` で pipeline を再実行してください; このファイルを
手書きしてはいけません。

### lock が拒否される理由

`lock-publication` は `publication_lock.json` を書かず、`locked: false`、
attempt ID、単一の `reason` 文字列を報告して `2` で終了します。チェックは下の
順に走り、最初に失敗したものが報告される reason になります。

| `reason` | 原因 |
|---|---|
| `publication lock requires an exposed authoring binding` | attempt の `authoring_binding.json` が無いか、そのパスがチェックポイントの外に出るか symlink を経由している |
| `blocked publication decision cannot be locked` | 記録された決定が `blocked` である |
| `publication decision no longer names the current build` | 決定の PaperBuild digest、authoring-binding digest、run ID、attempt ID のいずれかが現在の `paper_build.json` および binding と食い違っている |
| `publication attempt is not finalized` | manuscript の state ファイルが別の attempt を指しているか、その state が `finalized` でない |
| `publication inputs changed after decision` | snapshot された source、ネストした PaperBuild artifact、または bound された manuscript の入力が、記録された digest とサイズに一致しなくなった |
| `publication reproduction evidence is stale` | `reproduction` の sub-verdict が `pass` でない、または `ors_phase1.json` が無い・symlink 経由で到達する・その sub-verdict が記録した digest にもう hash されない |
| `publication build does not identify one final PDF` | build の final artifact に `pdf` role が 0 個または 2 個以上ある — 単一の compile PDF artifact が代わりになるのは、final のものが 1 つも無い場合だけです |

freshness の行は 7 つの中で最も広い範囲を持ちます。snapshot が `missing` と
して記録した source が現在は存在する場合、パスを持つ source が digest も
サイズも持たず安定したバイト同一性を欠く場合、build が同じ artifact role と
パスに対して 2 つの異なる identity を宣言している場合、あるいは bound された
5 つの manuscript の入力 — requirement profile、context、readiness、
section brief、authoring binding — が build がそれらの role で記録した attempt
ディレクトリのファイルとちょうど一致しない場合、それらの
profile/context/readiness/brief の digest lineage がもはや整合しない場合、
bound された readiness レポートの authoring verdict が `ready` でも
`ready_with_disclosures` でもない場合にも失敗します。これらのパスのいずれかに
symlink 経由で到達する場合も同じように失敗します。

不正な、あるいは読めない contract ファイルも同じ形で表面化します: 基になる
`OSError` またはスキーマ検証エラーが `reason` となり、終了コードは `2` の
ままです。

`finalized` state を書くのは `enforce` だけなので、`audit` の下で生まれた決定は
shadow decision です: `explain-publication` はそれを読みますが、
`lock-publication` は finalized でないとして拒否します。これは意図した audit の
姿勢であって欠陥ではありません。

ここでの拒否は、state のフィールドや digest を編集しても解消されません。
新しい attempt を再 compile するか、元の immutable な bundle で resume して
ください。

## ロールバック、プライバシー、保持

以後の起動をレガシー経路に戻すには `manuscript.mode: off` を設定します。これで
過去の attempt が消えるわけではありません。`.ari-manuscript` にはリサーチ
クエスチョン、失敗した結果の要約、パス、provider の identity、model に bound
された brief が含まれ得ます; チェックポイントのデータ分類に従って扱って
ください。authority の snapshot が含むのは identity と digest であって、
credential の値では決してありません。チェックポイントの秘匿化や削除は、その
research artifact に用いるのと同じ保持プロセスを通じてのみ行ってください。

## リリース評価

ラベル付きの fixture campaign は、恒久的なレポート契約へ集約できます:

```bash
PYTHONPATH=ari-core python scripts/evaluate_manuscript_complete.py \
  evaluation-cases.json --output manuscript-evaluation.json
```

入力は JSON のリスト（または `dataset_id` と `cases` を持つオブジェクト）です。
該当するケースが無い比率は `not_applicable` のままです; リリースの決定に用いた
topology、failure-injection、本物の Harness の証拠とあわせてレポートを保持して
ください。

素の JSON リストの場合は `--dataset-id DATASET_ID` を渡します。7 つの合成
baseline クラスは `ari-core/tests/fixtures/manuscript_complete/factory.py` が
生成します; 再生成と検証は次で行います:

```bash
PYTHONPATH=ari-core pytest -q \
  ari-core/tests/test_manuscript_complete.py::test_baseline_fixture_classes_are_executable \
  ari-core/tests/test_manuscript_complete.py::test_executable_fixture_expectations
```

生成された値はテスト専用で `SYNTHETIC_FIXTURE.json` を伴います; 保持される
科学的証拠でも Harness の証拠でもありません。

## リリースゲートと保持される CI 証拠

クローズドなリリースマニフェストは、clean な commit 済みリビジョンからのみ
実行してください。出力は worktree の外に置きます:

```bash
release_dir="$(mktemp -d)"
PYTHONPATH=ari-core python scripts/run_manuscript_complete_release.py \
  --output-dir "$release_dir" --require-clean --keep-going
```

レポートは `release_evidence.json` です; 各チェックの stdout/stderr は `logs/`
配下に保持され、レポート内の digest で名前が付きます。対象は、4 topology の
publication E2E、13 個すべての failure-injection ファミリー、加算的なレガシー
migration/rollback、恒久的な schema/snapshot/docs チェック、
paper/tool-registry の統合、そしてチェックインされた本物の native Harness の
publication チェーンです。

プルリクエストは同じマニフェストを
`.github/workflows/manuscript-complete.yml` から `--require-ci` 付きで実行し、
artifact を 90 日間保持します。dirty なソースリビジョンでのローカルレポートや、
`--require-ci` を使ったときの GitHub Actions 外でのレポートは、意図的に
`release_eligible` になりません。合成 topology fixture が示すのは配線と失敗時の
姿勢だけです; 本物の certification は、`ari-core/config/harnesses/evidence/`
配下に別途保持される native Harness の証拠のままです。

### `release_eligible` が意味すること・しないこと

`release_eligible` が true になるのは、マニフェストのすべてのチェックが実行
されて pass し、ソースリビジョンが clean で、かつ — `--require-ci` の下では —
その実行が GitHub Actions の中で起きた場合だけです。この 3 条件がそのすべて
です。これはリリースの必要条件であって、リリースの決定そのものではありません。

2 つの基準は人間の側に残り、マニフェストにもレポートにもどこにも符号化されて
いません: 未解決の critical または high の publication-safety issue が 1 件も
開いていないこと、そしてオペレータが blocked、予算枯渇、人間決定の各フローを
レビュー済みであること。後の読者がそれらが問われたと分かるよう、両方の答えを
保持したレポートの隣に記録してください。

リリースのスコープも同じやり方で、レポートの外で決まります。capability を
supported と記述してよいのは、それについて本物の保持された証拠が存在する範囲
だけです。その証拠を欠く Harness のスコープは unsupported かつ blocked のまま
であり、unsupported として文書化されます; それはカバーされているスコープの
リリースに拒否権を持ちませんが、リリースノート、ドキュメント、論文で実装済み
として宣伝してはなりません。`release_evidence.json` はこれらのいずれも検査
しません — 拘束するのはリリースに署名する人です。

### failure-injection のブロッキングマトリクス

injection が満たされたと数えるのは、その欠陥が*ブロックする*場合だけです。
publication が依然として lock できるのに欠陥が記録されるのは、警告ではなく
テストの失敗です。したがって、注入されるフォールトはいずれも、`fail` と読め
なければならない sub-verdict と、フローが停止する地点を名指しします。

| 注入されるフォールト | 失敗する sub-verdict |
|---|---|
| build レコードが書かれた後に最終 PDF が削除される | `freshness` |
| `ors_phase1.json` が削除される | `reproduction` |
| 必要な disclosure が最終 TeX に存在しない | `claim_evidence` |
| contextual-negative の evidence ID が最終 TeX で support として引用される | `claim_evidence` |

停止の仕方はどの行でも同一です: publication の決定は `blocked`、名指しされた
sub-verdict は `fail`、lock は何も書かずに例外を送出し、attempt ディレクトリの
下に `publication_lock.json` は存在しません。CLI 越しには、
`ari manuscript lock-publication` が `locked: false` と拒否理由を伴って `2` で
終了する形で現れます。4 行すべては 1 つのパラメトライズドテスト
`ari-core/tests/test_manuscript_complete.py::test_publication_failure_injection_matrix_blocks_before_lock`
が担当し、`missing-finalizer-artifact` と
`contextual-negative-used-as-positive-support` の両 injection ファミリーが
これを名指ししています。

13 ファミリーの全体と、それぞれを担当するテストは
`scripts/manuscript_complete_release_gates.json` にあります。リリースランナーは
何かを実行する前にこのマニフェストを検証します: 未知のスキーマバージョン、
ちょうど 4 つの一意な ID になっていない topology のリスト、13 以外のファミリー
数、重複したファミリー ID または check ID、`argv` の無い check、あるいはツリー
にもう関数が存在しない名指しされたテストがあれば、レポートを生成せずにランを
中断します。
