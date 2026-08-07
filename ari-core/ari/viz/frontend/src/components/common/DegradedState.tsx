// ARI Dashboard – shared DegradedState (gui_refresh task 02).
//
// Canonical PARTIAL-data affordance: the surface rendered, but some portion is
// missing or unavailable (one endpoint failed while others succeeded, an
// artifact failed to parse, etc.). Deliberately DISTINCT from ErrorState
// (total failure): warning semantics via the `--status-warning` token family,
// `role="status"` (polite announcement, not an alert), and the surrounding
// content stays visible. Presentation-only — no fetch, no wire change.

import type { ReactNode } from 'react';
import { useT } from '../../i18n';
import { Button } from './Button';

interface DegradedStateProps {
  /** Override the default `t('common_degraded_title')` heading. */
  title?: string;
  /** Optional translated detail line (what is missing / why). */
  detail?: string;
  /** When supplied, renders a Retry button that calls this. */
  onRetry?: () => void;
  /** Optional extra content rendered below the detail line. */
  children?: ReactNode;
}

export function DegradedState({ title, detail, onRetry, children }: DegradedStateProps) {
  const t = useT();
  return (
    <div className="degraded-state" role="status">
      <div className="degraded-state-body">
        <div className="degraded-state-title">{title ?? t('common_degraded_title')}</div>
        {detail && <div className="degraded-state-detail">{detail}</div>}
        {children}
      </div>
      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          onClick={onRetry}
          style={{ flexShrink: 0 }}
        >
          {t('common_retry')}
        </Button>
      )}
    </div>
  );
}
