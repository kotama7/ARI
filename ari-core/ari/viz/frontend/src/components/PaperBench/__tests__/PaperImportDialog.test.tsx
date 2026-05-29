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

  it('uploads the selected PDF to /api/upload and forwards pdf_path on import', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/upload') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ok: true,
            path: '/tmp/staging/uploads/SC41406.2024.00019.pdf',
            filename: 'SC41406.2024.00019.pdf',
          }),
        } as Response);
      }
      if (url === '/api/paperbench/papers/import') {
        const body = JSON.parse(String(init?.body ?? '{}'));
        return Promise.resolve({
          ok: true,
          json: async () => ({
            paper_id: body.source,
            license: body.license,
            permissive: true,
            modifiable: true,
            redistributable: true,
            usable: true,
            note: '',
          }),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<PaperImportDialog />);
    fireEvent.change(screen.getByLabelText(/Source type/i), {
      target: { value: 'upload' },
    });

    const file = new File(['%PDF-1.7\n…'], 'SC41406.2024.00019.pdf', {
      type: 'application/pdf',
    });
    const fileInput = screen.getByLabelText(/PDF file/i) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    // Filename appears in the dialog and source defaults to the stem
    expect(screen.getByText(/SC41406\.2024\.00019\.pdf/)).toBeInTheDocument();
    expect(
      screen.getByDisplayValue('SC41406.2024.00019'),
    ).toBeInTheDocument();

    // Title is required by the form; fill it.
    fireEvent.change(screen.getByLabelText(/^Title$/i), {
      target: { value: 'SC paper external import' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Save to registry/i }));

    await waitFor(() => {
      const uploadCall = fetchMock.mock.calls.find((c) => c[0] === '/api/upload');
      expect(uploadCall).toBeDefined();
      // Multipart upload — body is a FormData instance, not a JSON string.
      expect(uploadCall![1]?.body).toBeInstanceOf(FormData);
    });
    await waitFor(() => {
      const importCall = fetchMock.mock.calls.find(
        (c) => c[0] === '/api/paperbench/papers/import',
      );
      expect(importCall).toBeDefined();
      const body = JSON.parse(String(importCall![1]?.body ?? '{}'));
      expect(body.source_type).toBe('upload');
      expect(body.pdf_path).toBe('/tmp/staging/uploads/SC41406.2024.00019.pdf');
      expect(body.title).toBe('SC paper external import');
    });
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
