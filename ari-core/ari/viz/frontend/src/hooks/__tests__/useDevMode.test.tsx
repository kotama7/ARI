import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useDevMode, isDevMode } from '../useDevMode';

/**
 * Unit coverage for the 071 developer-mode flag: default OFF, localStorage
 * persistence, and cross-instance sync (two mounted hooks stay consistent when
 * the flag flips — the weakness the useI18n pattern has and useDevMode fixes).
 * jest-dom matchers are avoided (untyped for tsc --noEmit here).
 */

function Probe({ label }: { label: string }) {
  const { devMode, setDevMode } = useDevMode();
  return (
    <div>
      <span data-testid={`state-${label}`}>{devMode ? 'on' : 'off'}</span>
      <button onClick={() => setDevMode(!devMode)}>toggle-{label}</button>
    </div>
  );
}

describe('useDevMode (071)', () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
  });

  it('defaults to OFF when the key is absent', () => {
    expect(isDevMode()).toBe(false);
    render(<Probe label="a" />);
    expect(screen.getByTestId('state-a').textContent).toBe('off');
  });

  it('reads ON from localStorage[ari_dev_mode] = "1"', () => {
    localStorage.setItem('ari_dev_mode', '1');
    expect(isDevMode()).toBe(true);
    render(<Probe label="a" />);
    expect(screen.getByTestId('state-a').textContent).toBe('on');
  });

  it('persists the flag and syncs every mounted instance when toggled', () => {
    render(
      <div>
        <Probe label="a" />
        <Probe label="b" />
      </div>,
    );
    expect(screen.getByTestId('state-a').textContent).toBe('off');
    expect(screen.getByTestId('state-b').textContent).toBe('off');

    fireEvent.click(screen.getByText('toggle-a'));

    // Persisted to localStorage...
    expect(localStorage.getItem('ari_dev_mode')).toBe('1');
    // ...and BOTH instances observe the change (cross-instance sync).
    expect(screen.getByTestId('state-a').textContent).toBe('on');
    expect(screen.getByTestId('state-b').textContent).toBe('on');
  });
});
