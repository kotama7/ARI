---
sources:
  - path: ari-core/ari/pipeline/experiment_md.py
    role: implementation
  - path: ari-skill-evaluator
    role: implementation
  - path: ari-core/ari/agent/workflow.py
    role: implementation
  - path: ari-core/ari/agent/guidance.py
    role: implementation
  - path: ari-core/ari/orchestrator/lineage_decision.py
    role: implementation
  - path: ari-core/ari/lineage.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-skill-paper/src/rubric.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

# experiment.md の書き方

`experiment.md` は ARI に何を実行させるかを記述する Markdown ファイル
です。各チェックポイントのルートに置かれ、1 つの run のドメイン知識
が集約される単一の真実情報源（コード変更不要で新しい実験を駆動可能）
となります。

## 最小例

```markdown
CSR 形式のスパース・密行列乗算 (SpMM) を CPU 向けに実装し、
右辺行列のサイズが変動しても高い性能を維持することを目指す。
理論演算性能とメモリ帯域から roofline モデルを構築し、
実測値と比較せよ。

Metrics: GB/s, GFlops/s
```

これだけで十分です。**`Metrics:`** 行は ARI の決定論的ヘルパー
`parse_metric_from_experiment_md`
(`ari-core/ari/pipeline/experiment_md.py:30`) が解析し、
`evaluation_criteria.json:primary_metric` の最後の手段の値として保存
されます。本文の文章は LLM 駆動の `generate_ideas` フローのシードと
なり、計画の残りを埋めます。

上記の例はそのまま**スモークテスト**にも使えます。`experiment.md`
として保存して `ari run experiment.md` を実行すれば、研究目標を
本気で書く前に CLI・`.env` 読み込み・メモリバックエンドの動作確認
を一気通貫で行えます。

## 認識されるセクション

ARI は特定のセクション構造を要求しません（ファイルは plain
Markdown として読まれます）。ただし以下の見出しは慣習的で、一部は
決定論的ヘルパーが解釈します:

### `Metrics:` 行（任意・推奨）

```markdown
Metrics: GB/s, GFlops/s
```

最初のトークン（ここでは `GB/s`）が抽出され、idea が決まっていない
段階での `evaluation_criteria.json:primary_metric` として保存され
ます。強制ではありません: この行が無ければ関数は `""` を返し、run は
そのまま続行します。行は `Metric` または `Metrics`（大文字小文字を
区別しない）で**始まり**、続けて `:` か `-` が必要です — 散文の途中に
埋もれた単語はマッチしません。

### `## Success Metrics` セクション（任意）

```markdown
## Success Metrics
- gflops_per_second: sustained throughput
- l2_hit_rate: cache behaviour
```

evaluator スキルの `_parse_success_metrics` は、インラインの
`Metrics:` 行より**先に**このセクションを読み、`- name:` の箇条書き
すべてを宣言済みメトリクスとして採ります。したがって
`## Success Metrics` セクションは `Metrics:` 行に追加されるのではなく、
それを上書きします。

### `## Research Goal`（任意・推奨）

意図を 1 段落で記述。LLM は `generate_ideas` 中にこれを直接読み込み
ます。曖昧なら仮説も曖昧になります。

### `## Required Workflow`（任意）

ツール呼び出し順を制約したい場合の番号付きリスト。多くの場合は
エージェントの判断に任せて省略します。

### `## Hardware Limits` / `## Rules`（任意）

ハード制約を箇条書きで。これらの*見出し*自体を解析するヘルパーは
ありません — ファイルの他の部分と同じく散文として LLM に届きます。
**決定論的に**解析されるのは、HPC が有効なときに限り、ドキュメント内の
どこにあっても `ari/agent/workflow.py` が拾う 2 つの独立したパターン
です:

```markdown
Partition: <partition-name>
Max CPUs: 64
```

`Partition:` は `hints.slurm_partition` を設定します（無ければ
`ARI_SLURM_PARTITION`、それも無ければ `sinfo` が報告する最初の `up`
パーティション）。`Max CPUs:` は LLM に提示される CPU 上限を設定します
（無ければ `ARI_SLURM_CPUS`）。

### `## Provided Files` / `## Local Files`（任意）

1 行 1 パス、または箇条書きで書いたパスが、バッチ開始時に basename で
**すべての**ノードの work_dir へコピーされます。`## 提供ファイル`、
`## 提供文件`、および見出しだけの `## Files` もエイリアスとして受理
されます。行はパス区切り文字を含む場合にのみカウントされ、行末の
`# コメント` は除去されます。黙ってスキップされるケースが 2 つあります:
basename がチェックポイントのメタファイル（例: `results.json`）である
ファイルはコピーされず、既に存在する宛先は上書きされません。

### `## SLURM Script Template`（任意）

LLM が変更可能なベースラインスクリプト。ベンチマーク起動が特殊な
場合のみ役立ちます。`## Rules` と同様、これを読む決定論的ヘルパーは
ありません — LLM 向けのコンテキストです。

### マジックコメント（ヘルパーが解析）

| コメント | 用途 |
|---------|------|
| `<!-- min_expected_metric: N -->` | レビュアー向けのヒントではなく、エージェントループ内の**ハード**な下限: 値が 2 つ以上抽出され `max(values) < N` のとき、`guidance.py` が `node.mark_failed()` を呼びます。解析に注意 — `ari/agent/workflow.py` は `([\d]+)` でマッチするため `2.5` は `2` と読まれますが、evaluator スキル自身のパーサは小数を受理します。 |
| `<!-- metric_keyword: NAME -->`   | メトリクス抽出器へのヒント。`Metrics:` 行も `## Success Metrics` セクションも無い場合の `expected_metrics` のフォールバック元でもあります |

## v0.6 / v0.7 の追加要素

### ルブリック / venue 選択（v0.6）

`experiment.md` は **plan**、**venue** は
`ari-core/config/reviewer_rubrics/<id>.yaml` にあり、`ARI_RUBRIC`
env var（既定は `neurips`）で選択します。ルブリックが提供するのは
BFTS ジャッジの判定軸です。**公開レビュー**は別のつまみです:
`review_paper` は `rubric_id` を `workflow.yaml` の `paper_rubric`
（既定は `generic_conference`）から取り、`ARI_RUBRIC` を読みません。
つまり `ARI_RUBRIC` だけを切り替えてもレビューは generic ルブリックの
ままです — 探索とレビューを同じ venue で判定させたい場合は両方を設定して
ください。詳細は
`docs/concepts/architecture.md#plan--venue-contract-v070`。

### VirSci 自動追記ブロック（v0.6）

`generate_ideas` 実行時、パイプラインがチェックポイントの
`experiment.md` にラベル付きブロックを書き戻します:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected research idea
...
## Plan sections (full text in idea.json)
...
## Alternatives considered (not pursued in this run)
...
<!-- END AUTO-APPENDED -->
```

真ん中の見出しは `workflow.yaml:plan_promote` に従います（既定は上記の
`index_only`）。`full` では §本文をインライン展開した
`## Detailed experiment plan` が出力され、`off` では何も書かれません。

ブロックが書かれるのは**一度だけ**です: `_promote_plan_to_experiment_md`
は `AUTO-APPENDED` マーカーが既にあると即座に return するため、後続の
promote が古いブロックを更新することはありません — 再生成したい場合は
マーカーを削除してください。編集してよいのはマーカーの **上** の散文
のみで、begin/end マーカーの間は自動追記ヘルパーの所有物です。

### lineage 決定の記録（v0.7）

`stagnation_rule` が BFTS 複合スコア軌跡を監視します。停滞が
CONFIRMED になると、ARI はまず **決定論的に** `idea.json` 内で
最も有望な **未使用** の次点アイデアへピボットします
（`switch_to_idea`、同点時はインデックスの小さい方を選択、
`disable_generate_ideas` を付与）。これにより次点アイデアが
未使用のまま捨てられず、実際に試行されます。LLM ジャッジ
（`continue` / `switch_to_idea` / `fanout` / `terminate`）は、
決定論的ピボットが使えない場合（予算枯渇、再帰上限到達、未使用の
代替案が残っていない）の **フォールバック** としてのみ参照されます。
決定は（発火 1 件につき 1 レコード）
`{ckpt}/lineage_decisions.jsonl` に追記されます。`experiment.md`
への手動編集は不要です — 代替アイデアのカタログは `idea.json` に
あり、lineage の探索は `meta.json:parent_run_id` を辿ります。

### サブ実験の継承（v0.7）

| チャネル | 方向 | メカニズム |
|---|---|---|
| `venue.md` (rubric) | 継承 | `ARI_RUBRIC` env var |
| `memory` | 継承 | 祖先スコープ読み出し（`ari-skill-memory`）|
| `idea.json` (catalog) | 継承（read-only） | `ari/lineage.py` が `meta.json:parent_run_id` を辿る |
| `plan.md` / `experiment.md` (directive) | **継承しない** | 子は自身のものを書く |

子は自由にピボット可能。継承されるのは catalog と rubric のみ。

### ORS メタデータ（v0.7）

再現性フロー（`ari-skill-replicate` + `ari-skill-paper-re`）は
`experiment.md` 自体への新フィールドを必要としません。代わりに
チェックポイントに artefact が蓄積されます（`ors_rubric.json`、
`ors_grade.json`、`repro_sandbox/`）。詳細は
`docs/concepts/publication-lifecycle.md#publication-lifecycle-v070`。

## `experiment.md` の配置場所

ARI は次の順序で探します:

1. アクティブチェックポイントのルート: `$ARI_CHECKPOINT_DIR/experiment.md` —
   `tree.json` に記録されたパスは古くなっている可能性があるため、resume 時は
   こちらが優先されます。
2. `ari run experiment.md` への引数（初回起動時にチェックポイントへコピー）。
   これは必須の位置引数です: パスがファイルでない場合 `ari run` は終了コード 1
   で終了するため、新規 run が (1) にフォールバックすることはありません。

グローバルなデフォルトや `$HOME/.ari/` 検索はありません — v0.5.0
リファクタで全入力ファイルがチェックポイントスコープになりました。

## 関連

- `docs/concepts/architecture.md#plan--venue-contract-v070` — 完全な 2 ファイル契約
- `docs/concepts/publication-lifecycle.md#publication-lifecycle-v070` — `experiment.md` 周辺の出力
- `docs/reference/skills.md` — どのスキルが `experiment.md` のどのセクションを消費するか
