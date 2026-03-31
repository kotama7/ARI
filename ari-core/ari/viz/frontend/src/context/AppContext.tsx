// ARI Dashboard – global application context
// Provides shared state (AppState, WebSocket nodes, current page) to all components.

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { AppState, Checkpoint, TreeNode } from '../types';
import { fetchState, fetchCheckpoints } from '../services/api';
import { useWebSocket } from '../hooks/useWebSocket';

// ── context shape ──────────────────────────────

export interface AppContextType {
  /** Latest application state from /state endpoint. */
  state: AppState | null;
  /** Tree nodes streamed via WebSocket (real-time). */
  nodesData: TreeNode[];
  /** Currently active page/route name. */
  currentPage: string;
  /** Navigate to a different page. */
  setCurrentPage: (page: string) => void;
  /** Manually re-fetch /state. */
  refreshState: () => void;
  /** Whether the WebSocket is currently connected. */
  wsConnected: boolean;
  /** List of checkpoints (shared across Sidebar, Settings, etc.) */
  checkpoints: Checkpoint[];
  /** Re-fetch checkpoints list. */
  refreshCheckpoints: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

// ── polling interval ───────────────────────────

const STATE_POLL_MS = 5000;

// ── provider ───────────────────────────────────

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [currentPage, setCurrentPage] = useState<string>(() => {
    const h = window.location.hash.replace(/^#\/?/, '');
    return h || 'home';
  });

  // WebSocket for real-time node updates
  const { nodesData: wsNodes, connected: wsConnected } = useWebSocket();

  // Checkpoints list (shared)
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);

  const refreshCheckpoints = useCallback(async () => {
    try {
      const ck = await fetchCheckpoints();
      setCheckpoints(ck);
    } catch {
      // ignore
    }
  }, []);

  // Fetch /state
  const loadState = useCallback(async () => {
    try {
      const s = await fetchState();
      setState(s);
    } catch (err) {
      console.warn('[AppContext] failed to fetch /state', err);
    }
  }, []);

  // Sync currentPage with hash changes
  useEffect(() => {
    const onHashChange = () => {
      const h = window.location.hash.replace(/^#\/?/, '');
      setCurrentPage(h || 'home');
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Initial fetch + polling
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadState();
    refreshCheckpoints();
    timerRef.current = setInterval(() => {
      loadState();
      refreshCheckpoints();
    }, STATE_POLL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadState, refreshCheckpoints]);

  // Prefer WebSocket nodes when available, fall back to state.nodes
  const nodesData = wsNodes.length > 0 ? wsNodes : (state?.nodes ?? []);

  const value: AppContextType = {
    state,
    nodesData,
    currentPage,
    setCurrentPage,
    refreshState: loadState,
    wsConnected,
    checkpoints,
    refreshCheckpoints,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

// ── consumer hook ──────────────────────────────

export function useAppContext(): AppContextType {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error('useAppContext must be used within an <AppProvider>');
  }
  return ctx;
}
