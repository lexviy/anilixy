#!/usr/bin/env bash
set -Eeuo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { printf '%b[INFO]%b %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '%b[WARN]%b %s\n' "$YELLOW" "$NC" "$1" >&2; }
err() {
  printf '%b[ERR]%b %s\n' "$RED" "$NC" "$1" >&2
  exit 1
}
step() { printf '%b[STEP]%b %s\n' "$BLUE" "$NC" "$1"; }

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

LOCAL_BIN="$HOME/.local/bin"
LOCAL_SHARE="$HOME/.local/share/anilixy"
VENV_DIR="$LOCAL_SHARE/venv"
LAUNCHER="$LOCAL_BIN/anilixy"
ANI_CLI_SYSTEM="/usr/local/bin/ani-cli"
CONFIG_DIR="$HOME/.config/anilixy"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/anilixy"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/anilixy"

ask() {
  local prompt="$1"
  local default="${2:-n}"
  local reply=""

  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n]: " reply || true
    reply="${reply:-y}"
  else
    read -r -p "$prompt [y/N]: " reply || true
    reply="${reply:-n}"
  fi

  [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

pipx_has_anilixy() {
  local packages

  command_exists pipx || return 1
  packages="$(pipx list --short 2>/dev/null)" || return 1

  grep -Eq '^anilixy([[:space:]]|$)' <<<"$packages"
}

is_anilixy_wrapper() {
  [[ -f "$LAUNCHER" ]] && {
    grep -Fq '# anilixy-local-wrapper' "$LAUNCHER" ||
      grep -Fq 'exec "$HOME/.local/share/anilixy/venv/bin/anilixy" "$@"' "$LAUNCHER"
  }
}

remove_anilixy() {
  step "Removing anilixy..."

  if command_exists pipx; then
    if pipx_has_anilixy; then
      if ask "Uninstall the pipx installation of anilixy?"; then
        pipx uninstall anilixy
      else
        info "Keeping the pipx installation."
      fi
    else
      info "No pipx installation of anilixy was found."
    fi
  fi

  if [[ -d "$VENV_DIR" ]]; then
    if ask "Remove the local Python virtual environment at $VENV_DIR?"; then
      rm -rf -- "$VENV_DIR"
      info "Local virtual environment removed."
    else
      info "Keeping the local virtual environment."
    fi
  fi

  if is_anilixy_wrapper; then
    if ask "Remove the local anilixy launcher at $LAUNCHER?"; then
      rm -f -- "$LAUNCHER"
      info "Local launcher removed."
    else
      info "Keeping the local launcher."
    fi
  elif [[ -e "$LAUNCHER" ]]; then
    warn "Keeping $LAUNCHER because it was not created by the local installer."
  fi
}

remove_ani_cli() {
  step "Checking ani-cli..."

  if [[ ! -f "$ANI_CLI_SYSTEM" ]]; then
    info "No ani-cli installation found at $ANI_CLI_SYSTEM."
    return
  fi

  if ! ask "Remove ani-cli from $ANI_CLI_SYSTEM? (other programs may use it)"; then
    info "Keeping ani-cli at $ANI_CLI_SYSTEM."
    return
  fi

  if ! command_exists sudo; then
    warn "sudo is unavailable. Cannot remove $ANI_CLI_SYSTEM."
    return
  fi

  sudo rm -f -- "$ANI_CLI_SYSTEM"
  info "ani-cli removed from $ANI_CLI_SYSTEM."
}

dir_size() {
  du -sh -- "$1" 2>/dev/null | cut -f1
}

remove_if_empty() {
  [[ -d "$1" ]] && rmdir -- "$1" 2>/dev/null || true
}

remove_offline_manga() {
  local manga_dir="$DATA_DIR/manga"

  if [[ -d "$manga_dir" ]]; then
    if ask "Remove manga chapters saved offline at $manga_dir ($(dir_size "$manga_dir"))?"; then
      rm -rf -- "$manga_dir"
      info "Offline manga removed."
    else
      info "Keeping offline manga at $manga_dir."
    fi
  fi

  remove_if_empty "$DATA_DIR"
  remove_if_empty "$LOCAL_SHARE"
}

remove_cache() {
  if [[ ! -d "$CACHE_DIR" ]]; then
    return
  fi

  if ask "Remove cached covers and logs at $CACHE_DIR ($(dir_size "$CACHE_DIR"))?" y; then
    rm -rf -- "$CACHE_DIR"
    info "Cache removed."
  else
    info "Keeping cache at $CACHE_DIR."
  fi
}

remove_configuration() {
  if [[ ! -d "$CONFIG_DIR" ]]; then
    info "No configuration directory found."
    return
  fi

  warn "$CONFIG_DIR holds your settings, AniList login, Discord configuration,"
  warn "watch/reading progress, manga history and custom novels."
  if ask "Remove it? This cannot be undone"; then
    rm -rf -- "$CONFIG_DIR"
    info "Configuration removed."
  else
    info "Keeping configuration at $CONFIG_DIR."
  fi
}

main() {
  if ((EUID == 0)); then
    err "Run this script as a regular user, without sudo."
  fi

  printf '\n'
  info "anilixy uninstaller"
  warn "System packages such as Python, Git, mpv, curl and fzf will not be removed."
  warn "Review each prompt carefully before confirming removal."
  printf '\n'

  remove_anilixy
  remove_ani_cli
  remove_offline_manga
  remove_cache
  remove_configuration

  printf '\n'
  info "Uninstallation finished."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
