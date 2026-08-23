import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DegradedState, StaleDataBanner } from '..';

/**
 * Unit tests for the shared async-state banners (gui_refresh task 02):
 * DegradedState (partial data, warning semantics — distinct from ErrorState)
 * and StaleDataBanner (last known snapshot + freshness). A degraded surface
 * explains its degradation rather than going blank, and a dropped stream is
 * a freshness problem, never a state change — so an SSE drop must never be
 * presented as "run stopped".
 *
 * jest-dom matchers are intentionally avoided: they are loaded at runtime
 * (vitest.setup.ts) but are NOT typed for `tsc --noEmit` in this project (see
 * StateComponents.test.tsx). We assert with query/get helpers + vitest-native
 * matchers only.
 */
describe('common async-state kit — DegradedState / StaleDataBanner (gui_refresh 02)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
  });

  it('DegradedState renders role="status" with the default t(common_degraded_title)', () => {
    render(<DegradedState />);
    const banner = screen.getByRole('status');
    // Default title resolves through i18n (en → "Partial data").
    expect(banner.textContent).toContain('Partial data');
    expect(banner.className).toContain('degraded-state');
  });

  it('DegradedState honors title/detail overrides and renders children', () => {
    render(
      <DegradedState title="__deg_title__" detail="__deg_detail__">
        <span>__deg_child__</span>
      </DegradedState>,
    );
    expect(screen.queryByText('__deg_title__')).not.toBeNull();
    expect(screen.queryByText('__deg_detail__')).not.toBeNull();
    expect(screen.queryByText('__deg_child__')).not.toBeNull();
  });

  it('DegradedState calls onRetry when the retry button is clicked', () => {
    const onRetry = vi.fn();
    render(<DegradedState onRetry={onRetry} />);
    // en → common_retry = "Retry".
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('DegradedState hides the retry button when onRetry is absent', () => {
    render(<DegradedState detail="__no_retry__" />);
    expect(screen.queryByText('__no_retry__')).not.toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('StaleDataBanner announces politely and shows the last known timestamp', () => {
    render(<StaleDataBanner lastUpdated="2026-07-23 10:15:00" />);
    const banner = screen.getByRole('status');
    expect(banner.getAttribute('aria-live')).toBe('polite');
    // en → "Showing last known data." + "Last updated" + the raw timestamp.
    expect(banner.textContent).toContain('Showing last known data.');
    expect(banner.textContent).toContain('Last updated');
    expect(banner.textContent).toContain('2026-07-23 10:15:00');
  });

  it('StaleDataBanner falls back to t(common_stale_unknown) when lastUpdated is null', () => {
    render(<StaleDataBanner lastUpdated={null} />);
    const banner = screen.getByRole('status');
    expect(banner.textContent).toContain('unknown');
    // No refresh handler → no button.
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('StaleDataBanner calls onRefresh when the refresh button is clicked', () => {
    const onRefresh = vi.fn();
    render(<StaleDataBanner lastUpdated="2026-07-23" onRefresh={onRefresh} />);
    // en → common_refresh = "Refresh".
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
