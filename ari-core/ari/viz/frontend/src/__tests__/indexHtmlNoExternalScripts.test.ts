// @vitest-environment node
/// <reference types="vite/client" />
//
// Supply-chain guard for the SPA entry document (gui_refresh task 09
// Wave 5a — RR-P0-10 / MN-7).
//
// The GUI must be fully self-contained: every script and stylesheet comes
// out of the Vite bundle (npm dependencies, lockfile-pinned), never a CDN.
// This keeps the backend's Content-Security-Policy `script-src 'self'`
// honest — an external <script src> would both reintroduce the supply-chain
// exposure the CDN d3 tag had and break under the CSP at runtime.
//
// The source index.html is the single input Vite injects the hashed bundle
// tags into, so guarding it guards the built static/dist/index.html too.
// Loaded via a Vite `?raw` import (same pattern as v1TypesDrift.test.ts)
// because the app tsconfig deliberately has no @types/node.

import { describe, it, expect } from 'vitest';
import indexHtml from '../../index.html?raw';

const EXTERNAL = /^(https?:)?\/\//i;

describe('index.html self-containment (RR-P0-10 / MN-7)', () => {
  it('has no external <script src> (CSP script-src self must hold)', () => {
    const srcs = [...indexHtml.matchAll(/<script[^>]*\ssrc\s*=\s*["']([^"']+)["']/gi)].map(
      (m) => m[1],
    );
    for (const src of srcs) {
      expect(EXTERNAL.test(src), `external script src: ${src}`).toBe(false);
    }
  });

  it('has no external <link href> (stylesheets/fonts stay bundled)', () => {
    const hrefs = [...indexHtml.matchAll(/<link[^>]*\shref\s*=\s*["']([^"']+)["']/gi)].map(
      (m) => m[1],
    );
    for (const href of hrefs) {
      expect(EXTERNAL.test(href), `external link href: ${href}`).toBe(false);
    }
  });

  it('mentions no CDN host anywhere (regression guard for the d3 tag)', () => {
    expect(indexHtml).not.toMatch(
      /cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|jspm\.dev|esm\.sh/i,
    );
  });
});
