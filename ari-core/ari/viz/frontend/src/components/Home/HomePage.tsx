import { useMemo } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import { StatBox } from '../common/StatBox';
import { Card } from '../common/Card';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/EmptyState';

function StatusBadge({ status }: { status: string }) {
  if (status === 'running') return <Badge variant="yellow">{'⏳'} Running</Badge>;
  if (status === 'completed' || status === 'success') return <Badge variant="green">{'✓'} Done</Badge>;
  if (status === 'failed') return <Badge variant="red">{'✗'} Failed</Badge>;
  if (status === 'blocked') return <Badge variant="red">{'✗'} Blocked</Badge>;
  return <Badge variant="muted">{status}</Badge>;
}

export function HomePage() {
  const { t } = useI18n();
  const { checkpoints } = useAppContext();

  const { totalNodes, bestScore } = useMemo(() => {
    let nodes = 0;
    let best: number | null = null;
    for (const c of checkpoints) {
      nodes += c.node_count || 0;
      const sc = c.review_score;
      if (sc != null && (best === null || sc > best)) best = sc;
    }
    return { totalNodes: nodes, bestScore: best };
  }, [checkpoints]);

  const latest = checkpoints.length > 0 ? checkpoints[0] : null;

  return (
    <div className="page active home-dashboard" style={{ display: 'block' }}>
      <header className="workspace-header">
        <div>
          <div className="workspace-eyebrow">{t('nav_home')}</div>
          <h1>{t('home_title')}</h1>
          <p className="subtitle">{t('home_subtitle')}</p>
        </div>
        <a className="btn btn-primary workspace-primary-action" href="#/new">
          <span aria-hidden="true">{'＋'}</span>
          {t('nav_new')}
        </a>
      </header>

      {/* Portfolio summary */}
      <div className="grid-3" style={{ marginBottom: 16 }}>
        <StatBox
          value={checkpoints.length || 0}
          label={t('home_total_runs')}
        />
        <StatBox
          value={bestScore !== null ? bestScore.toFixed(1) : '—'}
          label={t('home_best_score')}
        />
        <StatBox
          value={totalNodes}
          label={t('home_total_nodes')}
        />
      </div>

      <div className="home-dashboard-grid">
        <Card className="home-latest-card" title={t('home_latest')}>
          {latest ? (
            <div>
              <div className="home-run-heading">
                <div>
                  <strong>{latest.id.replace(/^\d{8,14}_/, '').replace(/_/g, ' ')}</strong>
                  <code>{latest.id}</code>
                </div>
                <StatusBadge status={latest.status} />
              </div>

              <div className="home-run-metrics">
                <div>
                  <span>{t('home_total_nodes')}</span>
                  <strong>{latest.node_count}</strong>
                </div>
                <div>
                  <span>{t('review_score')}</span>
                  <strong>
                    {latest.review_score != null ? latest.review_score : '—'}
                  </strong>
                </div>
                <div>
                  <span>{t('projects_freshness')}</span>
                  <strong>
                    {latest.mtime
                      ? new Date(latest.mtime * 1000).toLocaleDateString()
                      : '—'}
                  </strong>
                </div>
              </div>

              <div className="home-run-links">
                <a href={`#/overview?run=${encodeURIComponent(latest.id)}`}>
                  {t('nav_overview')} {'→'}
                </a>
                <a href={`#/tree2?run=${encodeURIComponent(latest.id)}`}>
                  {t('nav_tree')} {'→'}
                </a>
                <a href={`#/results2?run=${encodeURIComponent(latest.id)}`}>
                  {t('nav_results')} {'→'}
                </a>
              </div>
            </div>
          ) : (
            <EmptyState
              message={t('home_no_experiments')}
              hint={t('home_subtitle')}
            />
          )}
        </Card>

        <Card className="home-workspaces-card" title={t('home_quick_actions')}>
          <div className="home-workspace-links">
            {[
              ['📁', 'projects', 'nav_projects'],
              ['📡', 'monitor', 'nav_monitor'],
              ['🗂️', 'experiments', 'nav_experiments'],
              ['⚡', 'workflow', 'nav_workflow'],
            ].map(([icon, path, labelKey]) => (
              <a key={path} href={`#/${path}`}>
                <span aria-hidden="true">{icon}</span>
                <strong>{t(labelKey)}</strong>
                <span aria-hidden="true">{'›'}</span>
              </a>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
