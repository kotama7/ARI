// ARI Dashboard – DetailPanel data-loading hook.
// Extracted from DetailPanel.tsx (refactor req 15, follow-up to 03): the three
// fetch-effect clusters (checkpoint memory, lazy access-log, lazy node-report +
// availability probe) plus the ancestor-scoped memory derivation. Moved verbatim
// — same effect bodies, same dependency arrays, same abort cleanup, same
// lazy-on-tab triggers — so behavior (and the §11 fetch/abort timing) is
// unchanged; only the container/data split moves.

import { useEffect, useMemo, useState } from 'react';
import {
  fetchCheckpointMemory,
  fetchMemoryAccess,
  fetchNodeReport,
  type MemoryEntry,
  type MemoryAccessResponse,
  type NodeReport,
} from '../../services/api';
import type { TreeNode } from '../../types';
import { computeAncestorIds } from './detailPanelHelpers';

export interface DetailPanelData {
  ancestorIds: string[];
  visibleMemory: MemoryEntry[];
  globalEntries: MemoryEntry[];
  memLoading: boolean;
  memError: string | null;
  accessData: MemoryAccessResponse | null;
  accessLoading: boolean;
  accessError: string | null;
  reportData: NodeReport | null;
  reportError: string | null;
  reportLoading: boolean;
  reportAvailable: boolean | null;
}

/**
 * Loads the per-node detail-panel data. `activeTab` gates the lazy access/report
 * fetches exactly as the inline effects did. Returns the values the tab JSX
 * reads; `memEntries` stays internal (only the ancestor-scoped `visibleMemory`
 * is exposed).
 */
export function useDetailPanelData(
  checkpointId: string | null | undefined,
  node: TreeNode | null,
  allNodes: TreeNode[] | undefined,
  activeTab: string,
): DetailPanelData {
  // ── Memory data ──
  const [memEntries, setMemEntries] = useState<MemoryEntry[] | null>(null);
  const [globalEntries, setGlobalEntries] = useState<MemoryEntry[]>([]);
  const [memLoading, setMemLoading] = useState(false);
  const [memError, setMemError] = useState<string | null>(null);

  // Ancestor chain (root → ... → self) computed from parent_id walk
  const ancestorIds = useMemo<string[]>(
    () => computeAncestorIds(node, allNodes),
    [node, allNodes],
  );

  useEffect(() => {
    if (!checkpointId || !node) {
      setMemEntries(null);
      return;
    }
    let aborted = false;
    setMemLoading(true);
    setMemError(null);
    fetchCheckpointMemory(checkpointId)
      .then((r) => {
        if (aborted) return;
        if (r.error) {
          setMemError(r.error);
          setMemEntries([]);
          setGlobalEntries([]);
        } else {
          setMemEntries(r.entries || []);
          setGlobalEntries(r.global || []);
        }
      })
      .catch((e) => {
        if (aborted) return;
        setMemError(String(e));
        setMemEntries([]);
      })
      .finally(() => {
        if (!aborted) setMemLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [checkpointId, node?.id]);

  const visibleMemory = useMemo(() => {
    if (!memEntries || !node) return [] as MemoryEntry[];
    const allowed = new Set(ancestorIds);
    return memEntries.filter((e) => allowed.has(e.node_id));
  }, [memEntries, node, ancestorIds]);

  // ── Access log data (lazy: fetched only when the Access tab is opened) ──
  const [accessData, setAccessData] = useState<MemoryAccessResponse | null>(null);
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessError, setAccessError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'access' || !checkpointId || !node) {
      return;
    }
    let aborted = false;
    setAccessLoading(true);
    setAccessError(null);
    fetchMemoryAccess(checkpointId, node.id)
      .then((r) => {
        if (aborted) return;
        if (r.error) setAccessError(r.error);
        setAccessData(r);
      })
      .catch((e) => {
        if (aborted) return;
        setAccessError(String(e));
        setAccessData(null);
      })
      .finally(() => {
        if (!aborted) setAccessLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [activeTab, checkpointId, node?.id]);

  // ── Node report data (lazy: fetched only when the Report tab is opened) ──
  const [reportData, setReportData] = useState<NodeReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportAvailable, setReportAvailable] = useState<boolean | null>(null);

  // Probe once per node-id whether a report exists, so we can show/hide the
  // tab without forcing the user to click it. We hit the same endpoint —
  // tiny payload — and remember the answer.
  useEffect(() => {
    if (!checkpointId || !node) {
      setReportAvailable(null);
      setReportData(null);
      return;
    }
    let aborted = false;
    fetchNodeReport(checkpointId, node.id)
      .then((r) => {
        if (aborted) return;
        if (r.error || !r.report) {
          setReportAvailable(false);
          setReportData(null);
        } else {
          setReportAvailable(true);
          setReportData(r.report);
        }
      })
      .catch(() => {
        if (!aborted) setReportAvailable(false);
      });
    return () => {
      aborted = true;
    };
  }, [checkpointId, node?.id]);

  useEffect(() => {
    if (activeTab !== 'report' || !checkpointId || !node) {
      return;
    }
    if (reportData) return; // already loaded by the availability probe.
    let aborted = false;
    setReportLoading(true);
    setReportError(null);
    fetchNodeReport(checkpointId, node.id)
      .then((r) => {
        if (aborted) return;
        if (r.error) setReportError(r.error);
        else if (r.report) setReportData(r.report);
      })
      .catch((e) => {
        if (!aborted) setReportError(String(e));
      })
      .finally(() => {
        if (!aborted) setReportLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [activeTab, checkpointId, node?.id, reportData]);

  return {
    ancestorIds,
    visibleMemory,
    globalEntries,
    memLoading,
    memError,
    accessData,
    accessLoading,
    accessError,
    reportData,
    reportError,
    reportLoading,
    reportAvailable,
  };
}
