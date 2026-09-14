// ARI Dashboard – Studio template/draft pickers (gui_refresh task 06;
// extracted from ConfigStudioPage in Wave 4e to keep the page under the
// LOC tripwire — no behavior change).
//
// Owns the template select + create controls and the draft create controls
// (template link + optional GOAL — the create-time document field a later
// POST /api/v1/runs materializes as {ckpt}/experiment.md). Navigation is
// delegated to the page via onNavigate (the #/studio?template=/?draft=
// hash is the page's routing state).

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useT } from '../../i18n';
import { v1Keys } from '../../hooks/useV1';
import {
  createRunDraftV1,
  createRunTemplateV1,
  toApiError,
  type ApiErrorV1,
  type RunTemplateSummaryV1,
} from '../../services/api/v1';
import { Button, Card } from '../common';

function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

interface StudioPickersProps {
  templates: RunTemplateSummaryV1[];
  /** '' when the page is not in template scope. */
  currentTemplate: string;
  /** Hash navigation: {} = project scope, {template} / {draft} = that doc. */
  onNavigate: (params: { template?: string; draft?: string }) => void;
}

export function StudioPickers({ templates, currentTemplate, onNavigate }: StudioPickersProps) {
  const t = useT();
  const queryClient = useQueryClient();

  const [newTemplateId, setNewTemplateId] = useState('');
  const [newTemplateName, setNewTemplateName] = useState('');
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [draftTemplate, setDraftTemplate] = useState('');
  const [draftGoal, setDraftGoal] = useState('');

  const createTemplate = async () => {
    if (newTemplateId === '' || newTemplateName === '') return;
    setPickerError(null);
    try {
      const created = await createRunTemplateV1(newTemplateId, newTemplateName);
      setNewTemplateId('');
      setNewTemplateName('');
      void queryClient.invalidateQueries({ queryKey: v1Keys.runTemplates() });
      onNavigate({ template: created.template_id });
    } catch (err) {
      setPickerError(errorText(toApiError(err), t('studio_request_id')));
    }
  };

  const createDraft = async () => {
    setPickerError(null);
    try {
      // The goal is a create-time document field (Wave 4e): the launch
      // later materializes it as {ckpt}/experiment.md.
      const created = await createRunDraftV1(
        draftTemplate === '' ? undefined : draftTemplate,
        {},
        draftGoal.trim() === '' ? undefined : draftGoal,
      );
      setDraftGoal('');
      onNavigate({ draft: created.draft_id });
    } catch (err) {
      setPickerError(errorText(toApiError(err), t('studio_request_id')));
    }
  };

  return (
    <Card>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <label style={{ display: 'block', fontSize: '.75rem', color: 'var(--muted)' }}>
            {t('studio_template_label')}
          </label>
          <select
            aria-label={t('studio_template_label')}
            value={currentTemplate}
            onChange={(e) => {
              const id = e.target.value;
              if (id === '') onNavigate({});
              else onNavigate({ template: id });
            }}
          >
            <option value="">{t('studio_none_option')}</option>
            {templates.map((tpl) => (
              <option key={tpl.template_id} value={tpl.template_id}>
                {tpl.name} ({tpl.template_id})
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <input
            type="text"
            aria-label={t('studio_template_id_placeholder')}
            placeholder={t('studio_template_id_placeholder')}
            value={newTemplateId}
            onChange={(e) => setNewTemplateId(e.target.value)}
            style={{ width: 170 }}
          />
          <input
            type="text"
            aria-label={t('studio_template_name_placeholder')}
            placeholder={t('studio_template_name_placeholder')}
            value={newTemplateName}
            onChange={(e) => setNewTemplateName(e.target.value)}
            style={{ width: 170 }}
          />
          <Button
            onClick={() => void createTemplate()}
            disabled={newTemplateId === '' || newTemplateName === ''}
          >
            {t('studio_template_create')}
          </Button>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <label style={{ display: 'block', fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('studio_draft_from_template')}
            </label>
            <select
              aria-label={t('studio_draft_from_template')}
              value={draftTemplate}
              onChange={(e) => setDraftTemplate(e.target.value)}
            >
              <option value="">{t('studio_none_option')}</option>
              {templates.map((tpl) => (
                <option key={tpl.template_id} value={tpl.template_id}>
                  {tpl.template_id}
                </option>
              ))}
            </select>
          </div>
          <input
            type="text"
            aria-label={t('studio_goal_placeholder')}
            placeholder={t('studio_goal_placeholder')}
            value={draftGoal}
            onChange={(e) => setDraftGoal(e.target.value)}
            style={{ width: 260 }}
          />
          <Button onClick={() => void createDraft()}>{t('studio_draft_create')}</Button>
        </div>
      </div>
      {pickerError && (
        <div role="alert" style={{ color: 'var(--status-danger)', fontSize: '.8rem', marginTop: 8 }}>
          {pickerError}
        </div>
      )}
    </Card>
  );
}
