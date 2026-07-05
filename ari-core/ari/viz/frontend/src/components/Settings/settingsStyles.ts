import type { CSSProperties } from 'react';

// Shared field styles for the Settings sections. Moved verbatim out of
// SettingsPage.tsx (formerly :337-352) so every extracted `sections/*`
// component consumes one definition instead of re-declaring it. Pure data —
// no React state — so the values are byte-identical to the pre-split panel.

export const inputStyle: CSSProperties = {
  padding: '6px 10px',
  borderRadius: '6px',
  border: '1px solid var(--border)',
  background: 'var(--card)',
  color: 'var(--text)',
  fontSize: '.85rem',
  width: '100%',
};

export const labelStyle: CSSProperties = {
  fontSize: '.82rem',
  color: 'var(--muted)',
  marginBottom: '4px',
  display: 'block',
};
