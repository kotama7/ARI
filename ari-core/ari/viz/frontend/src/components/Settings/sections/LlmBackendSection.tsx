import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import { PROVIDER_KEY_PLACEHOLDER } from '../settingsConstants';
import type { TFn } from '../settingsTypes';

interface LlmBackendSectionProps {
  t: TFn;
  provider: string;
  onProviderChange: (prov: string) => void;
  modelSelect: string;
  onModelSelectChange: (val: string) => void;
  modelCustom: string;
  setModelCustom: (v: string) => void;
  temperature: number;
  setTemperature: (v: number) => void;
  apiKey: string;
  setApiKey: (v: string) => void;
  baseUrl: string;
  setBaseUrl: (v: string) => void;
  currentModels: string[];
}

export function LlmBackendSection({
  t,
  provider,
  onProviderChange,
  modelSelect,
  onModelSelectChange,
  modelCustom,
  setModelCustom,
  temperature,
  setTemperature,
  apiKey,
  setApiKey,
  baseUrl,
  setBaseUrl,
  currentModels,
}: LlmBackendSectionProps) {
  return (
    <Card title={t('settings_llm')}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        {/* Provider */}
        <div>
          <label style={labelStyle}>{t('s_provider')}</label>
          <select
            value={provider}
            onChange={(e) => onProviderChange(e.target.value)}
            style={inputStyle}
          >
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="gemini">gemini</option>
            <option value="ollama">ollama</option>
            <option value="cli-shim">cli-shim (claude/codex)</option>
          </select>
        </div>

        {/* Model dropdown */}
        <div>
          <label style={labelStyle}>{t('s_model')}</label>
          <select
            value={modelSelect}
            onChange={(e) => onModelSelectChange(e.target.value)}
            style={inputStyle}
          >
            {currentModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            <option value="__custom__">{t('custom_entry')}</option>
          </select>
        </div>

        {/* Custom model input */}
        <div>
          <label style={labelStyle}>{t('settings_default_model')}</label>
          <input
            type="text"
            value={modelCustom}
            onChange={(e) => setModelCustom(e.target.value)}
            placeholder={t('model_custom_placeholder')}
            style={inputStyle}
          />
        </div>

        {/* Temperature */}
        <div>
          <label style={labelStyle}>{t('s_temperature')}</label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value) || 1.0)}
            style={inputStyle}
          />
        </div>

        {/* API Key (hidden for ollama) */}
        {provider !== 'ollama' && (
          <div>
            <label style={labelStyle}>API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={PROVIDER_KEY_PLACEHOLDER[provider] || 'api key'}
              style={inputStyle}
            />
          </div>
        )}

        {/* Base URL (ollama / cli-shim) */}
        {(provider === 'ollama' || provider === 'cli-shim') && (
          <div>
            <label style={labelStyle}>
              {provider === 'cli-shim' ? 'Base URL (CLI Shim)' : 'Base URL (Ollama)'}
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={
                provider === 'cli-shim'
                  ? 'http://localhost:8900/v1'
                  : 'http://localhost:11434'
              }
              style={inputStyle}
            />
          </div>
        )}
      </div>
    </Card>
  );
}
