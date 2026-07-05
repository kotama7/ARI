import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

/**
 * SettingsGroup — a progressive-disclosure wrapper that groups one or more
 * settings <Card>s under a sensitivity tier (Essentials / Project /
 * Infrastructure / Diagnostics & Danger Zone), per the 069 disclosure design.
 *
 * CONTRACT-CRITICAL: children are ALWAYS rendered (mounted). Collapsing only
 * toggles CSS `display` on the body wrapper — it never conditionally unmounts
 * the cards. This keeps every <Card>'s `.card-title` in the DOM so the frozen
 * SettingsContract test (TEN cards) stays green regardless of open/closed
 * state. Advanced tiers simply start collapsed so an everyday operator sees
 * Essentials first.
 */
interface SettingsGroupProps {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  danger?: boolean;
  children: ReactNode;
}

export function SettingsGroup({
  title,
  subtitle,
  defaultOpen = true,
  danger = false,
  children,
}: SettingsGroupProps) {
  const [open, setOpen] = useState(defaultOpen);

  const headerStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    width: '100%',
    padding: '8px 4px',
    background: 'transparent',
    border: 'none',
    borderBottom: '1px solid var(--border)',
    cursor: 'pointer',
    textAlign: 'left',
    color: danger ? 'var(--red)' : 'var(--text)',
    fontSize: '.9rem',
    fontWeight: 700,
  };

  const bodyStyle: CSSProperties = {
    display: open ? 'flex' : 'none',
    flexDirection: 'column',
    gap: '16px',
    marginTop: open ? '12px' : 0,
  };

  return (
    <section className={`settings-group${danger ? ' settings-group-danger' : ''}`}>
      <button
        type="button"
        className="settings-group-header"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={headerStyle}
      >
        <span
          aria-hidden="true"
          style={{
            display: 'inline-block',
            transition: 'transform .15s',
            transform: open ? 'rotate(90deg)' : 'none',
          }}
        >
          {'▸'}
        </span>
        <span>{title}</span>
        {subtitle && (
          <span style={{ fontWeight: 400, fontSize: '.78rem', color: 'var(--muted)' }}>
            {subtitle}
          </span>
        )}
      </button>
      <div className="settings-group-body" style={bodyStyle}>
        {children}
      </div>
    </section>
  );
}
