// ARI Dashboard – useWebSocket hook
// WebSocket is disabled: /state polling in AppContext handles all data updates.
// This avoids connection errors in proxy/tunnel environments.

import { useState } from 'react';
import type { TreeNode } from '../types';

export function useWebSocket(): { nodesData: TreeNode[]; connected: boolean } {
  const [nodesData] = useState<TreeNode[]>([]);
  return { nodesData, connected: false };
}
