import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import { DEFAULT_PROVIDER } from '../settingsConstants';
import { useModelCatalog } from '../../../hooks/useModelCatalog';

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
  const catalog = useModelCatalog();
  const served = catalog.modelsFor(provider);
  const models = served.length ? served : catalog.modelsFor(DEFAULT_PROVIDER);
  return (
    <Card title="VLM Figure Review">
      <label style={labelStyle}>VLM Model</label>
      <select
        value={vlmReviewModel}
        onChange={(e) => setVlmReviewModel(e.target.value)}
        style={inputStyle}
      >
        {models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </Card>
  );
}
