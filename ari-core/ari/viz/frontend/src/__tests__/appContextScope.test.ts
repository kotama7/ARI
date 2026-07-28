// @vitest-environment node
/// <reference types="vite/client" />
//
// AppContext legacy-scoping guard (gui_refresh G2 tail; plan 03 §State
// ownership — AppContext shrinks from remote-data store to shell-level UI
// concern, with deletion decided last; RR-P0-8 disposition).
//
// The v2 workspaces source remote data run-explicitly from /api/v1 via
// react-query (useV1 hooks) and scope themselves with ?run= URL state.
// AppContext — the legacy /state poller + global-active-checkpoint store —
// must not gain new v2 consumers, or the G6 legacy-removal gate (plan 03
// §Migration sequence step 7: delete duplicate router / legacy remote state)
// becomes un-executable.
//
// Structural source-scan (same spirit as indexHtmlNoExternalScripts.test.ts):
// every non-test source file under the v2 component dirs is loaded raw via
// import.meta.glob and grepped for a context/AppContext import specifier.
// __tests__ files are excluded — tests legitimately mount <AppProvider> as
// the page harness. The single PINNED exception is IdeasV2Page.tsx: its
// research-goal card deliberately reads the AppContext /state goal behind a
// run-identity gate (state.checkpoint_id === ?run=) because no run-scoped v1
// endpoint serves the goal yet — documented in that file's header. Shrinking
// the exception list is welcome; growing it is a G2-tail regression.

import { describe, it, expect } from 'vitest';
// Raw source of the context itself (not part of the v2 glob) for the
// legacy-scoped declaration check.
import APP_CONTEXT_SOURCE from '../context/AppContext.tsx?raw';

// Raw eager glob: v2 dirs only, tests excluded. Patterns must stay literal
// (Vite resolves import.meta.glob statically).
const v2Sources = import.meta.glob(
  [
    '../components/Projects/**/*.{ts,tsx}',
    '../components/Overview/**/*.{ts,tsx}',
    '../components/TreeV2/**/*.{ts,tsx}',
    '../components/IdeasV2/**/*.{ts,tsx}',
    '../components/ResultsV2/**/*.{ts,tsx}',
    '../components/Governance/**/*.{ts,tsx}',
    '../components/ConfigBrowser/**/*.{ts,tsx}',
    '../components/ConfigStudio/**/*.{ts,tsx}',
    '!**/__tests__/**',
  ],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>;

// Import specifiers that bind a module to the legacy context. Matches both
// `from '.../context/AppContext'` and dynamic `import('.../context/AppContext')`.
const APP_CONTEXT_IMPORT = /['"][^'"]*context\/AppContext['"]/;

// Pinned exception set — see header. Keys are the glob's relative paths.
const ALLOWED = new Set(['../components/IdeasV2/IdeasV2Page.tsx']);

describe('v2 workspaces stay AppContext-free (plan 03 G2 tail / RR-P0-8)', () => {
  it('scans a non-vacuous v2 source set', () => {
    // Guards the glob itself: if the dirs move, this fails loudly instead of
    // the import scan passing on zero files.
    expect(Object.keys(v2Sources).length).toBeGreaterThanOrEqual(15);
  });

  it('no v2 source file imports context/AppContext beyond the pinned exception', () => {
    const offenders = Object.entries(v2Sources)
      .filter(([, source]) => APP_CONTEXT_IMPORT.test(source))
      .map(([path]) => path)
      .sort();
    expect(
      offenders,
      'v2 components must source remote data from /api/v1 (useV1 + ?run= URL ' +
        'state), never from the legacy AppContext /state poller. Remove the ' +
        'import, or (only for a documented legacy-parity gap like the ' +
        'IdeasV2 research-goal card) pin it in ALLOWED with a header comment.',
    ).toEqual([...ALLOWED].sort());
  });

  it('AppContext.tsx keeps its legacy-scoped declaration', () => {
    // The header is the human-facing half of this guard; keep them together.
    expect(APP_CONTEXT_SOURCE).toContain('LEGACY-SCOPED');
  });
});
