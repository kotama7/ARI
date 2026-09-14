import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigStudioPage } from '../ConfigStudioPage';
import {
  fetchConfigSchemaV1,
  fetchModelCatalogV1,
  fetchProjectConfigV1,
  fetchRunDraftV1,
  fetchRunTemplatesV1,
  fetchSecretsStatusV1,
  launchRunV1,
  patchRunDraftV1,
  resolveDraftConfigV1,
  validateRunDraftV1,
  type ConfigFieldV1,
  type ConfigSchemaV1,
  type DraftValidationV1,
  type ModelCatalogV1,
  type ProjectConfigV1,
  type RequestIdV1,
  type ResolvedNewRunConfigV1,
  type RunDraftV1,
  type RunTemplateListV1,
  type SecretStatusV1,
} from '../../../services/api/v1';

/**
 * ADR-09 mode selection in the Configuration Studio (accepted by the program
 * 2026-07-27 — the GUI may select the execution mode and the paper mode FOR A
 * NEW RUN, superseding the "no CLI flag / no GUI toggle" statement in
 * docs/guides/execution_modes.md).
 *
 * The typed v1 fetchers are mocked at the module boundary (react-query hooks
 * and ApiErrorV1 normalization stay REAL), pinning:
 *   - ONE control per intent writes BOTH leaves of its pair, and the Studio
 *     save carries them in a SINGLE PATCH — never one key without the other;
 *   - the 2x2 combination matrix renders and round-trips (the axes are
 *     orthogonal: all four combinations are reachable and displayable);
 *   - re-selecting the stored value clears the pending pair, so the DEFAULT
 *     path (simple_bfts + linear) writes NOTHING at all;
 *   - the launch review shows the RESOLVED mode from the resolve-config
 *     manifest, not the raw selection: a backend-reported fallback renders
 *     requested -> resolved plus the resolver warning verbatim;
 *   - a mode_interlock_mismatch validation error blocks the launch with the
 *     typed message shown;
 *   - the remaining rqgm.* tree renders VALUES but exposes no editable
 *     control (governance tuning stays file-owned in this release).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchConfigSchemaV1: vi.fn(),
    fetchProjectConfigV1: vi.fn(),
    fetchRunTemplatesV1: vi.fn(),
    fetchRunDraftV1: vi.fn(),
    patchRunDraftV1: vi.fn(),
    fetchSecretsStatusV1: vi.fn(),
    fetchModelCatalogV1: vi.fn(),
    resolveDraftConfigV1: vi.fn(),
    validateRunDraftV1: vi.fn(),
    launchRunV1: vi.fn(),
  };
});

const schemaMock = vi.mocked(fetchConfigSchemaV1);
const projectMock = vi.mocked(fetchProjectConfigV1);
const templatesMock = vi.mocked(fetchRunTemplatesV1);
const draftMock = vi.mocked(fetchRunDraftV1);
const patchDraftMock = vi.mocked(patchRunDraftV1);
const secretsMock = vi.mocked(fetchSecretsStatusV1);
const catalogMock = vi.mocked(fetchModelCatalogV1);
const resolveMock = vi.mocked(resolveDraftConfigV1);
const validateMock = vi.mocked(validateRunDraftV1);
const launchMock = vi.mocked(launchRunV1);

const DRAFT_ID = 'draft-abc123def456';
const DRAFT_REVISION = 7;

// ── payload builders (shapes from v1types.gen.ts) ───────────────────────

function makeField(overrides: Partial<ConfigFieldV1> & { path: string }): ConfigFieldV1 {
  return {
    applies_when: null,
    category: 'Models',
    default: null,
    enum: null,
    env_override: null,
    level: 'basic',
    mutability: 'draft',
    notes: null,
    required: false,
    scope: 'project',
    sensitivity: 'public',
    source: 'pydantic',
    value_type: 'str',
    ...overrides,
  };
}

/** The four ADR-09 mode leaves plus two of the ~96 read-only tuning leaves. */
function makeSchema(): ConfigSchemaV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-schema',
    resolver_version: 'legacy-compatible-1',
    fields: [
      makeField({ path: 'llm.model', default: 'default-model' }),
      makeField({
        path: 'ari.mode',
        category: 'Execution mode',
        enum: ['simple_bfts', 'ari_rqgm'],
        default: 'simple_bfts',
        mutability: 'new_run_only',
        scope: 'run',
        applies_when: 'paired with rqgm.enabled (one intent — set both)',
      }),
      makeField({
        path: 'rqgm.enabled',
        category: 'Execution mode',
        value_type: 'bool',
        default: false,
        mutability: 'new_run_only',
        scope: 'run',
      }),
      makeField({
        path: 'paper.mode',
        category: 'Execution mode',
        enum: ['linear', 'rqgm_archive'],
        default: 'linear',
        mutability: 'new_run_only',
        scope: 'run',
      }),
      makeField({
        path: 'rqgm.paper.enabled',
        category: 'Execution mode',
        value_type: 'bool',
        default: false,
        mutability: 'new_run_only',
        scope: 'run',
      }),
      makeField({
        path: 'rqgm.epoch.size',
        category: 'Governance',
        value_type: 'int',
        default: 10,
        mutability: 'new_run_only',
        level: 'expert',
        scope: 'run',
        applies_when: 'ari.mode=ari_rqgm',
      }),
      makeField({
        path: 'rqgm.adversarial.audit_ratio',
        category: 'Governance',
        value_type: 'float',
        default: 0.25,
        mutability: 'new_run_only',
        level: 'expert',
        scope: 'run',
      }),
    ],
  };
}

function makeProject(): ProjectConfigV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-project',
    revision: 1,
    values: {},
    updated_paths_count: 0,
  };
}

function makeTemplates(): RunTemplateListV1 & RequestIdV1 {
  return { schema_version: 1, request_id: 'req-templates', templates: [] };
}

function makeDraft(values: Record<string, unknown> = {}): RunDraftV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-draft',
    draft_id: DRAFT_ID,
    template_id: null,
    revision: DRAFT_REVISION,
    values,
    goal: 'Audit an HPC paper',
    updated_at: '2026-07-27T00:00:00Z',
  };
}

function makeSecrets(): SecretStatusV1 & RequestIdV1 {
  return { schema_version: 1, request_id: 'req-secrets', secrets: [] };
}

function makeCatalog(): ModelCatalogV1 & RequestIdV1 {
  return { schema_version: 1, request_id: 'req-catalog', providers: [] };
}

/** Resolved manifest: NESTED values, exactly like ari.config.resolver. */
function makeResolved(
  overrides: Partial<ResolvedNewRunConfigV1> = {},
): ResolvedNewRunConfigV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-resolve',
    resolver_version: 'legacy-compatible-1',
    run_id: DRAFT_ID,
    digest: 'sha256:m0d3sel3ct',
    resolved_at: '2026-07-27T00:00:00Z',
    source_stack: ['default', 'draft'],
    values: {
      ari: { mode: 'simple_bfts' },
      paper: { mode: 'linear' },
      rqgm: { enabled: false, paper: { enabled: false } },
    },
    provenance: {
      'ari.mode': {
        source: 'default',
        mutable: true,
        confidence: 'high',
        rejected_override: null,
      },
      'paper.mode': {
        source: 'default',
        mutable: true,
        confidence: 'high',
        rejected_override: null,
      },
    },
    secret_references: {},
    warnings: [],
    ...overrides,
  };
}

function makeValidation(
  overrides: Partial<DraftValidationV1> = {},
): DraftValidationV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-validate',
    draft_id: DRAFT_ID,
    valid: true,
    errors: [],
    warnings: [],
    ...overrides,
  };
}

// ── harness ─────────────────────────────────────────────────────────────

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConfigStudioPage />
    </QueryClientProvider>,
  );
}

/** Render the draft scope and open the Execution section. */
async function openExecutionSection() {
  renderPage();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /⚙️ Execution/ })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole('button', { name: /⚙️ Execution/ }));
  await waitFor(() => expect(screen.getByLabelText('Execution mode')).toBeInTheDocument());
}

async function openLaunchReview() {
  renderPage();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Resolve & validate' })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Resolve & validate' }));
  await waitFor(() => expect(resolveMock).toHaveBeenCalledWith(DRAFT_ID, undefined));
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/studio?draft=${DRAFT_ID}`;
  vi.clearAllMocks();
  vi.stubGlobal('crypto', {
    randomUUID: () => '00000000-0000-4000-8000-000000000001',
  } as unknown as Crypto);
  schemaMock.mockResolvedValue(makeSchema());
  projectMock.mockResolvedValue(makeProject());
  templatesMock.mockResolvedValue(makeTemplates());
  draftMock.mockResolvedValue(makeDraft());
  patchDraftMock.mockResolvedValue(makeDraft());
  secretsMock.mockResolvedValue(makeSecrets());
  catalogMock.mockResolvedValue(makeCatalog());
  resolveMock.mockResolvedValue(makeResolved());
  validateMock.mockResolvedValue(makeValidation());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ConfigStudio Execution section (ADR-09 mode selection)', () => {
  it('writes BOTH leaves of an intent pair in ONE PATCH', async () => {
    await openExecutionSection();

    fireEvent.change(screen.getByLabelText('Execution mode'), {
      target: { value: 'ari_rqgm' },
    });
    // One user action -> two keys in the edit buffer, never one alone.
    expect(screen.getByText('2 unsaved edit(s)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(patchDraftMock).toHaveBeenCalledTimes(1));
    expect(patchDraftMock).toHaveBeenCalledWith(
      DRAFT_ID,
      { 'ari.mode': 'ari_rqgm', 'rqgm.enabled': true },
      DRAFT_REVISION,
    );
  });

  it('writes the paper intent pair independently of the execution intent', async () => {
    await openExecutionSection();

    fireEvent.change(screen.getByLabelText('Paper mode'), {
      target: { value: 'rqgm_archive' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(patchDraftMock).toHaveBeenCalledTimes(1));
    // The execution pair is untouched — the two axes are orthogonal.
    expect(patchDraftMock).toHaveBeenCalledWith(
      DRAFT_ID,
      { 'paper.mode': 'rqgm_archive', 'rqgm.paper.enabled': true },
      DRAFT_REVISION,
    );
    expect(screen.getByText(/The two settings are independent/)).toBeInTheDocument();
  });

  it('renders and round-trips all four mode combinations', async () => {
    const combos: Array<[string, boolean, string, boolean]> = [
      ['simple_bfts', false, 'linear', false],
      ['simple_bfts', false, 'rqgm_archive', true],
      ['ari_rqgm', true, 'linear', false],
      ['ari_rqgm', true, 'rqgm_archive', true],
    ];
    for (const [mode, enabled, paperMode, paperEnabled] of combos) {
      draftMock.mockResolvedValue(
        makeDraft({
          'ari.mode': mode,
          'rqgm.enabled': enabled,
          'paper.mode': paperMode,
          'rqgm.paper.enabled': paperEnabled,
        }),
      );
      const view = renderPage();
      await waitFor(() =>
        expect(screen.getByRole('button', { name: /⚙️ Execution/ })).toBeInTheDocument(),
      );
      fireEvent.click(screen.getByRole('button', { name: /⚙️ Execution/ }));
      await waitFor(() =>
        expect(screen.getByLabelText('Execution mode')).toBeInTheDocument(),
      );
      // Saved pair round-trips into both selects, and no combination is
      // flagged inconsistent (all four are valid).
      expect((screen.getByLabelText('Execution mode') as HTMLSelectElement).value).toBe(mode);
      expect((screen.getByLabelText('Paper mode') as HTMLSelectElement).value).toBe(paperMode);
      expect(screen.queryByText(/This pair is inconsistent/)).toBeNull();
      expect(screen.getByText('No unsaved edits.')).toBeInTheDocument();
      view.unmount();
    }
  });

  it('re-selecting the stored value clears the pair — the default path writes nothing', async () => {
    await openExecutionSection();

    fireEvent.change(screen.getByLabelText('Execution mode'), {
      target: { value: 'ari_rqgm' },
    });
    expect(screen.getByText('2 unsaved edit(s)')).toBeInTheDocument();
    // Back to the (unwritten) default: no redundant ari:/rqgm: keys are
    // materialized, so a default launch stays byte-identical to today.
    fireEvent.change(screen.getByLabelText('Execution mode'), {
      target: { value: 'simple_bfts' },
    });
    expect(screen.getByText('No unsaved edits.')).toBeInTheDocument();
    expect(
      (screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(patchDraftMock).not.toHaveBeenCalled();
  });

  it('flags an inconsistent stored pair instead of silently accepting it', async () => {
    draftMock.mockResolvedValue(
      makeDraft({ 'ari.mode': 'ari_rqgm', 'rqgm.enabled': false }),
    );
    await openExecutionSection();
    expect(screen.getByText(/This pair is inconsistent/)).toBeInTheDocument();
    expect(screen.getByText(/mode_interlock_mismatch/)).toBeInTheDocument();
  });

  it('renders the rqgm.* tuning tree read-only: values, no editable control', async () => {
    await openExecutionSection();

    const group = screen
      .getByText('RQGM governance parameters (read-only)')
      .closest('details') as HTMLElement;
    // Effective values are visible so the user sees what will apply ...
    expect(within(group).getByText('rqgm.epoch.size')).toBeInTheDocument();
    expect(within(group).getByText('10')).toBeInTheDocument();
    expect(within(group).getByText('rqgm.adversarial.audit_ratio')).toBeInTheDocument();
    expect(within(group).getByText('0.25')).toBeInTheDocument();
    // ... and the two selectable leaves are NOT duplicated here.
    expect(within(group).queryByText('rqgm.enabled')).toBeNull();
    expect(within(group).queryByText('rqgm.paper.enabled')).toBeNull();
    // No editable control of any kind inside the group.
    expect(group.querySelectorAll('input, select, textarea, button').length).toBe(0);
    expect(
      within(group).getByText(/Governance tuning parameters come from configuration files/),
    ).toBeInTheDocument();
  });
});

describe('Launch review shows the RESOLVED mode (ADR-09)', () => {
  it('shows the resolved pair as effective when the backend honored it', async () => {
    draftMock.mockResolvedValue(
      makeDraft({ 'ari.mode': 'ari_rqgm', 'rqgm.enabled': true }),
    );
    resolveMock.mockResolvedValue(
      makeResolved({
        values: {
          ari: { mode: 'ari_rqgm' },
          paper: { mode: 'linear' },
          rqgm: { enabled: true, paper: { enabled: false } },
        },
      }),
    );
    await openLaunchReview();

    const review = screen
      .getByText('Immutable launch summary')
      .closest('.card') as HTMLElement;
    expect(within(review).getByText('ari_rqgm')).toBeInTheDocument();
    expect(within(review).getByText('(rqgm.enabled=true)')).toBeInTheDocument();
    expect(within(review).getByText('linear')).toBeInTheDocument();
    expect(within(review).getAllByText('effective').length).toBe(2);
    expect(screen.queryByText(/Requested mode was not applied/)).toBeNull();
  });

  it('shows the RESOLVED mode (not the raw selection) and the resolver warning on a fallback', async () => {
    // Raw draft selection: ari_rqgm. Backend resolution: the interlock did
    // not agree, so the manifest carries the POST-fallback simple_bfts plus
    // the rejected_override explanation and the resolver warning.
    const WARNING =
      'ari.mode=ari_rqgm but rqgm.enabled=False; falling back to simple_bfts ' +
      '(resolve_effective_mode parity: warn + fallback, never an error)';
    draftMock.mockResolvedValue(makeDraft({ 'ari.mode': 'ari_rqgm' }));
    resolveMock.mockResolvedValue(
      makeResolved({
        provenance: {
          'ari.mode': {
            source: 'draft',
            mutable: true,
            confidence: 'high',
            rejected_override: {
              source: 'draft',
              value: 'ari_rqgm',
              reason: 'interlock_mismatch',
              expected: null,
            },
          },
          'paper.mode': {
            source: 'default',
            mutable: true,
            confidence: 'high',
            rejected_override: null,
          },
        },
        warnings: [WARNING],
      }),
    );
    validateMock.mockResolvedValue(makeValidation({ warnings: [WARNING] }));
    await openLaunchReview();

    // The prominent fallback alert: requested -> resolved + the warning verbatim.
    const alert = screen
      .getByText(/Requested mode was not applied/)
      .closest('.card') as HTMLElement;
    expect(within(alert).getByText('ari_rqgm')).toBeInTheDocument();
    expect(within(alert).getByText('simple_bfts')).toBeInTheDocument();
    expect(within(alert).getByText(WARNING)).toBeInTheDocument();

    // The immutable summary shows the RESOLVED value, flagged as a fallback —
    // never the raw ari_rqgm selection the Studio form still displays.
    const review = screen
      .getByText('Immutable launch summary')
      .closest('.card') as HTMLElement;
    expect(within(review).getByText('simple_bfts')).toBeInTheDocument();
    expect(within(review).queryByText('ari_rqgm')).toBeNull();
    expect(within(review).getByText('fell back')).toBeInTheDocument();
  });

  it('blocks the launch on mode_interlock_mismatch with the typed message shown', async () => {
    validateMock.mockResolvedValue(
      makeValidation({
        valid: false,
        errors: [
          {
            path: 'ari.mode',
            reason: 'mode_interlock_mismatch',
            message:
              "ari.mode and rqgm.enabled are one intent — set both to " +
              "('ari_rqgm', true) or ('simple_bfts', false)",
            expected: [
              ['ari_rqgm', true],
              ['simple_bfts', false],
            ],
          },
        ],
      }),
    );
    await openLaunchReview();

    expect(screen.getByText('invalid')).toBeInTheDocument();
    expect(screen.getByText('mode_interlock_mismatch')).toBeInTheDocument();
    expect(screen.getByText(/are one intent — set both to/)).toBeInTheDocument();
    // Structurally blocked: confirm + launch disabled, POST never sent.
    expect(
      (screen.getByLabelText(/I reviewed this immutable summary/) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    const launchBtn = screen.getByRole('button', { name: 'Launch run' }) as HTMLButtonElement;
    expect(launchBtn.disabled).toBe(true);
    fireEvent.click(launchBtn);
    expect(launchMock).not.toHaveBeenCalled();
  });
});
