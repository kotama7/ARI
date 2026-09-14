import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigStudioPage } from '../ConfigStudioPage';
import {
  ApiErrorV1,
  fetchConfigSchemaV1,
  fetchModelCatalogV1,
  fetchProjectConfigV1,
  fetchRunDraftV1,
  fetchRunTemplatesV1,
  fetchSecretsStatusV1,
  launchRunV1,
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
  type RunLaunchedV1,
  type RunTemplateListV1,
  type SecretStatusV1,
} from '../../../services/api/v1';

/**
 * Studio launch flow (gui_refresh task 06 Wave 4e; backend MN-10
 * POST /api/v1/runs). The launch order is fixed — resolve -> validate ->
 * immutable review -> idempotent create -> canonical redirect — and these
 * cases pin that no step can be skipped and that one approval spawns at most
 * one run.
 *
 * The typed v1 fetchers are mocked at the module boundary (react-query
 * hooks + ApiErrorV1 normalization stay REAL), pinning:
 *   - resolve -> validate -> review -> launch happy path: the effective
 *     config diff vs defaults (non-default provenance rows only), the
 *     immutable review summary (digest, changed count, server-issued
 *     run_id note), explicit confirm gating, and the canonical
 *     '#/overview?run=<run_id>' redirect from the SERVER-issued run_id —
 *     never an mtime/latest-checkpoint guess;
 *   - a validation failure (mode_locked) blocks the launch structurally
 *     (confirm + launch disabled, POST never sent);
 *   - double-click sends ONE POST, and a retry after a failure reuses the
 *     SAME idempotency key (one review approval == one key);
 *   - a launch failure renders the typed error envelope (message +
 *     request_id + per-path details.errors incl. missing_goal).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchConfigSchemaV1: vi.fn(),
    fetchProjectConfigV1: vi.fn(),
    fetchRunTemplatesV1: vi.fn(),
    fetchRunDraftV1: vi.fn(),
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
const secretsMock = vi.mocked(fetchSecretsStatusV1);
const catalogMock = vi.mocked(fetchModelCatalogV1);
const resolveMock = vi.mocked(resolveDraftConfigV1);
const validateMock = vi.mocked(validateRunDraftV1);
const launchMock = vi.mocked(launchRunV1);

const DRAFT_ID = 'draft-abc123def456';
const RUN_ID = '20260726120000_my-run-a1b2c3';

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

function makeSchema(): ConfigSchemaV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-schema',
    resolver_version: 'legacy-compatible-1',
    fields: [
      makeField({ path: 'llm.backend', default: 'openai' }),
      makeField({ path: 'llm.model', default: 'default-model' }),
      makeField({
        path: 'llm.api_key',
        sensitivity: 'secret_reference',
        scope: 'installation',
      }),
      makeField({
        path: 'ari.mode',
        category: 'Execution mode',
        enum: ['simple_bfts', 'ari_rqgm'],
        default: 'simple_bfts',
        mutability: 'new_run_only',
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

function makeDraft(overrides: Partial<RunDraftV1> = {}): RunDraftV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-draft',
    draft_id: DRAFT_ID,
    template_id: null,
    revision: 2,
    values: { 'llm.model': 'draft-model' },
    goal: 'Study adversarial audit chains',
    updated_at: '2026-07-26T00:00:00Z',
    ...overrides,
  };
}

function makeSecrets(): SecretStatusV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-secrets',
    secrets: [
      {
        name: 'OPENAI_API_KEY',
        configured: true,
        source_class: 'repo_env',
        last_updated: null,
      },
      { name: 'ANTHROPIC_API_KEY', configured: false, source_class: null, last_updated: null },
    ],
  };
}

function makeCatalog(): ModelCatalogV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-catalog',
    providers: [
      { id: 'openai', name: 'OpenAI', models: ['gpt-5.4'], env_key: 'OPENAI_API_KEY' },
    ],
  };
}

function makeResolved(): ResolvedNewRunConfigV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-resolve',
    resolver_version: 'legacy-compatible-1',
    run_id: DRAFT_ID,
    digest: 'sha256:d1g3st0000',
    resolved_at: '2026-07-26T00:00:00Z',
    source_stack: ['defaults', 'draft'],
    values: { 'llm.backend': 'openai', 'llm.model': 'draft-model' },
    provenance: {
      'llm.backend': {
        source: 'default',
        mutable: true,
        confidence: 'high',
        rejected_override: null,
      },
      'llm.model': {
        source: 'draft',
        mutable: true,
        confidence: 'high',
        rejected_override: null,
      },
    },
    secret_references: {
      'llm.api_key': { provider: 'env', configured: true },
    },
    warnings: [],
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

function makeLaunched(): RunLaunchedV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-launch',
    accepted: true,
    idempotent_replay: false,
    run_id: RUN_ID,
    status_url: `/api/v1/runs/${RUN_ID}`,
    checkpoint_path: `/tmp/ws/checkpoints/${RUN_ID}`,
  };
}

// ── harness ─────────────────────────────────────────────────────────────

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConfigStudioPage />
    </QueryClientProvider>,
  );
}

async function openReview() {
  renderPage();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Resolve & validate' })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Resolve & validate' }));
  await waitFor(() => expect(resolveMock).toHaveBeenCalledWith(DRAFT_ID, undefined));
  expect(validateMock).toHaveBeenCalledWith(DRAFT_ID, undefined);
  // The calls being issued does not mean React Query has committed their
  // resolved state. Wait for the shared review surface so assertions below
  // are independent of scheduler timing across Vitest/React versions.
  await waitFor(() =>
    expect(screen.getByText('Immutable launch summary')).toBeInTheDocument(),
  );
}

// crypto.randomUUID is stubbed for deterministic key assertions (one key
// per review approval).
let uuidCounter = 0;
const randomUUIDMock = vi.fn(
  (): string => `00000000-0000-4000-8000-${String(++uuidCounter).padStart(12, '0')}`,
);

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/studio?draft=${DRAFT_ID}`;
  vi.clearAllMocks();
  uuidCounter = 0;
  vi.stubGlobal('crypto', { randomUUID: randomUUIDMock } as unknown as Crypto);
  schemaMock.mockResolvedValue(makeSchema());
  projectMock.mockResolvedValue(makeProject());
  templatesMock.mockResolvedValue(makeTemplates());
  draftMock.mockResolvedValue(makeDraft());
  secretsMock.mockResolvedValue(makeSecrets());
  catalogMock.mockResolvedValue(makeCatalog());
  resolveMock.mockResolvedValue(makeResolved());
  validateMock.mockResolvedValue(makeValidation());
  launchMock.mockResolvedValue(makeLaunched());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ConfigStudioPage launch flow (gui_refresh task 06 Wave 4e)', () => {
  it('resolve -> validate -> review -> launch redirects to the canonical overview URL', async () => {
    await openReview();

    // Draft goal is shown (the goal step of the narrowed state machine).
    expect(screen.getByText('Study adversarial audit chains')).toBeInTheDocument();
    // Verdict badge from the validate call.
    expect(screen.getByText('valid')).toBeInTheDocument();

    // Effective-config diff vs defaults: ONLY the non-default provenance
    // row (llm.model), with default vs effective and the source badge.
    // Scoped to the diff card: the Studio form above also renders field
    // paths and mutability badges.
    const diffCard = screen
      .getByText('Changed vs defaults')
      .closest('.card') as HTMLElement;
    expect(within(diffCard).getByText('llm.model')).toBeInTheDocument();
    expect(within(diffCard).getByText('draft-model')).toBeInTheDocument();
    expect(within(diffCard).getByText('default-model')).toBeInTheDocument();
    // Provenance source badge for the changed row.
    expect(within(diffCard).getAllByText('draft').length).toBeGreaterThan(0);
    // llm.backend resolved from defaults -> not a diff row.
    expect(within(diffCard).queryByText('llm.backend')).toBeNull();

    // Secret readiness rows from the existing status hook — flags only
    // (scoped: the form's SecretField shows readiness text too).
    const secretsCard = screen
      .getByText('Secret readiness')
      .closest('.card') as HTMLElement;
    expect(within(secretsCard).getByText('OPENAI_API_KEY')).toBeInTheDocument();
    expect(within(secretsCard).getByText(/configured \(repo_env\)/)).toBeInTheDocument();
    expect(within(secretsCard).getByText('not configured')).toBeInTheDocument();
    // Locked-governance note (ADR-09 pending).
    expect(within(secretsCard).getByText(/mode_locked/)).toBeInTheDocument();

    // Immutable review summary: digest + changed-fields count +
    // server-issued run_id intent (never a client guess).
    expect(screen.getByText('Immutable launch summary')).toBeInTheDocument();
    expect(screen.getByText('sha256:d1g3st0000')).toBeInTheDocument();
    expect(
      screen.getByText('server-issued at accept (never guessed from checkpoints)'),
    ).toBeInTheDocument();

    // Launch stays disabled until the review is explicitly confirmed.
    const launchBtn = screen.getByRole('button', { name: 'Launch run' }) as HTMLButtonElement;
    expect(launchBtn.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/I reviewed this immutable summary/));
    expect(launchBtn.disabled).toBe(false);

    fireEvent.click(launchBtn);
    await waitFor(() =>
      expect(launchMock).toHaveBeenCalledWith({
        draftId: DRAFT_ID,
        displayName: undefined,
        profile: undefined,
        idempotencyKey: '00000000-0000-4000-8000-000000000001',
      }),
    );

    // Canonical redirect from the SERVER-issued run_id, the last step of the
    // launch order — no mtime/latest-checkpoint polling, which would race a
    // concurrent launch onto the wrong run.
    await waitFor(() =>
      expect(window.location.hash).toBe(`#/overview?run=${RUN_ID}`),
    );
  });

  it('blocks the launch when validation fails (mode_locked) — POST never sent', async () => {
    validateMock.mockResolvedValue(
      makeValidation({
        valid: false,
        errors: [
          {
            path: 'ari.mode',
            reason: 'mode_locked',
            message: 'ari.mode is governance-locked pending ADR-09',
            expected: null,
          },
        ],
      }),
    );
    await openReview();

    expect(screen.getByText('invalid')).toBeInTheDocument();
    // Per-path error row via the shared ValidationSummary.
    expect(screen.getByText('mode_locked')).toBeInTheDocument();
    expect(
      screen.getByText('ari.mode is governance-locked pending ADR-09'),
    ).toBeInTheDocument();

    // Confirm + launch are structurally disabled on an invalid draft.
    expect(
      (screen.getByLabelText(/I reviewed this immutable summary/) as HTMLInputElement).disabled,
    ).toBe(true);
    const launchBtn = screen.getByRole('button', { name: 'Launch run' }) as HTMLButtonElement;
    expect(launchBtn.disabled).toBe(true);
    fireEvent.click(launchBtn);
    expect(launchMock).not.toHaveBeenCalled();
  });

  it('double-click sends ONE POST and a retry reuses the same idempotency key', async () => {
    let resolveFirst!: (v: RunLaunchedV1 & RequestIdV1) => void;
    let rejectFirst!: (e: unknown) => void;
    launchMock.mockImplementationOnce(
      () =>
        new Promise((res, rej) => {
          resolveFirst = res;
          rejectFirst = rej;
        }),
    );
    await openReview();

    fireEvent.click(screen.getByLabelText(/I reviewed this immutable summary/));
    const launchBtn = screen.getByRole('button', { name: 'Launch run' });
    // Double-click while the first POST is in flight.
    fireEvent.click(launchBtn);
    fireEvent.click(launchBtn);
    expect(launchMock).toHaveBeenCalledTimes(1);
    expect((launchBtn as HTMLButtonElement).disabled).toBe(true);

    // First attempt fails retryably -> the SAME review approval retries
    // with the SAME key (idempotent replay server-side).
    rejectFirst(
      new ApiErrorV1({
        code: 'internal',
        message: 'spawn failed',
        details: null,
        request_id: 'req-500',
        retryable: true,
      }),
    );
    await waitFor(() => expect(screen.getByText(/Launch failed/)).toBeInTheDocument());

    launchMock.mockResolvedValueOnce(makeLaunched());
    fireEvent.click(screen.getByRole('button', { name: 'Launch run' }));
    await waitFor(() => expect(launchMock).toHaveBeenCalledTimes(2));
    const firstKey = launchMock.mock.calls[0][0].idempotencyKey;
    const secondKey = launchMock.mock.calls[1][0].idempotencyKey;
    expect(firstKey).toBe('00000000-0000-4000-8000-000000000001');
    expect(secondKey).toBe(firstKey);
    expect(randomUUIDMock).toHaveBeenCalledTimes(1);
    void resolveFirst; // first promise settled via rejectFirst above
  });

  it('renders the typed error envelope (request_id + per-path errors) on launch failure', async () => {
    launchMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'invalid_request',
        message: 'draft failed launch validation (1 error(s))',
        details: {
          errors: [
            {
              path: 'goal',
              reason: 'missing_goal',
              message: 'the draft has no goal text',
            },
          ],
        },
        request_id: 'req-launch-400',
        retryable: false,
      }),
    );
    await openReview();

    fireEvent.click(screen.getByLabelText(/I reviewed this immutable summary/));
    fireEvent.click(screen.getByRole('button', { name: 'Launch run' }));

    await waitFor(() =>
      expect(screen.getByText(/draft failed launch validation/)).toBeInTheDocument(),
    );
    // request_id is the support handle: the envelope's per-dispatch id is
    // rendered so a bug report can name one server-side dispatch.
    expect(screen.getByText(/req-launch-400/)).toBeInTheDocument();
    // Per-path envelope rows (missing_goal) via the shared summary.
    expect(screen.getByText('missing_goal')).toBeInTheDocument();
    expect(screen.getByText('the draft has no goal text')).toBeInTheDocument();
    // No redirect happened.
    expect(window.location.hash).toBe(`#/studio?draft=${DRAFT_ID}`);
  });
});
