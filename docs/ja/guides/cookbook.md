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
last_verified: 2026-06-10
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
> や `bfts:` ブロックはどちらのファイルにも追加できます。

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

**`hpc`** — パーティションを自動検出する SLURM/PBS/LSF クラスタ:

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
ファイル（例: `bigjob.yaml`）を置き、`--profile bigjob` で選択します:

```yaml
profile: bigjob
hpc:
  enabled: true
  scheduler: auto
  partition: gpu
  cpus_per_task: 32
  memory_gb: 128
  walltime: "12:00:00"
bfts:
  max_total_nodes: 40
  parallel: 8
```

パーティション検出と SLURM の詳細については [HPC セットアップ](hpc_setup.md)
を参照してください。

## 探索と評価器のチューニング

ARI は 4 つの独立した評価レイヤを公開しています。各デフォルトは従来の挙動を
再現する no-op です。完全なセマンティクスは
[設定 → BFTS 評価レイヤ](../reference/configuration.md#bfts-evaluation-layers-configurable)
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

**汎用の 5 軸の代わりにカスタム軸（例: 高速化）を測定する:**

```yaml
evaluator:
  axis_mode: custom
  custom_axes: [correctness, speedup, reproducibility]
  # axis_weights below set the relative weight of each named axis
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

`ARI_RUBRIC` を切り替えると、BFTS のスコアリング軸と公開レビュー基準が
同時に変わります — [用語集 → venue](../reference/glossary.md) と
[アーキテクチャ → Plan / Venue contract](../concepts/architecture.md#plan--venue-contract-v070)
を参照してください。

---

関連項目: [設定リファレンス](../reference/configuration.md) ·
[HPC セットアップ](hpc_setup.md) · [PaperBench クイックスタート](paperbench/paperbench_quickstart.md) ·
[用語集](../reference/glossary.md)
