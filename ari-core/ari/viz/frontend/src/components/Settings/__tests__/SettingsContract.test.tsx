import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

/**
 * Tier-1 Settings contract (subtask 073 §7.4; pins the 067 invariant that the
 * 070 tabbed redesign must preserve). Two invariants:
 *   1. every settings section renders (067 verified TEN <Card> sections — the
 *      059 "9 cards" figure undercounts the read-only Skills table + the
 *      Project-Management card);
 *   2. Save POSTs a flat object with EXACTLY the 24 keys (SettingsPage.tsx:235-260)
 *      to /api/settings (the dashboard-API contract).
 *
 * The api + AppContext modules are mocked so the component mounts without a live
 * backend; nothing here changes the component or the wire shape.
 */

// vi.mock is hoisted above module top-level consts, so the mock fn must be
// created inside vi.hoisted() to be referenceable from the factory.
const { saveSettings } = vi.hoisted(() => ({
  saveSettings: vi.fn((_settings: Record<string, unknown>) => Promise.resolve({ ok: true })),
}));

vi.mock('../../../services/api', () => ({
  fetchSettings: vi.fn().mockResolvedValue({}),
  saveSettings,
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

// Imported after the mocks so SettingsPage binds to the mocked modules.
import SettingsPage from '../SettingsPage';

// The exact 24-key flat POST shape (SettingsPage.tsx:235-260). 070 must keep it.
const EXPECTED_KEYS = [
  'llm_model', 'llm_backend', 'llm_base_url', 'temperature', 'llm_api_key',
  'semantic_scholar_key', 'retrieval_backend', 'ssh_host', 'ssh_port', 'ssh_user',
  'ssh_path', 'ssh_key', 'slurm_partitions', 'slurm_partition', 'slurm_cpus',
  'slurm_memory_gb', 'slurm_walltime', 'container_mode', 'container_image',
  'container_pull', 'vlm_review_model', 'letta_base_url', 'letta_api_key',
  'letta_embedding_config',
].sort();

// The section titles SettingsPage renders as <Card title=...> (en locale). The
// i18n-keyed titles resolve via useI18n; the rest are literal strings.
const EXPECTED_SECTION_TITLES = [
  'Language', 'LLM Backend', 'Paper Retrieval', 'VLM Figure Review',
  'Memory (Letta)', 'SLURM / HPC Defaults', 'Container', 'Available Skills',
  'SSH Remote Host', 'Project Management',
];

describe('SettingsPage contract (Tier-1; 067 invariant 070 must preserve)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    saveSettings.mockClear();
  });

  it('renders all ten settings sections as <Card> titles', async () => {
    const { container } = render(<SettingsPage />);
    // jest-dom matchers are intentionally avoided (they are not typed for
    // `tsc --noEmit` in this project); getByText throws if absent, so awaiting
    // it in waitFor is a sufficient mount gate.
    await waitFor(() => expect(screen.queryByText('LLM Backend')).not.toBeNull());
    const titles = Array.from(container.querySelectorAll('.card-title')).map(
      (el) => el.textContent,
    );
    for (const title of EXPECTED_SECTION_TITLES) {
      expect(titles).toContain(title);
    }
    // 067 recorded TEN cards (corrects the 059 "9 cards" undercount).
    expect(titles.length).toBe(10);
  });

  it('Save posts exactly the 24-key flat object', async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.queryByText('LLM Backend')).not.toBeNull());
    fireEvent.click(screen.getByRole('button', { name: /Save Settings/i }));
    await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(1));
    const payload = saveSettings.mock.calls[0][0] as Record<string, unknown>;
    expect(Object.keys(payload).sort()).toEqual(EXPECTED_KEYS);
  });
});
