#!/usr/bin/env bash
# ============================================================================
# install_latex.sh — Step 4: LaTeX (optional)
# ============================================================================

echo ""
echo -e "${BOLD}  🐜 [4/6] $(m step4)${RESET}"
echo ""

if command -v pdflatex &>/dev/null; then
  ok "pdflatex: $(which pdflatex)"
elif [ -n "${PDFLATEX_PATH:-}" ] && [ -x "$PDFLATEX_PATH" ]; then
  ok "pdflatex: $PDFLATEX_PATH"
else
  info "$(m latex_missing)"
  echo ""
  case "$OS_NAME" in
    macOS)
      echo "    brew install --cask mactex-no-gui"
      echo "    # or: conda install -c conda-forge texlive-core" ;;
    Linux)
      echo "    conda install -c conda-forge texlive-core   # No sudo"
      echo "    sudo apt install texlive-full                # Debian/Ubuntu"
      echo "    sudo dnf install texlive texlive-latex       # RHEL/Fedora" ;;
    *)
      echo "    conda install -c conda-forge texlive-core" ;;
  esac
fi
