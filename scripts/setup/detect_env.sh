#!/usr/bin/env bash
# ============================================================================
# detect_env.sh — Detect OS, shell, Python, pip, git
# ============================================================================

echo ""
info "$(m detecting_env)"
echo ""

# --- Detect OS --------------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
  Linux*)  OS_NAME="Linux" ;;
  Darwin*) OS_NAME="macOS" ;;
  MINGW*|MSYS*|CYGWIN*) OS_NAME="Windows"
    warn "$(m win_warn)"
    echo "    https://docs.microsoft.com/en-us/windows/wsl/install" ;;
  *) OS_NAME="Unknown" ;;
esac
ok "$(m os): $OS_NAME ($OS)"

# --- Detect shell -----------------------------------------------------------
CURRENT_SHELL="$(basename "${SHELL:-/bin/sh}")"
ok "$(m shell): $CURRENT_SHELL"

# --- Find Python 3 ----------------------------------------------------------
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      PYTHON="$candidate"
      break
    else
      warn "$candidate $ver — $(m python_old)"
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  fail "$(m python_not_found)"
  echo ""
  case "$OS_NAME" in
    macOS)  echo "    brew install python@3.12" ;;
    Linux)  echo "    sudo apt install python3.12   # Debian/Ubuntu"
            echo "    sudo dnf install python3.12   # RHEL/Fedora"
            echo "    conda install python=3.12     # Any platform" ;;
    *)      echo "    https://www.python.org/downloads/" ;;
  esac
  exit 1
fi
ok "Python: $PYTHON ($($PYTHON --version 2>&1))"

# --- Find pip (must match the detected Python) ------------------------------
PIP=""
# Prefer $PYTHON -m pip to guarantee pip matches the correct Python version
if $PYTHON -m pip --version &>/dev/null 2>&1; then
  PIP="$PYTHON -m pip"
else
  for candidate in pip3 pip; do
    if command -v "$candidate" &>/dev/null; then
      # Verify this pip belongs to the same Python
      pip_py_ver=$("$candidate" --version 2>&1 | grep -oP 'python \K\d+\.\d+' || echo "")
      python_ver=$("$PYTHON" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
      if [ "$pip_py_ver" = "$python_ver" ]; then
        PIP="$candidate"
        break
      fi
    fi
  done
fi

if [ -z "$PIP" ]; then
  info "$(m pip_missing)"
  $PYTHON -m ensurepip --upgrade 2>/dev/null || {
    fail "$(m pip_fail)"
    echo "    $PYTHON -m ensurepip --upgrade"
    echo "    # or: curl -sS https://bootstrap.pypa.io/get-pip.py | $PYTHON"
    exit 1
  }
  PIP="$PYTHON -m pip"
fi
ok "pip: $($PIP --version 2>&1 | head -1)"

# --- Find git ---------------------------------------------------------------
if ! command -v git &>/dev/null; then
  warn "$(m git_missing)"
  echo "    https://git-scm.com/downloads"
fi
