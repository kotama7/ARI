// ARI Dashboard – Configuration Studio (gui_refresh task 06 Wave 4d;
// plans 06 §Workspace structure / §Interaction model / §Schema-driven
// rendering, 05 §Configuration API).
//
// The EDITING extension of the read-only ConfigBrowser (Wave 3b): the same
// canonical field registry (GET /api/v1/config/schema) now drives a
// schema-generated form over the ADR-12 config documents:
//
//   - PROJECT scope: GET/PATCH /api/v1/projects/default/config with
//     If-Match optimistic concurrency (stale revision -> 409 -> reload
//     banner; per-path 400 rejections -> ValidationSummary);
//   - TEMPLATE / DRAFT scope (?template=<id> / ?draft=<id>): pick or create
//     a run template / run draft and edit its values through the identical
//     form (same registry validation server-side);
//   - field controls are generated from metadata (plan 06 §Schema-driven
//     rendering): enum -> select, bool -> switch, int/float -> number
//     input, str -> text input, secret_reference -> SecretField (wired to
//     the write-only PUT /api/v1/secrets/{secret_id} + readiness display),
//     composite types -> explicitly disabled with a reason (custom editors
//     are a later extension point — never silently hidden);
//   - model/provider suggestions come from the server catalog
//     (GET /api/v1/config/catalogs/models) — no frontend model constants;
//   - provenance/mutability badges are the ConfigBrowser exports, so the
//     two config surfaces cannot drift on badge semantics.
//
// ADR-09 (accepted 2026-07-27) replaced the former locked-governance group
// with an EXECUTION section (ExecutionSection.tsx): the two orthogonal mode
// INTENTS — ari.mode+rqgm.enabled and paper.mode+rqgm.paper.enabled — are
// selectable for a NEW RUN, each through ONE control that writes both leaves
// of its pair so a single Save PATCHes them together. Every OTHER rqgm.*
// tuning leaf stays read-only (collapsed, shared ConfigBrowser rows) with
// its effective value visible.
//
// Presentation (plan 02: v2 workspaces are built from semantic tokens and
// shared primitives only) — actions are the shared <Button> (primary for the
// affirmative one, outline for its secondary); the scope bar is the shared
// <TabStrip> paired with this page's role="tabpanel"; the category rail is
// the shared <NavRail> (a list with aria-current). Both composites are
// NAVIGATION, so neither is given the .btn action treatment.
//
// Wave 4e adds the LAUNCH flow to the DRAFT scope (LaunchPanel.tsx —
// plan 06 §Launch protocol): resolve-config -> validate -> immutable
// review -> idempotent POST /api/v1/runs -> canonical
// '#/overview?run=<run_id>' redirect. Drafts now carry an optional GOAL
// (create-time document field the launch materializes as experiment.md).

import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useT } from '../../i18n';
import {
  useConfigSchemaV1,
  useModelCatalogV1,
  useProjectConfigV1,
  useRunDraftV1,
  useRunTemplatesV1,
  useRunTemplateV1,
  useSecretsStatusV1,
  v1Keys,
} from '../../hooks/useV1';
import {
  patchProjectConfigV1,
  patchRunDraftV1,
  patchRunTemplateV1,
  toApiError,
  type ApiErrorV1,
  type ConfigFieldV1,
} from '../../services/api/v1';
import {
  Badge,
  Button,
  Card,
  ErrorState,
  LoadingState,
  NavRail,
  TabStrip,
  type NavRailItem,
  type TabStripItem,
} from '../common';
import { MUTABILITY_VARIANT } from '../ConfigBrowser/ConfigReadOnlyTable';
import { ExecutionSection } from './ExecutionSection';
import { LaunchPanel } from './LaunchPanel';
import { isExecutionSectionPath, type ModeIntentPair } from './modeIntents';
import { SecretField } from './SecretField';
import { StudioPickers } from './StudioPickers';
import { ValidationSummary, patchErrorsFromDetails, type PatchErrorV1 } from './ValidationSummary';

// ── hash params (#/studio?template=<id> / #/studio?draft=<id>) ──────────

interface StudioParams {
  template: string;
  draft: string;
}

function paramsFromHash(): StudioParams {
  const query = window.location.hash.split('?')[1] ?? '';
  const q = new URLSearchParams(query);
  return { template: q.get('template') ?? '', draft: q.get('draft') ?? '' };
}

function setStudioHash(params: Partial<StudioParams>): void {
  const q = new URLSearchParams();
  if (params.draft) q.set('draft', params.draft);
  else if (params.template) q.set('template', params.template);
  const qs = q.toString();
  window.location.hash = qs === '' ? '#/studio' : `#/studio?${qs}`;
}

type Scope = 'project' | 'template' | 'draft';

/** The two scopes reachable from the scope tab strip (a draft is entered
 *  through the draft pickers, so it has no tab of its own). */
type ScopeTabId = 'project' | 'template';

/** DOM id namespace shared by the scope tabs and their panel. */
const SCOPE_TABS_ID = 'studio-scope';

// ── field classification (plan 06; ADR-09 Execution section) ────────────

/** Execution section: the 4 selectable mode leaves + the read-only rqgm.* tree. */
function isExecutionField(field: ConfigFieldV1): boolean {
  return isExecutionSectionPath(field.path, field.category);
}

const EXECUTION_GROUP = '__execution__';

/** Primary control kind derived from registry metadata (union minus None). */
function controlKind(
  field: ConfigFieldV1,
): 'secret' | 'enum' | 'bool' | 'number' | 'text' | 'composite' {
  if (field.sensitivity === 'secret_reference') return 'secret';
  if (field.enum && field.enum.length > 0) return 'enum';
  const members = field.value_type
    .split('|')
    .map((m) => m.trim())
    .filter((m) => m !== 'None' && m !== '');
  if (members.length !== 1) return 'composite';
  const t = members[0];
  if (t === 'bool') return 'bool';
  if (t === 'int' || t === 'float') return 'number';
  if (t === 'str') return 'text';
  return 'composite';
}

/**
 * Deterministic display form of a config value (same discipline as the
 * ConfigBrowser: never a raw JSON.stringify dump into the render tree).
 */
function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `[${v.map(formatValue).join(', ')}]`;
  if (typeof v === 'object') {
    const entries = Object.entries(v as Record<string, unknown>);
    return `{${entries.map(([k, val]) => `${k}: ${formatValue(val)}`).join(', ')}}`;
  }
  return String(v);
}

function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

// ── page ────────────────────────────────────────────────────────────────

export function ConfigStudioPage() {
  const t = useT();
  const queryClient = useQueryClient();

  const [params, setParams] = useState<StudioParams>(paramsFromHash);
  useEffect(() => {
    const onHashChange = () => setParams(paramsFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const scope: Scope = params.draft !== '' ? 'draft' : params.template !== '' ? 'template' : 'project';

  const schemaQ = useConfigSchemaV1();
  const secretsQ = useSecretsStatusV1();
  const catalogQ = useModelCatalogV1();
  const projectQ = useProjectConfigV1();
  const templatesQ = useRunTemplatesV1();
  const templateQ = useRunTemplateV1(scope === 'template' ? params.template : '');
  const draftQ = useRunDraftV1(scope === 'draft' ? params.draft : '');

  // The active document (values + revision for If-Match).
  const doc = useMemo(() => {
    if (scope === 'template') {
      return {
        ready: templateQ.data !== undefined,
        values: (templateQ.data?.values ?? {}) as Record<string, unknown>,
        revision: templateQ.data?.revision ?? 0,
      };
    }
    if (scope === 'draft') {
      return {
        ready: draftQ.data !== undefined,
        values: (draftQ.data?.values ?? {}) as Record<string, unknown>,
        revision: draftQ.data?.revision ?? 0,
      };
    }
    return {
      ready: projectQ.data !== undefined,
      // Defensive ?? {}: offline shells mock this endpoint loosely.
      values: (projectQ.data?.values ?? {}) as Record<string, unknown>,
      revision: projectQ.data?.revision ?? 0,
    };
  }, [scope, projectQ.data, templateQ.data, draftQ.data]);

  // Pending (unsaved) edits: {dotted.path: value}.
  const [pending, setPending] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<PatchErrorV1[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [savedNote, setSavedNote] = useState(false);
  const [saving, setSaving] = useState(false);

  // Switching document target drops the edit buffer + result banners.
  useEffect(() => {
    setPending({});
    setValidationErrors([]);
    setSaveError(null);
    setConflict(false);
    setSavedNote(false);
  }, [scope, params.template, params.draft]);

  const fields = useMemo(() => schemaQ.data?.fields ?? [], [schemaQ.data]);
  const editableFields = useMemo(() => fields.filter((f) => !isExecutionField(f)), [fields]);
  const executionFields = useMemo(() => fields.filter(isExecutionField), [fields]);

  // Category rail: registry order, the Execution section pinned last.
  const categories = useMemo(() => {
    const seen: string[] = [];
    for (const f of editableFields) {
      if (!seen.includes(f.category)) seen.push(f.category);
    }
    return seen;
  }, [editableFields]);

  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const activeCategory =
    selectedCategory !== '' &&
    (selectedCategory === EXECUTION_GROUP || categories.includes(selectedCategory))
      ? selectedCategory
      : (categories[0] ?? '');

  const fieldCategory = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of fields) {
      map.set(f.path, isExecutionField(f) ? EXECUTION_GROUP : f.category);
    }
    return map;
  }, [fields]);

  const editCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const path of Object.keys(pending)) {
      const cat = fieldCategory.get(path) ?? 'Other';
      counts.set(cat, (counts.get(cat) ?? 0) + 1);
    }
    return counts;
  }, [pending, fieldCategory]);

  const pendingCount = Object.keys(pending).length;

  const setPendingValue = (path: string, value: unknown) => {
    setPending((prev) => ({ ...prev, [path]: value }));
    setSavedNote(false);
  };
  const clearPendingValue = (path: string) => {
    setPending((prev) => {
      if (!(path in prev)) return prev;
      const next = { ...prev };
      delete next[path];
      return next;
    });
  };

  const fieldByPath = useMemo(() => {
    const map = new Map<string, ConfigFieldV1>();
    for (const f of fields) map.set(f.path, f);
    return map;
  }, [fields]);

  /** Effective form value: pending edit > saved document > registry default. */
  const valueOfPath = (path: string): unknown => {
    if (path in pending) return pending[path];
    if (path in doc.values) return doc.values[path];
    return fieldByPath.get(path)?.default;
  };
  const currentValue = (field: ConfigFieldV1): unknown => valueOfPath(field.path);

  /** Saved (document or registry-default) value — the "no edit" baseline. */
  const savedValueOf = (path: string): unknown =>
    path in doc.values ? doc.values[path] : fieldByPath.get(path)?.default;

  /**
   * ADR-09: write BOTH leaves of one mode intent, never one without the
   * other. The Studio's Save collects the whole edit buffer into a single
   * PATCH, so the pair reaches the server in ONE request and the document can
   * never hold the half-set the backend rejects (`mode_interlock_mismatch`).
   *
   * Re-selecting the value the document already stores clears the pending
   * pair instead of materializing redundant keys — the default selection
   * (simple_bfts + linear) therefore writes nothing at all.
   */
  const selectModePair = (pair: ModeIntentPair, mode: string) => {
    const enabled = mode === pair.activeMode;
    const savedMode = savedValueOf(pair.modePath);
    const savedEnabled = Boolean(savedValueOf(pair.enablePath));
    setSavedNote(false);
    setPending((prev) => {
      const next = { ...prev };
      if (mode === savedMode && enabled === savedEnabled) {
        delete next[pair.modePath];
        delete next[pair.enablePath];
        return next;
      }
      next[pair.modePath] = mode;
      next[pair.enablePath] = enabled;
      return next;
    });
  };

  const invalidateActiveDoc = () => {
    if (scope === 'project') {
      void queryClient.invalidateQueries({ queryKey: v1Keys.projectConfig('default') });
    } else if (scope === 'template') {
      void queryClient.invalidateQueries({ queryKey: v1Keys.runTemplate(params.template) });
      void queryClient.invalidateQueries({ queryKey: v1Keys.runTemplates() });
    } else {
      void queryClient.invalidateQueries({ queryKey: v1Keys.runDraft(params.draft) });
    }
  };

  const reloadAfterConflict = () => {
    setConflict(false);
    invalidateActiveDoc();
  };

  const save = async () => {
    if (pendingCount === 0 || !doc.ready || saving) return;
    setSaving(true);
    setValidationErrors([]);
    setSaveError(null);
    setConflict(false);
    setSavedNote(false);
    try {
      if (scope === 'project') {
        await patchProjectConfigV1(pending, doc.revision);
      } else if (scope === 'template') {
        await patchRunTemplateV1(params.template, pending, doc.revision);
      } else {
        await patchRunDraftV1(params.draft, pending, doc.revision);
      }
      setPending({});
      setSavedNote(true);
      invalidateActiveDoc();
    } catch (err) {
      const e = toApiError(err);
      if (e.code === 'revision_conflict') {
        // Stale If-Match (plan 06: revision conflict -> explicit reload,
        // unsaved edits stay local so nothing is silently discarded).
        setConflict(true);
      } else {
        const perPath = patchErrorsFromDetails(e.details);
        if (perPath.length > 0) setValidationErrors(perPath);
        else setSaveError(errorText(e, t('studio_request_id')));
      }
    } finally {
      setSaving(false);
    }
  };

  // ── model suggestions from the server catalog (plan 06) ───────────────

  const providers = useMemo(() => catalogQ.data?.providers ?? [], [catalogQ.data]);
  const activeProvider = String(
    (('llm.backend' in pending ? pending['llm.backend'] : doc.values['llm.backend']) ??
      fields.find((f) => f.path === 'llm.backend')?.default ??
      '') as string,
  );
  const modelSuggestions = useMemo(() => {
    const match = providers.find((p) => p.id === activeProvider);
    if (match) return match.models ?? [];
    return providers.flatMap((p) => p.models ?? []);
  }, [providers, activeProvider]);
  const defaultSecretName = providers.find((p) => p.id === activeProvider)?.env_key ?? undefined;

  const secrets = useMemo(() => secretsQ.data?.secrets ?? [], [secretsQ.data]);

  // ── loading / error shell ─────────────────────────────────────────────

  const hardError: ApiErrorV1 | null =
    schemaQ.isError && schemaQ.data === undefined ? schemaQ.error : null;
  const loading = schemaQ.isPending;

  // ── field row rendering ───────────────────────────────────────────────

  const renderControl = (field: ConfigFieldV1) => {
    const kind = controlKind(field);
    const value = currentValue(field);
    if (kind === 'secret') {
      return (
        <SecretField
          secrets={secrets}
          defaultName={defaultSecretName}
          onSaved={() =>
            void queryClient.invalidateQueries({ queryKey: v1Keys.secretsStatus() })
          }
        />
      );
    }
    if (kind === 'enum') {
      const enumValues = field.enum ?? [];
      const idx = enumValues.findIndex((v) => v === value);
      return (
        <select
          aria-label={field.path}
          value={idx >= 0 ? String(idx) : ''}
          onChange={(e) => {
            const i = e.target.value;
            if (i === '') clearPendingValue(field.path);
            else setPendingValue(field.path, enumValues[Number(i)]);
          }}
        >
          <option value="">{t('studio_none_option')}</option>
          {enumValues.map((v, i) => (
            <option key={String(v)} value={String(i)}>
              {formatValue(v)}
            </option>
          ))}
        </select>
      );
    }
    if (kind === 'bool') {
      return (
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <input
            type="checkbox"
            role="switch"
            aria-label={field.path}
            checked={Boolean(value)}
            onChange={(e) => setPendingValue(field.path, e.target.checked)}
          />
          <span style={{ fontSize: '.8rem' }}>{Boolean(value) ? 'true' : 'false'}</span>
        </label>
      );
    }
    if (kind === 'number') {
      const isInt = field.value_type.split('|').some((m) => m.trim() === 'int');
      return (
        <input
          type="number"
          aria-label={field.path}
          step={isInt ? 1 : 'any'}
          value={typeof value === 'number' ? String(value) : ''}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === '') {
              clearPendingValue(field.path);
              return;
            }
            const n = Number(raw);
            if (!Number.isNaN(n)) setPendingValue(field.path, isInt ? Math.trunc(n) : n);
          }}
          style={{ width: 120 }}
        />
      );
    }
    if (kind === 'text') {
      const listId = field.path === 'llm.model' && modelSuggestions.length > 0 ? 'studio-model-suggestions' : undefined;
      return (
        <>
          <input
            type="text"
            aria-label={field.path}
            list={listId}
            value={typeof value === 'string' ? value : formatValue(value)}
            onChange={(e) => setPendingValue(field.path, e.target.value)}
            style={{ width: '100%', maxWidth: 320 }}
          />
          {listId && (
            <datalist id={listId}>
              {modelSuggestions.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          )}
        </>
      );
    }
    // Composite (list/dict/nested model): explicitly disabled with a reason
    // (plan 06: unavailable controls show why — never silently hidden).
    return (
      <div>
        <input
          type="text"
          aria-label={field.path}
          disabled
          value={formatValue(value)}
          readOnly
          style={{ width: '100%', maxWidth: 320, opacity: 0.6 }}
        />
        <div style={{ color: 'var(--muted)', fontSize: '.72rem' }}>
          {t('studio_composite_note')}
        </div>
      </div>
    );
  };

  const renderFieldRow = (field: ConfigFieldV1) => {
    const edited = field.path in pending;
    const savedInDoc = field.path in doc.values;
    return (
      <tr key={field.path}>
        <td style={{ verticalAlign: 'top' }}>
          <code style={{ fontSize: '.8rem' }}>{field.path}</code>
          {field.applies_when && (
            <div style={{ color: 'var(--muted)', fontSize: '.72rem' }}>
              {t('config_applies_when')}: {field.applies_when}
            </div>
          )}
        </td>
        <td style={{ verticalAlign: 'top' }}>{renderControl(field)}</td>
        <td style={{ verticalAlign: 'top' }}>
          {edited ? (
            <Badge variant="yellow">{t('studio_edited_badge')}</Badge>
          ) : savedInDoc ? (
            <Badge variant="green">{t('studio_saved_badge')}</Badge>
          ) : (
            <Badge variant="muted">{t('studio_default_badge')}</Badge>
          )}
        </td>
        <td style={{ verticalAlign: 'top' }}>
          <Badge variant={MUTABILITY_VARIANT[field.mutability]}>{field.mutability}</Badge>
        </td>
      </tr>
    );
  };

  const activeFields = editableFields.filter((f) => f.category === activeCategory);
  const executionActive = activeCategory === EXECUTION_GROUP;

  // ── navigation composites (shared primitives, plan 02) ────────────────

  // Scope tabs. The draft scope has no tab: a draft is entered from the draft
  // pickers below, exactly as before.
  const templateCount = templatesQ.data?.templates?.length ?? 0;
  const scopeTabs: TabStripItem<ScopeTabId>[] = [
    { id: 'project', label: t('studio_scope_project') },
    {
      id: 'template',
      label: t('studio_scope_template'),
      disabled: templateCount === 0,
      title: templateCount === 0 ? t('studio_template_none') : undefined,
    },
  ];
  const selectScope = (id: ScopeTabId) => {
    if (id === 'project') {
      setStudioHash({});
      return;
    }
    const first = templatesQ.data?.templates?.[0]?.template_id ?? '';
    if (first !== '') setStudioHash({ template: first });
    else setStudioHash({ template: params.template });
  };

  // Category rail: registry categories + the pinned Execution section, each
  // with its pending-edit count as a trailing badge.
  const railBadge = (key: string) => {
    const edits = editCounts.get(key) ?? 0;
    return edits > 0 ? <Badge variant="yellow">{edits}</Badge> : undefined;
  };
  const railItems: NavRailItem[] = [
    ...categories.map((cat) => ({ id: cat, label: cat, accessory: railBadge(cat) })),
    {
      id: EXECUTION_GROUP,
      label: `⚙️ ${t('studio_exec_section_title')}`,
      accessory: railBadge(EXECUTION_GROUP),
    },
  ];

  // ── render ────────────────────────────────────────────────────────────

  return (
    <div className="page active" id="page-studio" style={{ display: 'block' }}>
      <h1>{t('studio_title')}</h1>
      <p className="subtitle">{t('studio_subtitle')}</p>

      {hardError ? (
        <ErrorState
          message={errorText(hardError, t('studio_request_id'))}
          onRetry={() => void schemaQ.refetch()}
        />
      ) : loading ? (
        <LoadingState />
      ) : (
        <>
          {/* Scope tabs: project defaults / run template / run draft. This is
              navigation, not an action — the shared TabStrip primitive, never
              the .btn treatment. */}
          <TabStrip
            items={scopeTabs}
            activeId={scope}
            onSelect={selectScope}
            ariaLabel={t('studio_scope_label')}
            idPrefix={SCOPE_TABS_ID}
          />
          {scope === 'draft' && (
            <p style={{ color: 'var(--text-muted)', fontSize: '.8rem', margin: '0 0 8px' }}>
              {t('studio_draft_label')}: {params.draft}
            </p>
          )}

          <div
            role="tabpanel"
            id={`${SCOPE_TABS_ID}-panel-${scope}`}
            // The draft scope has no tab of its own (it is entered from the
            // draft pickers), so the panel names itself in that case.
            aria-labelledby={scope === 'draft' ? undefined : `${SCOPE_TABS_ID}-tab-${scope}`}
            aria-label={scope === 'draft' ? t('studio_scope_label') : undefined}
          >
            {/* Template picker / creation + draft creation (extracted). */}
            <StudioPickers
              templates={templatesQ.data?.templates ?? []}
              currentTemplate={scope === 'template' ? params.template : ''}
              onNavigate={setStudioHash}
            />

            {/* Revision-conflict reload banner (plan 06 §Interaction model). */}
            {conflict && (
              <Card>
                <div role="alert" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <Badge variant="red">{t('studio_conflict_title')}</Badge>
                  <span style={{ fontSize: '.85rem' }}>{t('studio_conflict_body')}</span>
                  <Button size="sm" onClick={reloadAfterConflict}>
                    {t('studio_reload')}
                  </Button>
                </div>
              </Card>
            )}

            <ValidationSummary errors={validationErrors} />
            {saveError && (
              <Card>
                <div role="alert" style={{ color: 'var(--status-danger)', fontSize: '.85rem' }}>
                  {saveError}
                </div>
              </Card>
            )}

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              {/* Left rail: categories with per-category edit counts. Slice
                  navigation, not actions — the shared NavRail primitive. */}
              <NavRail
                items={railItems}
                activeId={activeCategory}
                onSelect={setSelectedCategory}
                ariaLabel={t('studio_categories')}
              />

              {/* Main: schema-driven form for the active category. */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {scope === 'template' && !doc.ready ? (
                  <Card>
                    <p style={{ fontSize: '.85rem', margin: 0 }}>{t('studio_no_document')}</p>
                  </Card>
                ) : executionActive ? (
                  // ADR-09: two mode intents (editable, new-run only) + the
                  // read-only rqgm.* tree — never a generic editable table.
                  <ExecutionSection
                    fields={executionFields}
                    scope={scope}
                    valueOf={valueOfPath}
                    isPending={(path) => path in pending}
                    isSaved={(path) => path in doc.values}
                    onSelectPair={selectModePair}
                  />
                ) : (
                  <Card>
                    <div style={{ overflowX: 'auto' }}>
                      <table>
                        <thead>
                          <tr>
                            <th>{t('config_col_field')}</th>
                            <th>{t('config_col_value')}</th>
                            <th>{t('config_col_source')}</th>
                            <th>{t('config_col_mutability')}</th>
                          </tr>
                        </thead>
                        <tbody>{activeFields.map(renderFieldRow)}</tbody>
                      </table>
                    </div>
                  </Card>
                )}

                {/* Bottom save bar (plan 06 §Interaction model). */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
                  <Button
                    onClick={() => void save()}
                    disabled={pendingCount === 0 || saving || !doc.ready}
                  >
                    {t('studio_save')}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setPending({});
                      setValidationErrors([]);
                      setSaveError(null);
                    }}
                    disabled={pendingCount === 0}
                  >
                    {t('studio_discard')}
                  </Button>
                  <span style={{ color: 'var(--text-muted)', fontSize: '.8rem' }}>
                    {pendingCount > 0
                      ? `${pendingCount} ${t('studio_pending_edits')}`
                      : t('studio_no_pending')}
                  </span>
                  {savedNote && <Badge variant="green">{t('studio_saved_note')}</Badge>}
                  <span style={{ color: 'var(--text-muted)', fontSize: '.75rem' }}>
                    {t('studio_revision')}: {doc.revision}
                  </span>
                </div>

                {/* Launch flow — DRAFT scope only (Wave 4e, plan 06 §Launch
                    protocol). Stepper goal -> review -> launch over the
                    MN-10 idempotent POST /api/v1/runs. */}
                {scope === 'draft' && draftQ.data !== undefined && (
                  <LaunchPanel
                    draftId={params.draft}
                    goal={draftQ.data.goal ?? null}
                    revision={doc.revision}
                    fields={fields}
                  />
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
