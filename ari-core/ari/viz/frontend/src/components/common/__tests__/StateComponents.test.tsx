import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LoadingState, EmptyState, ErrorState } from '..';

/**
 * Unit tests for the shared empty/loading/error state kit (subtask 072).
 *
 * jest-dom matchers are intentionally avoided: they are loaded at runtime
 * (vitest.setup.ts) but are NOT typed for `tsc --noEmit` in this project (see
 * SettingsContract.test.tsx / devModeAndDangerousOps.test.tsx). Using them would
 * add fresh typecheck errors. We assert with query/get helpers + vitest-native
 * matchers only.
 */
describe('common state kit — LoadingState / EmptyState / ErrorState (072)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
  });

  it('LoadingState renders the spinner and the default t(loading) label', () => {
    const { container } = render(<LoadingState />);
    expect(container.querySelector('.spinner')).not.toBeNull();
    // Default label resolves through i18n (en → "Loading…").
    expect(screen.getByText(/Loading/)).toBeTruthy();
  });

  it('LoadingState honors an explicit label override', () => {
    render(<LoadingState label="__custom_loading__" />);
    expect(screen.queryByText('__custom_loading__')).not.toBeNull();
  });

  it('EmptyState renders the message, optional icon and hint', () => {
    render(<EmptyState icon="📭" message="__empty_msg__" hint="__empty_hint__" />);
    expect(screen.queryByText('__empty_msg__')).not.toBeNull();
    expect(screen.queryByText('__empty_hint__')).not.toBeNull();
    expect(screen.queryByText('📭')).not.toBeNull();
  });

  it('ErrorState renders the message and calls onRetry when the retry button is clicked', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="__boom__" onRetry={onRetry} retryLabel="__retry__" />);
    expect(screen.queryByText('__boom__')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '__retry__' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('ErrorState hides the retry button when onRetry is absent', () => {
    render(<ErrorState message="__boom2__" />);
    expect(screen.queryByText('__boom2__')).not.toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('ErrorState accepts a message from either api error regime (plain string)', () => {
    // Regime A: thrown message (get/post → useApi.error). Regime B: {error} body
    // (pbGet/pbPost). Both surface as a plain string — ErrorState renders either.
    render(<ErrorState message="thrown: HTTP 500" />);
    expect(screen.queryByText('thrown: HTTP 500')).not.toBeNull();
  });
});
