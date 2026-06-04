#!/usr/bin/env bash
# assemble_site.sh — build the single Pages artifact (_site/) for L3:
#   - the bespoke landing at the site root (/ARI/),
#   - the VitePress docs dist at /ARI/docs/ (en + ja + zh),
#   - a noindex redirect stub at /ARI/docs.html for old bookmarks,
#   - .nojekyll.
# Run from the repo root, AFTER `vitepress build` has produced the dist:
#   bash scripts/docs/assemble_site.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SITE="$ROOT/_site"
DIST="$ROOT/docs/.vitepress/dist"

if [[ ! -d "$DIST" ]]; then
  echo "assemble_site: VitePress dist missing ($DIST) — run 'npm run --prefix docs docs:build' first" >&2
  exit 1
fi

rm -rf "$SITE"
mkdir -p "$SITE/docs"

# bespoke landing → site root
cp docs/index.html docs/tokens.css docs/site.css docs/version.json \
   docs/sitemap.xml docs/robots.txt "$SITE/"
cp -r docs/assets "$SITE/assets"
cp -r docs/i18n "$SITE/i18n"

# VitePress docs → /docs/
cp -r "$DIST/." "$SITE/docs/"

# redirect stub for old /docs.html bookmarks. noindex; it does NOT emit a
# canonical — the destination VitePress page owns the per-locale canonical
# (see docs/README.md). JS deep-links the locale matching localStorage('ari-lang');
# the meta-refresh is the no-JS fallback.
cat > "$SITE/docs.html" <<'STUB'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ARI Documentation</title>
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url=docs/">
<script>
(function () {
  var l = 'en';
  try { l = localStorage.getItem('ari-lang') || 'en'; } catch (e) {}
  var dest = l === 'ja' ? 'docs/ja/' : l === 'zh' ? 'docs/zh/' : 'docs/';
  location.replace(dest);
})();
</script>
</head>
<body>Redirecting to the <a href="docs/">ARI documentation</a>…</body>
</html>
STUB

touch "$SITE/.nojekyll"
echo "assembled _site: $(find "$SITE" -type f | wc -l) files"
