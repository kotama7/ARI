"""Test i18n consistency: all languages share the same keys (React/TypeScript migration)."""
import re
from pathlib import Path

REACT_SRC = Path(__file__).parent.parent / "ari" / "viz" / "frontend" / "src"
I18N_DIR = REACT_SRC / "i18n"
EN_TS = I18N_DIR / "en.ts"
JA_TS = I18N_DIR / "ja.ts"
ZH_TS = I18N_DIR / "zh.ts"

# Regex matching CJK ideographs, Hiragana, Katakana (catches hardcoded ja/zh text)
_CJK_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uF900-\uFAFF]")


def _extract_ts_keys(ts_path: Path) -> set[str]:
    """Parse keys from a TypeScript i18n dict like `const en: Record<...> = { key: 'val', ... };`."""
    src = ts_path.read_text()
    # Match property keys: identifier followed by colon (skip comment lines)
    keys = set()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        m = re.match(r"(\w+)\s*:", stripped)
        if m:
            keys.add(m.group(1))
    return keys


# ── Tests ──


class TestNoHardcodedCJKOutsideI18NDict:
    """React component TSX files must not contain CJK characters outside i18n dicts."""

    # Whitelist: language selector option text (e.g. "日本語", "中文") is intentional
    _OPTION_RE = re.compile(r"['\"][\u3040-\u9FFF\uF900-\uFAFF]+['\"]")

    def _visible_lines(self, text: str) -> list[tuple[int, str]]:
        hits = []
        for lineno, line in enumerate(text.splitlines(), 1):
            check = line
            if _CJK_RE.search(check):
                hits.append((lineno, line.strip()))
        return hits

    def test_react_components_no_hardcoded_cjk(self):
        """TSX component files must not have hardcoded CJK (use i18n keys instead)."""
        components_dir = REACT_SRC / "components"
        for tsx in sorted(components_dir.rglob("*.tsx")):
            src = tsx.read_text()
            hits = self._visible_lines(src)
            # Filter out language selector options (e.g. '日本語', '中文')
            filtered = []
            for lineno, line in hits:
                # Allow: option elements with CJK (language selectors)
                if re.search(r"['\"][\u3040-\u9FFF\uF900-\uFAFF]+['\"]", line):
                    continue
                # Allow: unicode escape sequences
                if "\\u" in line:
                    continue
                filtered.append((lineno, line))
            assert filtered == [], (
                f"Hardcoded CJK in {tsx.name}:\n"
                + "\n".join(f"  L{n}: {l}" for n, l in filtered)
            )

    def test_api_service_no_hardcoded_cjk(self):
        """api.ts must not have hardcoded CJK."""
        src = (REACT_SRC / "services" / "api.ts").read_text()
        hits = self._visible_lines(src)
        assert hits == [], (
            f"Hardcoded CJK in api.ts:\n"
            + "\n".join(f"  L{n}: {l}" for n, l in hits)
        )


class TestI18NKeyConsistency:
    """All supported languages must have the same set of i18n keys."""

    def test_all_three_languages_present(self):
        assert EN_TS.exists(), "en.ts not found"
        assert JA_TS.exists(), "ja.ts not found"
        assert ZH_TS.exists(), "zh.ts not found"

    def test_en_ja_keys_match(self):
        en = _extract_ts_keys(EN_TS)
        ja = _extract_ts_keys(JA_TS)
        missing_ja = en - ja
        extra_ja = ja - en
        assert not missing_ja, f"Keys in en but missing from ja: {missing_ja}"
        assert not extra_ja, f"Keys in ja but missing from en: {extra_ja}"

    def test_en_zh_keys_match(self):
        en = _extract_ts_keys(EN_TS)
        zh = _extract_ts_keys(ZH_TS)
        missing_zh = en - zh
        extra_zh = zh - en
        assert not missing_zh, f"Keys in en but missing from zh: {missing_zh}"
        assert not extra_zh, f"Keys in zh but missing from en: {extra_zh}"


class TestI18NIndexImports:
    """i18n/index.ts must import all three languages and provide useI18n hook."""

    def test_index_imports_all_languages(self):
        src = (I18N_DIR / "index.ts").read_text()
        assert "import en from" in src, "index.ts must import en"
        assert "import ja from" in src, "index.ts must import ja"
        assert "import zh from" in src, "index.ts must import zh"

    def test_index_exports_useI18n(self):
        src = (I18N_DIR / "index.ts").read_text()
        assert "useI18n" in src, "index.ts must export useI18n hook"

    def test_index_has_fallback_to_en(self):
        """useI18n must fall back to en when key not found in current language."""
        src = (I18N_DIR / "index.ts").read_text()
        assert "translations.en" in src or "'en'" in src, \
            "useI18n must fall back to English translations"


class TestComponentsUseI18N:
    """React components must use useI18n, not hardcoded strings for i18n keys."""

    def test_nav_items_use_i18n_keys(self):
        """All i18n nav keys must be referenced in the React source."""
        combined_parts = []
        for f in sorted(REACT_SRC.rglob("*.tsx")):
            combined_parts.append(f.read_text())
        for f in sorted(REACT_SRC.rglob("*.ts")):
            combined_parts.append(f.read_text())
        combined = "\n".join(combined_parts)
        for key in ['nav_home', 'nav_monitor', 'nav_tree', 'nav_results', 'nav_settings', 'nav_idea']:
            assert key in combined, f"Missing i18n key reference: {key}"
