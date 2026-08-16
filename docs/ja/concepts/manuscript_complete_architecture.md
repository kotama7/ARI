---
sources:
  - path: ari-core/ari/manuscript
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_archive.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/adversarial/round.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-core/ari/science_data_contract.py
    role: schema
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: docs/reference/rest_api.md
    role: doc
  - path: docs/concepts/gui_architecture.md
    role: doc
last_verified: 2026-08-09
---

# Manuscript Complete アーキテクチャ

Manuscript Complete は、研究探索と論文執筆のあいだに置かれた固定された境界です。
これは、ありうるすべての事実が分かっていることを意味しません。選択された profile
の中のすべての requirement が、writer が入力を受け取る前に、明示的な status、理由、
証拠参照、修復姿勢を持っていることを意味します。

```text
simple BFTS or ARI-RQGM
        │
        ▼
evidence segment ── provenance / ScienceData / retrieval / EAR / figures / KCA
        │
        ▼
fixed compiler ── snapshot → context + omissions → readiness → section briefs
        │                         │
        │ ready                   └─ gap → bounded repair → research runtime
        ▼
linear writer or RQGM archive
        │
        ▼
verification segment
        │
        ▼
readiness ∧ claim gate ∧ assurance ∧ compile ∧ reproduction ∧ freshness
        │
        ▼
PublicationDecisionV1 → PublicationLockV1 or an explicit block
```

3 本の独立した軸は `ari.mode`（`simple_bfts|ari_rqgm`）、`paper.mode`
（`linear|rqgm_archive`）、`manuscript.mode`（`off|audit|enforce`）です。どの軸も
他の軸を有効化しません。4 通りの研究／論文トポロジすべてが、同じ context 契約と
readiness 契約を消費します。

## 権限レイヤ

- コンパイラが inventory、適用可能性、evidence lane、omission、readiness を
  所有します。これらは決定論的な事実であって、モデルの判断ではありません。
- writer と reviewer が所有するのは散文への注記だけです。requirement の status を
  変えることも、証拠を昇格させることもできません。
- RQGM は、有効なとき修復提案の系譜を統治します; 修復エンベロープは
  requirement ID、変数、許可された変更、予算、source context を固定します。
- KCA は Knowledge lock、Provider binding、target を厳密に指定した Harness
  attestation を供給します。修復はそれらの identity を継承し、新しい Provider や
  Harness を昇格させることは決してありません。
- assurance の権限は事実レイヤの上で止まります。`ScienceData` 契約は attestation も
  tier も certification 状態も持たず、コンパイラは `science_data.json` を、digest は
  取るが決して書き換えない通常のチェックポイント成果物として inventory に載せます。
  したがって `assurance.mode` がノードの測定を動かせるのは `publishable` と
  `exploratory` のあいだだけであり、どちらも主張に使える事実です;
  `contextual_negative` や `excluded` への降格は、mode に依存しないシグナル —
  実行結果、成果物の来歴、陳腐化、測定の不在、記録された failed / tampered な
  property 判定 — からのみ生じます。assurance mode を引き上げることが変えるのは、
  肯定的な主張に対してどの証拠が許容されるかであって、どの測定が記録されたかでは
  ありません。
- Knowledge レコードと Capability レコードは来歴であって昇格ではありません。
  どちらも evidence lane の決定への入力ではなく、その決定が読むのは、ノードの実行
  status、実際の測定を持つかどうか、成果物の来歴、フロンティア上の有効性とクラス、
  property 判定、assurance と attestation の状態だけです。したがって Knowledge の
  被覆が記録されていないノードは、失敗した測定ではなく、記録された文脈がより少ない
  測定にすぎません。
- `enforce` の下では、Harness attestation が無いと current-certification の
  requirement は `unavailable` になり、attestation はあるが未認証の候補ではそれが
  `missing` になります。どちらも `assurance_certification` resolver を伴うため、
  公開はブロックされたまま、ギャップは修復可能なままです。どちらもレガシー
  アクセスの暗黙の付与ではありません。後続の修復 request は、必要とする capability
  と Harness の identity を名指しします; manuscript レイヤはそれらの identity を
  記録するだけで、自ら付与することはありません。
- publication evaluator は hard gate を互いに独立に保ちます。レビューのスコアが、
  失敗した claim / certification / compile / reproduction / freshness の各 gate を
  埋め合わせることはできません。

## Evidence lane と主題の選択

`publishable` の証拠は肯定的な主張を支えてよいものです。`exploratory` の証拠は
議論してよいものの、主要な証明として使うことは禁じられます。`contextual_negative`
の証拠は、失敗・null・放棄・結論不能の履歴として見えるまま残さなければならず、
肯定的な事実を支えることはできません。`excluded` の証拠は stale、消去済み、
改竄済み、あるいはその他の理由で許容されないものです。

科学的な勝者は、公開適格性が評価される前に凍結されます。認証済みの次点は利用可能な
代替として報告されますが、未認証の勝者を黙って置き換えることはありません。その
ような変更には、明示的な選択ポリシーの決定と、新しく束縛された attempt が必要です。

## ワークフローと状態

唯一の `ari-core/config/workflow.yaml` が、追加的な
`evidence|authoring|verification` のメタデータを担います。選択されたランは一時的な
無効ステージのビューを導出します; 2 つ目の manuscript ワークフローは存在しません。
各セグメントは、自身の workflow digest、解決済みステージ、論理的な入力、変更された
出力、status、source attempt を記録します。completed なレコードが再利用できるのは、
入力と出力のすべての digest が fresh であるあいだだけです。

attempt は snapshot と profile の digest から導出され、
`.ari-manuscript/attempts/<attempt-id>/` の下に保存されます。状態変化は、追記専用で
digest 連鎖した遷移ログを成します。新しいソースバイトは新しい attempt を作ります;
古い attempt とブロックされたドラフトは監査のために保持されます。

## バックエンド統合

`audit` では、レガシーな writer の入力と出力の挙動が権威を保ったまま、コンパイラが
シャドウ bundle とシャドウ publication decision を出力します。`enforce` では、
linear writer は境界のないレガシー context ではなく、レンダリング済みの section
brief を受け取ります。RQGM archive の候補も同じ brief と authoring binding を
受け取ります; archive が失敗したときのフォールバック先は、束縛された linear writer
に限られます。どちらのバックエンドも research executor を受け取りません。

`audit` が生成しないものが 1 つあります: 比較です。レガシー writer の payload を
manuscript の inventory と突き合わせる audit モードの成果物 — context には
あるが writer の payload には無い項目、writer の payload にあるが型付き context
の出所を持たない項目、cap または budget に起因して観測された omission、
failed/null/系譜外の可視性の差分、authoring に出ていない assurance と provenance
のフィールドを記録するもの — は予約された設計であり、実装されていません。
`ari-core/ari/manuscript/coordinator.py` の `compile_manuscript` が永続化する
attempt 成果物の種類は `audit` でも `enforce` でも同じ — snapshot、requirement
profile、context、omission manifest、readiness、そして brief が組み立てられた
場合は brief bundle と authoring binding — であり、その中に比較のレコードは
ありません。したがって audit 実行が定量化しないまま残すのは、コンパイラが
組み立てたものと、writer が実際に渡されたものとの差です。

共有されるバックエンドインタフェースのオブジェクトは存在しません。両バックエンドは
同じ authoring binding と section brief の bundle を消費しますが、別々の呼び出し
経路を通ります: linear の authoring はワークフローの `authoring` セグメントを
走らせ、archive は `PaperArchiveRuntime.run_archive` を走らせます。後者は linear
パイプラインを明示的なフォールバック callable として受け取ります。共通の
`PaperBackend` 型 — バックエンド、mode、入力 digest、候補と勝者の系譜、ドラフト
成果物の digest、モデル使用量とコスト、hard-disqualification の理由を単一の
レコードで返す 1 つの `generate` エントリポイント — は予約された設計であり、
実装されていません。archive の実際の結果面は `paper_archive_state.json` 上の
`manuscript_authoring` です: status、束縛された manuscript 入力とその fingerprint、
`stale_reasons`、`failure_reason`、`winner_id`、`winner_tex_sha256`。モデル使用量と
コストはそこに含まれません; エポックごとの expansion、adversary、anchor 採点、
prompt candidate、compile の各カウントは、同じファイルの `budget_counters` へ別途
ミラーされます。enforce の下でフォールバックが許容されるかどうかは、インタフェース
ではなく、フォールバックの callable 自体に設定された `_ari_manuscript_bound` 属性が
担います。

RQGM archive は、開始または再開の前に、attempt ローカルな profile、snapshot、
omission、context、readiness、brief、binding の連鎖を厳密に検証します。正準な
archive 入力 fingerprint はさらに、すべての section brief digest、allowed /
contextual-negative / forbidden の evidence ID、必要な開示、omission の件数を
覆います。この fingerprint は `paper_archive_state.json`、すべてのドラフト
レコード、統治された reviewer のレビューレコードに保存されます。進化した writer や
reviewer のプロンプトハッシュは別個の identity のままです: プロンプト進化が固定
された manuscript ブロックを変えることはできません。

enforce モードでは、各候補は best-belief 選択の前に、読み取り専用の予備的な
claim gate、成果物／来歴の検査、contextual-negative / forbidden の evidence ID
検査、必須開示の検査を受けます。各候補は内容についてだけでなく、凍結された bundle
そのものに対しても再検査されます: そのノードとエポックに対応するドラフトレコードが、
bundle 自身の入力 fingerprint を、binding、profile、context、readiness、
brief-bundle の各 digest とともに持っていなければならず、`enforce` の下では
そのレコードが manuscript-bound と印されてもいなければなりません。現在のエポックに
対応するドラフトレコードを持たない候補も、同じようにこれらの検査に落ちます。この
不一致はそれ自体が hard な理由なので、より前の bundle の下で書かれたドラフトは、
本文が綺麗であっても後の bundle の下で勝つことはできません。hard に落ちた候補は
archive 履歴に残りますが `_valid_for_frontier=false` を持ちます; reviewer の
utility がそれを埋め合わせることはできません。最終の publication evaluator は、
linear と archive のどちらの authoring についても、正確な最終 TeX に対して
evidence lane と開示の検査を繰り返すので、候補のスクリーニングが唯一の
インタロックであることは決してありません。audit モードは同じ診断を記録しますが
authoring の適格性を変えず、結果をレガシー authoring とラベル付けします。変更の
ない再開は束縛済みのレコードを再利用し、fingerprint が変わっている場合は、勝者
スキップ経路にも新しいモデル呼び出しにも入る前に検出されます。enforce の下で
archive の生成が失敗した場合、許されるのは同じ binding を消費すると明示的に印された
フォールバックだけです。

manuscript の binding が archive の選択に加算的な utility 項を寄与することは
ありません。候補の manuscript 評価が書くのは診断であり、`enforce` の下では
埋め合わせ不能な `_valid_for_frontier=false` センチネルです; ドラフトの
`_scientific_score` は archive の reviewer が与えたスコアのままで、manuscript の
パスがそれを書き換えることは決してありません。段階評価される manuscript の軸 —
必須 section 項目の被覆、claim–evidence リンクの被覆、記録された参照文献に対する
引用の適切さ、そして pass/fail ではなくスコアとして表される開示の完全性 — は予約
された設計であり、実装されていません。また brief は、それらを採点するために必要な
ものを運んでいません: brief の evidence lane が束縛するのは参照文献ではなく
evidence ID であり、参照文献が writer に届くのは通常の `related-work` コンテンツ
項目としてだけで、個々の主張をそれを支える証拠や参照文献に結び付ける構造は brief の
中に存在しません。存在するのは三値で埋め合わせ不能な区別です: 候補は `admissible`
であるか、`audit_findings` を持つか、`enforce` の下では `hard_disqualified` である
かのいずれかです。

archive の所見は archive の内側に留まります。それらはドラフトレコードと archive の
状態に永続化され、archive の外側でそれらを読むものはありません: 型付きの
`paper_diagnostic` レコードは無く、執筆時の所見を requirement ID に対応付ける
validator も無く、archive の所見から修復 request へ至る経路もありません。修復 plan
が導出されるのは、status が `missing` または `unavailable` であり、かつ resolver の
種別を名指しする readiness の requirement 行からだけであり、各 request はそれが
答える requirement ID に束縛されます。適格な archive の診断を固定された validator を
通じて後続の修復ラウンドへ受理することは予約された設計であって現在の挙動ではなく、
それを統べることになる規則も同様です: 診断から修復への対応付けは、問題となった
ドラフト、ビルド、主張、証拠の digest を、それが上げる request に束縛しなければ
ならず、同じギャップについての readiness と pre-flight のシグナルに対して重複除去
されなければなりません。どちらの半分も実装されていません。
`ResearchRepairRequestV1` は `target_claim_ids` と `target_node_ids` を宣言しますが、
唯一のプロデューサは両方を空のままにし、契約自身の identity 重複 validator 以外に
それらを読むものはありません; ドラフトレコードが実際に運ぶ digest — その TeX
ハッシュ、予備的な claim gate レポートの digest、そしてそれが書かれた時点の
manuscript 入力・binding・profile・context・readiness・brief-bundle の各 digest —
は、その 1 つの候補についてのスクリーニング証拠であって、どの request のキーにも
なりません。文章品質についての所見には、そもそも archive の外へ出る経路が
まったくありません: この境界は今日、検査によってではなく構造によって保たれています。

### RQGM paper-candidate pre-flight

`ari.mode: ari_rqgm` の下では、共有された paper dispatch が、manuscript 軸を解決する
よりも、また何かをコンパイルするよりも*前に* RQGM の paper-candidate pre-flight を
走らせます。そのラウンドで judge に検証された攻撃は、境界の付いた utility ペナルティ
を適用し、それがノードの `_scientific_score` をその場で書き換えます。そして探索の
snapshot が候補を並べ `scientific_winner_id` を確定するときに読むのは、まさにその
キーです。したがって pre-flight での降格は manuscript の科学的な勝者を動かし得ますが、
それこそが意図です: 論文が対象とする主題は、最後のガバナンスラウンドの前ではなく
後の勝者であるべきだからです。

このラウンドは論文自身の成果物を攻撃するため、そのうち少なくとも 1 つが既に存在する
ことを条件にゲートされています。1 つも無いとき pre-flight は延期され、dispatch は
linear 側と archive 側の両方で、論文フェーズの後に一度だけそれを再度呼び出します
（1 回の dispatch で二度走らないようガードされています）。その後段のラウンドが走るの
はパイプラインが終わった後であり — manuscript 軸が有効なときは、この attempt の
snapshot、readiness レポート、brief、verification も終わった後です — その後に
snapshot を作り直すものは何も無いので、そのペナルティが選択に届くのは、それを生んだ
ランの中ではなく、次回の呼び出しで replay を通じてです。

この継ぎ目における分業のすべては順序です。requirement の status を割り当てるのは
readiness evaluator だけであり、それは requirement profile、コンパイル済み context、
omission マニフェストの純粋関数です; 敵対ケースログを読むことは決してありません。
エスカレーションのラウンドが変異させるのはメモリ上のノードだけであり、snapshot が
inventory に載せるのは既知のチェックポイント成果物の固定リストで、そこにガバナンスの
ログは 1 つも含まれません。したがって pre-flight から manuscript コンパイラへ通じる
唯一のチャネルは、snapshot が読むノードスコアです。ゆえにパイプライン後のラウンドが、
既に記録された `missing` や `unavailable` の requirement を `satisfied` に変えること
はできません。

再適用を防ぐのは bundle の digest ではなくレコードの identity です。各ペナルティは
敵対ケースログ内の `utility_record` 行であり、base、penalty、final の各スコアを値で
運びます。再読み込み時、レコードがノードへ replay されるのは、そのノードの現在
スコアがそのレコードの保存された base スコアとまだ等しいあいだだけです; 既に final
の値になっているスコアや、その後に再計算・再採点されたスコアはそのまま放置されます;
そして後続レコードの `supersedes` に名指しされたレコードが再適用されることは決して
ないので、ノードを免責したフロンティア修復が取り消されることはありません。ラウンド
マーカーはノードごと・ラウンド種別ごとに一度きりなので、paper-candidate ラウンドは、
あるノードについてすべての呼び出しを通じて高々一度しか走りません。すべてのステップは
fail-open です: 失敗はログに残るだけで、論文パイプラインをブロックすることは決して
ありません。

pre-flight は探索の軸の上に載っています。`manuscript.mode: off` は manuscript の
コンパイルと readiness gate を取り除きますが、pre-flight は取り除きません。そして
`manuscript.mode` のどの値も、このラウンドが発火するかどうかを変えません。

## レガシー context 組み立てと、それを削除するための条件

レガシー経路は、射影された ScienceData、構成ごとの結果、候補 claim、ソース抜粋、
図の context、検索された参考文献を 1 本の `experiment_summary` 文字列へ連結して
writer 入力を作り、その文字列を budget ではなく 4 つの固定 cap で有限に保ちます。

| cap の対象 | cap | 場所 |
|---|---|---|
| 構成ごとの結果エントリ | 10 | `ari-skill-paper/src/server.py` の `write_paper_iterative` |
| 候補 claim | 20 | 同じ関数; `ari-core/ari/pipeline/verified_context.py` の `render_grounded_block` の `max_claims` がこれをミラーします |
| 引用候補として提示される参考文献 | 12 | 同じ関数の reference-context ブロック |
| authoring プロンプト中の実験 context の文字数 | 48,000 | 同じ関数の authoring 呼び出し地点 |

これらは budget ではなく truncation です。スライスが何を落としたかは記録されず、
落ちたものは後から参照できず、必須の事実と任意の事実が同じ規則 — リスト中の位置
— で捨てられます。

manuscript モードはこれらの cap を緩めるのではなく、迂回します。最初の 3 つの
ブロックは authoring 入力が manuscript binding を持たないときにだけ組み立てられる
ので、束縛された run はそれらをそもそも組み立てません。`enforce` では
`ari-core/ari/pipeline/driver.py` の manuscript 境界が、authoring のモデル呼び出しが
始まる前に `experiment_summary` と `paper_context` のテンプレート変数を、
レンダリング済みの section brief bundle で置き換えます; RQGM archive も同じ bundle を
自分の writer / reviewer プロンプトへ束縛します。`audit` は意図的に writer の bytes と
テンプレート入力を触らず、`off` では境界は import も含めて no-op です。したがって
10 / 20 / 12 / 48k の挙動は、`off` または `audit` の run が今も受け取るものそのものです。

`enforce` で cap を置き換えるのは、accounting を伴う section 単位の budgeting です。
`manuscript.brief_character_budget`（既定 24,000 文字、run 単位ではなく section 単位）が
各 section brief を bound し、収まらない必須の disclosure や必須項目は黙って落とされる
のではなく raise し、各 brief は `omitted_item_ids` を持つ（renderer がこれを出力する）
ので、budget が実際に落としたものは ID で参照可能なまま残ります。

実装として出荷されている挙動のうち 2 点は、置き換えを読み過ぎうる箇所なので、
正確に述べておきます:

- `ari-core/ari/manuscript/briefs.py` の builder は現在、省略ではなく *分割* します。
  budget を超えた section は `<section>`、`<section>.part-002` … となり、この builder が
  作るどの brief でも `omitted_item_ids` は空のままです。省略のチャネルは contract と
  renderer には存在しますが、それを埋める出荷コード経路はまだありません。
- 48,000 文字の truncation は manuscript モードに条件づけられていません。authoring
  呼び出し時点で `experiment_summary` が保持しているもの — レンダリング済みの brief
  bundle を含む — に適用されます。brief の budget は section 単位なので、section 数が
  十分に多い bundle は 48,000 文字を超え、レガシーのスライスに切られ得ます。

レガシー組み立てとその cap の削除は、manuscript モードが存在することでは正当化され
ません。削除には次の 4 つがすべて成り立つことが必要です:

1. サポートされるすべての manuscript 有効バックエンドが section brief を消費する;
2. `off` の互換ポリシーに承認済みの置き換えがあるか、deprecation リリースがある;
3. 同等のレガシー fixture カバレッジが新経路に存在する;
4. マイグレーション／リリース文書が、変化した出力挙動を明示している。

4 つがすべて成り立つまで、レガシー経路と manuscript 経路は融合させず明示的なまま
保たれます。ただし今日の時点で完全に素な関係ではありません。図の context ブロックは
manuscript binding で gate されていない唯一のレガシーブロックであり、どちらの
バックエンドも writer に figures manifest を渡し続けるため、`enforce` の下でも
writer 入力はレンダリング済みの bundle にその図の行が連結されたものになります。
binding が実際に置き換えるのは、上限の掛かった 3 ブロックと 2 つのテンプレート変数
です。

これらは将来ありうる削除に対する条件であり、スケジュールでも、削除を行うという約束でも
ありません。今日コード上で観測できるのは、この条件がまだ実在するものを gate している
こと — レガシー組み立ては存在し到達可能で、`off` と `audit` のすべての run が使うのは
それであること — と、出荷されている 2 つの authoring バックエンドがどちらも `enforce`
の下で既に brief を受け取っていることだけです。それが 1 番目の条件を満たすかどうかは、
どのバックエンドをサポート対象とするかというリリース上の判断であって、コードが答える
ことではありません。

## 自動修復ラウンド

自動の研究修復が存在するのは `ari run` と `ari resume` の中だけであり、しかも
`manuscript.mode` が `enforce` かつ `manuscript.repair.policy` が `auto` のときだけ
です。research executor を組み立てて paper dispatch へ渡すのはこの 2 つのエントリ
だけなので、`ari paper` は修復 plan を報告できても実験を開始することはできません。
修復が作るのは高々 admit されたノードだけで、通常の BFTS/RQGM 実行ループを使い、
通常の RQGM/KCA フックを走らせます。

この姿勢の下では、論文フェーズは evidence セグメントと最初の authoring 呼び出しの
あいだで、境界の付いた外側ループを走らせます。1 ラウンドは次のとおりです:

```text
evidence segment
        │
        ▼
compile ── context / omissions / readiness
        │
        ├─ authoring-ready ────────► leave the loop and author
        ├─ no admitted request ────► stop, blocked
        ▼
admit the ordered plan → execute each admitted request once
        │
        ▼
commit the round record → rebuild evidence → recompile as the next round
```

ラウンドはゼロから番号が付き、連続していなければなりません。ラウンド予算が上限を
掛けるのは、そのチェックポイントが合計で何ラウンドをコミットするかであり、呼び出し
ごとでも attempt ごとでもなく、永続化されたラウンドレコードから数えられます。それら
のレコードは attempt の成分を持たない 1 つの `.ari-manuscript/auto-rounds/`
ディレクトリに置かれ、ガードはその中のすべてのレコードを最大値と突き合わせます;
attempt ID は snapshot と profile の digest から導出され、各ラウンドは証拠を再構築
するので snapshot を動かします。したがって 1 つのループの連続するラウンドが異なる
attempt に属しながら、同じカウンタを削っていくことがあります。

ループが readiness に先んじて執筆することは決してありません。linear と archive の
どちらのバックエンドも、authoring のモデル呼び出しの前に evidence セグメントを
走らせ、コンパイルし、ループに入ります。ループが未 ready を返した場合、フェーズは
ドラフトを書く代わりに authoring のブロックを送出し、archive 側では状態が
`authoring` へ移る前に送出します。audit モードがループに入ることは決してありません。

request は resolver の種別ごとにまとめられ、固定された resolver の優先順位 —
派生的な再構築と retrieval が新しい実験より先、人間の決定が最後 — で並べられるので、
同じ readiness は常に同じ plan を生みます。実行は科学的なことを何も主張しません。
コーディネータは測定を行わず、executor の結果が requirement を閉じることもありません:
requirement が閉じるのは、再構築された証拠と再コンパイルされた readiness がそう言う
からにほかなりません。

各 request は自分の resolver が返るとすぐに不変のトランザクションをコミットし、
ラウンドレコードは plan 全体が走った後、証拠の再構築の前にコミットされます。
したがって中断は繰り返しではなく replay になります: 既に記録された request は再度
呼び出されるのではなく、追加の予算コストゼロでそのトランザクションから再利用され、
既に記録されたラウンドは再構築と再コンパイルへ直接スキップします。

自動化は予算を使ってよいものの、権限を広げることは決してありません。admit された
すべての request は、自分の resolver が走る直前に、現在の source context digest と、
plan が admit された時点で捕捉された権限 digest に対して再検査されます。stale な
context や変わった権限は、古いエンベロープの下で request を実行するのではなく、その
request を失敗させます。比較対象となる権限スナップショットは、資格情報が無いことを
明示するマーカーを伴った成果物 identity と mode 名の一覧なので、それを再検証しても
確認できるのはエンベロープが変わっていないことだけです; それ自体が付与になることは
決してありません。

admit された実験 request が実体化するノードはちょうど 1 つです。そのノードの
identity は request の digest から導出され、request ID、requirement ID、source
context digest、許可された変更は、ノード自身のフィールドです。ノードは研究ループに
入る前にチェックポイントへ書かれるので、中断されたラウンドは、同じ request に対して
2 つ目を開くのではなく、同じ系譜に束縛されたノードへ再開します。RQGM が有効なとき、
ノードは通常の expansion と同じ 2 つのフックを、同じ引数で通ります: 現在のエポックが
それらを持つときにエポックのコンポーネント、プロンプトハッシュ、エポック ID をノード
へ書き込むプロデューサスタンプと、親 → 修復ノードの組に対する expansion 提案
レコードです。したがって修復は、系譜の脇からではなく通常の扉から系譜に入ります。

続いてノードは通常の研究ループによって実行されます。そのあいだ、ランのノード上限は
現在のツリーサイズに保たれます。ループが展開するのはツリーがその上限より小さい
あいだだけなので、修復ノードは最後まで実行されますが、その後に自分自身のフロンティア
を展開することはできません。ランの元の上限は後で復元され、ループが例外を送出した
ときも復元されます。これが修復ラウンドを加算的に保つものです: 修復ラウンドは admit
された予算を消費し、新しい探索ではなく束縛された 1 つのノードを残します。

停止はブロックと同じではありません。ラウンド予算または累積予算を使い切ること、
あるいは context digest も requirement の status も変えなかったラウンドを完了する
ことは、attempt を `repair_pending` のままにします。空の plan、resolver の不在、
`human_required` の結果は、代わりに `blocked_unavailable` を記録します。どちらの
遷移も、attempt の現在の状態から合法であるときにだけ書かれるので、停止が繰り返され
ても同一のホップが 2 つ追記されることはありません。

ループに入るのは 1 回の呼び出しにつき高々一度、authoring の前のその 1 点だけです。
authoring 中、verification 中、あるいは publication decision の時点で初めて見える
ようになった診断が、そこへ再び入ることはありません: `enforce` の下では publication
evaluator が `finalized` または `publication_blocked` を記録し、パイプラインはその
decision を返し、その後ループを呼ぶものは何もありません。ループ自身の受理ステップが
`repair_pending` へ昇格させるのは `blocked_unavailable` だけで、
`publication_blocked` は決して昇格させません。したがって、さらなる修復のために
`publication_blocked` から出ることはオペレータの行為です — その遷移を発行する唯一の
コード経路は明示的な `ari manuscript repair` であり、これは選択された admit 済みの
request を実行し、再コンパイルします。代わりに `ari run` や `ari resume` を再実行
した場合は、現在のソースバイトを改めて束縛し、その新しいコンパイルがもう一度
authoring-ready でなかったときにだけ自動ループへ再び入ります。authoring 後の診断
から同一呼び出し内で新しい番号付きラウンドへ戻り、ドラフトを自動的に無効化すること
は、予約された設計であって実装されていません。

## 読み取り面

Manuscript Complete は GUI も REST の面も持ちません。コミット済みの
`ari-core/ari/viz/v1/openapi.json` は manuscript のエンドポイントを 1 つも宣言して
おらず、[REST API リファレンス](../reference/rest_api.md)も
[ダッシュボードアーキテクチャ](gui_architecture.md)もそれを記述していません。

オペレータが読むのは `ari manuscript` コマンド群と、`.ari-manuscript/` 配下の
attempt 成果物です。すべてのサブコマンドは JSON を印字し、何かを決める 4 つは、
答えが no のとき `2` で終了します: `status --fail-if-blocked` は `repair_required`
または `blocked` の authoring verdict、あるいは `blocked` の publication verdict の
とき、`repair` は実行した request に続く再コンパイルが、admit されたいずれかの
request の requirement を閉じないまま残したとき、`explain-publication` は
`publishable` 以外のあらゆる decision のとき、そして `lock-publication` は lock が
拒否されたとき — publishable でない decision、現在のビルドをもう名指ししていない
decision、finalize されていない attempt、変わった入力、stale な reproduction の証拠、
あるいは唯一の最終 PDF が無いこと。ビューアが無いことを無害にしているのは、この
性質です: いかなる公開安全性の保証もビューアの存在に依存してはならないので、
ダッシュボードが使えないことが、安全でないビルドが公開された理由になることは決して
ありません。

読み取りモデルは予約された設計であり、実装されていません。もし追加されるなら、
それは同じ `ari.public.manuscript` 契約を読み、それらの契約が既に運んでいるもの —
requirement のマトリクス、evidence lane、omission、修復の予算、attempt の系譜、
そして互いに独立した publication gate — だけを表示し、readiness を再計算したり自前の
gate verdict を導出したりしては決してなりません。readiness 規則の 2 つ目の実装は、
2 つ目の真実源になってしまいます。

[契約](../reference/manuscript_complete_contracts.md)、
[profile ガイド](../reference/manuscript_complete_profile.md)、
[オペレータランブック](../guides/manuscript_complete_operations.md)を参照してください。
