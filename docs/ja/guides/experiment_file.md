---
sources:
  - path: ari-core/ari/pipeline/experiment_md.py
    role: implementation
  - path: ari-skill-evaluator
    role: implementation
last_verified: 2026-05-25
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
(`ari-core/ari/pipeline/experiment_md.py:31`) が解析し、
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

### `Metrics:` 行（必須）

```markdown
Metrics: GB/s, GFlops/s
```

最初のトークン（ここでは `GB/s`）が抽出され、idea が決まっていない
段階での `evaluation_criteria.json:primary_metric` として保存され
ます。"metric" / "metrics" を含むプレーンな散文でも同様に動作します。

### `## Research Goal`（任意・推奨）

意図を 1 段落で記述。LLM は `generate_ideas` 中にこれを直接読み込み
ます。曖昧なら仮説も曖昧になります。

### `## Required Workflow`（任意）

ツール呼び出し順を制約したい場合の番号付きリスト。多くの場合は
エージェントの判断に任せて省略します。

### `## Hardware Limits` / `## Rules`（任意）

ハード制約を箇条書きで。エージェントはシステムコンテキストの一部と
して読みます。

### `## SLURM Script Template`（任意）

LLM が変更可能なベースラインスクリプト。ベンチマーク起動が特殊な
場合のみ役立ちます。

### マジックコメント（ヘルパーが解析）

| コメント | 用途 |
|---------|------|
| `<!-- min_expected_metric: N -->` | レビュアー向けのソフトな下限 |
| `<!-- metric_keyword: NAME -->`   | メトリクス抽出器へのヒント |

## v0.6 / v0.7 の追加要素

### ルブリック / venue 選択（v0.6）

`experiment.md` は **plan**、**venue** は
`ari-core/config/reviewer_rubrics/<id>.yaml` にあり、`ARI_RUBRIC`
env var で選択します。ルブリックは BFTS 判定軸と公開レビュー基準
の両方を提供します。詳細は
`docs/concepts/architecture.md#plan--venue-contract-v070`。

### VirSci 自動追記ブロック（v0.6）

`generate_ideas` 実行時、パイプラインがチェックポイントの
`experiment.md` にラベル付きブロックを書き戻します:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected idea
...
## Plan §-tags
...
## Alternatives considered
...
<!-- END AUTO-APPENDED -->
```

ブロックは冪等（promote ごとに書き直され、重複しません）。
マーカーの **上** の散文のみ編集してください。

### lineage 決定の記録（v0.7）

`stagnation_rule` が BFTS 複合スコア軌跡を監視し、停滞を検知すると
LLM ジャッジが `continue` / `switch_to_idea` / `fanout` /
`terminate` のいずれかを選択。決定は
`{ckpt}/lineage_decisions.jsonl` に追記されます。`experiment.md`
への手動編集は不要です。

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

1. アクティブチェックポイントのルート: `$ARI_CHECKPOINT_DIR/experiment.md`
2. `ari run experiment.md` への引数（初回起動時にチェックポイントへコピー）

グローバルなデフォルトや `$HOME/.ari/` 検索はありません — v0.5.0
リファクタで全入力ファイルがチェックポイントスコープになりました。

## 関連

- `docs/concepts/architecture.md#plan--venue-contract-v070` — 完全な 2 ファイル契約
- `docs/concepts/publication-lifecycle.md#publication-lifecycle-v070` — `experiment.md` 周辺の出力
- `docs/reference/skills.md` — どのスキルが `experiment.md` のどのセクションを消費するか
