#!/usr/bin/env bash
# ============================================================================
# install_pdf.sh — Step 3: PDF tools (optional)
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [3/6] $(m step3)${RESET}"
echo ""

PDF_OK=false

if $PYTHON -c "import fitz" 2>/dev/null; then
  ok "pymupdf (fitz) ✔"
  PDF_OK=true
fi

if $PYTHON -c "from pdfminer.high_level import extract_text" 2>/dev/null; then
  ok "pdfminer.six ✔"
  PDF_OK=true
fi

if command -v conda &>/dev/null; then
  info "$(m conda_trying)"
  if run_with_ants "poppler + chktex" conda install -c conda-forge poppler chktex -y --quiet; then
    ok "poppler + chktex ✔"
  else
    warn "conda install skipped (non-fatal)"
  fi
else
  info "$(m conda_none)"
fi

if command -v pdftotext &>/dev/null; then
  ok "pdftotext ✔"
fi
