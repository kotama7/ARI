#!/usr/bin/env bash
# setup_fonts.sh — Install Noto CJK fonts for the report build.
# Called by humans (not by Make), once per machine.
set -euo pipefail

OS="$(uname -s)"
note() { printf '\033[1;36m[setup_fonts]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[setup_fonts]\033[0m %s\n' "$*" >&2; exit 1; }

install_linux() {
    if command -v apt-get >/dev/null 2>&1; then
        note "Detected apt-get; installing fonts-noto-cjk"
        sudo apt-get update -qq
        sudo apt-get install -y fonts-noto-cjk fonts-noto-cjk-extra
    elif command -v dnf >/dev/null 2>&1; then
        note "Detected dnf; installing google-noto-{sans,serif}-cjk-fonts"
        sudo dnf install -y google-noto-sans-cjk-fonts google-noto-serif-cjk-fonts
    elif command -v pacman >/dev/null 2>&1; then
        note "Detected pacman; installing noto-fonts-cjk"
        sudo pacman -S --noconfirm noto-fonts-cjk
    elif command -v tlmgr >/dev/null 2>&1; then
        note "Falling back to tlmgr; installing noto-cjk (TeX Live)"
        tlmgr install noto-cjk
    else
        fail "No supported package manager found. Install Noto CJK fonts manually."
    fi
}

install_macos() {
    if command -v brew >/dev/null 2>&1; then
        note "Detected brew; installing font-noto-{sans,serif}-cjk casks"
        brew install --cask font-noto-sans-cjk font-noto-serif-cjk || true
    else
        fail "Install Homebrew first: https://brew.sh/"
    fi
}

case "$OS" in
    Linux)  install_linux ;;
    Darwin) install_macos ;;
    *)      fail "Unsupported OS: $OS" ;;
esac

note "Verifying fc-list for ja/zh"
fc-list :lang=ja | head -1 || fail "No Japanese fonts detected. fc-cache may be needed."
fc-list :lang=zh | head -1 || fail "No Chinese fonts detected."
note "Done."
