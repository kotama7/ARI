import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PaperImportDialog } from '../PaperImportDialog';

describe('PaperImportDialog (PLAN_GUI §8 acceptance: license warning)', () => {
  beforeEach(() => {
    // Reset localStorage so useI18n defaults consistently
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
  });

  it('renders the permissive license badge for CC BY 4.0', () => {
    render(<PaperImportDialog />);
    const licenseInput = screen.getByDisplayValue(/CC BY 4\.0/i);
    expect(licenseInput).toBeInTheDocument();
    // The optimistic local classifier shows "Permissive license — usable"
    expect(screen.getByText(/Permissive license/i)).toBeInTheDocument();
  });

  it('switches the badge to warning when an unusable license is typed', () => {
    render(<PaperImportDialog />);
    const licenseInput = screen.getByDisplayValue(/CC BY 4\.0/i) as HTMLInputElement;
    fireEvent.change(licenseInput, { target: { value: 'Proprietary Corp License' } });
    // The warning copy must appear
    expect(screen.getByText(/License may require review/i)).toBeInTheDocument();
    // The "permissive" copy must no longer be visible
    expect(screen.queryByText(/^✅ Permissive license/i)).not.toBeInTheDocument();
  });

  it('shows the "Fetch metadata" button when source_type=arxiv and posts to /api/paperbench/arxiv/<id>', async () => {
    const mockResponse = {
      arxiv_id: '2404.14193',
      title: 'LLAMP: assessing latency tolerance',
      authors: ['Alice', 'Bob'],
      year: 2024,
      license: 'arXiv non-exclusive',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => mockResponse,
      ok: true,
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<PaperImportDialog />);
    // Source type defaults to 'arxiv'
    const sourceInput = screen.getByDisplayValue('') as HTMLInputElement;
    fireEvent.change(sourceInput, { target: { value: '2404.14193' } });

    const fetchBtn = screen.getByRole('button', { name: /Fetch metadata/i });
    fireEvent.click(fetchBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/paperbench/arxiv/2404.14193',
      );
    });
    // Title was populated from the response
    await waitFor(() => {
      expect(
        screen.getByDisplayValue('LLAMP: assessing latency tolerance'),
      ).toBeInTheDocument();
    });
    // Authors were joined as comma-separated string
    expect(screen.getByDisplayValue('Alice, Bob')).toBeInTheDocument();
  });
});
