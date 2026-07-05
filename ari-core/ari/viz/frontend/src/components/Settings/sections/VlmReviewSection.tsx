import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import { PROVIDER_MODELS, DEFAULT_PROVIDER } from '../settingsConstants';

interface VlmReviewSectionProps {
  provider: string;
  vlmReviewModel: string;
  setVlmReviewModel: (v: string) => void;
}

export function VlmReviewSection({
  provider,
  vlmReviewModel,
  setVlmReviewModel,
}: VlmReviewSectionProps) {
  return (
    <Card title="VLM Figure Review">
      <label style={labelStyle}>VLM Model</label>
      <select
        value={vlmReviewModel}
        onChange={(e) => setVlmReviewModel(e.target.value)}
        style={inputStyle}
      >
        {(PROVIDER_MODELS[provider] || PROVIDER_MODELS[DEFAULT_PROVIDER]).map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </Card>
  );
}
