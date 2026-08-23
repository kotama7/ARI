import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GovernancePage } from '../GovernancePage';
import { REGISTRY_STATUS_VALUES } from '../shared';
import {
  fetchRqgmAuditV1,
  fetchRqgmCapabilitiesV1,
  fetchRqgmEpochDetailV1,
  fetchRqgmEpochsV1,
  fetchRqgmEvolutionV1,
  fetchRqgmNodeLineageV1,
  fetchRqgmOverviewV1,
  fetchRqgmPaperArchiveV1,
  fetchRqgmPoliciesV1,
  fetchRqgmRegistryV1,
  fetchRqgmScoreRewritesV1,
  fetchRunTreeV1,
  type RequestIdV1,
  type RqgmAuditPageV1,
  type RqgmCapabilitiesV1,
  type RqgmEpochDetailV1,
  type RqgmEpochsV1,
  type RqgmEvolutionV1,
  type RqgmNodeLineageV1,
  type RqgmOverviewV1,
  type RqgmPaperArchiveV1,
  type RqgmPoliciesV1,
  type RqgmRegistryV1,
  type RqgmScoreRewritesPageV1,
  type TreeV1,
} from '../../../services/api/v1';

/**
 * GovernancePage (gui_refresh task 08 Wave 4a — read-only RQGM governance
 * workspace). The workspace is observation only — there is no mutation
 * endpoint on this surface — and the presentation rules it must not blur are
 * in docs/reference/rqgm_gui_read_models.md, "Presentation truth rules the
 * API enforces".
 *
 * The typed v1 fetchers are mocked at the module boundary (react-query
 * hooks and page logic stay REAL). Pins:
 *   - the capability STATE screen for a simple_bfts run (explanation, not
 *     an error);
 *   - each of the nine tabs rendering from mocked DTOs behind proper
 *     tablist/tab/tabpanel roles (Wave 4b adds Epoch Timeline, Evolution
 *     and Paper Archive);
 *   - raw-vs-validated separation: a raw attack row can never show a
 *     penalty number — a raw claim is not a validated penalty, and only an
 *     adjudicated record may drive one;
 *   - the exhaustive 10-status registry lifecycle vocabulary render (each
 *     status its own badge class — never node-score classes);
 *   - channel-2 lineage FACETING by policy hash (two hashes ⇒ two facet
 *     containers, never one continuous series);
 *   - audit cursor pagination appending without duplicates;
 *   - the structurally-inert impeachment-chain note (zero attacks +
 *     exploration-only adversary roles ⇒ capability state, not health);
 *   - epoch FACETING (one facet per epoch, each naming its own policy
 *     hash; no cross-epoch comparison UI — an explicit refusal note);
 *   - an open epoch's absent boundary counts rendered as absence, and a
 *     source-less `fallbacks` rendered as unknown — never zero;
 *   - evolution raw-vs-adopted separation (adopted via registry replay
 *     gets the success badge; a raw candidate is labeled, a meta output is
 *     inert provenance);
 *   - paper-mode independence (execution + paper chips side by side) and
 *     absent-artifact flags (draft_count null => not present, never 0;
 *     anchor disabled => the reviewed best-of-N / no-writer-sanction note).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchRqgmCapabilitiesV1: vi.fn(),
    fetchRqgmOverviewV1: vi.fn(),
    fetchRqgmRegistryV1: vi.fn(),
    fetchRqgmAuditV1: vi.fn(),
    fetchRqgmNodeLineageV1: vi.fn(),
    fetchRqgmScoreRewritesV1: vi.fn(),
    fetchRqgmPoliciesV1: vi.fn(),
    fetchRqgmEpochsV1: vi.fn(),
    fetchRqgmEpochDetailV1: vi.fn(),
    fetchRqgmEvolutionV1: vi.fn(),
    fetchRqgmPaperArchiveV1: vi.fn(),
    fetchRunTreeV1: vi.fn(),
  };
});

const capsMock = vi.mocked(fetchRqgmCapabilitiesV1);
const overviewMock = vi.mocked(fetchRqgmOverviewV1);
const registryMock = vi.mocked(fetchRqgmRegistryV1);
const auditMock = vi.mocked(fetchRqgmAuditV1);
const lineageMock = vi.mocked(fetchRqgmNodeLineageV1);
const rewritesMock = vi.mocked(fetchRqgmScoreRewritesV1);
const policiesMock = vi.mocked(fetchRqgmPoliciesV1);
const epochsMock = vi.mocked(fetchRqgmEpochsV1);
const epochDetailMock = vi.mocked(fetchRqgmEpochDetailV1);
const evolutionMock = vi.mocked(fetchRqgmEvolutionV1);
const paperMock = vi.mocked(fetchRqgmPaperArchiveV1);
const treeMock = vi.mocked(fetchRunTreeV1);

const RUN = 'run-g';
const POLICY_A = 'aaaaaaaaaaaa';
const POLICY_B = 'cccccccccccc';

// ── payload builders (shapes from v1types.gen.ts) ───────────────────────

function makeCaps(
  overrides: Partial<RqgmCapabilitiesV1> = {},
): RqgmCapabilitiesV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-caps',
    run_id: RUN,
    enabled: true,
    mode: 'ari_rqgm',
    mode_source: 'launch_config',
    paper_mode: false,
    reasons: [],
    ...overrides,
  };
}

function makeOverview(): RqgmOverviewV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-ov',
    run_id: RUN,
    current_epoch: 'epoch_2',
    utility_policy_hash: POLICY_A,
    constitution_hash: 'bbbbbbbbbbbb',
    registry_summary: {
      component_count: 1,
      prompt_count: 10,
      components_by_status: { active: 1 },
      prompts_by_status: { active: 1, retired: 1 },
    },
    last_committed_transition_at: '2026-07-20T00:00:00+00:00',
    integrity: {
      transitions_chain_ok: true,
      registry_verified: true,
      audit_chain_ok: true,
    },
    degraded_reasons: [],
  };
}

/** One prompt per lifecycle status — the exhaustive-vocabulary fixture. */
function makeRegistry(): RqgmRegistryV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-reg',
    run_id: RUN,
    verified: true,
    rollup_as_of_event_hash: 'tail12345678',
    replay_tail_event_hash: 'tail12345678',
    components: [
      {
        component_id: 'cmp_adv_1',
        role: 'exploit_hunter', // exploration role — no paper_* in this run
        tier: 'institutional',
        status: 'active',
        prompt_id: null,
        epoch_id_registered: 'epoch_1',
        capabilities: {},
        source_event_ids: ['ev_cmp_1'],
      },
    ],
    prompts: REGISTRY_STATUS_VALUES.map((status, i) => ({
      prompt_id: `prm_${status}`,
      role: 'reviewer',
      status,
      prompt_hash: `hash${i}0000000`,
      prompt_sha256: '',
      source: {},
      spec_ref: null,
      epoch_id_registered: 'epoch_1',
      source_event_ids: [`ev_prm_${i}`],
    })),
    active_components: { exploit_hunter: 'cmp_adv_1' },
    active_prompt_hashes: {},
    degraded_reasons: [],
  };
}

function makeLineage(
  nodeId: string,
  overrides: Partial<RqgmNodeLineageV1> = {},
): RqgmNodeLineageV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-lin',
    run_id: RUN,
    node_id: nodeId,
    penalty_channel: [
      {
        source: 'utility_record',
        record_id: 'utl_1',
        epoch_id: 'epoch_2',
        policy_hash: POLICY_A,
        values: { base_score: 0.8, penalty: 0.3, final_score: 0.5 },
        state: 'computed',
        validated_attack_ids: ['vat_1'],
      },
    ],
    policy_channel: [
      {
        source: 'node_metrics',
        record_id: null,
        epoch_id: null,
        policy_hash: POLICY_A,
        values: { _scientific_score: 0.5 },
        state: 'computed',
        validated_attack_ids: [],
      },
      {
        source: 'erasure_event',
        record_id: 'erase_1',
        epoch_id: 'epoch_3',
        policy_hash: POLICY_B,
        values: { invalidated: true },
        state: 'invalidated',
        validated_attack_ids: [],
      },
    ],
    raw_attacks: [
      {
        kind: 'raw',
        record_id: 'atk_1',
        adversary_type: 'exploit_hunter',
        severity_claimed: 'high',
        status: 'judged',
        epoch_id: 'epoch_2',
        target_node_id: nodeId,
      },
    ],
    validated_attacks: [
      {
        kind: 'validated',
        record_id: 'vat_1',
        raw_attack_id: 'atk_1',
        judgment_id: 'jdg_1',
        verdict: 'upheld',
        severity: 'medium',
        affected_components: ['cmp_adv_1'],
        target_component_id: 'cmp_adv_1',
        epoch_id: 'epoch_2',
      },
    ],
    degraded_reasons: [],
    ...overrides,
  };
}

function makeEmptyPage<T extends object>(base: T): T & RequestIdV1 {
  return { ...base, request_id: 'req-x' };
}

function makeRewrites(): RqgmScoreRewritesPageV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    entries: [],
    next_cursor: null,
    total_entries: 0,
    degraded_reasons: [],
  });
}

function makePolicies(): RqgmPoliciesV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    current_policy_hash: POLICY_A,
    policies: [],
    degraded_reasons: [],
  });
}

function makeTree(): TreeV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    revision: 1,
    nodes: [{ id: 'node-1' }, { id: 'node-2' }],
  });
}

/** Two committed-replay epochs under DIFFERENT policy hashes; epoch_3 is
 * still open (no boundary => transition_counts null, not zeros). */
function makeEpochs(): RqgmEpochsV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    current_epoch: 'epoch_3',
    epochs: [
      {
        epoch_id: 'epoch_2',
        opened_at_event: 'ev_open_2',
        opened_by_transition_id: 'txn_1',
        utility_policy_hash: POLICY_A,
        boundary_committed: true,
        closed_by_transition_id: 'txn_2',
        transition_counts: {
          adoptions: 2,
          sanctions: 1,
          retirements: 1,
          bans: 0,
          // No epoch_transition audit source in this fixture — unknown.
          fallbacks: null,
        },
      },
      {
        epoch_id: 'epoch_3',
        opened_at_event: 'ev_open_3',
        opened_by_transition_id: 'txn_2',
        utility_policy_hash: POLICY_B,
        boundary_committed: false,
        closed_by_transition_id: null,
        transition_counts: null,
      },
    ],
    degraded_reasons: [],
  });
}

function makeEpochDetail(epochId: string): RqgmEpochDetailV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    epoch: {
      epoch_id: epochId,
      opened_at_event: 'ev_open_2',
      opened_by_transition_id: 'txn_1',
      utility_policy_hash: POLICY_A,
      boundary_committed: true,
      closed_by_transition_id: 'txn_2',
      transition_counts: {
        adoptions: 2,
        sanctions: 1,
        retirements: 1,
        bans: 0,
        fallbacks: null,
      },
    },
    epoch_seq: 2,
    status: 'closed',
    node_count_at_open: 7,
    previous_epoch_id: 'epoch_1',
    registry_version: 'rv_7',
    epoch_fingerprint: 'fp_2222222222',
    active_components: {},
    active_prompt_hashes: {},
    opening_transaction: {
      kind: 'transaction' as const,
      transition_id: 'txn_1',
      byte_offset: 512,
      first_event_id: 'ev_a',
      last_event_id: 'ev_b',
      event_count: 4,
      committed_at: '2026-07-19T00:00:00+00:00',
    },
    closing_transaction: {
      kind: 'transaction' as const,
      transition_id: 'txn_2',
      byte_offset: 4096,
      first_event_id: 'ev_c',
      last_event_id: 'ev_d',
      event_count: 6,
      committed_at: '2026-07-20T00:00:00+00:00',
    },
    policy_prompt_id: 'prm_policy_a',
    policy_body: {
      composite: 'weighted_sum',
      axis_weights: { novelty: 0.5, rigor: 0.5 },
      frontier_score: 'max',
      depth_penalty_lambda: 0.1,
      ucb_c: 1.2,
    },
    governance_report_present: true,
    governance_report_record_id: 'rep_epoch_2',
    degraded_reasons: [],
  });
}

/** One entry per kind: an ADOPTED prompt candidate, a NOT-adopted utility
 * policy candidate, and an inert meta output (adopted null). */
function makeEvolution(): RqgmEvolutionV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    evolution_present: true,
    meta_outputs_present: true,
    entries: [
      {
        kind: 'prompt' as const,
        record_id: 'evo_1',
        candidate_id: 'cand_1',
        parent_ref: 'prm_parent',
        proposed_prompt_hash: 'hashP1111111',
        proposed_policy_hash: null,
        epoch_id: 'epoch_2',
        role: 'reviewer',
        mutation_kind: 'rewrite',
        status: 'candidate',
        validation_record_count: 2,
        validation_passed_count: 2,
        adopted: true,
        adopted_via: 'txn_2',
        adopted_prompt_id: 'prm_new',
        output_kind: null,
        target_role: null,
        source: 'prompt_evolution' as const,
        source_offset: 0,
      },
      {
        kind: 'utility_policy' as const,
        record_id: 'evo_2',
        candidate_id: 'cand_2',
        parent_ref: null,
        proposed_prompt_hash: null,
        proposed_policy_hash: 'hashU2222222',
        epoch_id: 'epoch_2',
        role: 'utility_policy',
        mutation_kind: 'reweight',
        status: 'candidate',
        validation_record_count: 1,
        validation_passed_count: 0,
        adopted: false,
        adopted_via: null,
        adopted_prompt_id: null,
        output_kind: null,
        target_role: null,
        source: 'prompt_evolution' as const,
        source_offset: 210,
      },
      {
        kind: 'meta' as const,
        record_id: 'meta_1',
        candidate_id: null,
        parent_ref: null,
        proposed_prompt_hash: null,
        proposed_policy_hash: null,
        epoch_id: 'epoch_2',
        role: null,
        mutation_kind: null,
        status: null,
        validation_record_count: 0,
        validation_passed_count: 0,
        adopted: null,
        adopted_via: null,
        adopted_prompt_id: null,
        output_kind: 'observation',
        target_role: 'reviewer',
        source: 'meta_outputs' as const,
        source_offset: 0,
      },
    ],
    degraded_reasons: [],
  });
}

/** Absence-heavy fixture: no paper_archive_state.json, no draft archive,
 * no frozen paper utility policy (anchor unknown), no stat, no winner. */
function makePaperArchive(
  overrides: Partial<RqgmPaperArchiveV1> = {},
): RqgmPaperArchiveV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    state_present: false,
    paper_mode: null,
    mode_source: null,
    rqgm_paper_enabled: null,
    paper_epoch_fingerprint: null,
    archive_present: false,
    epochs: [],
    draft_count: null,
    anchor: { enabled: null, corpus_present: false },
    self_preference: {
      stat_present: false,
      epoch_id: null,
      margin: null,
      ai_mean: null,
      human_mean: null,
      sample_count: null,
    },
    winner: { node_id: null, materialized: false },
    degraded_reasons: [],
    ...overrides,
  });
}

function auditEntry(offset: number, id: string) {
  return {
    byte_offset: offset,
    event_id: id,
    event_type: 'audit_record',
    record_id: `rec_${id}`,
    record_type: 'governance_report',
    epoch_id: 'epoch_1',
    event_hash: `h_${id}`,
    ts_iso: '2026-07-20T00:00:00+00:00',
    summary: { stage: 'final' },
    payload: null,
  };
}

function makeAuditPage(
  entries: ReturnType<typeof auditEntry>[],
  nextCursor: number | null,
  total: number,
): RqgmAuditPageV1 & RequestIdV1 {
  return makeEmptyPage({
    schema_version: 1 as const,
    run_id: RUN,
    entries,
    next_cursor: nextCursor,
    total_entries: total,
    chain_ok: true,
    source_revision: 1000,
    degraded_reasons: [],
  });
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
      <GovernancePage />
    </QueryClientProvider>,
  );
}

/** Standard enabled-run mock set; individual tests override as needed. */
function mockEnabledRun() {
  capsMock.mockResolvedValue(makeCaps());
  overviewMock.mockResolvedValue(makeOverview());
  registryMock.mockResolvedValue(makeRegistry());
  rewritesMock.mockResolvedValue(makeRewrites());
  policiesMock.mockResolvedValue(makePolicies());
  treeMock.mockResolvedValue(makeTree());
  lineageMock.mockImplementation(async (_run, nodeId) => makeLineage(nodeId));
  auditMock.mockResolvedValue(makeAuditPage([auditEntry(0, 'aud_1')], null, 1));
  epochsMock.mockResolvedValue(makeEpochs());
  epochDetailMock.mockImplementation(async (_run, epochId) => makeEpochDetail(epochId));
  evolutionMock.mockResolvedValue(makeEvolution());
  paperMock.mockResolvedValue(makePaperArchive());
}

async function openTab(name: string) {
  fireEvent.click(screen.getByRole('tab', { name }));
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/governance?run=${RUN}`;
  for (const m of [
    capsMock,
    overviewMock,
    registryMock,
    auditMock,
    lineageMock,
    rewritesMock,
    policiesMock,
    epochsMock,
    epochDetailMock,
    evolutionMock,
    paperMock,
    treeMock,
  ]) {
    m.mockReset();
  }
});

describe('GovernancePage (gui_refresh Wave 4a read-only RQGM workspace)', () => {
  it('renders the capability state screen (not an error) for a simple_bfts run', async () => {
    capsMock.mockResolvedValue(
      makeCaps({ enabled: false, mode: null, mode_source: null, reasons: ['simple_bfts run'] }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText('Governance is not active for this run'),
      ).toBeInTheDocument(),
    );
    // Explanation + activation path: an unavailable surface explains itself
    // and names how to turn it on, instead of hiding or showing an error.
    expect(
      screen.getByText(/simple_bfts execution mode/),
    ).toBeInTheDocument();
    expect(screen.getByText(/ari\.mode: ari_rqgm/)).toBeInTheDocument();
    expect(screen.getByText('This is a capability state, not an error.')).toBeInTheDocument();
    expect(screen.getByText(/simple_bfts run/)).toBeInTheDocument();
    // NOT an error affordance: no ErrorState, and no governance fetch beyond
    // capabilities was attempted.
    expect(document.querySelector('.error-state')).toBeNull();
    expect(overviewMock).not.toHaveBeenCalled();
    // Both independent axes stay visible (execution mode ≠ paper mode).
    expect(screen.getByText(/Execution mode/)).toBeInTheDocument();
    expect(screen.getByText(/Paper mode/)).toBeInTheDocument();
  });

  it('renders the Overview tab from the mocked DTO with a11y tab roles', async () => {
    mockEnabledRun();
    renderPage();

    await waitFor(() => expect(screen.getByText('epoch_2')).toBeInTheDocument());
    // a11y composite: tablist with 9 tabs; overview selected.
    const tablist = screen.getByRole('tablist');
    const tabs = within(tablist).getAllByRole('tab');
    expect(tabs).toHaveLength(9);
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Overview',
      'Epoch Timeline',
      'Registry',
      'Accountability',
      'Score Lineage',
      'Evolution',
      'Paper Archive',
      'Knowledge · Capability · Assurance',
      'Audit',
    ]);
    const selected = tabs.filter((tab) => tab.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent('Overview');
    const panel = screen.getByRole('tabpanel');
    expect(panel.getAttribute('aria-labelledby')).toBe('gov-tab-overview');
    // Overview DTO facts: policy hash, constitution hash, integrity badges.
    expect(screen.getAllByText(POLICY_A).length).toBeGreaterThan(0);
    expect(screen.getByText('bbbbbbbbbbbb')).toBeInTheDocument();
    expect(screen.getAllByText('verified')).toHaveLength(3);
  });

  it('shows DegradedState with reasons when a chain is broken — worded as governance, not research failure', async () => {
    mockEnabledRun();
    const broken = makeOverview();
    broken.integrity = {
      transitions_chain_ok: false,
      registry_verified: null,
      audit_chain_ok: true,
    };
    broken.degraded_reasons = ['rqgm_transitions.jsonl: hash chain broken at ev_9 (byte 512)'];
    overviewMock.mockResolvedValue(broken);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Governance record degraded')).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/does not mean the research run failed/),
    ).toBeInTheDocument();
    expect(
      screen.getByText('rqgm_transitions.jsonl: hash chain broken at ev_9 (byte 512)'),
    ).toBeInTheDocument();
    // Tri-state, not binary: broken and missing render as distinct badges.
    expect(screen.getByText('broken')).toBeInTheDocument();
    expect(screen.getByText('source missing')).toBeInTheDocument();
  });

  it('Registry tab renders the exhaustive 10-status lifecycle vocabulary with per-status badges', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Registry');

    await waitFor(() => expect(screen.getByText('prm_candidate')).toBeInTheDocument());
    expect(screen.getByText('snapshot verified')).toBeInTheDocument();
    for (const status of REGISTRY_STATUS_VALUES) {
      const badges = screen.getAllByTestId(`reg-status-${status}`);
      expect(badges.length).toBeGreaterThan(0);
      for (const badge of badges) {
        // Registry lifecycle badges use the reg-badge family and NEVER a
        // node-score class: registry standing and node score state are two
        // different state machines and share no field or legend.
        expect(badge.className).toContain(`reg-badge--${status}`);
        expect(badge.className).not.toContain('nodestate-badge');
      }
    }
    // Active-set marker on active/probationary_active rows only: the
    // component + the two active-family prompts.
    expect(screen.getAllByText('active set').length).toBeGreaterThanOrEqual(3);
  });

  it('Accountability tab separates raw from validated — a raw attack row never shows a penalty number', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Accountability');

    const select = await screen.findByLabelText('Node');
    fireEvent.change(select, { target: { value: 'node-1' } });

    const rawSection = await screen.findByTestId('raw-attacks');
    const validatedSection = await screen.findByTestId('validated-attacks');
    // Raw side: the claim renders with its explicit no-penalty cell...
    expect(within(rawSection).getByText('atk_1')).toBeInTheDocument();
    expect(within(rawSection).getByText('raw claim')).toBeInTheDocument();
    expect(within(rawSection).getByText('high')).toBeInTheDocument();
    expect(within(rawSection).getByText('no penalty (unadjudicated)')).toBeInTheDocument();
    // ...and NEVER a penalty number (0.3 is the validated penalty of the
    // lineage fixture — it must not leak into the raw table).
    expect(within(rawSection).queryByText('0.3')).toBeNull();
    expect(within(rawSection).queryByText(/penalty:\s*\d/)).toBeNull();
    // Validated side: the adjudicated chain refs (atk_ → jdg_ → vat_) and
    // impeachment-facing fields.
    expect(within(validatedSection).getByText('vat_1')).toBeInTheDocument();
    expect(within(validatedSection).getByText('atk_1')).toBeInTheDocument();
    expect(within(validatedSection).getByText('jdg_1')).toBeInTheDocument();
    expect(within(validatedSection).getByText('upheld')).toBeInTheDocument();
    expect(within(validatedSection).getAllByText('cmp_adv_1').length).toBeGreaterThan(0);
  });

  it('Accountability tab shows the structurally-inert chain note on zero attacks + exploration roles', async () => {
    mockEnabledRun();
    lineageMock.mockImplementation(async (_run, nodeId) =>
      makeLineage(nodeId, {
        raw_attacks: [],
        validated_attacks: [],
        penalty_channel: [],
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Accountability');

    const select = await screen.findByLabelText('Node');
    fireEvent.change(select, { target: { value: 'node-2' } });

    await waitFor(() =>
      expect(
        screen.getByText('Impeachment chain structurally inert'),
      ).toBeInTheDocument(),
    );
    // Honest framing: zero recorded attacks is a data point, never evidence
    // of health, and here nothing could have been filed at all — the note
    // explains WHY the chain cannot fire (design), and the zero-count hint
    // also refuses to equate zero with health.
    expect(screen.getByText(/cannot fire by design/)).toBeInTheDocument();
    expect(screen.getAllByText(/not evidence of health/).length).toBeGreaterThan(0);
  });

  it('Score Lineage renders two-channel data and never joins policy hashes into one facet', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Score Lineage');

    const select = await screen.findByLabelText('Node');
    fireEvent.change(select, { target: { value: 'node-1' } });

    // Channel 1: base → validated penalty → final waterfall values.
    const penalty = await screen.findByTestId('penalty-channel');
    expect(within(penalty).getByText('0.8')).toBeInTheDocument();
    expect(within(penalty).getByText('0.3')).toBeInTheDocument();
    expect(within(penalty).getByText('0.5')).toBeInTheDocument();
    expect(within(penalty).getByText('vat_1')).toBeInTheDocument();

    // Channel 2: TWO facet containers — one per policy hash — and each hash
    // confined to its own facet: a utility policy defines what a score
    // MEANS, so observations under different hashes are measurements on
    // different instruments and are never one continuous series.
    const facets = screen.getAllByTestId(/^policy-facet-/);
    expect(facets).toHaveLength(2);
    const facetA = screen.getByTestId(`policy-facet-${POLICY_A}`);
    const facetB = screen.getByTestId(`policy-facet-${POLICY_B}`);
    expect(within(facetA).queryByText(POLICY_B)).toBeNull();
    expect(within(facetB).queryByText(POLICY_A)).toBeNull();
    // Invalidation marker rides on the second facet.
    expect(within(facetB).getByTestId('node-state-invalidated')).toBeInTheDocument();
    // The comparability warning is always visible.
    expect(
      screen.getByText(/never one continuous series/),
    ).toBeInTheDocument();
  });

  it('Audit tab paginates with load-more, appending without duplicates', async () => {
    mockEnabledRun();
    auditMock.mockImplementation(async (_run, query = {}) => {
      if ((query.cursor ?? 0) >= 200) {
        return makeAuditPage([auditEntry(200, 'aud_3')], null, 3);
      }
      return makeAuditPage([auditEntry(0, 'aud_1'), auditEntry(100, 'aud_2')], 200, 3);
    });
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Audit');

    await screen.findByText('aud_1');
    expect(screen.getByText('aud_2')).toBeInTheDocument();
    expect(screen.getByText('rqgm_audit.jsonl@0')).toBeInTheDocument();
    expect(screen.getByText('rqgm_audit.jsonl@100')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('aud_3');
    expect(auditMock).toHaveBeenCalledWith(
      RUN,
      expect.objectContaining({ cursor: 200 }),
    );
    // Appended, no duplicates: each event id renders exactly once.
    for (const id of ['aud_1', 'aud_2', 'aud_3']) {
      expect(screen.getAllByText(id)).toHaveLength(1);
    }
    // The end-of-log notice replaces the button once next_cursor is null.
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
    expect(screen.getByText('End of committed log.')).toBeInTheDocument();
    expect(screen.getByText('3 / 3 events')).toBeInTheDocument();
  });

  it('Epoch Timeline facets per epoch, refuses cross-epoch comparison, and never renders absence as zero', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Epoch Timeline');

    // One facet per epoch (Score Lineage faceting pattern) — each epoch
    // confined to its own container with its OWN policy hash.
    const facet2 = await screen.findByTestId('epoch-facet-epoch_2');
    const facet3 = screen.getByTestId('epoch-facet-epoch_3');
    expect(within(facet2).getByText(POLICY_A)).toBeInTheDocument();
    expect(within(facet2).queryByText(POLICY_B)).toBeNull();
    expect(within(facet3).getByText(POLICY_B)).toBeInTheDocument();
    expect(within(facet3).queryByText(POLICY_A)).toBeNull();
    // Explicit refusal of naive cross-epoch comparison instead of a
    // comparison widget: epochs with different utility policy hashes are not
    // directly comparable, so each renders as its own facet.
    expect(screen.getByText(/not directly comparable/)).toBeInTheDocument();

    // Committed boundary: real status-change counts, with the source-less
    // fallbacks field as unknown — not 0.
    expect(within(facet2).getByText('boundary committed')).toBeInTheDocument();
    expect(within(facet2).getByText(/adoptions: 2/)).toBeInTheDocument();
    expect(
      within(facet2).getByText('fallbacks: unknown (no audit source)'),
    ).toBeInTheDocument();
    // Open epoch: absence, never a row of zeros.
    expect(
      within(facet3).getByText('boundary not committed (epoch open)'),
    ).toBeInTheDocument();
    expect(
      within(facet3).getByText(/transition counts do not exist/),
    ).toBeInTheDocument();
    expect(within(facet3).queryByText(/adoptions: 0/)).toBeNull();
    expect(within(facet3).getByText('current epoch')).toBeInTheDocument();
  });

  it('Epoch Timeline detail loads the 5-key policy body, boundary transactions and report presence', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Epoch Timeline');

    const facet2 = await screen.findByTestId('epoch-facet-epoch_2');
    fireEvent.click(within(facet2).getByRole('button', { name: 'Inspect' }));

    const detail = await screen.findByTestId('epoch-detail-epoch_2');
    expect(epochDetailMock).toHaveBeenCalledWith(RUN, 'epoch_2');
    // The write-once policy body: all 5 governed keys in canonical order.
    const bodyTable = within(detail).getByTestId('epoch-policy-body');
    for (const key of [
      'composite',
      'axis_weights',
      'frontier_score',
      'depth_penalty_lambda',
      'ucb_c',
    ]) {
      expect(within(bodyTable).getByText(key)).toBeInTheDocument();
    }
    expect(within(bodyTable).getByText('weighted_sum')).toBeInTheDocument();
    // Boundary transaction summary with raw-source offsets.
    expect(within(detail).getByText('txn_1')).toBeInTheDocument();
    expect(within(detail).getByText('rqgm_transitions.jsonl@512')).toBeInTheDocument();
    expect(within(detail).getByText('rqgm_transitions.jsonl@4096')).toBeInTheDocument();
    // Governance report presence (with its record id).
    expect(within(detail).getByText('governance report present')).toBeInTheDocument();
    expect(within(detail).getByText('rep_epoch_2')).toBeInTheDocument();
  });

  it('Evolution tab separates raw candidates from adopted policies and keeps meta outputs inert', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Evolution');

    const promptGroup = await screen.findByTestId('evo-group-prompt');
    const policyGroup = screen.getByTestId('evo-group-utility_policy');
    const metaGroup = screen.getByTestId('evo-group-meta');

    // Adopted row: success badge + the citing transition (registry replay
    // join), confined to the prompt group.
    expect(within(promptGroup).getByText('adopted')).toBeInTheDocument();
    expect(within(promptGroup).getByText(/txn_2/)).toBeInTheDocument();
    // Raw candidate: explicitly labeled, never conflated with adoption.
    expect(
      within(policyGroup).getByText('candidate (not adopted)'),
    ).toBeInTheDocument();
    expect(within(policyGroup).queryByText('adopted')).toBeNull();
    // Meta output: inert provenance, not a failed candidate.
    expect(
      within(metaGroup).getByText('inert provenance (not adoptable)'),
    ).toBeInTheDocument();
    expect(within(metaGroup).queryByText('candidate (not adopted)')).toBeNull();
    // Parent link and per-source raw offsets.
    expect(within(promptGroup).getByText('prm_parent')).toBeInTheDocument();
    expect(within(promptGroup).getByText('prompt_evolution.jsonl@0')).toBeInTheDocument();
    expect(within(policyGroup).getByText('prompt_evolution.jsonl@210')).toBeInTheDocument();
    expect(within(metaGroup).getByText('rqgm_meta_outputs.jsonl@0')).toBeInTheDocument();
  });

  it('Paper Archive shows both independent mode chips and renders absence as absence (never zero)', async () => {
    mockEnabledRun();
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Paper Archive');

    // Execution mode and paper mode are INDEPENDENT axes — all four
    // combinations are valid — so both chips render side by side and the
    // bare word "mode" is never used alone: the run executes under ari_rqgm
    // while its paper mode is linear.
    const strip = await screen.findByTestId('paper-mode-strip');
    expect(within(strip).getByText('Execution mode:')).toBeInTheDocument();
    expect(within(strip).getByText('ari_rqgm')).toBeInTheDocument();
    expect(within(strip).getByText('Paper mode:')).toBeInTheDocument();
    expect(within(strip).getByText('linear')).toBeInTheDocument();
    expect(within(strip).getByText(/independent axes/)).toBeInTheDocument();
    // state_present=false: linear is a transparent derivation from absence.
    expect(within(strip).getByText(/derived from that absence/)).toBeInTheDocument();

    // Absent artifacts render as absence — never as zero/healthy defaults.
    const archiveCard = screen.getByTestId('paper-archive-card');
    expect(
      within(archiveCard).getByText(/paper_draft_archive\.jsonl not present/),
    ).toBeInTheDocument();
    expect(within(archiveCard).queryByText('0')).toBeNull();
    const anchorCard = screen.getByTestId('paper-anchor-card');
    expect(
      within(anchorCard).getByText('anchor state unknown (no frozen paper utility policy)'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('paper-selfpref-card')).getByText(
        /paper_self_preference_stat\.json not present/,
      ),
    ).toBeInTheDocument();
    // Reviewed selection != governance winner != research result.
    expect(
      within(screen.getByTestId('paper-winner-card')).getByText(
        /never to be equated with the governance winner/,
      ),
    ).toBeInTheDocument();
  });

  it('Paper Archive renders the anchor-disabled note and a recorded rqgm_archive mode with a null draft_count as not-present', async () => {
    mockEnabledRun();
    paperMock.mockResolvedValue(
      makePaperArchive({
        state_present: true,
        paper_mode: 'rqgm_archive',
        mode_source: 'launch_config',
        rqgm_paper_enabled: true,
        archive_present: true,
        epochs: ['paper_epoch_1'],
        draft_count: null,
        anchor: { enabled: false, corpus_present: true },
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole('tablist')).toBeInTheDocument());
    await openTab('Paper Archive');

    const strip = await screen.findByTestId('paper-mode-strip');
    expect(within(strip).getByText('rqgm_archive')).toBeInTheDocument();
    // Recorded state: no derived-from-absence warning.
    expect(within(strip).queryByText(/derived from that absence/)).toBeNull();
    // anchor.enabled=false => the consequence is carried verbatim: the
    // archive is reviewed best-of-N and writer sanctions cannot fire.
    const anchorCard = screen.getByTestId('paper-anchor-card');
    expect(within(anchorCard).getByText('anchor disabled')).toBeInTheDocument();
    expect(
      within(anchorCard).getByText(
        'Anchor disabled: the archive is reviewed best-of-N and writer sanctions cannot fire.',
      ),
    ).toBeInTheDocument();
    // draft_count=null with a present archive file list: not present, NOT 0.
    const countCell = screen.getByTestId('paper-draft-count');
    expect(within(countCell).getByText('not present')).toBeInTheDocument();
    expect(within(countCell).queryByText('0')).toBeNull();
  });

  it('shows the no-run empty state when the hash carries no ?run param', async () => {
    window.location.hash = '#/governance';
    renderPage();
    expect(
      await screen.findByText(/No run selected/),
    ).toBeInTheDocument();
    expect(capsMock).not.toHaveBeenCalled();
  });
});
