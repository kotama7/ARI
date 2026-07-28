// ARI Dashboard – shared StaleDataBanner (gui_refresh task 02).
//
// Freshness notice for live surfaces: when a stream (SSE) drops we must NOT
// claim "run stopped" — we keep showing the last known snapshot and say how
// fresh it is (plan 01 §Empty and degraded states). Uses the `--status-info`
// token family (a freshness notice, not a warning/error). `aria-live="polite"`
// so screen readers hear freshness changes without interruption spam. The
// caller passes an already-formatted `lastUpdated` string (or null when the
// snapshot time is unknown). Presentation-only — no fetch, no wire change.

import { useT } from '../../i18n';
import { Button } from './Button';

interface StaleDataBannerProps {
  /** Already-formatted timestamp of the last known snapshot; null = unknown. */
  lastUpdated: string | null;
  /** When supplied, renders a Refresh button that calls this. */
  onRefresh?: () => void;
}

export function StaleDataBanner({ lastUpdated, onRefresh }: StaleDataBannerProps) {
  const t = useT();
  return (
    <div className="stale-banner" role="status" aria-live="polite">
      <span className="stale-banner-msg">
        {t('common_stale_showing_last')}{' '}
        <span className="stale-banner-time">
          {t('common_stale_last_updated')}: {lastUpdated ?? t('common_stale_unknown')}
        </span>
      </span>
      {onRefresh && (
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          style={{ flexShrink: 0 }}
        >
          {t('common_refresh')}
        </Button>
      )}
    </div>
  );
}
