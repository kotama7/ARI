---
sources:
  - path: ari-core/ari/harness_registry.py
    role: implementation
  - path: ari-core/ari/harness_select.py
    role: implementation
  - path: ari-core/ari/cli/harness.py
    role: implementation
  - path: ari-core/ari/cli/__init__.py
    role: implementation
  - path: ari-core/ari/evaluator/deterministic_evaluator.py
    role: implementation
  - path: ari-core/ari/assurance/problems.py
    role: implementation
  - path: ari-core/config/harnesses/problems
    role: config
  - path: ari-core/tests/test_harness_pool.py
    role: test
  - path: ari-core/tests/test_harness_select.py
    role: test
last_verified: 2026-08-09
---

# Harness プール: 計測方法を継承するのではなく、選ぶ

**現在の位置づけ。** 以下で述べるプールは*プロトタイプ*のレジストリ
（`ari/harness_registry.py`）であり、`$ARI_WORKSPACE/harnesses/<task>/` から
harness を解決します。ARI はそのようなツリーを同梱しておらず、本研究が使った
ものは退役済みなので、オペレータが自前の harness ツリーへ `ARI_WORKSPACE` を
向けない限り、レジストリは今や何も解決しません。採点される作業は代わりに
**pinned problem** を通ります — `ARI_PROBLEM` で名指しされる
`ari-core/config/harnesses/problems/` 配下のディレクトリで、ピン留めされた
scaffolding、ピン留めされた case セット、登録済みの oracle を持ち、フラグと
計測区間は 1 つの共有計測器が所有します。レジストリに到達するのは
`ARI_PROBLEM` が未設定のときだけです。したがって以下は、プールの設計と今も
それを実装しているコードの記述であって、このリポジトリに存在する harness
ツリーの記述ではありません。

## タスクごとに harness が 1 つであることの問題

タスク名と、それを計測する方法は、かつて同じものでした。`stencil` は科学的な
問い（「この機械で 3 次元 7 点 Jacobi ステンシルを最適化せよ」）と、「どう採点
するか」への 1 つの特定の答えの両方を指していました。選ぶ対象が存在しないので、
選択もありませんでした。

これは中立な既定値ではありません。計測を信頼できるものにする性質はすべて
**選択**であり、各々の選択は一度だけ、目に見えない形で行われ、少なくとも一度は
誤っていたことが判明しました:

| 選択 | 何だったか | 何にならねばならなかったか | 誤った選択の代償 |
|---|---|---|---|
| 分母 | 素朴な実装 | 有能な凍結参照実装 | スコアが「何もしないこと」からの距離を計測していた |
| 問題サイズ | LLC の内側に収まるワーキングセット | その外側のワーキングセット | 研究が必要とした最適化の勾配が存在しなかった |
| 計測区間 | 壁時計、チーム生成を内側に含む | 内部タイマー、チーム生成を外側に | 参照実装の時間の 37〜54% は kernel ではなかった |
| ツールチェーン | 既定にピン留め | 探索空間の一部 | 同じコンパイラが 1 つのフラグで 6.8 倍動いた |
| 環境 | 周囲まかせ | 記録して検査する | 1 つの変数が同じソースを 5.9 倍動かした |

いずれも、harness が誤っていると気づくことで見つかったのであって、代替と比較
して見つかったのではありません。プールは代替を存在させるので、比較は失敗の後
ではなく前に利用できます。

## プールが変えること

**1 つのタスクが複数の harness を持ち、それらは食い違いうる。** 食い違いは結果
であって、隠すべき欠陥ではありません。擁護可能な 2 つの harness が 2 つの候補を
別々に順位付けるなら、「候補 A のほうが良い」という主張は、コードについての
主張であると同時に harness についての主張でもあったのであり、読者にはそれを知る
権利があります。タスクごとに harness が 1 つの下では、これは構造的に見えません。

**選択が明示的で記録された行為になる。** 環境記録と同じ論法です: どの harness
を、どんな代替の中から、どんな根拠で選んだのかを述べない研究は、最も重要な軸に
おいて再現可能ではありません。「最良の harness を使った」は、プールと基準が
書き留められない限り反証不能です。

**頑健性が計測可能になる。** 興味深い問いは「候補がどんなスコアを取ったか」では
なく「harness を変えてもその知見は生き残るか」です。その問いは今日、立てることす
らできません。

## harness が何のためのものかを宣言する

`harness.toml` は harness を*実行する*方法（entry, kwargs, ファイル digest,
axis, scale）を宣言します。harness が何の*ため*のものかについては何も述べて
おらず、それこそが選択に必要なものです。`[declares]` ブロックは機械可読であり、
重要なことに、**capability だけでなく限界も述べます**。これは manifest の完全性
digest の対象に含まれます。プールが選択の根拠にするものだからです: 宣言された
band を編集すれば、採点対象のバイトを 1 つも変えずに、どの harness が研究を
計測するかが変わります。

```toml
[declares]
question    = "time to solution against a competent reference, same machine"
denominator = "competent_frozen"      # naive | competent_frozen | anchor_matched | best_known
resolves    = 0.00149                  # measured band: the smallest difference it can separate
cost_s      = 97.7                     # seconds per scoring at the declared repetitions
requires    = ["c_compiler", "openmp"] # capabilities, probed by executing, not by name
sees        = ["memory_bandwidth", "numa_placement", "large_page_policy"]
blind_to    = ["problem_generation"]   # the problem arrives from outside the timed window
```

重みの大半を担うのは 2 つのフィールドです。

`resolves` は **band** です — 主張されたものではなく、計測されたものです。
0.25% より近い 2 つの候補を分離できない harness を、期待される効果が 0.1% の
研究に選んではなりません; セレクタは今それを拒否し、計測日を持たない band も
拒否します。誰かが打ち込んだ数値と誰かが測った数値は、そうでなければ区別が
つかないからです。

`blind_to` は、その harness が構造的に見ることのできないものを記録します。これは
推測ではありません: large-page ポリシーが stencil harness を 5.9 倍動かし、GEMM
と SpMM はノイズの内側に留めることが実測されました。stencil の候補だけが自前で
メモリを確保し、計測区間の*内側*でファーストタッチするからです。これはそれらの
harness の恒久的な性質であり、誰かの手控えではなく manifest に属します。

## 選択: まず手動で、次に自動で

手動の選択が先に来ますが、それは慎重さのためだけではありません。自動セレクタは、
食い違う相手となる手動のベースラインが無ければ検証できません — 突き合わせる
対象が存在しないからです。

    ari harness select --resolve 0.002 --budget-s 120 --must-see large_page_policy

は、すべての harness を順位付けし、それぞれを適格または不適格にした宣言済みの
性質を添えて出力します。そしてオペレータが選びます。このコマンドは
`ari/cli/harness.py` で定義され単体テストもありますが、**現在 `ari` CLI には
マウントされていません**: `ari harness` は assurance の harness スイートが占めて
おり、それを覆い隠すのではなくプール側の app をトップレベルから外したため、今日
この順位付けに到達できるのは `ari.harness_select.rank` 経由だけです。何も適格で
ないときは exit 2 になります。それが結果だからです: 要求が誤っているか、プールに
まだ存在しない harness が欠けているかのどちらかです。それでも最も近いものを走ら
せれば、答えではなく数値が出るだけです。自動モードは、同じ順位付けにポリシーを
適用し、結果をまったく同じように記録するものになりますが、まだ存在しません。

**セレクタは決して結果で順位付けしてはなりません。** 最良のスコアを与える
harness を選ぶセレクタは score hacking の機械であり、しかもそれは起こりやすい
事故でしょう: 「候補が最も良い成績を出す harness を選ぶ」は自然な文でありながら
致命的な基準です。選択は run の*前*に宣言された性質 — 問いとの適合、分解能、
コスト、capability、盲点 — に対して行い、決して結果に対しては行いません。これは
慣習ではなく構造的に強制されます: セレクタのモジュールは harness をロードできる
もの、結果ファイルを読めるもの、何かを実行できるものを一切インポートせず、テスト
がそれをその AST から表明します。どちらのガードも、違反したときに失敗することが
検証済みです。

## これが変えないこと

完全性のピン、変更されたファイルに対する `refusing to score` の挙動、そして
ノードの編集がスコアラに届かないという規則は、すべてそのまま変わりません。登録は
manifest の存在によるままです。タスクごとに複数の harness を持つプールは、それら
の性質をより一層必要とします。

## バリアントの作り方

バリアントは**別のディレクトリ**です — これによって各 harness は独立に
content-addressed のままになります — が、コードを**コピーしません**。リンク
します:

    harnesses/gemm_incache/
        gemm_harness.py -> ../gemm/gemm_harness.py     # symlink
        gemm_kernels    -> ../gemm/gemm_kernels        # symlink
        experiment.md   -> ../gemm/experiment.md       # symlink
        harness.toml                                   # the only real file

digest はシンボリックリンクを*透過して*読まれます。これがこのやり方を単に便利
なだけでなく正しいものにしています: 両方の manifest が同じバイト列をピン留め
するので、共有ソースを編集すると**両方**のバリアントのピンが同時に壊れます。
コピーであれば、静かに乖離していく 2 つのファイルに 2 つのピンが乗ることになり、
2 つ目のコピーは 1 つ目が既に直した scaffolding のまま採点を続けてしまいます。

異なる点はすべて manifest の中にあります:

    [harness]
    task = "gemm"                  # the question it answers; the pool it joins

    [measure_kwargs]
    shapes = [[512, 512, 512]]     # the preliminary problem: 6.0 MiB, fits in L2

問題定義を環境変数ではなく `[measure_kwargs]` に置くことが要点です。
`ARI_STENCIL_SHAPES` は、ピン留めされたバイトも manifest ハッシュも
`measure_kwargs` も動かさずに、採点対象の問題をまるごと差し替えられます —
harness は別の問題で計測した band を宣伝し続けます。宣言された kwarg は digest
の内側にあります。つまみをどうしても環境に残さねばならない場合は、band が計測
されたときの値とともに `[declares.band_conditions]` にそれを名指しします。すると
run が一致しないとき、セレクタは band を拒否します。それで問題は検出できます;
宣言された kwarg なら問題そのものが無くなります。

あるタスクに 2 つ目の harness を登録することは、意図的に**破壊的**です:
`load("gemm")` はそこで拒否し、すべての呼び出し側が harness を名指しする
（あるいは `ARI_HARNESS` を設定する）必要があります。これは設計が働いている
状態です — そうでなければ、ディレクトリ名の性質でしかないスコアが、タスクの性質
として報告されることになります — が、進行中の研究にバリアントを追加することは、
利便ではなく決断だということでもあります。

## 未解決のもの

- **誰が `resolves` を計測するか。** band は計測されねばならず、それはバリアント
  ごとにノード時間を要します（セレクタの拒否は `tools/measure_resolution_band.py`
  を名指ししますが、これはこのリポジトリに存在するファイルではありません）。また
  バリアントは、自分の派生元となった構成の band を継承してはなりません — その
  数値はもう一方の構成のものです。manifest は計測の日付と繰り返し回数を持ち、
  セレクタは日付の無い band を拒否するので、未計測のバリアントは分解能では単に
  選択不能です。セレクタがまさにその状態にあるものとして名指しする 2 つの harness
  （`erfc`、`meshpart`）は退役した workspace ツリーに住んでいたので、このリポジトリ
  から到達できる harness で band を宣言しているものは 1 つもありません。
- **harness 間の一致。** それを報告するには「2 つの harness の下での同一候補」の
  定義が必要です。凍結参照実装については素直ですが、両方でコンパイルが通るとは
  限らないエージェント生成コードについてはそうではありません。これが存在するまで、
  プールは harness を*選ばせて*はくれますが、知見がその選択を生き延びるかどうかを
  問うことはまだできません — それこそがプールが作られた目的の問いです。
- **自動選択。** 順位付けは利用できますが、それにポリシーを適用して勝者を走らせる
  ものは何もありません。それを行うものは何であれ、手動の経路が既にそうしているの
  とまったく同じように、選択と代替を記録しなければなりません。
