// ARI Dashboard – DetailPanel pure helpers.
// Extracted from DetailPanel.tsx (refactor req 15, follow-up to 03): the pure
// ancestor-chain walk used to scope which memory entries a node may see.
// Pure logic, no React — the container calls computeAncestorIds inside useMemo.

import type { TreeNode } from '../../types';

/**
 * Ancestor chain (root → … → self) for `node`, computed from the parent_id walk
 * over `allNodes`. Returns `[node.id]` when `allNodes` is absent, and `[]` when
 * `node` is null. Cycle-safe (tracks a seen-set). Verbatim from DetailPanel's
 * previous inline useMemo body.
 */
export function computeAncestorIds(
  node: TreeNode | null,
  allNodes?: TreeNode[],
): string[] {
  if (!node || !allNodes) return node ? [node.id] : [];
  const byId = new Map<string, TreeNode>();
  allNodes.forEach((n) => byId.set(n.id, n));
  const chain: string[] = [];
  let cur: TreeNode | undefined = byId.get(node.id);
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    chain.unshift(cur.id);
    const pid = cur.parent_id;
    cur = pid ? byId.get(pid) : undefined;
  }
  return chain;
}
