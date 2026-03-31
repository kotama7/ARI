#!/usr/bin/env bash
# ============================================================================
# spinner.sh — Ant-march animation for long-running commands
# ============================================================================
# Usage:
#   run_with_ants "Installing packages..." command arg1 arg2
#   run_with_ants "$(m step1)" pip install -e ./ari-core/
#
# The ants march across the terminal while the command runs in background.
# On success: shows check mark.  On failure: shows cross mark.
# ============================================================================

# Width of the ant trail
_ANT_WIDTH=20

# Ant march frames — ants walk left-to-right, then loop
_ant_frames() {
  local width=$_ANT_WIDTH
  local trail=""
  local i=$1

  # Build the trail: dots with ants scattered
  trail=""
  for ((p=0; p<width; p++)); do
    # Place an ant every 4 positions, shifting by frame index
    if (( (p + i) % 4 == 0 )); then
      trail+="🐜"
    else
      trail+=" ."
    fi
  done
  echo "$trail"
}

# Spinner with marching ants
# Args: $1 = message, $2.. = command to run
run_with_ants() {
  local msg="$1"
  shift

  # Non-interactive: just run the command
  if [ ! -t 1 ]; then
    echo "  $msg"
    "$@"
    return $?
  fi

  # Run command in background, capture output
  local tmpfile
  tmpfile=$(mktemp)
  "$@" >"$tmpfile" 2>&1 &
  local cmd_pid=$!

  local frame=0

  # Hide cursor
  tput civis 2>/dev/null || true

  while kill -0 "$cmd_pid" 2>/dev/null; do
    local ants
    ants=$(_ant_frames $frame)
    printf "\r  ${CYAN}%s${RESET} %s " "$ants" "$msg"
    frame=$(( (frame + 1) % _ANT_WIDTH ))
    sleep 0.15
  done

  # Get exit status
  wait "$cmd_pid"
  local exit_code=$?

  # Show cursor
  tput cnorm 2>/dev/null || true

  # Clear the spinner line
  printf "\r%*s\r" 80 ""

  if [ $exit_code -eq 0 ]; then
    ok "$msg"
  else
    fail "$msg"
    # Show last few lines of output on failure
    tail -5 "$tmpfile" | while IFS= read -r line; do
      echo -e "     ${RED}│${RESET} $line"
    done
  fi

  rm -f "$tmpfile"
  return $exit_code
}

# Progress bar with ants — for multi-item installs
# Args: $1 = current, $2 = total, $3 = item name
ant_progress() {
  local current=$1
  local total=$2
  local item=$3

  if [ ! -t 1 ]; then return; fi

  local pct=$(( current * 100 / total ))
  local bar_width=20
  local filled=$(( current * bar_width / total ))
  local empty=$(( bar_width - filled ))

  # Bar fills right-to-left so the left-facing 🐜 walks forward
  local bar=""
  for ((i=0; i<empty; i++)); do bar+="░"; done
  # Place an ant at the frontier
  if [ $empty -gt 0 ]; then
    bar+="🐜"
  else
    bar+="🐜"
    filled=$((filled - 1))
  fi
  for ((i=0; i<filled; i++)); do bar+="█"; done

  printf "\r  ${CYAN}[%s]${RESET} %3d%% %s " "$bar" "$pct" "$item"
}

# Fun colony status messages — randomly shown during long installs
_colony_messages_en=(
  "The colony is working hard..."
  "Ants carrying bytes..."
  "Building the anthill..."
  "Scout ants found dependencies..."
  "Worker ants assembling packages..."
  "Queen ant approves this build..."
)
_colony_messages_ja=(
  "コロニーが頑張っています..."
  "蟻たちがバイトを運搬中..."
  "蟻塚を建設中..."
  "偵察蟻が依存関係を発見..."
  "働き蟻がパッケージを組立中..."
  "女王蟻がビルドを承認..."
)
_colony_messages_zh=(
  "蚁群正在努力工作..."
  "蚂蚁们搬运字节中..."
  "正在建造蚁巢..."
  "侦察蚁发现了依赖..."
  "工蚁正在组装包..."
  "蚁后批准了这次构建..."
)

colony_say() {
  local lang="${SETUP_LANG:-en}"
  local -n msgs="_colony_messages_${lang}"
  local idx=$(( RANDOM % ${#msgs[@]} ))
  echo -e "  ${CYAN}🐜💬${RESET} ${msgs[$idx]}"
}
