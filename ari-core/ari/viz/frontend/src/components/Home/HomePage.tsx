import { useMemo } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import { StatBox } from '../common/StatBox';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';

function StatusBadge({ status }: { status: string }) {
  if (status === 'running') return <Badge variant="yellow">{'⏳'} Running</Badge>;
  if (status === 'completed' || status === 'success') return <Badge variant="green">{'✓'} Done</Badge>;
  if (status === 'failed') return <Badge variant="red">{'✗'} Failed</Badge>;
  return <Badge variant="muted">{status}</Badge>;
}

export function HomePage() {
  const { t } = useI18n();
  const { setCurrentPage, checkpoints } = useAppContext();

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

  const navigateTo = (page: string) => {
    setCurrentPage(page);
    window.location.hash = '#/' + page;
  };

  const latest = checkpoints.length > 0 ? checkpoints[0] : null;

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('home_title')}</h1>
      <p className="subtitle">{t('home_subtitle')}</p>

      {/* Stat boxes */}
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

      {/* Quick Actions + Latest Experiment */}
      <div className="grid-2">
        <Card title={t('home_quick_actions')}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Button variant="primary" onClick={() => navigateTo('new')}>
              {'✨'} {t('nav_new')}
            </Button>
            <Button variant="outline" onClick={() => navigateTo('monitor')}>
              {'📡'} {t('nav_monitor')}
            </Button>
            <Button variant="outline" onClick={() => navigateTo('results')}>
              {'📊'} {t('nav_results')}
            </Button>
            <Button variant="outline" onClick={() => navigateTo('experiments')}>
              {'🗂️'} {t('nav_experiments')}
            </Button>
          </div>
        </Card>

        <Card title={t('home_latest')}>
          {latest ? (
            <div style={{ fontSize: '.85rem', lineHeight: 1.8 }}>
              <div>
                ID: <strong>{latest.id}</strong>
              </div>
              <div>
                Nodes: <strong>{latest.node_count}</strong>
              </div>
              <div>
                Score:{' '}
                <strong>
                  {latest.review_score != null ? latest.review_score : '—'}
                </strong>
              </div>
              <div>
                Status: <StatusBadge status={latest.status} />
              </div>
              <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigateTo('results')}
                >
                  View Results {'→'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigateTo('tree')}
                >
                  View Tree {'→'}
                </Button>
              </div>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: 20 }}>
              <p>No experiments yet</p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
