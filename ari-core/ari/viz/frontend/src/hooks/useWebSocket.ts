// ARI Dashboard – useWebSocket hook
// Streams tree updates from the backend in real time.
// Backend: ws_serve on HTTP_PORT + 1 (server.py:_main). Watcher thread
// broadcasts on tree.json mtime change, so nodes flip PENDING→RUNNING→SUCCESS
// without waiting for the 5 s /state poll.
// Auto-reconnects with exponential backoff; when WS is unreachable (proxy /
// tunnel without the extra port), polling in AppContext still covers updates.

import { useEffect, useRef, useState } from 'react';
import type { TreeNode } from '../types';

interface TreeMessage {
  type?: string;
  data?: { nodes?: TreeNode[] };
}

export function useWebSocket(): { nodesData: TreeNode[]; connected: boolean } {
  const [nodesData, setNodesData] = useState<TreeNode[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayRef = useRef(1000);

  useEffect(() => {
    let cancelled = false;

    const scheduleReconnect = () => {
      if (cancelled) return;
      const delay = Math.min(delayRef.current, 30000);
      delayRef.current = Math.min(delay * 2, 30000);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    const connect = () => {
      if (cancelled) return;
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.hostname;
      const httpPort = parseInt(
        window.location.port || (proto === 'wss:' ? '443' : '80'),
        10,
      );
      const wsPort = httpPort + 1;
      const url = `${proto}//${host}:${wsPort}/`;

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        delayRef.current = 1000;
      };
      ws.onmessage = (ev) => {
        try {
          const msg: TreeMessage = JSON.parse(ev.data);
          const nodes = msg?.data?.nodes;
          if (Array.isArray(nodes)) {
            setNodesData(nodes);
          }
        } catch {
          // malformed payload — ignore
        }
      };
      ws.onerror = () => {
        // onclose will follow; handle reconnect there
      };
      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        try {
          ws.close();
        } catch {
          // ignore
        }
      }
    };
  }, []);

  return { nodesData, connected };
}
