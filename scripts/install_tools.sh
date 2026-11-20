#!/usr/bin/env bash
# Install subfinder for Codespaces. Never fail the build.
set +e
echo "Checking tools..."
command -v curl >/dev/null && echo "curl: OK" || echo "curl: MISSING"
command -v python3 >/dev/null && echo "python3: OK" || echo "python3: MISSING"
command -v git >/dev/null && echo "git: OK" || echo "git: MISSING"

if command -v subfinder >/dev/null; then
  echo "subfinder: already installed"
  subfinder -version 2>/dev/null || true
  exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SF_ARCH="amd64" ;;
  aarch64|arm64) SF_ARCH="arm64" ;;
  *) SF_ARCH="amd64" ;;
esac

# Try the GitHub release binary first.
VER="$(curl -s https://api.github.com/repos/projectdiscovery/subfinder/releases/latest | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)"
if [ -n "$VER" ]; then
  echo "Installing subfinder $VER ($SF_ARCH)..."
  cd /tmp && curl -sL -o subfinder.zip "https://github.com/projectdiscovery/subfinder/releases/download/${VER}/subfinder_${VER#v}_linux_${SF_ARCH}.zip" \
    && unzip -o -q subfinder.zip subfinder 2>/dev/null \
    && mkdir -p "$HOME/.local/bin" && mv subfinder "$HOME/.local/bin/subfinder" \
    && chmod +x "$HOME/.local/bin/subfinder" \
    && echo "subfinder: installed to ~/.local/bin/subfinder"
fi

if ! command -v subfinder >/dev/null && [ -x "$HOME/.local/bin/subfinder" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi

# Fallback: go install, if Go exists.
if ! command -v subfinder >/dev/null && command -v go >/dev/null; then
  echo "Trying go install for subfinder..."
  go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest 2>/dev/null || true
  export PATH="$HOME/go/bin:$PATH"
fi

if command -v subfinder >/dev/null; then
  echo "subfinder: OK"
else
  echo "subfinder: SKIP - not installed, scan_site.py will skip that step and continue"
fi
echo "install_tools.sh done (build continues even if subfinder was skipped)"
exit 0
