import { describe, it } from 'vitest';

/**
 * Tier-2 sibling-gated invariants (subtask 073 §7.4). These assert behavior that
 * DOES NOT EXIST YET, so they ship as `it.todo` to keep the intent discoverable
 * and reviewable without going red on today's 059-only tree. Each names the
 * sibling that un-skips (converts to a real assertion) it. Do NOT enable any of
 * these until its sibling lands — that would violate the 059-only hard gate.
 */
describe('dashboard UX invariants pending sibling refactors (Tier-2)', () => {
  // Un-skip when 070 (developer-mode gate) + 071 land.
  it.todo(
    'hides the { } Raw node-JSON tab (DetailPanel.tsx:364) when developer mode is OFF [enable with 070]',
  );
  it.todo(
    'hides the /api/env-keys secret readback UI when developer mode is OFF [enable with 070]',
  );

  // Un-skip when 071 fixes the api.ts:585 confirmed:true hardcode.
  it.todo(
    'sends confirmed:true only after an explicit user confirmation payload [enable with 071]',
  );

  // Un-skip when 068/069/070 add ARIA tab semantics to Settings/DetailPanel tabs.
  it.todo(
    'Settings/DetailPanel tabs expose role=tab / role=tabpanel / aria-selected [enable with 068/069/070]',
  );

  // Un-skip when 072 lands the empty/loading/error state kit.
  it.todo(
    'renders skeleton/empty/error states via a shared <ErrorBanner>/state kit [enable with 072]',
  );
});
