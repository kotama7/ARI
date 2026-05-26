---
sources:
  - path: ari-core/ari/cli
    role: implementation
  - path: ari-core/ari/agent/loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-26
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

1. **`make_metric_spec`** — あなたの目標から主要メトリクス（ここでは GFLOP/s、高いほど
   良い）を確定します。
2. **`survey`** — 最終的な論文が実在の参考文献を引用できるよう、文献を検索します。
3. **`generate_ideas`** — VirSci のマルチエージェント討議が問題を議論し、`idea.json` を
   書きます: 仮説、主要メトリクス、実験プランです。これは実行全体で **一度だけ** 走ります。

提案された内容は **Ideas** ページを開いて読んでください。

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

これは **Monitor** ページと **Tree** ページでライブに観察できます。任意のノードをクリックすると、
Overview、Trace（すべてのツール呼び出し）、Code、Output の各タブが表示されます。

初心者を驚かせる挙動が 2 つあります — どちらも意図的なものです:

- **失敗ノードは再実行されません。** ARI は代わりに `debug` 子を展開するので、修正は
  新しいノードとして記録されます。
- **新しいファイルを生成しない子は _sterile_ とマークされ剪定されます。** 出力ファイルは
  親から継承されないため、子はスコアを得るために実際に実験を再実行しなければなりません。
  （[FAQ](faq.md)と [用語集 → sterile](../reference/glossary.md)を参照。）

探索はあなたのノード数/深さの予算で停止します。完全なツリーは `tree.json` / `nodes_tree.json`
として保存されます。

## 5. ツリーから論文へ（BFTS 後のパイプライン）

探索が終わると、`workflow.yaml` 駆動のパイプラインがツリーを論文に変換します
（[公開ライフサイクル](../concepts/publication-lifecycle.md)を参照）:

1. **transform_data** がツリー全体を読み、ハードウェア、方法論、発見を
   `science_data.json` に抽出します。
2. **generate_figures** が作図コードを書き、続いて **VLM** がメイン図をレビューし、
   スコアが低ければループバックします。
3. **write_paper** が LaTeX を起草し、推敲し、調査結果から BibTeX を取り込みます →
   `full_paper.tex` / `.pdf`。
4. **review_paper** が選択されたベニュールーブリックに対して 1 名以上のレビュアーエージェントを
   走らせます（2 名以上いる場合は Area Chair のメタ査読が集約します）。
5. **generate_ear** が再現性バンドル `ear/` を組み立てます（コード、入力データ、図表、
   `reproduce.sh`、LICENSE — ただし実験の出力は含めません）。

すべては **Results** ページで読めます: Overleaf 風エディタ、査読スコア、EAR ブラウザです。

## 6. 再現性を検証する（ORS）

最後に ARI は、独立した審査員がするやり方で自身の成果を検証します
（[ORS](../guides/paperbench/paperbench_quickstart.md)）:

- **Phase 1** がサンドボックス内で `reproduce.sh` を実行し（利用可能なら SLURM、なければ
  docker / apptainer / local）、期待される成果物が現れるかを確認します。
- **Phase 2** が結果を自動生成された PaperBench ルーブリックに対して採点します。これには
  **negative control**（空のリポジトリはゼロ近くのスコアにならなければならない）が含まれ、
  何もしないことで採点を得られないようにします。

判定は `reproducibility_report.json` にあります。

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
| `reproducibility_report.json` | ORS の判定 |

## 次に進む先

- 目標ファイルにもっと役割を持たせる: [実験ファイルの書き方](../guides/experiment_file.md)
- 探索を深く理解する: [BFTS アルゴリズム](../concepts/bfts.md)
- 大規模に実行する: [HPC セットアップ](../guides/hpc_setup.md)
- 他人の論文を再現する: [PaperBench クイックスタート](../guides/paperbench/paperbench_quickstart.md)

---

関連: [クイックスタート](quickstart.md) · [FAQ](faq.md) ·
[用語集](../reference/glossary.md) · [アーキテクチャ](../concepts/architecture.md)
