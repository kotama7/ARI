---
sources:
  - path: ari-core/config/profiles
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# クックブック

最もよく使う設定ノブのコピー＆ペースト用レシピ集です。これは網羅的な
[設定リファレンス](../reference/configuration.md)に対する how-to の補完であり、
レシピが完全なオプション一覧を必要とする場合は、それを繰り返すのではなく
そちらへリンクします。

> **オーバーライドの配置場所。** 環境プロファイルは
> `ari-core/config/profiles/<name>.yaml` に、ラン全体の設定は
> `workflow.yaml` に置きます。プロファイルは、`--profile <name>`（CLI）を
> 渡すかウィザードで選択すると、デフォルトの上にマージされます。`evaluator:`
> や `bfts:` ブロックは `workflow.yaml` に追加します。
>
> **`--profile` がマージするのは 4 キーだけです。** docstring の記述に反して、
> `_apply_profile`（`ari-core/ari/cli/run.py`）はディープマージではありません。
> 読むのは `bfts.max_total_nodes`、`bfts.max_parallel_nodes`（またはその歴史的な
> 綴りである `parallel`）、`hpc.enabled`、`hpc.scheduler` の 4 つだけです。
> プロファイル YAML のそれ以外のキー — `partition`、`cpus_per_task`、
> `memory_gb`、`walltime`、`max_concurrent_jobs`、および `evaluator:` ブロック —
> はファイルから読み込まれた後、黙って捨てられます。それらは代わりに
> `workflow.yaml`（`resources:`、`evaluator:`、`bfts:`）か環境変数
> （`ARI_SLURM_PARTITION`）に置いてください。

## 環境プロファイル: laptop / HPC / cloud

3 つのプロファイルが標準で同梱されています。`ari run experiment.md --profile hpc`
（またはウィザードの Resources ステップ）で選択します。

**`laptop`** — 小規模なローカル実行、スケジューラなし:

```yaml
profile: laptop
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 8
  parallel: 2
```

**`hpc`** — スケジューラを有効化する（`scheduler:` より下のキーはファイルに
記録されるだけでマージされません。パーティションは `ARI_SLURM_PARTITION`、
実験ファイルの `Partition:` 行、あるいは `sinfo` が報告する最初の `up`
パーティションから解決されます）:

```yaml
profile: hpc
hpc:
  enabled: true
  scheduler: auto
  partition: auto
  cpus_per_task: 8
  memory_gb: 32
  walltime: "04:00:00"
  max_concurrent_jobs: 4
bfts:
  max_total_nodes: 20
  parallel: 4
```

**`cloud`** — スケジューラはないが、より広い並列探索:

```yaml
profile: cloud
hpc:
  enabled: false
  scheduler: none
bfts:
  max_total_nodes: 16
  parallel: 4
```

**レシピ — 独自のプロファイルを作る。** `ari-core/config/profiles/` に新しい
ファイル（例: `bigjob.yaml`）を置き、`--profile bigjob` で選択します。内容は
マージされる 4 キーに留めてください — それ以外にここへ書いたものは無視され、
ファイルに解決できないプロファイル名は警告をログに出して処理を続行するだけです:

```yaml
profile: bigjob
hpc:
  enabled: true
  scheduler: auto
bfts:
  max_total_nodes: 40
  parallel: 8
```

サイジングのノブは `workflow.yaml` の `resources:` ブロックに置きます。その
キー名は `cpus` / `memory_gb` / `gpus` / `walltime` / `partition` です — または
環境変数（`ARI_SLURM_PARTITION`）に置きます。

パーティション検出と SLURM の詳細については [HPC セットアップ](hpc_setup.md)
を参照してください。

## 探索と評価器のチューニング

ARI は 4 つの独立した評価レイヤを公開しています。各デフォルトは従来の挙動を
再現する no-op です。完全なセマンティクスは
[設定 → BFTS 評価レイヤ](../reference/configuration.md#bfts-の評価層-設定で切替可能)
にあります。以下のレシピはよく使う組み合わせです。

**ボトルネックスコアリング — *すべて*の軸が良好なときだけノードを報酬する:**

```yaml
evaluator:
  composite: weighted_min   # the score is the lowest axis; weights gate participation
```

**より多くの探索 — UCB スタイルのフロンティアランキング**（同じ高スコアノードを
探索が再展開し続けるときに有効）:

```yaml
bfts:
  frontier_score: ucb_like
  ucb_c: 1.0                # 0.0 reduces this back to the default strategy
```

**浅いノードを優先する — フォールバックランキングで深さにペナルティを与える:**

```yaml
bfts:
  frontier_score: depth_penalized
  depth_penalty_lambda: 0.1
```

**ルーブリック由来の軸の代わりにカスタム軸（例: 高速化）を測定する**
（`axis_mode` のデフォルトは `dynamic` で、有効なルーブリックから軸を構築します）。
`custom_axes` は `{name, description, weight}` レコードのリストです — 文字列だけの
リストは設定ロード時に拒否されます:

```yaml
evaluator:
  axis_mode: custom
  custom_axes:
    - name: correctness
      description: "結果が許容誤差内で参照実装と一致するか"
      weight: 0.4
    - name: speedup
      description: "ベースラインに対する実時間の高速化率（1.0 = 変化なし）"
      weight: 0.4
    - name: reproducibility
      description: "記録された成果物から実行を再現できるか"
      weight: 0.2
```

**監査前の挙動を厳密に再現する**（正規の 5 軸と調和平均を固定する）:

```yaml
evaluator:
  axis_mode: legacy
  composite: harmonic_mean
```

**独自の選択プロンプトに差し替える**（Layer D）— `ari-core/ari/prompts/`
配下のテンプレートを指す（`.md` サフィックスなし）。同じプレースホルダを
保持する必要があります:

```yaml
bfts:
  select_prompt: orchestrator/my_select          # needs {experiment_goal} {memory_context} {candidates}
  expand_select_prompt: orchestrator/my_expand    # needs {experiment_goal} {candidates}
```

## PaperBench: 再現 vs 監査

どちらのモードも同じルーブリック機構で駆動されます。違いは何を対象に
指すかです。エンドツーエンドのフローは
[PaperBench クイックスタート](paperbench/paperbench_quickstart.md)を、
すべてのノブは[環境変数](../reference/environment_variables.md)を参照してください。

**論文を再現する**（コードを最初から実行して採点する）。自動選択が誤った
ものを選んでしまう場合は、Phase 1 のサンドボックスを明示的に固定します:

```bash
export ARI_PHASE1_SANDBOX=slurm        # or docker / apptainer / singularity / local
export ARI_SLURM_PARTITION=gpu          # required when the sandbox is slurm
```

**論文を監査する**（論文*それ自体*が再現可能な程度に十分よく記述されて
いるかを判定する）— ルーブリックを通じて監査用の venue テンプレートを
選択します:

```bash
export ARI_RUBRIC=sc                    # venue template: sc / neurips / nature
```

`ARI_RUBRIC`（既定は `neurips`）は、BFTS のスコアリング軸を導出する元となる
`ari-core/config/reviewer_rubrics/` 配下の rubric YAML を選びます。公開レビュー
基準は**別のつまみ**です: `review_paper` ステージは rubric をワークフローの明示的な
入力、すなわち `workflow.yaml` の `paper_rubric`（既定は `generic_conference`）
として受け取ります。探索とレビューを同じ venue で判定させたい場合は両方を設定して
ください — [用語集 → venue](../reference/glossary.md) と
[アーキテクチャ → Plan / Venue contract](../concepts/architecture.md#plan-venue-契約-v0-7-0)
を参照してください。

---

関連項目: [設定リファレンス](../reference/configuration.md) ·
[HPC セットアップ](hpc_setup.md) · [PaperBench クイックスタート](paperbench/paperbench_quickstart.md) ·
[用語集](../reference/glossary.md)
