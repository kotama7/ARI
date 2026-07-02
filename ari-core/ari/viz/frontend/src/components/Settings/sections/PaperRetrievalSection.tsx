import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import type { TFn } from '../settingsTypes';

interface PaperRetrievalSectionProps {
  t: TFn;
  retrievalBackend: string;
  setRetrievalBackend: (v: string) => void;
  ssKey: string;
  setSsKey: (v: string) => void;
}

export function PaperRetrievalSection({
  t,
  retrievalBackend,
  setRetrievalBackend,
  ssKey,
  setSsKey,
}: PaperRetrievalSectionProps) {
  return (
    <Card title={t('settings_paper')}>
      <label style={labelStyle}>Paper Retrieval Backend</label>
      <div style={{ display: 'flex', gap: '16px', marginBottom: '12px' }}>
        {([
          ['semantic_scholar', 'Semantic Scholar'],
          ['alphaxiv', 'AlphaXiv'],
          ['both', 'Both (parallel)'],
        ] as const).map(([val, label]) => (
          <label
            key={val}
            style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '.85rem', cursor: 'pointer' }}
          >
            <input
              type="radio"
              name="retrieval_backend"
              value={val}
              checked={retrievalBackend === val}
              onChange={() => setRetrievalBackend(val)}
            />
            {label}
          </label>
        ))}
      </div>
      <label style={labelStyle}>Semantic Scholar API Key</label>
      <input
        type="password"
        value={ssKey}
        onChange={(e) => setSsKey(e.target.value)}
        placeholder="(optional)"
        style={inputStyle}
      />
    </Card>
  );
}
