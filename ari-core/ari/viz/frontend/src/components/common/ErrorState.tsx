// ARI Dashboard – shared ErrorState (subtask 072).
//
// Canonical error affordance: a token-colored (`var(--red)`) message plus an
// optional Retry button. Accepts a plain `message: string` from EITHER api error
// regime — a thrown message (get/post, surfaced via useApi.error) OR a
// `response.error` body (pbGet/pbPost). It does NOT unify the two regimes (that
// stays a services/api.ts contract concern); it only renders whatever string it
// is handed. Presentation-only.

import { useT } from '../../i18n';
import { Button } from './Button';

interface ErrorStateProps {
  /** The error text (thrown message or `{error}` body). */
  message: string;
  /** When supplied, renders a Retry button that calls this. */
  onRetry?: () => void;
  /** Override the default `t('cfg_retry')` retry label. */
  retryLabel?: string;
  /** Render as an inline row instead of a padded banner. */
  inline?: boolean;
}

export function ErrorState({ message, onRetry, retryLabel, inline = false }: ErrorStateProps) {
  const t = useT();
  return (
    <div className={inline ? 'error-state error-state-inline' : 'error-state'}>
      <span className="error-state-msg">{message}</span>
      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          onClick={onRetry}
          style={{ marginLeft: 8, flexShrink: 0 }}
        >
          {retryLabel ?? t('cfg_retry')}
        </Button>
      )}
    </div>
  );
}
