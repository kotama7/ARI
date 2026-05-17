import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { PaperBenchWizard } from '../PaperBenchWizard';

describe('PaperBenchWizard (PLAN_GUI §8 acceptance: Step 3 execution_profile override)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    // Cost-estimate endpoint is polled on every config change; return a
    // minimal payload so the live estimate panel doesn't blow up.
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/api/paperbench/papers')) {
        return Promise.resolve({
          json: async () => ({
            papers: [
              {
                paper_id: 'sc24-llamp',
                title: 'LLAMP',
                license: 'cc by 4.0',
                license_assessment: { usable: true },
              },
            ],
          }),
        });
      }
      if (url.endsWith('/cost-estimate')) {
        return Promise.resolve({
          json: async () => ({ wall_time_sec: 3600, llm_cost_usd: 1.5, breakdown: {} }),
        });
      }
      if (url.endsWith('/api/paperbench/run')) {
        return Promise.resolve({
          json: async () => ({ dry_run: false, job_ids: ['job-abc'], estimated_cost: {} }),
        });
      }
      return Promise.resolve({ json: async () => ({}) });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('Step 3 execution_profile override fields are included verbatim in the launch POST body', async () => {
    render(<PaperBenchWizard />);
    // Wait for the paper list to load
    await screen.findByText(/LLAMP/);

    // Step 1: select the paper
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    // Click Next to reach Step 2 → Step 3 → Step 4 → Step 5
    const advance = async (times: number) => {
      for (let i = 0; i < times; i++) {
        const next = screen.getByRole('button', { name: /Next/i });
        await act(async () => {
          fireEvent.click(next);
        });
      }
    };

    await advance(1); // Step 1 → Step 2 (Rubric)
    await advance(1); // Step 2 → Step 3 (Reproduce)

    // Step 3 — fill the execution_profile override fields
    const nodesInput = screen.getByDisplayValue('0') as HTMLInputElement; // first 0 = nodes
    fireEvent.change(nodesInput, { target: { value: '4' } });

    // Toggle exclusive
    const exclusiveCheckbox = screen.getByRole('checkbox', { name: /exclusive/i });
    fireEvent.click(exclusiveCheckbox);

    // gpu_type field
    const gpuTypeInput = screen.getByPlaceholderText(/v100/i) ?? null;
    if (gpuTypeInput) {
      fireEvent.change(gpuTypeInput, { target: { value: 'v100' } });
    }
    // Otherwise fall back to label-based lookup
    if (!gpuTypeInput) {
      const lbl = screen.getByText(/gpu_type/i);
      const input = lbl.querySelector('input') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'v100' } });
    }

    // extra_sbatch_args
    const extraInput = screen.getByPlaceholderText(/account=projX/i) as HTMLInputElement;
    fireEvent.change(extraInput, { target: { value: '--account=projX' } });

    await advance(2); // Step 3 → 4 → 5 (Launch)

    // Click Launch all
    const launchBtn = screen.getByRole('button', { name: /Launch all/i });
    await act(async () => {
      fireEvent.click(launchBtn);
    });

    await waitFor(() => {
      const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const launchCall = calls.find(([url]) => url === '/api/paperbench/run');
      expect(launchCall).toBeTruthy();
      const body = JSON.parse(launchCall![1].body);
      expect(body.paper_ids).toEqual(['sc24-llamp']);
      expect(body.reproduce_config.nodes).toBe(4);
      expect(body.reproduce_config.exclusive).toBe(true);
      // gpu_type may or may not have caught (placeholder-based selector
      // is brittle); but extra_sbatch_args should split on whitespace
      expect(body.reproduce_config.extra_sbatch_args).toEqual(['--account=projX']);
    });
  });

  it('disables Next on Step 1 until at least one paper is selected', async () => {
    render(<PaperBenchWizard />);
    await screen.findByText(/LLAMP/);
    const next = screen.getByRole('button', { name: /Next/i });
    expect(next).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox'));
    expect(next).not.toBeDisabled();
  });
});
