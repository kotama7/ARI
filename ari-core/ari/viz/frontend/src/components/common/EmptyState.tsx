// ARI Dashboard – shared EmptyState (subtask 072).
//
// Canonical "no data yet" affordance built on the existing `.empty-state` /
// `.empty-icon` CSS (styles/components.css). Callers pass an already-translated
// `message` (and optional `hint` / emoji `icon`) so the same block renders on
// every list/detail surface. Presentation-only.

interface EmptyStateProps {
  /** Emoji/glyph shown above the message (e.g. "📊"). */
  icon?: string;
  /** Translated primary message. */
  message: string;
  /** Optional translated secondary line (e.g. a next-action hint). */
  hint?: string;
}

export function EmptyState({ icon, message, hint }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <p>{message}</p>
      {hint && (
        <p style={{ fontSize: '.8rem', opacity: 0.8, marginTop: 4 }}>{hint}</p>
      )}
    </div>
  );
}
