#!/usr/bin/env bash
# Install the pinned gitleaks, tflint and trivy releases into .tools/bin/ (git-ignored), checking
# each archive's SHA-256 against its pin file in scripts/.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root/.tools/bin"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# read_pin TOOL: sets VERSION and SHA256 from scripts/TOOL.pin.
read_pin() {
  local pin="$root/scripts/$1.pin" prefix
  prefix="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
  VERSION="$(sed -n "s/^${prefix}_VERSION=//p" "$pin")"
  SHA256="$(sed -n "s/^${prefix}_SHA256=//p" "$pin")"
  if [ -z "$VERSION" ] || [ -z "$SHA256" ]; then
    echo "scripts/$1.pin must set ${prefix}_VERSION and ${prefix}_SHA256" >&2
    exit 1
  fi
}

# fetch URL ARCHIVE: downloads into $tmp and checks the pinned SHA-256.
fetch() {
  curl -fsSL -o "$tmp/$2" "$1"
  (cd "$tmp" && echo "$SHA256  $2" | sha256sum -c -)
}

mkdir -p "$bin"

# gitleaks (scripts/public_check.py reads the same pin and refuses any other version).
read_pin gitleaks
if [ -x "$bin/gitleaks" ] && [ "$("$bin/gitleaks" version 2>/dev/null)" = "$VERSION" ]; then
  echo "gitleaks $VERSION already installed"
else
  archive="gitleaks_${VERSION}_linux_x64.tar.gz"
  fetch "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${archive}" "$archive"
  tar -xzf "$tmp/$archive" -C "$tmp" gitleaks
  install -m 755 "$tmp/gitleaks" "$bin/gitleaks"
  echo "gitleaks $VERSION installed"
fi

# tflint (lints the Terraform in infra/).
read_pin tflint
if [ -x "$bin/tflint" ] && "$bin/tflint" --version 2>/dev/null | grep -x "TFLint version $VERSION" >/dev/null; then
  echo "tflint $VERSION already installed"
else
  archive="tflint_linux_amd64.zip"
  fetch "https://github.com/terraform-linters/tflint/releases/download/v${VERSION}/${archive}" "$archive"
  unzip -q -o "$tmp/$archive" tflint -d "$tmp"
  install -m 755 "$tmp/tflint" "$bin/tflint"
  echo "tflint $VERSION installed"
fi

# trivy (scans the Terraform for misconfigurations).
read_pin trivy
if [ -x "$bin/trivy" ] && "$bin/trivy" --version 2>/dev/null | grep -x "Version: $VERSION" >/dev/null; then
  echo "trivy $VERSION already installed"
else
  archive="trivy_${VERSION}_Linux-64bit.tar.gz"
  fetch "https://github.com/aquasecurity/trivy/releases/download/v${VERSION}/${archive}" "$archive"
  tar -xzf "$tmp/$archive" -C "$tmp" trivy
  install -m 755 "$tmp/trivy" "$bin/trivy"
  echo "trivy $VERSION installed"
fi
