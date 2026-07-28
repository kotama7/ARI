import React, { useCallback, useRef, useState } from 'react';
import { useAppContext } from '../../context/AppContext';
import { useI18n } from '../../i18n';
import { switchCheckpoint } from '../../services/api';
import { navItems } from '../../app/routeRegistry';

interface NavEntry {
  key: string;
  icon: string;
  labelKey: string;
  /** Marks a v2-only entry: rendered only while the gui_v2 flag is on. */
  guiV2?: true;
  /**
   * Nav takeover (gui_refresh Wave 4c): nav key of the entry this one hides
   * while the gui_v2 flag is on (the registry's navReplaces target). The
   * replacer inherits the target's slot (order/icon/label via navItems()),
   * so only the hash a click writes changes.
   */
  navReplaces?: string;
}

// Derived from the single-source route registry (gui_refresh Wave 1 task 03);
// order, icons, and labels are identical to the pre-registry literal table.
// `key` is the hash path a click writes: `navPath` preserves the historical
// '#/new' URL for the wizard route (hash URLs are the frozen deployment
// contract). Exported for the route <-> nav parity test, which pins the
// exact table. Entries carrying the registry's guiV2 marker (Wave 2b:
// 'projects') stay in this table unconditionally — the Sidebar component
// filters them at render time based on the gui_v2 capability prop. A
// navReplaces entry (Wave 4c: 'tree_v2' over 'tree') additionally hides its
// target while the flag is on, so the slot swaps between the legacy and v2
// hash without ever showing both.
const NAV_ROUTES = navItems();
export const NAV_ITEMS: NavEntry[] = NAV_ROUTES.map((route) => {
  const target =
    route.navReplaces !== undefined
      ? NAV_ROUTES.find((r) => r.id === route.navReplaces)
      : undefined;
  return {
    key: route.navPath ?? route.path,
    icon: route.navIcon ?? '',
    labelKey: route.navLabelKey ?? '',
    ...(route.guiV2 ? { guiV2: true as const } : {}),
    ...(target !== undefined
      ? { navReplaces: target.navPath ?? target.path }
      : {}),
  };
});

export function Sidebar({ guiV2 = true }: { guiV2?: boolean }) {
  const { currentPage, setCurrentPage, state, checkpoints, refreshCheckpoints } = useAppContext();
  const { t } = useI18n();

  // ── Sidebar resize ──
  const sidebarRef = useRef<HTMLDivElement>(null);
  const [sidebarWidth, setSidebarWidth] = useState<number>(220);
  const dragging = useRef(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const newWidth = Math.max(60, Math.min(400, ev.clientX));
      setSidebarWidth(newWidth);
    };

    const onMouseUp = () => {
      dragging.current = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, []);

  // ── Project switcher ──
  const handleProjectSwitch = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const path = e.target.value;
      if (!path) return;
      try {
        await switchCheckpoint(path);
        refreshCheckpoints();
      } catch (err) {
        console.warn('Failed to switch checkpoint', err);
      }
    },
    [refreshCheckpoints],
  );

  // ── Mobile hamburger ──
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleNav = useCallback(
    (key: string) => {
      window.location.hash = `#/${key}`;
      setCurrentPage(key);
      setMobileOpen(false);
    },
    [setCurrentPage],
  );

  const isCollapsed = sidebarWidth < 100;

  // Nav takeover (gui_refresh Wave 4c): while the v2 shell is on, each
  // rendered navReplaces entry hides its target (e.g. 'tree_v2' takes the
  // 'tree' slot and writes '#/tree2'); while it is off, the guiV2 filter
  // hides the replacer instead and the legacy entry stays byte-identical.
  const replacedKeys = new Set(
    guiV2
      ? NAV_ITEMS.filter((item) => item.navReplaces !== undefined).map(
          (item) => item.navReplaces as string,
        )
      : [],
  );
  const visibleNavItems = NAV_ITEMS.filter(
    (item) => (guiV2 || !item.guiV2) && !replacedKeys.has(item.key),
  );

  return (
    <>
      {/* Hamburger button (visible only at <=480px via CSS) */}
      <button
        id="btn-hamburger"
        style={{ display: 'none' }}
        onClick={() => setMobileOpen((v) => !v)}
        aria-label="Menu"
      >
        {'☰'}
      </button>

      {/* Overlay for mobile sidebar */}
      {mobileOpen && (
        <div
          id="sidebar-overlay"
          className="active"
          onClick={() => setMobileOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,.5)',
            zIndex: 199,
          }}
        />
      )}

      <div
        ref={sidebarRef}
        id="sidebar"
        className={mobileOpen ? 'sidebar-open' : ''}
        style={{ width: sidebarWidth, minWidth: sidebarWidth }}
      >
        {/* Logo */}
        <div className="sidebar-logo">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img
              src="/logo.png"
              alt="ARI"
              style={{ width: 40, height: 40, objectFit: 'contain', borderRadius: 8 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
            {!isCollapsed && (
              <div className="sidebar-logo-text">
                <div style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.5px', color: 'var(--blue-light)' }}>ARI</div>
                <div style={{ fontSize: '.7rem', color: 'var(--muted)' }}>Autonomous Research Intelligence</div>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav>
          {visibleNavItems.map((item) => (
            <div
              key={item.key}
              className={`nav-item${currentPage === item.key || (item.key === 'new' && currentPage === 'wizard') ? ' active' : ''}`}
              onClick={() => handleNav(item.key)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleNav(item.key);
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              {!isCollapsed && <span className="nav-label">{t(item.labelKey)}</span>}
            </div>
          ))}
        </nav>

        {/* Project switcher */}
        {!isCollapsed && (
          <div id="project-switcher">
            <label>{t('active_project')}</label>
            <select
              id="project-select"
              value={state?.checkpoint_path ?? ''}
              onChange={handleProjectSwitch}
            >
              <option value="">{t('select_active_project')}</option>
              {checkpoints.map((cp) => (
                <option key={cp.id} value={cp.path}>
                  {cp.id}
                </option>
              ))}
            </select>
            {state?.status_label && (
              <div className="project-status">{state.status_label}</div>
            )}
          </div>
        )}

        {/* Resize handle */}
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: 0,
            bottom: 0,
            width: 5,
            cursor: 'col-resize',
            zIndex: 10,
          }}
          onMouseDown={onMouseDown}
        />
      </div>
    </>
  );
}
