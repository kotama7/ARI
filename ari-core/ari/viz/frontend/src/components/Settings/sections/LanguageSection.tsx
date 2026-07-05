import { Card } from '../../common';
import { inputStyle, labelStyle } from '../settingsStyles';
import type { TFn } from '../settingsTypes';

interface LanguageSectionProps {
  t: TFn;
  lang: string;
  onLangChange: (lang: string) => void;
}

export function LanguageSection({ t, lang, onLangChange }: LanguageSectionProps) {
  return (
    <Card title={t('settings_lang_section')}>
      <label style={labelStyle}>{t('settings_lang')}</label>
      <select
        value={lang}
        onChange={(e) => onLangChange(e.target.value)}
        style={inputStyle}
      >
        <option value="en">English</option>
        <option value="ja">{'日本語'}</option>
        <option value="zh">{'中文'}</option>
      </select>
    </Card>
  );
}
