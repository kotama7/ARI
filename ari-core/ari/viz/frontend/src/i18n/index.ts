import { useState, useCallback } from 'react';
import en from './en';
import ja from './ja';
import zh from './zh';

const translations: Record<string, Record<string, string>> = { en, ja, zh };

export function useI18n() {
  const [currentLang, setCurrentLangState] = useState<string>(
    () => localStorage.getItem('ari_lang') || 'ja',
  );

  const t = useCallback(
    (key: string): string => {
      const dict = translations[currentLang] || translations.en || {};
      return dict[key] || (translations.en || {})[key] || key;
    },
    [currentLang],
  );

  const setLanguage = useCallback((lang: string) => {
    localStorage.setItem('ari_lang', lang);
    setCurrentLangState(lang);
  }, []);

  return { t, setLanguage, currentLang };
}

export { en, ja, zh };
