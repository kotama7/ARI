---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-05-25
---

# BFTS アルゴリズム

ARI は 2 プール設計による真の最良優先木探索を実装しています:

- **`pending`**: 実行待ちのノード（親から既に展開済み）
- **`frontier`**: 完了済みだが未展開のノード

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # 実行待ちノード
    frontier = []         # 展開待ちの完了済みノード
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS ステップ 1: 最良のフロンティアノードを展開 ---
        # LLM が全完了ノードのメトリクスを読み、最も有望なノードを
        # 展開対象として選択（一度に全てではない）
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # _scientific_score に基づく
            frontier.remove(best)
            children = llm_propose_directions(best)     # 改善/アブレーション/検証
            pending.extend(children)
            all_nodes.extend(children)

        # --- BFTS ステップ 2: pending ノードのバッチを実行 ---
        batch = llm_select_next_nodes(pending, max_parallel)
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # 祖先チェーンメモリに保存
            if node.status == SUCCESS:
                frontier.append(node)         # 選択時に展開
            else:
                frontier.append(node)         # 失敗 → "debug" 子ノードで展開

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

主要な特性:
- **遅延展開**: 完了ノードは LLM が選択するまで展開されない — 低スコアのノードは無期限に待機する可能性がある
- **リトライなし**: 失敗ノードは `expand()` を通じて `debug` 子ノードを生成し、再実行はしない
- **厳密な予算**: `len(all_nodes) < max_total_nodes` で超過を防止
- **`generate_ideas` は一度だけ呼出**: ルートノード以降はループ防止のため抑制

### ノードラベル

| ラベル | 意味 |
|-------|---------|
| `draft` | ゼロからの新規実装 |
| `improve` | 親のパラメータまたはアルゴリズムの調整 |
| `debug` | 親の失敗の修正 |
| `ablation` | 一つのコンポーネントを除去してその影響を測定 |
| `validation` | 異なる条件で親を再実行 |

---
