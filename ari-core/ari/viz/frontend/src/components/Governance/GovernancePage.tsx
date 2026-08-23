// ARI Dashboard – Governance workspace (gui_refresh task 08 Wave 4a).
//
// The tab set and the truth rules the payloads already enforce are written
// down in docs/guides/rqgm_gui.md, "Tab by tab" and in
// docs/reference/rqgm_gui_read_models.md, "Presentation truth rules the API
// enforces". The route itself exists in exactly one place — its
// ROUTE_REGISTRY entry, which the router and the sidebar are both derived
// from; nothing here declares a path.
//
// READ-ONLY. Nine tabs (Overview / Epoch Timeline / Registry /
// Accountability / Score Lineage / Evolution / Paper Archive / Audit) over
// the Wave-4a/4b `/api/v1/runs/{run_id}/rqgm/*` read models via the typed
// react-query hooks (src/hooks/useV1.ts). The page never mutates governance
// state — v1 exposes no RQGM mutation endpoint — and never re-executes
// kernel/score-policy decisions: the read models parse committed artifacts
// and import no kernel code, so what renders here is a replay, not a rerun.
//
// Run scoping: reads `?run=` from the hash query (#/governance?run=<id>),
// the ConfigBrowserPage pattern. Capability gating never hides the route and
// never dresses an inactive capability as a failure — it names the reason
// instead: a run without RQGM artifacts renders a capability state screen —
// an explanation of how governance is activated — NOT an
// error. Realtime: topic 'run' events invalidate this run's rqgm query
// scope (events are invalidations, never data), and the connection state
// drives the shared StaleDataBanner.
//
// A11y: a tab-like surface has to be a real ARIA composite, never styled
// buttons — so the tab strip is a genuine role=tablist/tab/tabpanel
// composite with aria-selected/aria-controls wiring, fully keyboard
// navigable — rendered by the shared TabStrip primitive
// (src/components/common/TabStrip.tsx), which owns the
// `gov-tab-<id>` / `gov-panel-<id>` id convention this page's panel pairs with.

import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useT } from '../../i18n';
import {
  useRqgmCapabilitiesV1,
  useRunTreeV1,
  v1Keys,
} from '../../hooks/useV1';
import { useRunEvents } from '../../hooks/useRunEvents';
import type { EventTopic } from '../../shared/realtime/eventStream';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  StaleDataBanner,
  TabStrip,
} from '../common';
import { errorText } from './shared';
import { OverviewTab } from './OverviewTab';
import { EpochTimelineTab } from './EpochTimelineTab';
import { RegistryTab } from './RegistryTab';
import { AccountabilityTab } from './AccountabilityTab';
import { ScoreLineageTab } from './ScoreLineageTab';
import { EvolutionTab } from './EvolutionTab';
import { PaperArchiveTab } from './PaperArchiveTab';
import { AuditTab } from './AuditTab';
import { ScientificAssuranceTab } from './ScientificAssuranceTab';
import type { RqgmCapabilitiesV1 } from '../../services/api/v1';

// ── helpers ─────────────────────────────────────────────────────────────

/** `run` query param of the current hash (#/governance?run=<run_id>) or ''. */
function runFromHash(): string {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('run') ?? '';
}

// Tab order is a documented contract, not a local preference — the strip has
// to read in the order docs/guides/rqgm_gui.md, "Tab by tab" spells out,
// because that guide is what a user follows on screen (Wave 4b adds Epoch
// Timeline, Evolution and Paper Archive around the Wave-4a five).
const TAB_IDS = [
  'overview',
  'epochs',
  'registry',
  'accountability',
  'lineage',
  'evolution',
  'paper',
  'kca',
  'audit',
] as const;
type TabId = (typeof TAB_IDS)[number];

const TAB_LABEL_KEYS: Record<TabId, string> = {
  overview: 'gov_tab_overview',
  epochs: 'gov_tab_epochs',
  registry: 'gov_tab_registry',
  accountability: 'gov_tab_accountability',
  lineage: 'gov_tab_lineage',
  evolution: 'gov_tab_evolution',
  paper: 'gov_tab_paper',
  kca: 'gov_tab_kca',
  audit: 'gov_tab_audit',
};

const RUN_TOPICS: readonly EventTopic[] = ['run'];

// ── capability state screen (an explained state, never an error) ────────

function CapabilityScreen({ caps }: { caps: RqgmCapabilitiesV1 }) {
  const t = useT();
  return (
    <Card title={t('gov_cap_title')}>
      <p style={{ fontSize: '.85rem', marginBottom: 8 }}>{t('gov_cap_not_error')}</p>
      <p style={{ fontSize: '.85rem', marginBottom: 8 }}>
        {t('gov_cap_simple_bfts_explain')}
      </p>
      <p style={{ fontSize: '.85rem', marginBottom: 8 }}>{t('gov_cap_enable_hint')}</p>
      <ModeStrip caps={caps} />
      {(caps.reasons ?? []).length > 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginTop: 8 }}>
          {t('gov_cap_reasons')}: {(caps.reasons ?? []).join('; ')}
        </p>
      )}
    </Card>
  );
}

/** Execution mode and paper mode are independent axes — always shown as two
 * separate labelled chips, never collapsed into one and never rendered
 * apart, so neither is read as implying the other (glossary: the bare word
 * "Mode" alone is forbidden as a label). */
function ModeStrip({ caps }: { caps: RqgmCapabilitiesV1 }) {
  const t = useT();
  return (
    <p style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', fontSize: '.82rem' }}>
      <span>
        {t('gov_execution_mode')}:{' '}
        <Badge variant={caps.enabled ? 'green' : 'muted'}>
          {caps.mode ?? (caps.enabled ? 'ari_rqgm' : 'simple_bfts')}
        </Badge>
      </span>
      <span>
        {t('gov_mode_source')}:{' '}
        <code style={{ fontSize: '.78rem' }}>{caps.mode_source ?? t('gov_unknown')}</code>
      </span>
      <span>
        {t('gov_paper_mode')}:{' '}
        <Badge variant={caps.paper_mode ? 'blue' : 'muted'}>
          {caps.paper_mode ? 'rqgm_archive' : 'linear'}
        </Badge>
      </span>
    </p>
  );
}

// ── node selector (Accountability / Score Lineage tabs) ─────────────────

function NodeSelector({
  runId,
  nodeId,
  onChange,
}: {
  runId: string;
  nodeId: string;
  onChange: (id: string) => void;
}) {
  const t = useT();
  const treeQ = useRunTreeV1(runId);
  const nodeIds = useMemo(() => {
    const nodes = treeQ.data?.nodes ?? [];
    return nodes
      .map((n) => (typeof n.id === 'string' ? n.id : null))
      .filter((id): id is string => id !== null);
  }, [treeQ.data]);
  return (
    <div style={{ margin: '0 0 12px' }}>
      <label style={{ fontSize: '.82rem', display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        {t('gov_node_label')}
        <select
          value={nodeId}
          onChange={(e) => onChange(e.target.value)}
          aria-label={t('gov_node_label')}
        >
          <option value="">{t('gov_node_placeholder')}</option>
          {nodeIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

// ── page ────────────────────────────────────────────────────────────────

export function GovernancePage() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns the ?run param
  // itself (ConfigBrowserPage pattern — including in-place hash changes).
  const [runId, setRunId] = useState<string>(runFromHash);
  useEffect(() => {
    const onHashChange = () => setRunId(runFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const [tab, setTab] = useState<TabId>('overview');
  // Shared across the Accountability and Score Lineage tabs so switching
  // tabs keeps the investigated node.
  const [nodeId, setNodeId] = useState('');

  const capsQ = useRqgmCapabilitiesV1(runId);
  const queryClient = useQueryClient();
  const { connectionState, lastEventAt } = useRunEvents(
    runId === '' ? null : runId,
    RUN_TOPICS,
  );
  // Realtime → cache glue for the rqgm scope: a 'run' event is an
  // invalidation signal, never data — nothing on this page is rendered from
  // an event body, so duplicate or reordered events are harmless. Only
  // mounted queries refetch.
  useEffect(() => {
    if (lastEventAt !== null && runId !== '') {
      void queryClient.invalidateQueries({ queryKey: v1Keys.rqgm(runId) });
    }
  }, [lastEventAt, runId, queryClient]);

  const caps = capsQ.data;
  const stale =
    runId !== '' &&
    ((capsQ.data !== undefined && capsQ.isError) || connectionState !== 'live');
  const lastUpdatedMs = Math.max(capsQ.dataUpdatedAt || 0, lastEventAt ?? 0);

  let body;
  if (runId === '') {
    body = (
      <Card>
        <EmptyState icon="🏛️" message={t('gov_no_run')} hint={t('gov_no_run_hint')} />
      </Card>
    );
  } else if (capsQ.isPending) {
    body = <LoadingState />;
  } else if (capsQ.isError && capsQ.data === undefined) {
    body = (
      <ErrorState
        message={errorText(capsQ.error, t('gov_request_id'))}
        onRetry={() => void capsQ.refetch()}
      />
    );
  } else if (caps !== undefined && !caps.enabled) {
    // Capability state, not an error: name the reason and explain how
    // governance is activated, rather than hiding the route, erroring, or
    // fabricating an empty governed state.
    body = <CapabilityScreen caps={caps} />;
  } else if (caps !== undefined) {
    body = (
      <>
        <ModeStrip caps={caps} />
        <TabStrip
          items={TAB_IDS.map((id) => ({ id, label: t(TAB_LABEL_KEYS[id]) }))}
          activeId={tab}
          onSelect={setTab}
          ariaLabel={t('gov_title')}
          idPrefix="gov"
        />
        <div
          role="tabpanel"
          id={`gov-panel-${tab}`}
          aria-labelledby={`gov-tab-${tab}`}
        >
          {(tab === 'accountability' || tab === 'lineage') && (
            <NodeSelector runId={runId} nodeId={nodeId} onChange={setNodeId} />
          )}
          {tab === 'overview' && <OverviewTab runId={runId} />}
          {tab === 'epochs' && <EpochTimelineTab runId={runId} />}
          {tab === 'registry' && <RegistryTab runId={runId} />}
          {tab === 'accountability' && (
            <AccountabilityTab runId={runId} nodeId={nodeId} />
          )}
          {tab === 'lineage' && <ScoreLineageTab runId={runId} nodeId={nodeId} />}
          {tab === 'evolution' && <EvolutionTab runId={runId} />}
          {tab === 'paper' && (
            <PaperArchiveTab
              runId={runId}
              executionMode={caps.mode ?? (caps.enabled ? 'ari_rqgm' : 'simple_bfts')}
            />
          )}
          {tab === 'kca' && <ScientificAssuranceTab runId={runId} />}
          {tab === 'audit' && <AuditTab runId={runId} />}
        </div>
      </>
    );
  } else {
    body = <LoadingState />;
  }

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('gov_title')}</h1>
      <p className="subtitle">{t('gov_subtitle')}</p>

      {runId !== '' && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.85rem' }}>
          {t('gov_run_label')}: <code style={{ fontSize: '.85rem' }}>{runId}</code>
        </p>
      )}

      {stale && (
        <div style={{ marginBottom: 16 }}>
          <StaleDataBanner
            lastUpdated={
              lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : null
            }
            onRefresh={() => {
              void capsQ.refetch();
              void queryClient.invalidateQueries({ queryKey: v1Keys.rqgm(runId) });
            }}
          />
        </div>
      )}

      {body}
    </div>
  );
}
