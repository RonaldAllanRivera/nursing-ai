#!/usr/bin/env bash
# Install the pinned gitleaks release into .tools/bin/ (git-ignored), checking its SHA-256.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root/.tools/bin"

# The pin lives in one file that scripts/public_check.py also reads.
pin="$root/scripts/gitleaks.pin"
GITLEAKS_VERSION="$(sed -n 's/^GITLEAKS_VERSION=//p' "$pin")"
GITLEAKS_SHA256="$(sed -n 's/^GITLEAKS_SHA256=//p' "$pin")"
if [ -z "$GITLEAKS_VERSION" ] || [ -z "$GITLEAKS_SHA256" ]; then
  echo "scripts/gitleaks.pin must set GITLEAKS_VERSION and GITLEAKS_SHA256" >&2
  exit 1
fi

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
