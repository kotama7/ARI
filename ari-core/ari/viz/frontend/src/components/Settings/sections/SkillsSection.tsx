import { Card } from '../../common';
import type { TFn, SkillInfo } from '../settingsTypes';

interface SkillsSectionProps {
  t: TFn;
  skills: SkillInfo[];
}

export function SkillsSection({ t, skills }: SkillsSectionProps) {
  return (
    <Card title={t('settings_skills')}>
      {skills.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                {t('skill_label')}
              </th>
              <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                {t('skill_display_name')}
              </th>
              <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                Description
              </th>
              <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                Env
              </th>
            </tr>
          </thead>
          <tbody>
            {skills.map((s) => (
              <tr key={s.name}>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                  <code style={{ fontSize: '.78rem' }}>{s.name}</code>
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.85rem' }}>
                  {s.display_name}
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.8rem', color: 'var(--muted)' }}>
                  {s.description}
                </td>
                <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                  {s.requires_env && s.requires_env.length ? (
                    s.requires_env.join(', ')
                  ) : (
                    <span className="badge badge-green" style={{ fontSize: '.7rem' }}>
                      any
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>No skill.yaml found</div>
      )}
    </Card>
  );
}
