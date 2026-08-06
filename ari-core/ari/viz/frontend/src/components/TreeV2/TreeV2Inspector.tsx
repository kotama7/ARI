// ARI Dashboard – TreeV2 node inspector (gui_refresh task 07 Wave 4c,
// extracted verbatim from TreeV2Page.tsx in the task-07 tail so the page
// file stays under the LOC tripwire; behavior unchanged).
//
// Node summary using the FROZEN orchestrator vocabularies (see
// NODE_STATUSES / NODE_LABELS in TreeV2Page — unknown values render
// verbatim, never remapped), metrics including `_scientific_score` and the
// RQGM sentinels (via sentinelsOf in ./treeNodes), the node report via the
// existing legacy `/api/nodes/{run}/{node}/report` client, and the
// Governance / Config deep links.

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useT } from '../../i18n';
import { fetchNodeReport } from '../../services/api/nodeReport';
import type { NodeReport } from '../../services/api/nodeReport';
import { Badge, Button, Card, LoadingState } from '../common';
import { scalarMetricsOf, sentinelsOf } from './treeNodes';
import type { TreeNode } from '../../types';

const STATUS_VARIANT: Record<string, 'green' | 'red' | 'blue' | 'yellow' | 'muted'> = {
  pending: 'muted',
  running: 'blue',
  success: 'green',
  failed: 'red',
  abandoned: 'yellow',
};

// ── inspector building blocks ───────────────────────────────────────────

function InspectorRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, padding: '3px 0' }}>
      <span
        style={{
          color: 'var(--text-muted)',
          fontSize: '.72rem',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '.05em',
          flex: '0 0 130px',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: '.82rem', overflowWrap: 'anywhere' }}>{children}</span>
    </div>
  );
}

/** Status badge: verbatim token text (auditable exact value); the frozen
 * vocabulary only picks the color, unknown values render muted verbatim. */
function NodeStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'muted'}>{status || 'unknown'}</Badge>
  );
}

function NodeReportSection({ runId, nodeId }: { runId: string; nodeId: string }) {
  const t = useT();
  const reportQ = useQuery({
    // Legacy (non-v1) endpoint — its own key family, run/node inside the key.
    queryKey: ['nodeReport', runId, nodeId],
    queryFn: () => fetchNodeReport(runId, nodeId),
    enabled: runId !== '' && nodeId !== '',
  });

  let body: ReactNode;
  if (reportQ.isPending) {
    body = <LoadingState />;
  } else if (reportQ.isError || reportQ.data?.report === undefined) {
    body = (
      <p style={{ color: 'var(--text-muted)', fontSize: '.8rem', margin: 0 }}>
        {t('tree2_report_absent')}
      </p>
    );
  } else {
    const report: NodeReport = reportQ.data.report;
    body = (
      <>
        {report.what_was_done !== undefined && report.what_was_done !== '' && (
          <InspectorRow label={t('tree2_report_what')}>{report.what_was_done}</InspectorRow>
        )}
        {report.evaluator_reason !== undefined && report.evaluator_reason !== '' && (
          <InspectorRow label={t('tree2_report_evaluator')}>
            {report.evaluator_reason}
          </InspectorRow>
        )}
      </>
    );
  }
  return <Card title={t('tree2_report_title')}>{body}</Card>;
}

export function Inspector({
  runId,
  node,
  onClose,
}: {
  runId: string;
  node: TreeNode;
  onClose: () => void;
}) {
  const t = useT();
  const sentinels = sentinelsOf(node.metrics, node.scientific_score);
  const scalarMetrics = scalarMetricsOf(node.metrics);
  const hasScoreRows =
    sentinels.scientificScore !== null ||
    sentinels.prePenaltyScore !== null ||
    sentinels.validatedAttackPenalty !== null ||
    sentinels.utilityPolicyHash !== null ||
    sentinels.stale;

  return (
    <div
      className="tree2-inspector"
      data-testid="tree2-inspector"
      style={{
        width: 320,
        minWidth: 260,
        overflowY: 'auto',
        marginLeft: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <Card title={t('tree2_inspector_title')}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <code style={{ fontSize: '.8rem', overflowWrap: 'anywhere' }}>{node.id}</code>
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            aria-label={t('tree2_close')}
            style={{ fontSize: '.75rem', flexShrink: 0 }}
          >
            {t('tree2_close')}
          </Button>
        </div>
        <InspectorRow label={t('tree2_field_status')}>
          <NodeStatusBadge status={node.status} />
        </InspectorRow>
        <InspectorRow label={t('tree2_field_label')}>
          <Badge variant="muted">{node.label || 'other'}</Badge>
        </InspectorRow>
        <InspectorRow label={t('tree2_field_depth')}>{node.depth}</InspectorRow>
      </Card>

      <Card title={t('tree2_metrics_title')}>
        {sentinels.scientificScore !== null && (
          <InspectorRow label={t('tree2_scientific_score')}>
            <code style={{ fontSize: '.8rem' }}>{String(sentinels.scientificScore)}</code>
            {sentinels.stale && (
              <>
                {' '}
                <Badge variant="yellow">{t('tree2_stale_flag')}</Badge>
              </>
            )}
          </InspectorRow>
        )}
        {sentinels.prePenaltyScore !== null && (
          <InspectorRow label={t('tree2_pre_penalty')}>
            <code style={{ fontSize: '.8rem' }}>{String(sentinels.prePenaltyScore)}</code>
          </InspectorRow>
        )}
        {sentinels.validatedAttackPenalty !== null && (
          <InspectorRow label={t('tree2_validated_penalty')}>
            <code style={{ fontSize: '.8rem' }}>
              {String(sentinels.validatedAttackPenalty)}
            </code>
          </InspectorRow>
        )}
        {sentinels.utilityPolicyHash !== null && (
          <InspectorRow label={t('tree2_policy_hash')}>
            <code style={{ fontSize: '.78rem' }}>{sentinels.utilityPolicyHash}</code>
          </InspectorRow>
        )}
        {scalarMetrics.map(([key, value]) => (
          <InspectorRow key={key} label={key}>
            <code style={{ fontSize: '.8rem' }}>{value}</code>
          </InspectorRow>
        ))}
        {!hasScoreRows && scalarMetrics.length === 0 && (
          <p style={{ color: 'var(--text-muted)', fontSize: '.8rem', margin: 0 }}>
            {t('tree2_no_metrics')}
          </p>
        )}
      </Card>

      <NodeReportSection runId={runId} nodeId={node.id} />

      <Card title={t('tree2_links_title')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* GovernancePage reads only ?run= today — no node preselect is
              passed on purpose, and the note below says so (plan 07 deep
              links; revisit when task 08 adds ?node= support there). */}
          <a href={`#/governance?run=${encodeURIComponent(runId)}`}>
            {t('tree2_link_governance')}
          </a>
          <p style={{ color: 'var(--text-muted)', fontSize: '.72rem', margin: 0 }}>
            {t('tree2_link_governance_note')}
          </p>
          <a href={`#/config?run=${encodeURIComponent(runId)}`}>
            {t('tree2_link_config')}
          </a>
        </div>
      </Card>
    </div>
  );
}
