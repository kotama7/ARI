import React, { useCallback, useRef, useState } from 'react';
import { useAppContext } from '../../context/AppContext';
import { useI18n } from '../../i18n';
import { switchCheckpoint } from '../../services/api';

interface NavEntry {
  key: string;
  icon: string;
  labelKey: string;
}

const NAV_ITEMS: NavEntry[] = [
  { key: 'home', icon: '🏠', labelKey: 'nav_home' },
  { key: 'experiments', icon: '🗂️', labelKey: 'nav_experiments' },
  { key: 'monitor', icon: '📡', labelKey: 'nav_monitor' },
  { key: 'tree', icon: '🌳', labelKey: 'nav_tree' },
  { key: 'results', icon: '📊', labelKey: 'nav_results' },
  { key: 'new', icon: '✨', labelKey: 'nav_new' },
  { key: 'idea', icon: '💡', labelKey: 'nav_idea' },
  { key: 'workflow', icon: '⚡', labelKey: 'nav_workflow' },
  { key: 'settings', icon: '⚙️', labelKey: 'nav_settings' },
];

export function Sidebar() {
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
          {NAV_ITEMS.map((item) => (
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
