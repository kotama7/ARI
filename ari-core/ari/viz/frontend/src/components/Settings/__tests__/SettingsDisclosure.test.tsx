import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

/**
 * Progressive-disclosure safety test for the 070 settings refactor.
 *
 * The 069 sensitivity tiers are rendered by <SettingsGroup>, which collapses a
 * tier with CSS `display` only — it must NEVER unmount the cards inside. This
 * test proves that property directly: after collapsing a group, the panel still
 * has exactly TEN `.card-title` nodes in the DOM, so the frozen
 * SettingsContract (TEN cards) cannot be broken by the grouping.
 *
 * jest-dom matchers are intentionally avoided (they are not typed for
 * `tsc --noEmit` in this project — see SettingsContract.test.tsx).
 */

vi.mock('../../../services/api', () => ({
  fetchSettings: vi.fn().mockResolvedValue({}),
  saveSettings: vi.fn().mockResolvedValue({ ok: true }),
  fetchSkills: vi.fn().mockResolvedValue([]),
  fetchPartitions: vi.fn().mockResolvedValue([]),
  fetchCheckpoints: vi.fn().mockResolvedValue([]),
  deleteCheckpoint: vi.fn().mockResolvedValue({ ok: true }),
  testSSH: vi.fn().mockResolvedValue({ ok: true }),
  generateConfig: vi.fn().mockResolvedValue({ ok: true }),
  fetchContainerInfo: vi.fn().mockResolvedValue({}),
  restartLetta: vi.fn().mockResolvedValue({ ok: true }),
}));

vi.mock('../../../context/AppContext', () => ({
  useAppContext: () => ({ state: {}, refreshCheckpoints: vi.fn() }),
}));

import SettingsPage from '../SettingsPage';

describe('SettingsPage progressive disclosure (070; keeps all 10 cards mounted)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
  });

  it('renders four sensitivity-tier group headers', async () => {
    const { container } = render(<SettingsPage />);
    await waitFor(() => expect(screen.queryByText('LLM Backend')).not.toBeNull());
    const headers = container.querySelectorAll('.settings-group-header');
    expect(headers.length).toBe(4);
  });

  it('keeps exactly ten cards mounted after collapsing a tier', async () => {
    const { container } = render(<SettingsPage />);
    await waitFor(() => expect(screen.queryByText('LLM Backend')).not.toBeNull());
    expect(container.querySelectorAll('.card-title').length).toBe(10);
    // Collapse the Essentials tier (first group header) — CSS-only, no unmount.
    const firstHeader = container.querySelector('.settings-group-header') as HTMLElement;
    fireEvent.click(firstHeader);
    expect(container.querySelectorAll('.card-title').length).toBe(10);
  });
});
