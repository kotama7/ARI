// Vitest global setup. Loaded once per test process.
//
// - Imports @testing-library/jest-dom so matchers like .toBeInTheDocument()
//   work out of the box.
// - Stubs window.fetch / EventSource for tests that don't explicitly mock
//   them, so a missed mock surfaces as a clear "fetch not mocked" failure
//   rather than a network error.

import '@testing-library/jest-dom/vitest';
import { vi, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Default no-op EventSource (component tests can replace via vi.stubGlobal)
class FakeEventSource {
  url: string;
  readyState: number = 0;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  constructor(url: string) {
    this.url = url;
  }
  addEventListener() {
    /* no-op */
  }
  removeEventListener() {
    /* no-op */
  }
  close() {
    this.readyState = 2;
  }
  dispatchEvent() {
    return true;
  }
}
vi.stubGlobal('EventSource', FakeEventSource);
