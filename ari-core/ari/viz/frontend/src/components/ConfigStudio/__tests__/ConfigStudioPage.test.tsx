import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigStudioPage } from '../ConfigStudioPage';
import {
  ApiErrorV1,
  fetchConfigSchemaV1,
  fetchModelCatalogV1,
  fetchProjectConfigV1,
  fetchRunTemplatesV1,
  fetchSecretsStatusV1,
  patchProjectConfigV1,
  putSecretV1,
  type ConfigFieldV1,
  type ConfigSchemaV1,
  type ModelCatalogV1,
  type ProjectConfigV1,
  type RequestIdV1,
  type RunTemplateListV1,
  type SecretStatusV1,
  type SecretUpdatedV1,
} from '../../../services/api/v1';

/**
 * ConfigStudioPage (gui_refresh task 06 Wave 4d — schema-driven
 * Configuration Studio, non-governance slice). Controls are generated from
 * the server's field metadata rather than hand-placed, and writes are never
 * optimistic: the server's answer (a new revision, or a 409) is what the UI
 * adopts.
 *
 * The typed v1 fetchers are mocked at the module boundary (the react-query
 * hooks and ApiErrorV1 normalization stay REAL), pinning:
 *   - form generation from registry metadata (enum -> select, bool ->
 *     switch, number -> number input, str -> text input, composite ->
 *     disabled-with-reason);
 *   - PATCH /projects/default/config carries the loaded revision as
 *     If-Match; a 409 'revision_conflict' raises the reload banner (edits
 *     kept), a 400 'invalid_request' renders the per-path
 *     ValidationSummary;
 *   - the secret field NEVER renders a value: readiness display only, the
 *     write goes through PUT /secrets/{id}, the input is cleared on
 *     success, and readiness flips after the PUT;
 *   - 'Execution mode' + rqgm.* fields form the ADR-09 Execution section:
 *     two mode selects (disabled in PROJECT scope, which the backend refuses
 *     with not_project_scope) plus the read-only rqgm.* tuning tree.
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchConfigSchemaV1: vi.fn(),
    fetchProjectConfigV1: vi.fn(),
    patchProjectConfigV1: vi.fn(),
    fetchRunTemplatesV1: vi.fn(),
    fetchRunTemplateV1: vi.fn(),
    fetchRunDraftV1: vi.fn(),
    createRunTemplateV1: vi.fn(),
    createRunDraftV1: vi.fn(),
    patchRunTemplateV1: vi.fn(),
    patchRunDraftV1: vi.fn(),
    fetchSecretsStatusV1: vi.fn(),
    putSecretV1: vi.fn(),
    fetchModelCatalogV1: vi.fn(),
  };
});

const schemaMock = vi.mocked(fetchConfigSchemaV1);
const projectMock = vi.mocked(fetchProjectConfigV1);
const patchProjectMock = vi.mocked(patchProjectConfigV1);
const templatesMock = vi.mocked(fetchRunTemplatesV1);
const secretsMock = vi.mocked(fetchSecretsStatusV1);
const putSecretMock = vi.mocked(putSecretV1);
const catalogMock = vi.mocked(fetchModelCatalogV1);

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
      makeField({ path: 'llm.temperature', value_type: 'float', default: 1.0 }),
      makeField({
        path: 'bfts.max_total_nodes',
        category: 'Search (BFTS)',
        value_type: 'int',
        default: 25,
        scope: 'run',
      }),
      makeField({
        path: 'bfts.allow_web',
        category: 'Search (BFTS)',
        value_type: 'bool',
        default: false,
        scope: 'run',
      }),
      makeField({
        path: 'evaluator.axis_mode',
        category: 'Evaluation',
        enum: ['fixed', 'custom'],
        default: 'fixed',
        scope: 'run',
      }),
      makeField({
        path: 'skills',
        category: 'Skills',
        value_type: 'list[SkillConfig]',
        default: [],
      }),
      // ADR-09 Execution section: the two selectable mode intents ...
      makeField({
        path: 'ari.mode',
        category: 'Execution mode',
        enum: ['simple_bfts', 'ari_rqgm'],
        default: 'simple_bfts',
        mutability: 'new_run_only',
        scope: 'run',
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
      // ... and one of the ~96 tuning leaves that stay READ-ONLY.
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
    ],
  };
}

function makeProject(
  overrides: Partial<ProjectConfigV1> = {},
): ProjectConfigV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-project',
    revision: 3,
    values: { 'llm.model': 'saved-model' },
    updated_paths_count: 1,
    ...overrides,
  };
}

function makeTemplates(): RunTemplateListV1 & RequestIdV1 {
  return { schema_version: 1, request_id: 'req-templates', templates: [] };
}

function makeSecrets(configured: boolean): SecretStatusV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-secrets',
    secrets: [
      {
        name: 'OPENAI_API_KEY',
        configured,
        source_class: configured ? 'repo_env' : null,
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
      { id: 'openai', name: 'OpenAI', models: ['gpt-5.4', 'gpt-4o'], env_key: 'OPENAI_API_KEY' },
      {
        id: 'anthropic',
        name: 'Anthropic (Claude)',
        models: ['claude-opus-4-6'],
        env_key: 'ANTHROPIC_API_KEY',
      },
    ],
  };
}

function makeSecretUpdated(): SecretUpdatedV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-put',
    secret: {
      name: 'OPENAI_API_KEY',
      configured: true,
      source_class: 'repo_env',
      last_updated: null,
    },
  };
}

// ── harness ─────────────────────────────────────────────────────────────

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <ConfigStudioPage />
    </QueryClientProvider>,
  );
}

async function waitForForm() {
  await waitFor(() => expect(screen.getByLabelText('llm.model')).toBeInTheDocument());
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = '#/studio';
  vi.clearAllMocks();
  schemaMock.mockResolvedValue(makeSchema());
  projectMock.mockResolvedValue(makeProject());
  templatesMock.mockResolvedValue(makeTemplates());
  secretsMock.mockResolvedValue(makeSecrets(false));
  catalogMock.mockResolvedValue(makeCatalog());
});

describe('ConfigStudioPage (gui_refresh task 06 Wave 4d)', () => {
  it('generates controls from registry metadata (text/number/switch/select/composite)', async () => {
    renderPage();
    await waitForForm();

    // str -> text input; the saved project document value wins over the
    // registry default.
    const model = screen.getByLabelText('llm.model') as HTMLInputElement;
    expect(model.type).toBe('text');
    expect(model.value).toBe('saved-model');
    // ... and the unsaved field shows the registry default.
    expect((screen.getByLabelText('llm.backend') as HTMLInputElement).value).toBe('openai');

    // float -> number input (same Models category).
    const temperature = screen.getByLabelText('llm.temperature') as HTMLInputElement;
    expect(temperature.type).toBe('number');
    expect(temperature.value).toBe('1');

    // Category rail navigation: bool -> switch, int -> number input.
    fireEvent.click(screen.getByRole('button', { name: /Search \(BFTS\)/ }));
    const allowWeb = screen.getByLabelText('bfts.allow_web') as HTMLInputElement;
    expect(allowWeb.type).toBe('checkbox');
    expect(allowWeb.checked).toBe(false);
    const maxNodes = screen.getByLabelText('bfts.max_total_nodes') as HTMLInputElement;
    expect(maxNodes.type).toBe('number');
    expect(maxNodes.value).toBe('25');

    // enum -> select with the registry's closed options.
    fireEvent.click(screen.getByRole('button', { name: 'Evaluation' }));
    const axisMode = screen.getByLabelText('evaluator.axis_mode') as HTMLSelectElement;
    expect(axisMode.tagName).toBe('SELECT');
    const options = within(axisMode).getAllByRole('option').map((o) => o.textContent);
    expect(options).toContain('fixed');
    expect(options).toContain('custom');

    // composite -> explicitly disabled with a reason, never silently hidden.
    fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
    expect((screen.getByLabelText('skills') as HTMLInputElement).disabled).toBe(true);
    expect(
      screen.getByText(/Composite field — edit via workflow\.yaml/),
    ).toBeInTheDocument();

    // Mutability badges rendered from the registry (ConfigBrowser reuse).
    expect(screen.getAllByText('draft').length).toBeGreaterThan(0);
  });

  it('saves pending edits via PATCH with the loaded revision as If-Match', async () => {
    patchProjectMock.mockResolvedValue(
      makeProject({ revision: 4, values: { 'llm.model': 'new-model' } }),
    );
    renderPage();
    await waitForForm();

    fireEvent.change(screen.getByLabelText('llm.model'), {
      target: { value: 'new-model' },
    });
    // Left-rail edit count for the Models category.
    expect(
      within(screen.getByRole('button', { name: /Models/ })).getByText('1'),
    ).toBeInTheDocument();
    expect(screen.getByText('1 unsaved edit(s)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(patchProjectMock).toHaveBeenCalledWith({ 'llm.model': 'new-model' }, 3),
    );
    await waitFor(() => expect(screen.getByText('Saved.')).toBeInTheDocument());
    expect(screen.getByText('No unsaved edits.')).toBeInTheDocument();
  });

  it('raises the reload banner on a 409 revision conflict and keeps the edits', async () => {
    patchProjectMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'revision_conflict',
        message: 'stale revision',
        details: { expected: 3, actual: 5 },
        request_id: 'req-409',
        retryable: false,
      }),
    );
    renderPage();
    await waitForForm();

    fireEvent.change(screen.getByLabelText('llm.model'), {
      target: { value: 'conflicting-model' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() =>
      expect(screen.getByText('Revision conflict')).toBeInTheDocument(),
    );
    // Unsaved edits stay local: a conflicted save raises an explicit reload
    // affordance and keeps the edits, rather than quietly winning over the
    // newer document or discarding what the user typed.
    expect(screen.getByText('1 unsaved edit(s)')).toBeInTheDocument();

    const before = projectMock.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(screen.queryByText('Revision conflict')).toBeNull());
    // Reload refetches the document for a fresh revision.
    await waitFor(() => expect(projectMock.mock.calls.length).toBeGreaterThan(before));
  });

  it('renders the per-path ValidationSummary from a 400 invalid_request envelope', async () => {
    patchProjectMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'invalid_request',
        message: 'invalid config patch (1 path(s) rejected)',
        details: {
          errors: [
            {
              path: 'llm.model',
              reason: 'invalid_type',
              message: 'llm.model expects str, got int',
              expected: 'str',
            },
          ],
        },
        request_id: 'req-400',
        retryable: false,
      }),
    );
    renderPage();
    await waitForForm();

    fireEvent.change(screen.getByLabelText('llm.model'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() =>
      expect(screen.getByText('llm.model expects str, got int')).toBeInTheDocument(),
    );
    expect(screen.getByText(/Validation errors/)).toBeInTheDocument();
    expect(screen.getByText('invalid_type')).toBeInTheDocument();
  });

  it('secret field: readiness only, PUT flow, value never rendered, readiness flips', async () => {
    const SECRET = 'sk-proj-STUDIO-TEST-VALUE-001';
    secretsMock.mockResolvedValueOnce(makeSecrets(false));
    secretsMock.mockResolvedValue(makeSecrets(true));
    putSecretMock.mockResolvedValue(makeSecretUpdated());
    renderPage();
    await waitForForm();

    // Catalog env_key of the active provider (openai) preselects the target.
    const picker = screen.getByLabelText('Secret name') as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe('OPENAI_API_KEY'));
    expect(screen.getByText('not configured')).toBeInTheDocument();

    const input = screen.getByLabelText('Enter new secret value') as HTMLInputElement;
    expect(input.type).toBe('password');
    fireEvent.change(input, { target: { value: SECRET } });
    fireEvent.click(screen.getByRole('button', { name: 'Set secret' }));

    await waitFor(() =>
      expect(putSecretMock).toHaveBeenCalledWith('OPENAI_API_KEY', SECRET),
    );
    // Write-only: the input is cleared the moment the PUT resolves and the
    // plaintext exists nowhere in the DOM (display value or text).
    await waitFor(() => expect(input.value).toBe(''));
    expect(screen.queryByDisplayValue(SECRET)).toBeNull();
    expect(screen.queryByText(new RegExp(SECRET))).toBeNull();
    expect(document.body.innerHTML).not.toContain(SECRET);

    // Readiness flips after the PUT (the invalidated status refetch).
    await waitFor(() =>
      expect(screen.getByText(/configured \(repo_env\)/)).toBeInTheDocument(),
    );
    expect(screen.getByText('Secret updated.')).toBeInTheDocument();
  });

  it('collects Execution mode + rqgm.* into the ADR-09 Execution section, refused in PROJECT scope', async () => {
    renderPage();
    await waitForForm();

    // Execution-section fields are NOT ordinary editable categories.
    expect(screen.queryByRole('button', { name: 'Execution mode' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Governance' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /⚙️ Execution/ }));

    // Exactly two mode controls, both new-run only.
    const exec = screen.getByLabelText('Execution mode') as HTMLSelectElement;
    const paper = screen.getByLabelText('Paper mode') as HTMLSelectElement;
    expect(exec.tagName).toBe('SELECT');
    expect(paper.tagName).toBe('SELECT');
    expect(screen.getAllByText(/Applies to this NEW run only/).length).toBeGreaterThan(0);

    // PROJECT scope keeps refusing run-scoped mode paths (not_project_scope):
    // the controls are disabled with the reason instead of pretending.
    expect(exec.disabled).toBe(true);
    expect(paper.disabled).toBe(true);
    expect(screen.getByText(/not_project_scope/)).toBeInTheDocument();

    // The remaining rqgm.* tuning leaf is visible READ-ONLY (a value, no
    // control) — this scope can produce no pending edit at all.
    expect(screen.getByText('rqgm.epoch.size')).toBeInTheDocument();
    expect(screen.queryByLabelText('rqgm.epoch.size')).toBeNull();
    expect(screen.getByText('No unsaved edits.')).toBeInTheDocument();
    expect(
      (screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
