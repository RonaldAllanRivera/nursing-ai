#!/usr/bin/env bash
# Install the pinned gitleaks release into .tools/bin/ (git-ignored), checking its SHA-256.
set -euo pipefail

GITLEAKS_VERSION="8.30.1"
GITLEAKS_SHA256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root/.tools/bin"

if [ -x "$bin/gitleaks" ] && [ "$("$bin/gitleaks" version 2>/dev/null)" = "$GITLEAKS_VERSION" ]; then
  echo "gitleaks $GITLEAKS_VERSION already installed"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

archive="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
curl -fsSL -o "$tmp/$archive" \
  "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${archive}"
(cd "$tmp" && echo "$GITLEAKS_SHA256  $archive" | sha256sum -c -)

mkdir -p "$bin"
tar -xzf "$tmp/$archive" -C "$tmp" gitleaks
install -m 755 "$tmp/gitleaks" "$bin/gitleaks"
echo "gitleaks $GITLEAKS_VERSION installed"
