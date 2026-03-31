#!/usr/bin/env bash
# ============================================================================
# lang_select.sh — Interactive language selection (en / ja / zh)
# ============================================================================

# Auto-detect from env or locale
DEFAULT_IDX=0
SYS_LANG="${LANG:-${LC_ALL:-en_US.UTF-8}}"
case "$SYS_LANG" in
  ja*) DEFAULT_IDX=1 ;;
  zh*) DEFAULT_IDX=2 ;;
esac

LANG_OPTIONS=("English" "日本語" "中文")
LANG_CODES=("en" "ja" "zh")

if [ -t 0 ] && [ -t 1 ]; then
  # Interactive terminal — arrow-key selector
  echo -e "${BOLD}  🌐 Select language / 言語を選択 / 选择语言${RESET}"
  echo ""

  selected=$DEFAULT_IDX

  # Draw menu (3 options + 1 hint = 4 lines to redraw)
  draw_menu() {
    local total=$(( ${#LANG_OPTIONS[@]} + 1 ))  # options + hint line
    for ((n=0; n<total; n++)); do
      tput cuu1 2>/dev/null || printf '\033[1A'
    done
    for i in "${!LANG_OPTIONS[@]}"; do
      if [ "$i" -eq "$selected" ]; then
        printf "\r\033[K"
        echo -e "    ${GREEN}▸ ${BOLD}${LANG_OPTIONS[$i]}${RESET}"
      else
        printf "\r\033[K"
        echo -e "    ${CYAN}  ${LANG_OPTIONS[$i]}${RESET}"
      fi
    done
    printf "\r\033[K"
    echo -e "  ${CYAN}(↑↓ to move, Enter to select)${RESET}"
  }

  # Initial draw
  for i in "${!LANG_OPTIONS[@]}"; do
    if [ "$i" -eq "$selected" ]; then
      echo -e "    ${GREEN}▸ ${BOLD}${LANG_OPTIONS[$i]}${RESET}"
    else
      echo -e "    ${CYAN}  ${LANG_OPTIONS[$i]}${RESET}"
    fi
  done
  echo -e "  ${CYAN}(↑↓ to move, Enter to select)${RESET}"

  # Read arrow keys
  while true; do
    IFS= read -rsn1 key
    case "$key" in
      $'\x1b')
        read -rsn2 seq
        case "$seq" in
          '[A') # Up
            if [ "$selected" -gt 0 ]; then
              selected=$((selected - 1))
            fi ;;
          '[B') # Down
            if [ "$selected" -lt $((${#LANG_OPTIONS[@]} - 1)) ]; then
              selected=$((selected + 1))
            fi ;;
        esac
        draw_menu ;;
      '') # Enter
        break ;;
    esac
  done

  SETUP_LANG="${LANG_CODES[$selected]}"
  echo ""
else
  # Non-interactive — use auto-detected language
  SETUP_LANG="${LANG_CODES[$DEFAULT_IDX]}"
fi
