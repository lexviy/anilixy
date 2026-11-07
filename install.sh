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

command_exists() { command -v "$1" >/dev/null 2>&1; }

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
LOCAL_BIN="$HOME/.local/bin"
LOCAL_SHARE="$HOME/.local/share/anilixy"
VENV_DIR="$LOCAL_SHARE/venv"
LAUNCHER="$LOCAL_BIN/anilixy"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/anilixy.desktop"
ICON_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps/anilixy.png"
ANI_CLI_REF="${ANI_CLI_REF:-v5.1}"
ANI_CLI_DIR="/usr/local/bin"
MIN_PYTHON="3.10"

OS="$(uname -s)"
DISTRO=""
DISTRO_LIKE=""
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO="${ID:-}"
  DISTRO_LIKE="${ID_LIKE:-}"
fi

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

as_root() {
  if command_exists sudo; then
    sudo "$@"
  else
    err "sudo is required to install system dependencies."
  fi
}

is_anilixy_wrapper() {
  [[ -f "$LAUNCHER" ]] && grep -Fq '# anilixy-local-wrapper' "$LAUNCHER"
}

enable_extra_rpm_repos() {
  if [[ "$DISTRO" == "fedora" || "$DISTRO" == "nobara" ]]; then
    as_root dnf install -y \
      "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm"
  else
    local el
    el="$(rpm -E %rhel)"
    as_root dnf install -y \
      "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${el}.noarch.rpm"
    as_root dnf config-manager --set-enabled crb 2>/dev/null ||
      warn "Could not enable the CRB repository. Some packages may be missing."
    as_root dnf install -y \
      "https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-${el}.noarch.rpm"
  fi
}

install_dnf_dependencies() {
  as_root dnf install -y python3 python3-pip git curl wget

  if as_root dnf install -y mpv fzf; then
    return
  fi

  warn "mpv/fzf are not available in your enabled repositories."
  if [[ "$DISTRO" == "fedora" || "$DISTRO" == "nobara" ]]; then
    warn "On Fedora, mpv comes from RPM Fusion (https://rpmfusion.org)."
  else
    warn "On RHEL-based systems, mpv and fzf come from EPEL and RPM Fusion."
  fi

  if ask "Enable these repositories and try again?"; then
    enable_extra_rpm_repos
    if as_root dnf install -y mpv fzf; then
      return
    fi
  fi

  warn "mpv/fzf were not installed. anilixy will install, but anime playback needs them."
}

install_system_dependencies() {
  step "Installing system dependencies..."

  if [[ "$OS" == "Linux" ]]; then
    case "$DISTRO" in
    ubuntu | debian | linuxmint | pop | kali)
      as_root apt update
      as_root apt install -y python3 python3-venv python3-pip mpv git curl wget fzf
      ;;
    fedora | nobara | rhel | almalinux | alma | rocky | centos)
      install_dnf_dependencies
      ;;
    arch | manjaro | endeavouros | artix | cachyos)
      as_root pacman -S --needed --noconfirm python python-pip mpv git curl wget fzf
      ;;
    opensuse* | sles)
      as_root zypper install -y python3 python3-pip mpv git curl wget fzf
      ;;
    void)
      as_root xbps-install -Sy python3 python3-pip mpv git curl wget fzf
      ;;
    gentoo)
      as_root emerge --ask=n dev-lang/python media-video/mpv dev-vcs/git net-misc/curl net-misc/wget app-shells/fzf
      ;;
    *)
      err "Unsupported distribution: ${DISTRO:-unknown}${DISTRO_LIKE:+ (like $DISTRO_LIKE)}. Install Python $MIN_PYTHON+, pip, venv, mpv, Git, curl/wget and fzf manually."
      ;;
    esac
  elif [[ "$OS" == "Darwin" ]]; then
    command_exists brew || err "Homebrew is required: https://brew.sh"
    brew install python mpv git curl wget fzf
  else
    err "Unsupported operating system: $OS"
  fi
}

check_python() {
  command_exists python3 || err "python3 was not found after installing dependencies."

  if ! python3 -c "import sys; sys.exit(sys.version_info < (${MIN_PYTHON/./, }))"; then
    err "anilixy needs Python $MIN_PYTHON or newer, but python3 is $(python3 -c 'import platform; print(platform.python_version())'). Install a newer Python and run this script again."
  fi
}

install_ani_cli() {
  if command_exists ani-cli; then
    info "ani-cli is already installed at $(command -v ani-cli) (update it with: ani-cli -U)"
    return
  fi

  step "Installing ani-cli $ANI_CLI_REF from the official repository..."

  command_exists git || err "Git is required to install ani-cli."

  local tmp_dir
  tmp_dir="$(mktemp -d)"

  if ! git clone --depth 1 --branch "$ANI_CLI_REF" \
    https://github.com/pystardust/ani-cli.git "$tmp_dir/ani-cli"; then
    rm -rf "$tmp_dir"
    err "Failed to clone the ani-cli repository (ref $ANI_CLI_REF)."
  fi

  if ! as_root mkdir -p "$ANI_CLI_DIR" ||
    ! as_root install -m 0755 "$tmp_dir/ani-cli/ani-cli" "$ANI_CLI_DIR/ani-cli"; then
    rm -rf "$tmp_dir"
    err "Failed to install ani-cli into $ANI_CLI_DIR."
  fi

  rm -rf "$tmp_dir"

  info "ani-cli installed at $ANI_CLI_DIR/ani-cli"
}

install_pipx() {
  if command_exists pipx; then
    return
  fi

  if ! ask "Do you want to install pipx?"; then
    info "Skipping pipx. Using a Python virtual environment instead."
    return
  fi

  step "Installing pipx..."

  if [[ "$OS" == "Linux" ]]; then
    case "$DISTRO" in
    ubuntu | debian | linuxmint | pop | kali)
      as_root apt install -y pipx
      ;;
    fedora | nobara | rhel | almalinux | alma | rocky | centos)
      as_root dnf install -y pipx
      ;;
    arch | manjaro | endeavouros | artix | cachyos)
      as_root pacman -S --needed --noconfirm python-pipx
      ;;
    opensuse* | sles)
      as_root zypper install -y python3-pipx
      ;;
    void)
      as_root xbps-install -Sy python3-pipx
      ;;
    *)
      warn "Automatic pipx installation is not configured for this distribution."
      return
      ;;
    esac
  elif [[ "$OS" == "Darwin" ]]; then
    brew install pipx
  fi

  if command_exists pipx; then
    info "pipx installed successfully."
  else
    warn "pipx was not found after installation. Falling back to venv."
  fi
}

pipx_has_anilixy() {
  local packages
  packages="$(pipx list --short 2>/dev/null)" || return 1
  grep -Eq '^anilixy([[:space:]]|$)' <<<"$packages"
}

WANT_PDF=""

decide_pdf_support() {
  local had_pdf=0

  if command_exists pipx && pipx_has_anilixy &&
    pipx runpip anilixy show pymupdf >/dev/null 2>&1; then
    had_pdf=1
  elif [[ -x "$VENV_DIR/bin/python" ]] &&
    "$VENV_DIR/bin/python" -m pip show pymupdf >/dev/null 2>&1; then
    had_pdf=1
  fi

  if ((had_pdf)); then
    info "Keeping PDF light novel support (PyMuPDF)."
    WANT_PDF=1
  elif ask "Install PDF light novel support (PyMuPDF, ~25 MB)? EPUB works without it"; then
    WANT_PDF=1
  else
    WANT_PDF=0
  fi
}

remove_old_venv_install() {
  if is_anilixy_wrapper; then
    info "Removing the old venv launcher at $LAUNCHER..."
    rm -f -- "$LAUNCHER"
  fi
  if [[ -d "$VENV_DIR" ]]; then
    info "Removing the old virtual environment at $VENV_DIR..."
    rm -rf -- "$VENV_DIR"
  fi
}

install_with_pipx() {
  info "Using pipx..."

  remove_old_venv_install

  if pipx_has_anilixy; then
    info "Removing the previous pipx installation..."
    pipx uninstall anilixy
  fi

  pipx install "$PROJECT_DIR"

  if ((WANT_PDF)); then
    pipx inject anilixy pymupdf
  fi
}

install_with_venv() {
  info "pipx not found. Using a local virtual environment..."

  mkdir -p "$LOCAL_SHARE" "$LOCAL_BIN"

  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
  fi

  local spec="$PROJECT_DIR"
  if ((WANT_PDF)); then
    spec="$PROJECT_DIR[pdf]"
  fi

  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install --upgrade "$spec"

  if [[ -e "$LAUNCHER" ]] && ! is_anilixy_wrapper; then
    warn "$LAUNCHER already exists and was not created by this installer."
    if ! ask "Replace it with the anilixy launcher?"; then
      warn "Keeping $LAUNCHER. Run anilixy with: $VENV_DIR/bin/anilixy"
      return
    fi
  fi

  cat >"$LAUNCHER" <<'EOF'
#!/usr/bin/env bash
# anilixy-local-wrapper
exec "$HOME/.local/share/anilixy/venv/bin/anilixy" "$@"
EOF
  chmod 0755 "$LAUNCHER"
  info "Launcher created at $LAUNCHER"
}

install_anilixy() {
  step "Installing anilixy..."

  if ! command_exists pipx; then
    install_pipx
  fi

  decide_pdf_support

  if command_exists pipx; then
    install_with_pipx
  else
    install_with_venv
  fi
}

install_desktop_entry() {
  [[ "$OS" == "Linux" ]] || return 0

  local bin_dir=""
  if command_exists pipx; then
    bin_dir="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null)" || bin_dir=""
  fi
  local executable="${bin_dir:-$LOCAL_BIN}/anilixy"
  [[ -x "$executable" ]] || executable="$LAUNCHER"

  mkdir -p "$(dirname -- "$ICON_FILE")"
  cp -- "$PROJECT_DIR/assets/anilixy.png" "$ICON_FILE"

  mkdir -p "$(dirname -- "$DESKTOP_FILE")"
  cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Anilixy
Comment=Watch anime and read manga and light novels, synced with AniList
Exec="$executable"
Icon=anilixy
Terminal=true
Categories=AudioVideo;Video;Player;
Keywords=anime;manga;novel;anilist;
EOF
  info "App launcher entry created at $DESKTOP_FILE"
}

check_installation() {
  hash -r
  if command_exists anilixy; then
    info "Installation complete. Run with: anilixy"
    info "To update later: git pull && bash install.sh"
    return
  fi

  warn "Installation finished, but the anilixy command is not in your PATH."
  warn "Add $LOCAL_BIN to PATH, then open a new terminal."
  warn "For bash: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
  warn "For zsh:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
}

main() {
  if ((EUID == 0)); then
    err "Run this script as a regular user, without sudo."
  fi

  [[ -f "$PROJECT_DIR/pyproject.toml" ]] || err "pyproject.toml not found next to install.sh."

  info "Project: $PROJECT_DIR"
  info "System: $OS | Distribution: ${DISTRO:-unknown}"

  install_system_dependencies
  check_python
  install_ani_cli
  install_anilixy
  install_desktop_entry
  check_installation
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
