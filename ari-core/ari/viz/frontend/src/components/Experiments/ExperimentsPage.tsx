import { useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
  fetchSubExperiments,
} from '../../services/api';
import type { SubExperiment } from '../../services/api';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';

function StatusBadge({ status }: { status: string }) {
  if (status === 'running') return <Badge variant="yellow">{'⏳'} Running</Badge>;
  if (status === 'completed' || status === 'success') return <Badge variant="green">{'✓'} Done</Badge>;
  if (status === 'failed') return <Badge variant="red">{'✗'} Failed</Badge>;
  return <Badge variant="muted">{status}</Badge>;
}

export function ExperimentsPage() {
  const { t } = useI18n();
  const { setCurrentPage, checkpoints, refreshCheckpoints } = useAppContext();

  // lineage decisions (v0.7.0): pull sub-experiment metadata so we can render
  // lineage provenance — parent run id and inherit_idea_index — for
  // any checkpoint that was auto-spawned by a lineage decision5c decision.
  const [subById, setSubById] = useState<Record<string, SubExperiment>>({});
  useEffect(() => {
    let alive = true;
    fetchSubExperiments()
      .then((r) => {
        if (!alive) return;
        const m: Record<string, SubExperiment> = {};
        for (const s of r.sub_experiments) m[s.run_id] = s;
        setSubById(m);
      })
      .catch(() => { /* swallow — lineage column degrades to empty */ });
    return () => { alive = false; };
  }, [checkpoints]);

  const navigateTo = (page: string) => {
    setCurrentPage(page);
    window.location.hash = '#/' + page;
  };

  const viewResults = (id: string) => {
    // Store the selected checkpoint id so the Results page can pick it up
    sessionStorage.setItem('ari_selected_checkpoint', id);
    navigateTo('results');
  };

  const viewTree = (id: string) => {
    fetchCheckpointSummary(id).then((d) => {
      // Store tree data for the Tree page to consume
      if (d.nodes_tree && d.nodes_tree.nodes) {
        sessionStorage.setItem(
          'ari_tree_nodes',
          JSON.stringify(d.nodes_tree.nodes),
        );
      }
      navigateTo('tree');
    });
  };

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('experiments_title')}</h1>
      <p className="subtitle">{t('experiments_subtitle')}</p>

      <div
        style={{
          display: 'flex',
          gap: 10,
          marginBottom: 20,
          alignItems: 'center',
        }}
      >
        <Button variant="primary" onClick={() => navigateTo('new')}>
          {'✨'} {t('nav_new')}
        </Button>
        <Button variant="outline" onClick={refreshCheckpoints}>
          {'↻'} Refresh
        </Button>
      </div>

      <Card>
        {checkpoints.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">{'🗂️'}</div>
            <p>No experiments found</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t('project_id')}</th>
                <th>{t('status')}</th>
                <th>BFTS Nodes</th>
                <th>{t('review_score')}</th>
                <th>{t('experiments.lineage')}</th>
                <th>{t('date')}</th>
                <th>{t('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.map((c) => {
                const d = new Date(c.mtime * 1000).toLocaleString();
                const sub = subById[c.id];
                const parent = sub?.parent_run_id ?? null;
                const inheritIdx = sub?.inherit_idea_index ?? null;
                const terminated = sub?.parent_terminated ?? false;
                return (
                  <tr key={c.id}>
                    <td>
                      <code style={{ fontSize: '.8rem' }}>
                        {c.id.slice(0, 14)}
                      </code>
                    </td>
                    <td>
                      <StatusBadge status={c.status} />
                    </td>
                    <td>{c.node_count}</td>
                    <td>
                      {c.review_score != null ? (
                        <strong>{c.review_score}</strong>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
                      {parent ? (
                        <div>
                          <div>
                            ↳ <code style={{ fontSize: '.78rem' }}>
                              {parent.slice(0, 14)}
                            </code>
                          </div>
                          {inheritIdx != null && (
                            <Badge variant="muted">
                              {t('experiments.inherits')} ideas[{inheritIdx}]
                            </Badge>
                          )}
                          {terminated && (
                            <Badge variant="red">
                              {t('experiments.terminated')}
                            </Badge>
                          )}
                        </div>
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td
                      style={{
                        color: 'var(--muted)',
                        fontSize: '.8rem',
                      }}
                    >
                      {d}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => viewResults(c.id)}
                        >
                          Results
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => viewTree(c.id)}
                        >
                          Tree
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

    </div>
  );
}
