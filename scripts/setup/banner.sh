#!/usr/bin/env bash
# ============================================================================
# banner.sh — Completion banner and next steps
# ============================================================================

echo ""

# Animated ant parade on success
if [ -t 1 ] && [ "${ERRORS:-0}" -eq 0 ]; then
  _parade="🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜"
  # Quick left-to-right reveal
  for ((i=1; i<=${#_parade}; i++)); do
    printf "\r  ${BOLD}%s${RESET}" "${_parade:0:$i}"
    sleep 0.01
  done
  echo ""
else
  echo -e "${BOLD}  🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜🐜${RESET}"
fi

echo ""

if [ "${ERRORS:-0}" -gt 0 ]; then
  warn "$ERRORS $(m done_errors)"
else
  echo -e "  ${GREEN}${BOLD}🎉 $(m done)${RESET}"

  # Fun: ants celebrate with a little dance
  if [ -t 1 ]; then
    _dance_frames=(
      "  🐜 🐜 🐜  ♪ ♫ ♪"
      "  🐜  🐜  🐜 ♫ ♪ ♫"
      "  🐜 🐜 🐜  ♪ ♫ ♪"
    )
    for frame in "${_dance_frames[@]}"; do
      printf "\r%s" "$frame"
      sleep 0.3
    done
    printf "\r%*s\r" 40 ""
  fi
fi

echo ""
echo -e "${BOLD}  $(m next)${RESET}"

# Prefer venv-installed console script — works even when ~/bin has no symlink.
ARI_BIN="${ARI_ROOT}/.venv/bin/ari"

echo ""
echo "  $(m next_model)"
echo ""
echo "     # 🐜 Ollama (free, local)"
echo "     ollama pull qwen3:8b"
echo "     ollama serve   # omit if localhost:11434 already answers (daemon running)"
echo "     export ARI_BACKEND=ollama ARI_MODEL=qwen3:8b"
echo ""
echo "     # 🐜 OpenAI (cloud API)"
echo "     export ARI_BACKEND=openai ARI_MODEL=openai/gpt-4o OPENAI_API_KEY=sk-..."
echo ""
echo "     # 🐜 Anthropic (cloud API)"
echo "     export ARI_BACKEND=claude ARI_MODEL=anthropic/claude-sonnet-4-5 ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "  $(m next_run)"
if [ -x "$ARI_BIN" ]; then
  echo "     \"$ARI_BIN\" run experiment.md"
else
  echo "     ari run experiment.md"
fi
echo "     # or: \"$PYTHON\" -m ari.cli run <path-to-experiment.md>"
echo "     # Format and a copy-pasteable minimal example: docs/guides/experiment_file.md"
echo ""
echo "  $(m next_paper)"
if [ -x "$ARI_BIN" ]; then
  echo "     \"$ARI_BIN\" paper ./checkpoints/<run_id>/"
else
  echo "     ari paper ./checkpoints/<run_id>/"
fi
echo ""
echo "  $(m next_projects)"
if [ -x "$ARI_BIN" ]; then
  echo "     \"$ARI_BIN\" projects"
else
  echo "     ari projects"
fi
echo ""
echo "  $(m next_dash)"
if [ -x "$ARI_BIN" ]; then
  echo "     \"$ARI_BIN\" viz ./checkpoints/ --port 9886"
else
  echo "     ari viz ./checkpoints/ --port 9886"
fi
echo "     # → http://localhost:9886 🐜"
echo ""

# Shell config hint
RC_FILE=""
case "$CURRENT_SHELL" in
  bash) RC_FILE="~/.bashrc" ;;
  zsh)  RC_FILE="~/.zshrc" ;;
  fish) RC_FILE="~/.config/fish/config.fish" ;;
esac
if [ -n "$RC_FILE" ]; then
  MSG_TIP=$(m tip_rc)
  # shellcheck disable=SC2059
  printf "  $MSG_TIP\n" "$RC_FILE"
fi
echo ""
echo "  🐜 Happy researching!"
echo ""
