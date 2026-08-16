---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate/policy.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

# 最初の実験を、はじめから終わりまで

[クイックスタート](quickstart.md)は *どのボタンを押すか* を示します。このチュートリアルでは、
1 つの小さな実験を最初から最後までたどり — 目標 → 仮説 → 探索 → 論文 → 再現 — 各ステージが
*なぜ* 存在するのかを解説します。読み終える頃には、ARI がチェックポイントに残すすべての
ファイルを見分けられるようになり、より深く知りたいときにどのドキュメントを開けばよいかが
分かるようになります。

メカニズムに焦点を当てるため、あえてシンプルでドメインに依存しない目標を使います:
**このマシン上で密行列積ルーチンを高速化する。** ARI はこのために特化されているわけでは
ありません — 同じパイプラインは測定可能なあらゆる目標で動作し、ドメイン固有の選択はすべて
実行時に LLM が行います。

> **始める前に:** [クイックスタート](quickstart.md)を終えて、ダッシュボードが
> <http://localhost:8765> で立ち上がり、モデルが設定されている状態にしてください。

## 1. 目標を述べる（`experiment.md`）

実験ファイルはプレーンな Markdown です。最小構成は研究目標を数行書くだけ — コードは不要です:

```markdown
# Goal
Improve the throughput (GFLOP/s) of a dense single-precision matrix
multiplication on the available hardware. Compare against a naive triple loop.
```

これで十分です。あとから `## Provided Files` や制約を追加できますが（[実験ファイルの書き方](../guides/experiment_file.md)を参照）、
具体的な内容は ARI 自身が埋めます。

## 2. 起動

ダッシュボードでは **New Experiment** を使い、最初の実行は小さく保ってください（深さ 3、
ノード 5〜10、ワーカー 2〜4）。あるいは CLI から:

```bash
ari run experiment.md
```

`workspace/checkpoints/<timestamp>_<slug>/` にチェックポイントディレクトリが現れます。
以下のすべてはそこに着地します。

## 3. 調査と仮説（ルートノード）

最初のノードは、枠組みづくりの作業を順番に行います:

1. **`generate_ideas`** — VirSci のマルチエージェント討議が問題を議論し、`idea.json` を
   書きます: 仮説、主要メトリクス、実験プランです。これは実行全体で **一度だけ** 走り、
   主要メトリクス（ここでは GFLOP/s）とその方向（高いほど良い）を **設定** します。
2. **`make_metric_spec`** — その idea の `primary_metric` *から* 具体的な成功メトリクスを
   導出します（自由な推測ではありません）。
3. **`survey`** — 最終的な論文が実在の参考文献を引用できるよう、文献を検索します。

提案された内容は **アイデア** ページを開いて読んでください。

## 4. 探索（BFTS）

ここから ARI が探索します。これは線形のスクリプトではなく — [最良優先木探索](../concepts/bfts.md)です:

- 各 **ノード** は 1 つの具体的な試行で、[ReAct エージェント](../concepts/architecture.md#per-node-prompt-composition)が
  実行します。エージェントはコードを書き、（ローカルまたは SLURM 経由で）投入し、出力を読み、
  メトリクスを抽出します。
- 完了したノードは **frontier** に入ります。ARI は最も有望なものを繰り返し選び、
  `improve`、`ablation`、`validation`、`debug`、`draft` のいずれかのラベルが付いた
  単一の子へと **展開** します。
- ピアレビュアーの LLM（**`LLMEvaluator`**）が各ノードの `_scientific_score` を採点し、
  そのスコアが次にどのノードを展開するかを駆動します。

これは **実行モニター** ページと **探索ツリー** ページでライブに観察できます。ノードごとの詳細
パネル — Overview、MCP Trace（すべてのツール呼び出し）、Code、Memory、Access、Report — を見るには
レガシーのツリーページ `#/tree` を開いてください。Output タブはありません。ノードのファイルは
ファイルエクスプローラから閲覧します。

初心者を驚かせる挙動が 2 つあります — どちらも意図的なものです:

- **失敗ノードは再実行されません。** ARI は代わりに `debug` 子を展開するので、修正は
  新しいノードとして記録されます。
- **何も変えない子は _sterile_ とマークされ、二度と展開されません。** 出力ファイルは
  親から継承されないため、子は実際に実験を再実行しなければなりません。実行が固定問題
  （`ARI_PROBLEM`）を指定している場合、その問題が `score_inputs` を宣言し、sterile 判定は
  work_dir 全体の差分ではなく、まさにそれらのファイルのハッシュで決まります — work_dir 全体の
  規則は実際にはほとんど発火しません。どのノードも `results.json` のような記帳用ファイルを
  書き換えてしまうからです。
  sterile なノードは測定されたスコアと評価ステータスをそのまま保持します。失うのは展開される
  権利と、親を退役させる権利です。
  （[FAQ](faq.md)と [用語集 → sterile](../reference/glossary.md)を参照。）

探索はあなたのノード数/深さの予算で停止します。完全なツリーは `tree.json` / `nodes_tree.json`
として保存されます。

## 5. ツリーから論文へ（BFTS 後のパイプライン）

探索が終わると、`workflow.yaml` 駆動のパイプラインがツリーを論文に変換します
（[公開ライフサイクル](../concepts/publication-lifecycle.md)を参照）:

1. **audit_node_provenance** が、node_report に sha256 が記録されたノード成果物を
   すべて再ハッシュしてディスク上の実体と照合します — ノード出力が「実験結果」で
   あることをやめ「論文の証拠」になる、まさにその境界でです。成果物ごとに
   verified / mismatch / missing / unhashed を `node_provenance_audit.json` に
   報告します。ゲートではなくシグナルです。
2. **transform_data** がツリー全体を読み、ハードウェア、方法論、発見を
   `science_data.json` に抽出します。
3. **generate_ear** が再現性バンドル `ear/` を組み立てます（コード、入力データ、図表、
   `reproduce.sh`、LICENSE — ただし実験の出力は含めません）。これは論文が書かれた *後* では
   なく *前* に走ります: `write_paper` がこれに依存しているからで、バンドルこそが論文の指し示す
   証拠だからです。
4. **generate_figures** では、LLM は各図が「何を」示すか（メトリクス、チャート種別、
   x 軸）だけを選び、固定のレンダラが `science_data.json` から決定論的に描画します。
   続いて **VLM** が**すべての**図をレビューし、集約スコアは図の最小値なので、
   1 枚でも弱い図があればステージがループバックして再生成されます
   （しきい値 0.7、追加パスは最大 2 回）。
5. **write_paper** が LaTeX を起草し、推敲し、調査結果から BibTeX を取り込みます →
   `full_paper.tex` / `.pdf`。
6. **review_paper** が選択されたベニュールーブリックに対して 1 名以上のレビュアーエージェントを
   走らせます（2 名以上いる場合は Area Chair のメタ査読が集約します）。

デフォルトでは、パイプラインは現在 **claim-evidence 検証ループ** も実行します: 決定論的な
ハードゲートが報告された数値を再導出し、ブロックしない evidence-grounded セマンティックレビューが
その根拠に照らして本文を検査し、続いてアンカーを保持する推敲と再レンダリングがループを閉じます。
既定は **warn** モードですが、これは「報告のみ」ではありません: warn でも
objective-integrity の階層（`always_block_on` — 不変条件違反、correctness の失敗や
未カバー、プレースホルダの分母、再計算の不一致、未束縛・不一致の成果物…）は
最終ゲートをブロックします。これらは査読者の主観ではなく決定論的に偽だからです。
それ以外の指摘は報告されるだけで、`ARI_CLAIM_GATE_MODE=strict`（または
`claim_gate_policy.mode: strict`）を設定して初めてブロックされます。strict は
設定済みの `block_on` 指摘と、strict セクションの未カバーの結果数値も追加で
ブロックします。`mode: off` は決してブロックせず、draft フェーズのレポートも
どちらのモードでもブロックしません。詳細は[公開ライフサイクル](../concepts/publication-lifecycle.md)を参照してください。

すべてはサイドバーの **論文・成果** から読めます。このスロットはランを明示した
**読み取り専用**の要約（`#/results2?run=<run_id>`）を開きます — 査読スコア、再現性チェーン、
公開系譜です。Overleaf 風エディタと EAR ブラウザ（および EAR に対するすべての変更操作）は、
そこからリンクされるレガシーページ `#/results` にあります。

## 6. 再現性を検証する（ORS）

最後に ARI は、独立した審査員がするやり方で自身の成果を検証します
（[ORS](../guides/paperbench/paperbench_quickstart.md)）:

- **Phase 0** が最終論文から PaperBench ルーブリックを生成し、続いて何かが採点される前に
  **そのルーブリック自体を監査** します。各リーフに `vague_qualifier` /
  `no_paper_evidence` / `duplicate` / `unverifiable` のフラグを立て、フラグを
  `ors_rubric.json` に書き戻します（サマリは `ors_rubric.audit.json`）。採点自体は
  そのまま続行されます — これは品質シグナルであり、どの基準が不健全だったかを
  読み手が見られるようにするためです。
- **Phase 1** がサンドボックス内で `reproduce.sh` を実行し（利用可能なら SLURM、なければ
  docker / apptainer / local）、期待される成果物が現れるかを確認します。
- **Phase 2** が結果をそのルーブリックに対して採点します。これには
  **negative control**（空のリポジトリはゼロ近くのスコアにならなければならない）が含まれ、
  何もしないことで採点を得られないようにします。

判定は `ors_grade.json`（採点ステータス、リーフごとのスコア、negative control の結果）に
あり、Phase 1 の結果は `ors_phase1.json` にあります。

## 7. これで手元にあるもの

`workspace/checkpoints/<timestamp>_<slug>/` の中に:

| ファイル | 内容 |
|---|---|
| `idea.json` | VirSci による仮説 + プラン |
| `tree.json` / `nodes_tree.json` | メトリクス付きの完全な探索ツリー |
| `science_data.json` | 整形済みのサイエンス向けデータ |
| `full_paper.tex` / `.pdf` | 生成された論文 |
| `review_report.json` | ピアレビューのスコアとフィードバック |
| `ear/` | 再現性バンドル |
| `ors_grade.json` | ORS の判定 |

## 次に進む先

- 目標ファイルにもっと役割を持たせる: [実験ファイルの書き方](../guides/experiment_file.md)
- 探索を深く理解する: [BFTS アルゴリズム](../concepts/bfts.md)
- 大規模に実行する: [HPC セットアップ](../guides/hpc_setup.md)
- 他人の論文を再現する: [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)

---

関連: [クイックスタート](quickstart.md) · [FAQ](faq.md) ·
[用語集](../reference/glossary.md) · [アーキテクチャ](../concepts/architecture.md)
