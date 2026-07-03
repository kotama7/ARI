// ARI Dashboard – shared LoadingState (subtask 072).
//
// Canonical loading affordance: a spinner plus a translated label. Unifies the
// ad-hoc `<span className="spinner" /> {t('loading')}` / bare-spinner patterns
// scattered across pages. Presentation-only — no fetch, no wire change.
//
//   <LoadingState />                     → centered block, default t('loading')
//   <LoadingState inline />              → inline row (inside a card/editor)
//   <LoadingState label={t('loading_file')} />

import { useT } from '../../i18n';

interface LoadingStateProps {
  /** Override the default `t('loading')` label. */
  label?: string;
  /** Render as an inline row instead of a centered block. */
  inline?: boolean;
}

export function LoadingState({ label, inline = false }: LoadingStateProps) {
  const t = useT();
  const text = label ?? t('loading');
  const content = (
    <>
      <span className="spinner" /> {text}
    </>
  );
  if (inline) {
    return <span style={{ color: 'var(--muted)' }}>{content}</span>;
  }
  return <div className="loading-state">{content}</div>;
}
