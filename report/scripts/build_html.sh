#!/usr/bin/env bash
# build_html.sh <lang> — convert <lang>/main.tex to html/<lang>/index.html
#
# Toolchain order:
#   1. pandoc — preferred. Renders LaTeX to HTML5 directly without going
#      through a TeX font shaper, so CJK code points pass through cleanly.
#      build_html_pandoc.py post-processes the output to insert <img>
#      tags for TikZ figures (using the PNG previews under
#      shared/figures/preview/) and to inject the language switcher.
#   2. latexml — historical primary. Left as a fallback for future setups.
#   3. make4ht — last resort. Under the lualatex driver this drops
#      Japanese dakuten/handakuten marks (e.g. "ルブリック" → "ルフリック"),
#      so do not rely on it for ja/zh.
set -euo pipefail

LANG_CODE="${1:?usage: build_html.sh <en|ja|zh>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/${LANG_CODE}/main.tex"
OUT_DIR="${ROOT}/html/${LANG_CODE}"

mkdir -p "${OUT_DIR}"

if command -v pandoc >/dev/null 2>&1; then
    cd "${ROOT}"
    python3 scripts/build_html_pandoc.py --lang "${LANG_CODE}"
    exit 0
fi

if command -v latexml >/dev/null 2>&1 && command -v latexmlpost >/dev/null 2>&1; then
    XML="${OUT_DIR}/main.xml"
    latexml --destination="${XML}" --noparse --inputencoding=utf8 "${SRC}"
    latexmlpost --destination="${OUT_DIR}/index.html" --format=html5 \
                --javascript=https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.js \
                "${XML}"
    python3 "${ROOT}/scripts/inject_langnav.py" "${OUT_DIR}/index.html"
    exit 0
fi

if command -v make4ht >/dev/null 2>&1; then
    echo "[build_html] WARNING: pandoc and latexml unavailable; falling back to make4ht (CJK glyphs may be corrupted)"
    pushd "${ROOT}/${LANG_CODE}" >/dev/null
    if [ "${LANG_CODE}" = "zh" ]; then
        make4ht -ul main.tex "html5,mathjax"
    else
        make4ht main.tex "html5,mathjax"
    fi
    cp main.html "${OUT_DIR}/index.html"
    popd >/dev/null
    python3 "${ROOT}/scripts/inject_langnav.py" "${OUT_DIR}/index.html"
    exit 0
fi

echo "[build_html] none of pandoc/latexml/make4ht available; cannot build HTML"
exit 1
