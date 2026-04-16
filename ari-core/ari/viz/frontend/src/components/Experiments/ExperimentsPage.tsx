import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
} from '../../services/api';
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
                <th>{t('date')}</th>
                <th>{t('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.map((c) => {
                const d = new Date(c.mtime * 1000).toLocaleString();
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
